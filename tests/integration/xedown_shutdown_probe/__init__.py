"""Drives one shutdown scenario per xed launch, then stands aside.

`xedown_probe` runs a single long sequence that necessarily ends in exactly
one state -- and because that sequence disables the plugin near the end, the
only shutdown it has ever observed is a shutdown with xedown already
inactive. Scenarios like "close several Markdown tabs" or "close xed with a
live preview on screen" were never reached at all.

This probe exists to close that gap. Each launch runs ONE named scenario
(`XEDOWN_SHUTDOWN_SCENARIO`), leaves xed in that scenario's end state, and
writes `READY` to the report. The *runner*
(`scripts/run-shutdown-tests.sh`) then closes the window(s) the way a user
does -- a real window-manager close request -- and inspects xed's stderr.
The assertions here are not the point of the exercise: they exist so that a
scenario cannot report a clean shutdown by silently never having built a
preview in the first place. The real assertion is made by the runner, on
the log.

Nothing here ever calls `window.destroy()` -- that segfaults xed. Windows
are closed either by the runner through the window manager, or via
`window.close()`, which is the graceful delete-event path.

In control mode (`XEDOWN_SHUTDOWN_CONTROL=1`) xedown is not installed at
all. The same window/tab choreography runs, but the xedown-specific
assertions are skipped, so a scenario's log can be compared against a run
where the plugin does not exist. That comparison is what keeps the
runner's one allowlisted xed-core assertion honest.
"""

import os
import sys
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import Gio, GLib, GObject, Xed

SCENARIO = os.environ.get("XEDOWN_SHUTDOWN_SCENARIO", "preview-active")
REPORT = os.environ.get("XEDOWN_SHUTDOWN_REPORT", "/tmp/xedown-shutdown-report.txt")
TMPDIR = os.environ.get("XEDOWN_SHUTDOWN_TMPDIR", "/tmp")
CONTROL = os.environ.get("XEDOWN_SHUTDOWN_CONTROL") == "1"

CONTROLLER_ATTRIBUTE = "_xedown_controller"

# A plugin activates once per window, and three of these scenarios open a
# second window on purpose. Without this the whole sequence would start
# again, concurrently, against the wrong window.
_started = False

_results = []
_state = {}


def _write_report(final=None):
    lines = [
        "{} {}{}".format(
            "PASS" if ok else "FAIL", name, f" - {detail}" if detail else ""
        )
        for name, ok, detail in _results
    ]
    if final is not None:
        lines.append(final)
    with open(REPORT, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def _record(name, ok, detail=""):
    _results.append((name, ok, detail))
    sys.stderr.write(
        "SHUTDOWN-PROBE: {} {}{}\n".format(
            "PASS" if ok else "FAIL", name, f" - {detail}" if detail else ""
        )
    )
    sys.stderr.flush()
    _write_report()


def _finish():
    failed = any(not ok for _, ok, _ in _results)
    _write_report("FAILED" if failed else f"READY {SCENARIO}")
    sys.stderr.write(f"SHUTDOWN-PROBE: {'FAILED' if failed else 'READY'} {SCENARIO}\n")
    sys.stderr.flush()


def _md(name, body):
    """Write a Markdown file to disk and hand back its path.

    Content always arrives via the filesystem, never by editing a buffer:
    an unsaved document makes xed raise its own "save changes?" dialog at
    close, which nothing here can dismiss, and which would stall exactly
    the shutdown this probe exists to observe.
    """
    path = os.path.join(TMPDIR, name)
    with open(path, "w") as handle:
        handle.write(body)
    return path


def _open_tab(window, name, body):
    return window.create_tab_from_location(
        Gio.File.new_for_path(_md(name, body)), None, 0, False, True
    )


def _controller(tab):
    view = tab.get_view()
    return getattr(view, CONTROLLER_ATTRIBUTE, None) if view is not None else None


def _check_live_preview(label, tabs):
    """Assert every tab really is sitting in Preview with a built WebView.

    Skipped in control mode, where there is no plugin to have built one.
    This is the guard against a vacuous pass: a scenario that quietly
    failed to build any preview would otherwise shut down perfectly
    cleanly and prove nothing at all.
    """
    if CONTROL:
        return
    missing = []
    for index, tab in enumerate(tabs):
        controller = _controller(tab)
        if controller is None or controller.preview is None:
            missing.append(f"{index}:no-controller-or-preview")
        elif not controller.preview.widget.get_visible():
            missing.append(f"{index}:preview-not-visible")
        elif controller.frame.get_visible():
            missing.append(f"{index}:source-frame-still-visible")
    _record(f"{label}-previews-live", not missing, ", ".join(missing))


def _check_torn_down(label, views):
    if CONTROL:
        return
    leaked = [i for i, view in enumerate(views) if hasattr(view, CONTROLLER_ATTRIBUTE)]
    _record(f"{label}-controllers-released", not leaked, f"leaked: {leaked!r}")


# --- scenarios ----------------------------------------------------------
#
# Each is a list of (delay_before_this_step_ms, callable). The callable
# gets the probe instance. Delays are generous: a WebView load is async and
# a preview that has not finished loading is not the state these scenarios
# claim to be shutting down from.


def _scenario_close_tab(probe):
    """One Markdown tab, previewing, closed by hand. Then shutdown."""

    def open_it():
        _state["tab"] = _open_tab(probe.window, "close-tab.md", "# Close me\n\nBody.\n")
        _state["view"] = _state["tab"].get_view()

    def verify_then_close():
        _check_live_preview("close-tab", [_state["tab"]])
        probe.window.close_tab(_state["tab"])

    def verify_gone():
        _check_torn_down("close-tab", [_state["view"]])
        _check_live_preview("close-tab-remaining", [probe.window.get_active_tab()])

    return [(2500, open_it), (2000, verify_then_close), (1200, verify_gone)]


def _scenario_close_many_tabs(probe):
    """Four Markdown tabs opened, all previewing, then all closed."""

    def open_them():
        _state["tabs"] = [
            _open_tab(probe.window, f"many-{i}.md", f"# Tab {i}\n\nBody {i}.\n")
            for i in range(4)
        ]
        _state["views"] = [tab.get_view() for tab in _state["tabs"]]

    def verify():
        _check_live_preview("close-many", _state["tabs"])

    def close_them():
        # One at a time, the way a user clicks four close buttons -- not a
        # single close_all_tabs(), which takes a different code path in xed
        # and would not exercise the per-tab teardown this is aimed at.
        for tab in _state["tabs"]:
            probe.window.close_tab(tab)

    def verify_gone():
        _check_torn_down("close-many", _state["views"])

    return [
        (2500, open_them),
        (3000, verify),
        (500, close_them),
        (1500, verify_gone),
    ]


def _scenario_multi_window(probe):
    """Two real xed windows, Markdown previewing in both, closed by the runner."""

    def build():
        app = Xed.App.get_default()
        second = app.create_window(None)
        second.show_all()
        _state["second"] = second
        _state["tabs"] = [
            _open_tab(probe.window, "win1.md", "# Window one\n\nBody.\n"),
            _open_tab(second, "win2-a.md", "# Window two A\n\nBody.\n"),
            _open_tab(second, "win2-b.md", "# Window two B\n\nBody.\n"),
        ]

    def verify():
        _check_live_preview("multi-window", _state["tabs"])

    return [(2500, build), (3500, verify)]


def _scenario_move_tab(probe):
    """A tab moved between windows, then the active tab switched.

    This exact order -- move, then switch away from and back to another tab
    -- is the sequence that provokes the one allowlisted xed-core
    assertion, so it is reproduced faithfully here rather than being
    avoided.
    """

    def build():
        app = Xed.App.get_default()
        second = app.create_window(None)
        second.show_all()
        _state["second"] = second
        _state["original"] = probe.window.get_active_tab()
        _state["seed"] = _open_tab(second, "move-seed.md", "# Seed\n\nBody.\n")
        _state["movable"] = _open_tab(
            probe.window, "movable.md", "# Movable\n\nBody.\n"
        )
        _state["extra"] = _open_tab(probe.window, "stay.md", "# Stays put\n\nBody.\n")

    def move():
        _check_live_preview("move-tab-before", [_state["movable"], _state["extra"]])
        source = _state["movable"].get_parent()
        dest = _state["seed"].get_parent()
        _record("move-tab-notebooks-found", source is not None and dest is not None)
        if source is not None and dest is not None:
            source.move_tab(dest, _state["movable"], -1)

    def switch_tabs():
        # The second half of the provoking sequence, and it has to be away
        # AND BACK: switching once is not enough to reproduce the known
        # xed-core assertion (verified -- a single switch shuts down
        # silently). Getting this wrong would leave the allowlist untested
        # and this scenario quietly weaker than the bug it is aimed at.
        probe.window.set_active_tab(_state["extra"])
        probe.window.set_active_tab(_state["original"])

    def verify():
        _check_live_preview("move-tab-after", [_state["movable"], _state["extra"]])

    return [(2500, build), (3000, move), (1500, switch_tabs), (1200, verify)]


def _scenario_disable_plugin(probe):
    """xedown switched off through the same gsettings key Preferences uses."""

    def open_them():
        _state["tabs"] = [
            _open_tab(probe.window, f"disable-{i}.md", f"# Tab {i}\n\nBody.\n")
            for i in range(2)
        ]
        _state["views"] = [tab.get_view() for tab in _state["tabs"]]

    def verify_before():
        _check_live_preview("disable", _state["tabs"])

    def disable():
        settings = Gio.Settings.new("org.x.editor.plugins")
        active = settings.get_strv("active-plugins")
        settings.set_strv("active-plugins", [p for p in active if p != "xedown"])

    def verify_after():
        _check_torn_down("disable", _state["views"])
        if not CONTROL:
            # The source editor must be handed back, in every tab -- a tab
            # left showing a destroyed preview would be a broken window at
            # shutdown, not a clean one.
            hidden = []
            for index, tab in enumerate(_state["tabs"]):
                children = tab.get_children()
                frame = children[0] if children else None
                if frame is None or not frame.get_visible():
                    hidden.append(index)
            _record("disable-source-frames-returned", not hidden, f"hidden: {hidden!r}")

    return [
        (2500, open_them),
        (3000, verify_before),
        (500, disable),
        (2500, verify_after),
    ]


def _scenario_preview_active(probe):
    """Three Markdown tabs, every one of them previewing, closed as-is.

    The plainest scenario, and the one the older probe could never reach:
    nothing is disabled, nothing is closed by hand, the previews are live
    and on screen when the close request arrives.

    Every scenario here now closes with a live `Gio.FileMonitor` on each
    Markdown tab, because `watch_external_changes` is on by default -- so a
    monitor that outlived its controller would show up in any of them, with
    no change to any scenario.

    A settle timer still *armed* at close is deliberately NOT reached here,
    and cannot be. Arming one means writing the document's file from outside,
    and xed then refuses to close that tab without asking the user first --
    it checks the file when the view takes focus, marks the tab
    externally-modified, and raises a prompt no scripted scenario can answer,
    so the window never closes. That is xed's own behaviour rather than
    xedown's: this scenario was run with `XEDOWN_CONTROL=1`, the plugin
    uninstalled entirely, and hung in exactly the same way. The timer's
    teardown is covered instead by `FileWatch.stop()` being unconditional in
    `deactivate()`, which every scenario above exercises.
    """

    def open_them():
        _state["tabs"] = [probe.window.get_active_tab()] + [
            _open_tab(probe.window, f"live-{i}.md", f"# Live {i}\n\nBody.\n")
            for i in range(2)
        ]

    def verify():
        _check_live_preview("preview-active", _state["tabs"])

    return [(2500, open_them), (3500, verify)]


SCENARIOS = {
    "close-tab": _scenario_close_tab,
    "close-many-tabs": _scenario_close_many_tabs,
    "multi-window": _scenario_multi_window,
    "move-tab": _scenario_move_tab,
    "disable-plugin": _scenario_disable_plugin,
    "preview-active": _scenario_preview_active,
}


class XedownShutdownProbe(GObject.Object, Xed.WindowActivatable):
    __gtype_name__ = "XedownShutdownProbe"

    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _started
        if _started:
            return
        _started = True
        builder = SCENARIOS.get(SCENARIO)
        if builder is None:
            _record("unknown-scenario", False, SCENARIO)
            _finish()
            return
        self._steps = builder(self)
        self._schedule(0)

    def do_deactivate(self):
        pass

    def do_update_state(self):
        pass

    def _schedule(self, index):
        delay, _ = self._steps[index]
        GLib.timeout_add(delay, self._make_runner(index))

    def _make_runner(self, index):
        def run():
            _, step = self._steps[index]
            try:
                step()
            except Exception:  # noqa: BLE001 - a crash must become a FAIL, not silence
                _record(f"crash-in-step-{index}", False, traceback.format_exc())
                _finish()
                return False
            if index + 1 < len(self._steps):
                self._schedule(index + 1)
            else:
                _finish()
            return False

        return run
