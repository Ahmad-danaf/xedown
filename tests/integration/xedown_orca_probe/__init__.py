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

Every row below follows the same shape: prepare -> settle -> mark + act ->
settle -> next. Preparation (mode corrections, focus corrections, settings
writes) never shares a callback turn with the mark it precedes -- fix round 1
found two rows where it did, and in one of them (row 97) that was not merely
an attribution smell but the reason the row measured the wrong thing
entirely: see `step_row_97_focus_mode_bar`'s docstring.

Every preparation step gets a marker of its own now, even the ones that
measure silent today, and every burst of key presses is spaced out rather
than fired in one loop turn. Task 4 found both defects biting for real: an
unmarked `grab_focus()` in `step_row_97_focus_mode_bar` produced speech that
landed in `row-96-switch-back-to-preview`'s window and was misread as the
mode switch announcing itself, and an unthrottled 6x Tab burst in
`step_row_99_search_bar_tab` collapsed into Orca's own event-coalescing.
Neither was a xedown defect -- both were the instrument measuring the wrong
thing. See `TAB_PRESS_INTERVAL_MS` and the per-step docstrings below.
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

# Firing several key presses back-to-back, with no mainloop turn between them,
# puts their focus events within a few microseconds of each other -- well
# inside Orca's own event-coalescing window, which keeps only the most recent
# event of a given type from a burst and silently drops the rest. That
# measures as silence for a reason that has nothing to do with xedown (Task 4,
# Q3: row-99's 6-press Tab burst). A screen-reader user does not tab that
# fast, so spacing presses out is not a workaround for Orca -- it is matching
# what the probe is meant to simulate.
TAB_PRESS_INTERVAL_MS = 400

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

    def _in_modebar(self, modebar, widget):
        """True when `widget` is the mode bar itself or somewhere inside it.

        `Gtk.Widget.is_ancestor` is asked of the descendant, with the
        candidate ancestor as its argument -- the same direction
        `searchbar.py`'s own `contains_focus` uses it in.
        """
        return (
            modebar is not None
            and widget is not None
            and (widget is modebar or widget.is_ancestor(modebar))
        )

    def _modebar_focusables(self, modebar):
        """The mode bar's own controls a real Tab key press can reach, in
        pack order.

        `_stale_dot` is a `Gtk.Label` and never focusable regardless of
        visibility. `_refresh_button` only joins the chain while visible --
        the same condition `set_refresh_visible` uses -- because GTK's own
        focus traversal skips widgets that are not currently showing.
        """
        controls = [modebar._buttons[Mode.PREVIEW], modebar._buttons[Mode.SOURCE]]
        if modebar._refresh_button.get_visible():
            controls.append(modebar._refresh_button)
        return controls

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

    def _press_tabs(self, count, on_done):
        """Deliver `count` Gdk.KEY_Tab presses spaced `TAB_PRESS_INTERVAL_MS`
        apart, then call `on_done()`.

        Not a `for` loop with `self._press` inside it -- that fires every
        press in the same mainloop turn (see `TAB_PRESS_INTERVAL_MS`'s
        docstring for why that is wrong). Each press after the first is its
        own scheduled callback instead, using the same `_schedule` idiom
        every other step in this file uses, never `time.sleep` -- this runs
        on the GTK main loop the key events themselves are delivered through,
        and sleeping here would block delivery of the very events being
        measured.
        """
        if count <= 0:
            on_done()
            return False
        self._press(Gdk.KEY_Tab, 0)
        remaining = count - 1
        if remaining <= 0:
            on_done()
        else:
            self._schedule(
                TAB_PRESS_INTERVAL_MS,
                lambda: self._press_tabs(remaining, on_done),
            )
        return False

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
        self._schedule(SETTLE_MS, self.step_row_96_switch_to_source)
        return False

    def step_row_96_switch_to_source(self):
        """Row 96 (1 of 2): Ctrl+Shift+M. Does Orca say Markdown is now showing?

        `DEFAULT_MODE` is "preview" (`settings.py:123`) and this tab's path is
        new, so it opens in Preview -- no prep needed before this first press.
        """
        controller = self._controller()
        before = controller.state.mode if controller is not None else None
        mark("row-96-switch-to-source")
        self._press(
            Gdk.KEY_m, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        after = self._controller().state.mode if self._controller() else None
        record(
            "orca-row-96-switched-to-source",
            before is Mode.PREVIEW and after is Mode.SOURCE,
            f"{before} -> {after}",
        )
        self._schedule(SETTLE_MS, self.step_row_96_switch_back_to_preview)
        return False

    def step_row_96_switch_back_to_preview(self):
        """Row 96 (2 of 2): Ctrl+Shift+M again. Does Orca say Preview is back?

        The two directions get their own markers -- `row-96-switch-to-source`
        and this one -- so the transcript can attribute each announcement to
        the direction that produced it, rather than one window covering both
        and leaving which-said-what to guesswork.
        """
        controller = self._controller()
        before = controller.state.mode if controller is not None else None
        mark("row-96-switch-back-to-preview")
        self._press(
            Gdk.KEY_m, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        after = self._controller().state.mode if self._controller() else None
        record(
            "orca-row-96-switched-back-to-preview",
            before is Mode.SOURCE and after is Mode.PREVIEW,
            f"{before} -> {after}",
        )
        self._schedule(SETTLE_MS, self.step_row_97_focus_mode_bar)
        return False

    def step_row_97_focus_mode_bar(self):
        """Row 97, prepare: put focus on the mode bar's own first control.

        Fix round 1 found this row silently measuring the wrong thing: with
        mode left in SOURCE by (the old, single-press) row 96, `set_mode`'s
        SOURCE branch hands focus to `self.view` -- the source `GtkSource.View`
        -- whose `accepts-tab` property defaults to True, so the "Tab through
        the mode bar" presses inserted literal tab characters into the
        document instead of ever reaching the bar. Orca then correctly said
        nothing about the mode bar, and that silence would have been
        published as a naming defect. Row 96 now always ends back in Preview,
        which removes the accepts-tab hazard, but this step does not lean on
        that alone: it grabs focus onto the bar's first control explicitly,
        so where Tab starts is never again "wherever focus happens to be".

        This `grab_focus()` is marked in its own right (`row-97-focus-mode-bar`)
        because it is not silent: Task 4 traced "Preview toggle button
        pressed." -- misread as the mode switch announcing itself -- directly
        to this call. Before this mark existed, that speech landed inside
        `row-96-switch-back-to-preview`'s window because this step had no
        marker of its own. Any action that can cause speech owns a marker
        now, so that can never happen again.
        """
        controller = self._controller()
        mark("row-97-focus-mode-bar")
        if controller is not None and controller.modebar is not None:
            self._modebar_focusables(controller.modebar)[0].grab_focus()
        self._schedule(SETTLE_MS, self.step_row_97_mode_bar_tab)
        return False

    def step_row_97_mode_bar_tab(self):
        """Row 97: Tab through the mode bar. Is each control named aloud?

        Both containment checks are real: `self.window.get_focus()` is asked
        before the first press and again after the last, and each answer is
        compared against the live tree (`_in_modebar`) rather than assumed.
        Exactly enough Tab presses are sent to walk from the first focusable
        control to the last one currently visible (`_modebar_focusables`) --
        not a fixed guess, so the "after" check stays meaningful whether the
        refresh button happens to be showing or not. The presses themselves
        are spaced out (`_press_tabs`), not fired in one loop turn -- see
        `TAB_PRESS_INTERVAL_MS`.
        """
        controller = self._controller()
        modebar = controller.modebar if controller is not None else None
        before = self.window.get_focus()
        before_in_bar = self._in_modebar(modebar, before)
        mark("row-97-mode-bar-tab")
        record(
            "orca-mode-bar-focus-starts-in-the-bar",
            before_in_bar,
            f"focus: {before!r}",
        )
        presses = max(0, len(self._modebar_focusables(modebar)) - 1) if modebar else 0

        def _after_presses():
            after = self.window.get_focus()
            after_in_bar = self._in_modebar(modebar, after)
            record(
                "orca-mode-bar-tabbed",
                before_in_bar and after_in_bar,
                f"{presses} Tab press(es); focus after: {after!r}",
            )
            self._schedule(SETTLE_MS, self.step_row_97_activate_focused_button)

        self._press_tabs(presses, _after_presses)
        return False

    def step_row_97_activate_focused_button(self):
        """Row 97 (extra): activate the button just tabbed to, mode bar still
        focused. The suppression half of Task 6's mode announcement.

        Nothing earlier in this sequence ever presses a mode-bar button --
        every mode change up to here goes through Ctrl+Shift+M (row 96's two
        markers), which is the path `TabController.set_mode` is supposed to
        announce. This is the other path: `ModeBar.has_focus()` is True right
        now (row 97 just tabbed here without activating anything), so
        activating this button switches mode from *inside* the bar, and
        `set_mode` must NOT call `ModeBar.announce` here -- Orca already
        announces the toggle's own state change, and a second announcement
        would double it. Space is what `Gtk.Button`'s own binding set uses to
        activate a focused button, not Return, which risks a window's
        default action instead of this specific widget.

        Not asserted in `ROWS`/`SILENT_ROWS`: the one thing this row needs to
        show -- exactly one utterance, not two, since a real state-change
        announcement and a would-be duplicate mode announcement both contain
        the same "Markdown source" text as a substring -- cannot be told
        apart by `evaluate_rows`' substring/silence checks. It was verified
        by reading the raw Orca log directly, the same way Task 4 verified
        the announcement signal itself; see task-6-report.md. This step's
        marker exists so that verification is repeatable, not so it can be
        wired into the automated gate.

        The state check below waits a full `SETTLE_MS`, not a quick poll:
        unlike the Ctrl+Shift+M accelerator path (row 96), where `state.mode`
        already reflects the switch the instant `_press()` returns, a
        `Gtk.Button`'s own keyboard activation is not that synchronous --
        measured directly (a throwaway diagnostic build of this step, kept
        only in task-6-report.md) reading `Mode.PREVIEW` immediately after
        `_press()` and `Mode.SOURCE` a full 3s later, for the exact same
        press. The raw Orca log for that same run already showed the real
        object:state-changed:checked pair (Source -> checked, Preview ->
        unchecked) and the real AT-SPI focus event onto [text] (only
        reachable through `set_mode`'s own `self.view.grab_focus()`)
        starting within milliseconds of the press -- so xedown's own
        handling is not what is slow here; it is GTK's keyboard-activation
        path for a focused button being slower to settle than the
        AT-SPI/Orca side that already reacted to it.
        """
        mark("row-97-activate-focused-button")
        self._press(Gdk.KEY_space, 0)

        def _after_activation():
            after = self._controller().state.mode if self._controller() else None
            record(
                "orca-row-97-activated-focused-button",
                after is Mode.SOURCE,
                f"mode after activating the focused mode-bar button: {after}",
            )
            self._schedule(SETTLE_MS, self.step_row_98_prepare_preview)

        self._schedule(SETTLE_MS, _after_activation)
        return False

    def step_row_98_prepare_preview(self):
        """Row 98, prepare: make sure Preview is showing and actually focused.

        Row 97 deliberately leaves focus inside the mode bar, not the
        WebView, and docs/manual-smoke-test.md's row 98 is keyboard-only ("no
        click first") for the human tester -- it says nothing about where
        this probe's own synthetic focus should already be. Left alone, the
        Down/Page_Down presses below would land on whatever the mode bar's
        buttons do with them, not the document. The mode check used to be
        purely defensive, on the assumption mode was already Preview by
        construction; since `step_row_97_activate_focused_button` switches to
        Source for real (to measure the mode announcement's suppression
        path), this correction now genuinely runs, every time, taking mode
        back to Preview -- which happens, unsuppressed, to be a second live
        measurement of the same announcement row 96 already covers.

        Marked (`row-98-prepare-preview`) even though `grab_focus()` measures
        silent today (Task 4) -- that silence is luck, not design, and an
        unmarked action here would corrupt `row-97-mode-bar-tab`'s window
        exactly the way the equivalent call corrupted row 96's, the day this
        step's own effect stops being silent. The Ctrl+Shift+M correction
        just above it shares the same marker and, since Task 6, genuinely
        does speak.
        """
        controller = self._controller()
        mark("row-98-prepare-preview")
        if controller is not None and controller.state.mode is not Mode.PREVIEW:
            self._press(
                Gdk.KEY_m, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
            )
            controller = self._controller()
        if controller is not None and controller.preview is not None:
            controller.preview.widget.grab_focus()
        self._schedule(SETTLE_MS, self.step_row_98_preview_scroll)
        return False

    def step_row_98_preview_scroll(self):
        """Row 98: Down and Page Down with the preview showing, no click first.

        The precondition -- Preview mode, focus on the WebView -- is checked
        for real immediately before the scroll keys, not assumed. The keys
        are still delivered either way, so the sequence keeps moving and
        Orca still gets a chance to speak, but a broken precondition FAILs
        loudly here instead of the transcript being read as though it held.
        """
        controller = self._controller()
        mode_ok = controller is not None and controller.state.mode is Mode.PREVIEW
        focus = self.window.get_focus()
        focus_ok = (
            controller is not None
            and controller.preview is not None
            and focus is controller.preview.widget
        )
        mark("row-98-preview-scroll")
        record(
            "orca-preview-scroll-precondition",
            mode_ok and focus_ok,
            f"mode is Mode.PREVIEW: {mode_ok}, focus is the WebView: {focus_ok} ({focus!r})",
        )
        self._press(Gdk.KEY_Down, 0)
        self._press(Gdk.KEY_Page_Down, 0)
        self._schedule(SETTLE_MS, self.step_row_99_search_bar_tab)
        return False

    def step_row_99_search_bar_tab(self):
        """Row 99: Ctrl+F, then Tab through the search bar.

        The bar's opening is checked for real right after Ctrl+F -- visible,
        and actually holding focus (`SearchBar.owns_focus`, the same
        predicate `shortcuts.route_key` itself relies on to tell xedown's own
        entry apart from xed's) -- rather than assumed True regardless of
        what the key press actually did. The 6 Tab presses that follow are
        spaced out (`_press_tabs`), not fired in one loop turn -- Task 4
        found the old unthrottled burst collapsed into a sub-10ms cluster
        that Orca's own event-coalescing discards down to the last
        transition, measuring as silence for a reason that had nothing to do
        with xedown. See `TAB_PRESS_INTERVAL_MS`.
        """
        mark("row-99-search-bar-tab")
        self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        controller = self._controller()
        visible = (
            controller is not None
            and controller.searchbar is not None
            and controller.searchbar.get_visible()
        )
        focus = self.window.get_focus()
        focused = (
            controller is not None
            and controller.searchbar is not None
            and controller.searchbar.owns_focus(focus)
        )
        record(
            "orca-search-bar-opened",
            visible and focused,
            f"visible: {visible}, focus is the search entry: {focused} ({focus!r})",
        )

        def _after_tabs():
            self._schedule(SETTLE_MS, self.step_row_100_prepare_stale)

        self._press_tabs(6, _after_tabs)
        return False

    def step_row_100_prepare_stale(self):
        """Row 100, prepare: close any open bar, ensure Preview, auto off.

        Escape closes whatever row 99 left open. The mode guard and the
        `AUTO_REFRESH` write are the same two steps
        `xedown_probe.step_manual_refresh_setup` takes before its own
        equivalent buffer edit. None of the three should share a window with
        the mark that follows -- fix round 1 found them doing exactly that.

        Marked (`row-100-prepare-stale`) even though every action here
        measures silent today (Task 4) -- same reasoning as
        `row-98-prepare-preview`: that silence is luck, not design, and this
        step must never be able to corrupt `row-99-search-bar-tab`'s window.
        """
        mark("row-100-prepare-stale")
        self._press(Gdk.KEY_Escape, 0)
        controller = self._controller()
        if controller is not None and controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        xedown_settings.get_settings().set(xedown_settings.AUTO_REFRESH, False)
        self._schedule(SETTLE_MS, self.step_row_100_stale)
        return False

    def step_row_100_stale(self):
        """Row 100: the stale indicator.

        Uses the mechanism `xedown_probe.step_manual_refresh_setup` already
        establishes: `AUTO_REFRESH` is off (from the prepare step above), so
        this buffer change is exactly what an automatic refresh would have
        picked up, and both the stale dot and the refresh button become
        visible.
        """
        controller = self._controller()
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
        """End of sequence. Restores `AUTO_REFRESH` before finishing, the way
        `xedown_probe.step_manual_refresh_check` restores it after its own
        equivalent detour -- this probe must not leave a developer's real
        setting flipped, independently of whatever config sandboxing Task 3's
        harness adds.

        Marked *before* that write, not after: at this point in the sequence
        `state.preview_stale` is True (row 100's own edit set it) and mode is
        still Preview, so flipping `AUTO_REFRESH` back on really does reach
        `_refresh_body_now()` (`controller.py:1298-1353`) -- a genuine,
        speech-capable action. Writing the mark after it, as this step used
        to, would have left it landing inside `row-101-external-change`'s
        window, an *asserted* `ROWS` entry, which is exactly the contamination
        shape this task exists to close off. It happens to be silent today,
        but that must not be why it is unmarked.
        """
        mark("done")
        xedown_settings.get_settings().set(xedown_settings.AUTO_REFRESH, True)
        record("done", True)
        return False
