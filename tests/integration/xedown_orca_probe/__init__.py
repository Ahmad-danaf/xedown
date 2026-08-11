"""Drives one xed through the actions a screen-reader user would take.

This is the scripted half of `docs/manual-smoke-test.md` rows 95-101. It
exists separately from `xedown_probe` for a measured reason: that probe runs
182 assertions at speed, and with Orca listening it failed twice, at two
different steps, where the same harness without a screen reader passes 182
of 182. Orca's AT-SPI traffic perturbs it.

So this probe is slow and small on purpose. It performs one action, writes a
timestamped marker, and waits long enough for speech to settle before the
next. It asserts almost nothing about the widget tree -- `xedown_probe`
already covers that, and re-asserting it here would prove nothing new. What
this probe produces is *attribution*: the marker file that lets
`tests/unit/orca_transcript.py` say which utterance belongs to which action.
"""

import datetime
import os
import sys
import traceback

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Xed

REPORT = os.environ.get("XEDOWN_ORCA_REPORT", "/tmp/xedown-orca-report.txt")
MARKERS = os.environ.get("XEDOWN_ORCA_MARKERS", "/tmp/xedown-orca-markers.txt")

# Speech is not instant, and an utterance that lands after the next marker is
# attributed to the wrong action. Every gap between actions is at least this
# long -- generous rather than tight, because the cost of being wrong is a
# misattributed finding, and the whole run is still under a minute.
SETTLE_MS = 3000

results = []
_sequence_started = False

# Resolved lazily for the same reason `xedown_probe` does it: libpeas treats
# an already-present `sys.modules["xedown"]` entry as a name collision and
# refuses to load the real plugin under it, so an `import xedown` at module
# load time can race ahead of libpeas and break the plugin under test.
Mode = None
xedown_settings = None


def _lazy_imports():
    global Mode, xedown_settings
    from xedown import settings as _settings
    from xedown.document_state import Mode as _Mode

    Mode = _Mode
    xedown_settings = _settings


def _format_line(name, passed, detail):
    status = "PASS" if passed else "FAIL"
    suffix = f" - {detail}" if detail else ""
    return f"{status} {name}{suffix}"


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    line = _format_line(name, passed, detail)
    sys.stderr.write(f"ORCA-PROBE: {line}\n")
    sys.stderr.flush()
    with open(REPORT, "w") as handle:
        handle.write("\n".join(_format_line(n, p, d) for n, p, d in results) + "\n")


def mark(name):
    """Timestamp this moment, in the format the transcript parser reads.

    Local time to microseconds, matching Orca's own debug-log stamps -- the
    two are compared directly, so they have to be the same clock.
    """
    stamp = datetime.datetime.now().strftime("%H:%M:%S.%f")  # noqa: DTZ005
    with open(MARKERS, "a") as handle:
        handle.write(f"{stamp} {name}\n")
    sys.stderr.write(f"ORCA-PROBE: MARK {stamp} {name}\n")
    sys.stderr.flush()


_SAMPLE_MD = (
    "# Scroll Test\n\n"
    "An **emphasised** phrase, and a [link](https://example.com).\n\n"
    + "\n\n".join(
        f"Paragraph {i}. Filler text to build page height. " * 3 for i in range(120)
    )
    + "\n\n```python\nprint(42)\n```\n"
)


class XedownOrcaProbe(GObject.Object, Xed.WindowActivatable):
    __gtype_name__ = "XedownOrcaProbe"

    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _sequence_started
        if _sequence_started:
            return
        _sequence_started = True
        GLib.timeout_add(4000, self._guard(self.step_setup))

    def do_deactivate(self):
        pass

    def do_update_state(self):
        pass

    # --- infrastructure ------------------------------------------------

    def _guard(self, fn):
        def run():
            try:
                return fn()
            except Exception:  # noqa: BLE001 - a crash must become a FAIL
                record(f"probe-crashed-in-{fn.__name__}", False, traceback.format_exc())
                return False

        return run

    def _schedule(self, delay_ms, fn):
        GLib.timeout_add(delay_ms, self._guard(fn))
        return False

    def _controller(self):
        view = self.window.get_active_view()
        return getattr(view, "_xedown_controller", None) if view is not None else None

    def _press(self, keyval, state):
        """Deliver a real key press.

        Deliberately duplicated from `xedown_probe/__init__.py:2448` rather
        than shared. These are two separately-installable libpeas plugins,
        and this harness installs only this one -- sharing would mean either
        installing a plugin it never enables or adding a third module to two
        harness scripts, against the module-name collision hazard the other
        probe's own docstring warns about at length. Twenty duplicated lines
        is the cheaper risk. If that file's version changes, change this one.

        `hardware_keycode` and a device are both load-bearing: GTK's
        accelerator lookup goes through its key hash by keycode, and an event
        with no device never reaches GTK's key-press handling at all.
        """
        window = self.window
        keymap = Gdk.Keymap.get_for_display(window.get_display())
        ok, entries = keymap.get_entries_for_keyval(keyval)
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        event.window = window.get_window()
        event.send_event = True
        event.time = Gtk.get_current_event_time()
        event.state = state
        event.keyval = keyval
        event.hardware_keycode = entries[0].keycode if ok and entries else 0
        event.group = entries[0].group if ok and entries else 0
        seat = window.get_display().get_default_seat()
        if seat is not None:
            keyboard = seat.get_keyboard()
            if keyboard is not None:
                event.set_device(keyboard)
        Gtk.main_do_event(event)

    # --- the sequence --------------------------------------------------

    def step_setup(self):
        _lazy_imports()
        path = os.path.join(
            os.environ.get("XEDOWN_ORCA_TMPDIR", "/tmp"), "orca-sample.md"
        )
        with open(path, "w") as handle:
            handle.write(_SAMPLE_MD)
        self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        record("orca-setup-opened-a-document", True, path)
        self._schedule(SETTLE_MS, self.step_row_96_mode_switch)
        return False

    def step_row_96_mode_switch(self):
        """Row 96: Ctrl+Shift+M twice. Does Orca say which mode is now on?"""
        controller = self._controller()
        before = controller.state.mode if controller is not None else None
        mark("row-96-mode-switch")
        self._press(
            Gdk.KEY_m, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        after = self._controller().state.mode if self._controller() else None
        record(
            "orca-mode-actually-switched",
            before is not None and after is not None and before is not after,
            f"{before} -> {after}",
        )
        self._schedule(SETTLE_MS, self.step_row_97_mode_bar_tab)
        return False

    def step_row_97_mode_bar_tab(self):
        """Row 97: Tab through the mode bar. Is each control named aloud?"""
        mark("row-97-mode-bar-tab")
        for _ in range(4):
            self._press(Gdk.KEY_Tab, 0)
        record("orca-mode-bar-tabbed", True, "4 Tab presses delivered")
        self._schedule(SETTLE_MS, self.step_row_98_preview_scroll)
        return False

    def step_row_98_preview_scroll(self):
        """Row 98: Down and Page Down with the preview showing, no click first."""
        controller = self._controller()
        if controller is not None and controller.state.mode is not Mode.PREVIEW:
            self._press(
                Gdk.KEY_m,
                Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK,
            )
        mark("row-98-preview-scroll")
        self._press(Gdk.KEY_Down, 0)
        self._press(Gdk.KEY_Page_Down, 0)
        record("orca-preview-scroll-keys-delivered", True, "Down, Page_Down")
        self._schedule(SETTLE_MS, self.step_row_99_search_bar_tab)
        return False

    def step_row_99_search_bar_tab(self):
        """Row 99: Ctrl+F, then Tab through the search bar."""
        mark("row-99-search-bar-tab")
        self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        for _ in range(6):
            self._press(Gdk.KEY_Tab, 0)
        record("orca-search-bar-tabbed", True, "Ctrl+F then 6 Tab presses")
        self._schedule(SETTLE_MS, self.step_row_100_stale)
        return False

    def step_row_100_stale(self):
        """Row 100: the stale indicator.

        Uses the mechanism `xedown_probe.step_manual_refresh_setup` already
        establishes: turn AUTO_REFRESH off through the settings store, then
        change the buffer while Preview is showing. That is exactly what an
        automatic refresh would have picked up, so the preview falls behind
        and both the stale dot and the refresh button become visible.
        """
        self._press(Gdk.KEY_Escape, 0)
        controller = self._controller()
        if controller is not None and controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        xedown_settings.get_settings().set(xedown_settings.AUTO_REFRESH, False)
        mark("row-100-stale")
        if controller is not None:
            document = controller.document
            document.insert(document.get_end_iter(), "\n\nmanual refresh marker\n")
        record(
            "orca-stale-triggered",
            controller is not None,
            "AUTO_REFRESH off, then a buffer change while Preview shows",
        )
        self._schedule(SETTLE_MS, self.step_row_101_external_change)
        return False

    def step_row_101_external_change(self):
        """Row 101: the external-change bar -- already measured to be announced."""
        path = os.path.join(
            os.environ.get("XEDOWN_ORCA_TMPDIR", "/tmp"), "orca-sample.md"
        )
        mark("row-101-external-change")
        with open(path, "w") as handle:
            handle.write("# Rewritten outside xed\n\nBy the Orca probe.\n")
        record("orca-external-change-written", True, path)
        self._schedule(SETTLE_MS * 2, self.step_done)
        return False

    def step_done(self):
        mark("done")
        record("done", True)
        return False
