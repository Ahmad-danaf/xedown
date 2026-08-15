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

import itertools
import os
import sys
import weakref

# Before every other import that could reach xedown: the wrap has to see
# the plugin's first connection, and `install()` is a no-op once xedown is
# already loaded. This file's own xedown import sits inside a function
# body, so module-import time is early enough -- checked, not assumed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from leakcheck import hooks as leakhooks

leakhooks.install()

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


# `_watch_label` gives `_check_live_preview` and `_check_torn_down` a shared,
# stable name for a tab, keyed by the tab's own View -- reachable from both
# (via `tab.get_view()` on one side, handed directly on the other) -- rather
# than by its position in whatever list either call happens to be iterating.
# Positional labels break the moment the two calls see lists of different
# length: multi-window watches three tabs and tears down two, and under the
# old `webview:{index}`/`docstate:{index}` scheme the second window's own
# re-watch (`close_second_window`, indices 0 and 1 again) silently overwrote
# window one's entries while leaving one of window two's stranded -- watched
# forever, never released.
#
# A bare `id(view)` was considered and rejected: it is a memory address, and
# nothing here guarantees a later object never reuses one a dead, already-
# released view held. A counter, assigned once per view the first time it is
# watched and remembered here for the view's lifetime, does not have that
# problem. The mapping is a weak one, matching `watch_object`'s own rule --
# an id cache that pinned the views it names would itself be a leak.
_watch_ids = weakref.WeakKeyDictionary()
_watch_id_seq = itertools.count()


def _watch_label(view, prefix):
    watch_id = _watch_ids.get(view)
    if watch_id is None:
        watch_id = next(_watch_id_seq)
        _watch_ids[view] = watch_id
    return f"{prefix}:{watch_id}"


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
        else:
            view = tab.get_view()
            leakhooks.watch_object(
                controller.preview.widget, _watch_label(view, "webview")
            )
            # The spec's "stale document state" bullet, made concrete. A
            # DocumentState still reachable after teardown means the
            # controller is too, and with it the view and its buffer.
            leakhooks.watch_object(controller.state, _watch_label(view, "docstate"))
    _record(f"{label}-previews-live", not missing, ", ".join(missing))


def _check_torn_down(label, views):
    if CONTROL:
        return
    leaked = [i for i, view in enumerate(views) if hasattr(view, CONTROLLER_ATTRIBUTE)]
    _record(f"{label}-controllers-released", not leaked, f"leaked: {leaked!r}")
    for view in views:
        leakhooks.release_object(_watch_label(view, "webview"))
        leakhooks.release_object(_watch_label(view, "docstate"))


def _audit(label, since=None):
    """Assert nothing outlived the teardown just performed.

    Skipped in control mode, where there is no plugin to have leaked.
    `hooks.audit()` collects garbage first, so a Python-side cycle that the
    collector can break is not reported as a leak.

    `since`, if given, is a checkpoint from `leakhooks.checkpoint()` taken
    before the scenario built the thing it is about to tear down -- without
    it, every audit reports every still-live resource in the process,
    including ones a different, still-open tab or window legitimately
    holds. See tests/unit/test_leak_ledger.py.
    """
    if CONTROL:
        return
    findings = leakhooks.audit(since=since)
    _record(
        f"{label}-no-leaks",
        not findings,
        leakhooks.format_findings(findings),
    )


# --- scenarios ----------------------------------------------------------
#
# Each is a list of (delay_before_this_step_ms, callable). The callable
# gets the probe instance. Delays are generous: a WebView load is async and
# a preview that has not finished loading is not the state these scenarios
# claim to be shutting down from.


def _scenario_close_tab(probe):
    """One Markdown tab, previewing, closed by hand. Then shutdown."""

    def open_it():
        # Before this scenario's own tab exists, so the audit below is
        # scoped to what THIS scenario acquires -- not the runner's own
        # tab, already open in this window before the probe did anything.
        _state["checkpoint"] = leakhooks.checkpoint()
        _state["tab"] = _open_tab(probe.window, "close-tab.md", "# Close me\n\nBody.\n")
        _state["view"] = _state["tab"].get_view()

    def verify_then_close():
        _check_live_preview("close-tab", [_state["tab"]])
        probe.window.close_tab(_state["tab"])

    def verify_gone():
        _check_torn_down("close-tab", [_state["view"]])
        # Before the remaining-tab check below: that check calls
        # `_check_live_preview` too, which would `watch_object` the
        # survivor's WebView under its own fresh, never-released label -- a
        # legitimately-alive record, inside this checkpoint's scope, that
        # the audit would otherwise report as this scenario's own leak of a
        # tab nothing here ever intends to close.
        _audit("close-tab", since=_state["checkpoint"])
        _check_live_preview("close-tab-remaining", [probe.window.get_active_tab()])

    return [(2500, open_it), (2000, verify_then_close), (1200, verify_gone)]


def _scenario_close_many_tabs(probe):
    """Twelve Markdown tabs opened, all previewing, then all closed.

    The spec's "10+ tabs" requirement. Delays are widened over the original
    four-tab version, not shortened anywhere: twelve WebViews take longer to
    build, and twelve controllers take longer to tear down, than four.
    """

    def open_them():
        # Before any of this scenario's own tabs exist, so the audit below
        # is scoped to what THIS scenario acquires -- not the runner's own
        # tab, already open in this window before the probe did anything.
        _state["checkpoint"] = leakhooks.checkpoint()
        _state["tabs"] = [
            _open_tab(probe.window, f"many-{i}.md", f"# Tab {i}\n\nBody {i}.\n")
            for i in range(12)
        ]
        _state["views"] = [tab.get_view() for tab in _state["tabs"]]

    def verify():
        _check_live_preview("close-many", _state["tabs"])

    def close_them():
        # One at a time, the way a user clicks twelve close buttons -- not a
        # single close_all_tabs(), which takes a different code path in xed
        # and would not exercise the per-tab teardown this is aimed at.
        for tab in _state["tabs"]:
            probe.window.close_tab(tab)

    def verify_gone():
        _check_torn_down("close-many", _state["views"])
        _audit("close-many", since=_state["checkpoint"])

    return [
        (2500, open_them),
        (9000, verify),
        (500, close_them),
        (4500, verify_gone),
    ]


def _scenario_multi_window(probe):
    """Two real xed windows, Markdown previewing in both.

    The first window is left as-is for the runner to close, the way a user
    closing xed with several windows open actually ends -- but the second
    is closed here, gracefully (`window.close()`, never `.destroy()` -- see
    this module's own docstring), so the scenario can audit its own
    teardown instead of ending before anything has actually torn down.
    """

    def build():
        _state["tabs"] = [_open_tab(probe.window, "win1.md", "# Window one\n\nBody.\n")]
        # Checkpointed here: after window one's tab (never torn down by
        # this scenario -- the runner closes it afterward, like any other
        # still-open window) but before window two, or either of ITS tabs,
        # exist. Checkpointing any later -- e.g. in close_second_window(),
        # after both of window two's TabControllers have already been
        # built -- would put every connect()/timeout_add() their
        # construction made below the checkpoint's sequence number,
        # permanently out of `findings(since=...)`'s scope. That is exactly
        # the population a forgotten disconnect would show up in, so this
        # audit would end up checking only the close itself, blind to the
        # thing it exists to catch.
        _state["checkpoint"] = leakhooks.checkpoint()
        app = Xed.App.get_default()
        second = app.create_window(None)
        second.show_all()
        _state["second"] = second
        _state["tabs"] += [
            _open_tab(second, "win2-a.md", "# Window two A\n\nBody.\n"),
            _open_tab(second, "win2-b.md", "# Window two B\n\nBody.\n"),
        ]
        _state["second_tabs"] = _state["tabs"][1:]
        _state["second_views"] = [tab.get_view() for tab in _state["second_tabs"]]

    def verify():
        _check_live_preview("multi-window", _state["tabs"])
        # Window one is left open for the runner to close afterward, never
        # torn down by this scenario -- but the call above just watched its
        # webview and DocumentState too, as a side effect of confirming ITS
        # preview is live in the same pass as window two's. Release that
        # watch right away: with per-view labels now stable (see
        # `_watch_label`) rather than positional, nothing later collides
        # with it and overwrites it away by accident, so left alone it would
        # sit inside the checkpoint's scope, unreleased and alive for the
        # rest of this scenario, and `verify_gone`'s audit would read it as
        # a leak of a tab nothing here ever intends to close.
        first_view = _state["tabs"][0].get_view()
        leakhooks.release_object(_watch_label(first_view, "webview"))
        leakhooks.release_object(_watch_label(first_view, "docstate"))

    def close_second_window():
        # Re-watches window two's tabs specifically -- matching what
        # `_check_torn_down` below releases -- rather than relying on the
        # "multi-window" watch above. Labels are stable per view now, so
        # this just re-records the same two entries `verify` already made;
        # it no longer matters that both calls index `second_tabs`/`tabs`
        # differently.
        _check_live_preview("multi-window-second", _state["second_tabs"])
        _state["second"].close()

    def verify_gone():
        _check_torn_down("multi-window", _state["second_views"])
        _audit("multi-window", since=_state["checkpoint"])

    return [
        (2500, build),
        (3500, verify),
        (500, close_second_window),
        (1500, verify_gone),
    ]


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
        # Captured before the move: `verify_focus_watch_moved` below needs
        # to tell "still watching the window the tab left" apart from
        # "watching the window the tab is in now", and after the move
        # nothing else records which window that was.
        _state["origin_window"] = probe.window
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

    def verify_focus_watch_moved():
        # The controller deliberately SURVIVES a tab move -- this scenario
        # must never assert teardown. What it asserts instead is that the
        # "set-focus" watch followed the tab: the old window's connection
        # was dropped and a new one made against the window the tab is in
        # now. A leak and a functional regression share a symptom here -- if
        # the old window still held the handler, Escape would stop closing
        # the search bar for that tab AND the old window would be pinning a
        # controller that should be free to go when that window closes.
        controller = _controller(_state["movable"])
        window = controller._toplevel() if controller is not None else None
        _record(
            "move-tab-controller-survived",
            controller is not None and controller.preview is not None,
        )
        _record(
            "move-tab-focus-watch-follows-the-tab",
            controller is not None and controller._focus_window is window,
            f"watching {controller and controller._focus_window!r}, tab is in {window!r}",
        )
        _record(
            "move-tab-old-window-released",
            controller is not None
            and controller._focus_window is not _state.get("origin_window"),
        )
        # No leakhooks._audit here: nothing in this scenario is ever torn
        # down (the controller and every tab it touches deliberately
        # survive), so there is no checkpoint placement that both (a)
        # includes anything meaningful and (b) doesn't guarantee a finding
        # -- the moved tab's now-permanent post-move focus-watch connection
        # is legitimately alive and would show up as one no matter where a
        # checkpoint were taken. The three assertions above -- "the
        # controller survived", "the watch follows the tab", "the old
        # window let go" -- ARE this scenario's audit; see design doc
        # docs/superpowers/specs/2026-08-14-lifecycle-stress-design.md
        # §6.2: "move-tab's audit asserts the focus watch was re-pointed to
        # the new window and released from the old one."

    return [
        (2500, build),
        (3000, move),
        (1500, switch_tabs),
        (1200, verify),
        (1000, verify_focus_watch_moved),
    ]


def _scenario_disable_plugin(probe):
    """xedown switched off through the same gsettings key Preferences uses."""

    def open_them():
        # Before this scenario's own tabs exist, so the audit in
        # verify_registries_empty is scoped to what THIS scenario acquires
        # -- not the runner's own tab, already open in this window before
        # the probe did anything (that tab's controller is torn down by
        # `disable()` too, but the registry checks below cover it globally,
        # unscoped, so the scoped audit does not need to).
        _state["checkpoint"] = leakhooks.checkpoint()
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

    def verify_registries_empty():
        # Disabling the plugin tears down every controller in the process
        # -- the strictest of the three Task 4 scenarios, so this is where
        # the registries must be provably empty, globally, not just for
        # this scenario's own two tabs.
        if CONTROL:
            return
        from xedown import controller as xedown_controller
        from xedown import imagescheme

        _record(
            "disable-plugin-live-controllers-empty",
            not xedown_controller._live_controllers,
            f"{len(xedown_controller._live_controllers)} left",
        )
        _record(
            "disable-plugin-failure-listeners-empty",
            not imagescheme._failure_listeners,
            f"{len(imagescheme._failure_listeners)} left",
        )
        _audit("disable-plugin", since=_state["checkpoint"])

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
        verify_registries_empty()

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

    The last step reaches the one state nothing else here does: a settle
    timer still *armed* when the close request arrives. A timer that outlived
    `deactivate()` would fire into a torn-down controller, and it is the only
    branch of `FileWatch._cancel_settle` that is ever taken -- every other
    scenario stops an unarmed watch, so deleting that call would pass them
    all.

    It arms the timer by poking the monitor's own handler rather than by
    writing the file, and the distinction is the whole reason this works.
    Writing the document's file from outside makes xed refuse to close that
    tab without asking the user: it checks the file when the view takes
    focus, marks the tab externally-modified, and raises a prompt no scripted
    scenario can answer, so the window never closes. That is xed's own
    behaviour rather than xedown's -- this scenario was run with
    `XEDOWN_CONTROL=1`, the plugin uninstalled entirely, and hung in exactly
    the same way. Poking the handler leaves the file untouched, so xed has
    nothing to object to, while xedown's timer is armed exactly as a real
    write would have armed it.
    """

    def open_them():
        _state["tabs"] = [probe.window.get_active_tab()] + [
            _open_tab(probe.window, f"live-{i}.md", f"# Live {i}\n\nBody.\n")
            for i in range(2)
        ]

    def verify():
        _check_live_preview("preview-active", _state["tabs"])

    def arm_settle_timer():
        # Not asserted in control mode: there is no plugin to arm.
        if CONTROL:
            return
        controller = _controller(_state["tabs"][1])
        watch = getattr(controller, "_watch", None)
        if watch is None:
            _record("preview-active-timer-armed", False, "no watch to arm")
            return
        watch._on_changed()
        _record(
            "preview-active-timer-armed",
            watch._settle_source != 0,
            "the close below must arrive with a settle timer still pending",
        )

    # 100ms, well inside FileWatch's 300ms settle: the runner asks the window
    # to close as soon as this returns READY.
    return [(2500, open_them), (3500, verify), (100, arm_settle_timer)]


def _scenario_settings_window(probe):
    """Open and close the settings window five times, then close as-is.

    The leak this exists to catch is not visible in any other scenario: the
    panel holds a settings-store token and a stylesheet-watcher token, and
    both stores outlive every window. One missed disconnect keeps the panel,
    the window and everything they reference alive for the life of the
    process, and five rounds make a per-open leak obvious rather than
    marginal.

    The last round is left OPEN when the close request arrives, so the path
    where the window is destroyed by xed's own teardown -- rather than by the
    user clicking Close -- is the one under test at shutdown.
    """

    def cycle():
        if CONTROL:
            return
        from xedown.prefswindow import SettingsWindow

        for _ in range(5):
            window = SettingsWindow(probe.window)
            panel = window.panel
            window.destroy()
            if panel._settings_token is not None or panel._settle:
                _record(
                    "settings-window-cycle-clean",
                    False,
                    f"token={panel._settings_token!r} timers={panel._settle!r}",
                )
                return
        _record("settings-window-cycle-clean", True, "five opens, five clean closes")

    def leave_one_open():
        if CONTROL:
            return
        from xedown.prefswindow import SettingsWindow

        _state["settings_window"] = SettingsWindow(probe.window)
        _record(
            "settings-window-open-at-shutdown",
            _state["settings_window"].get_visible(),
            "the close request below arrives with the window still up",
        )

    return [(2500, cycle), (600, leave_one_open)]


def _scenario_close_with_fetches_in_flight(probe):
    """Several remote images, permitted, pointed at a real hung fetch.

    `imagescheme.shutdown()` (added Task 15, wired to the last controller
    tearing down) cancels only work still QUEUED --
    `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)`'s own
    contract. Anything already RUNNING keeps running regardless, and the
    interpreter's own `atexit` hook joins those threads either way, so a
    close request that lands mid-fetch can delay the process exiting by up
    to `remoteimages.MAX_TOTAL_S` (15s), the wall-clock deadline on one whole
    fetch. `TIMEOUT_S` (5s) is the socket timeout and bounds a single read,
    not the transfer -- a server that keeps dribbling never trips it, which
    is why the deadline exists. This scenario exists to confirm that
    close still completes CLEANLY within that bound -- not that it completes
    instantly, which it does not and is not supposed to.

    `httpbingo.org` -- a public mirror of the well-known httpbin.org test
    service -- is used deliberately, for the same reason the live probe's
    remote-image steps use it: a plain local server is refused by design
    (`remoteimages.check_destination` only accepts a public destination), so
    a real public HTTPS server is the only way to exercise a real,
    genuinely outstanding fetch rather than a stub. Its `/delay/10` endpoint
    guarantees the fetch is still running, not merely queued, when the
    close request arrives -- `verify_outstanding` below checks that
    directly, so this scenario cannot pass vacuously by racing a fetch that
    happened to already settle.
    """

    def open_and_permit():
        if CONTROL:
            _state["tab"] = _open_tab(
                probe.window,
                "fetches-in-flight.md",
                "# Fetches in flight\n\nBody.\n",
            )
            return
        # Four separate URLs -- MAX_CONCURRENT is 4 -- so this is four
        # genuinely outstanding fetches, not one.
        body = "# Fetches in flight\n\n" + "\n\n".join(
            f"![never resolves {i}]"
            f"(https://httpbingo.org/delay/10?probe=shutdown-{i})"
            for i in range(4)
        )
        _state["tab"] = _open_tab(probe.window, "fetches-in-flight.md", body)
        controller = _controller(_state["tab"])
        if controller is not None:
            controller._on_load_images_requested(controller.modebar)

    def verify_outstanding():
        _check_live_preview("fetches-in-flight", [_state["tab"]])
        if CONTROL:
            return
        from xedown import imagescheme

        fetcher = imagescheme.get_fetcher()
        outstanding = [u for u in fetcher._waiting if "probe=shutdown-" in u]
        _record(
            "fetches-in-flight-actually-outstanding",
            len(outstanding) > 0,
            f"waiting: {sorted(fetcher._waiting)!r}",
        )

    # The runner closes the window as soon as this scenario reports READY,
    # which is immediately after verify_outstanding -- so the close request
    # arrives well inside the 5s window the fetches above were started in.
    return [(2500, open_and_permit), (3000, verify_outstanding)]


def _scenario_settings_configurable(probe):
    """The plugin manager's route, five times, then closed as-is.

    Separate from the scenario above because the two hosts release the panel
    differently: ours destroys it from a window close, peas destroys it with a
    dialog we never see. A panel that only cleans up when its window closes
    would pass `settings-window` and leak here.
    """

    def cycle():
        if CONTROL:
            return
        from gi.repository import Peas, PeasGtk

        engine = Peas.Engine.get_default()
        info = engine.get_plugin_info("xedown")
        if info is None:
            _record("configurable-cycle-clean", False, "peas does not know xedown")
            return
        for _ in range(5):
            extension = engine.create_extension(
                info, PeasGtk.Configurable.__gtype__, [], []
            )
            widget = extension.create_configure_widget()
            widget.destroy()
            if widget._settings_token is not None or widget._settle:
                _record(
                    "configurable-cycle-clean",
                    False,
                    f"token={widget._settings_token!r} timers={widget._settle!r}",
                )
                return
        _record("configurable-cycle-clean", True, "five widgets, five clean destroys")

    return [(2500, cycle)]


def _scenario_re_enable(probe):
    """Disable xedown, turn it back on, and use it again in one session.

    The process-wide registrations survive a disable -- `register_once` is
    idempotent for the life of the process and `imagescheme.shutdown()`
    leaves `get_fetcher()` able to build a fresh one. Both facts are load
    bearing for this cycle and neither has ever been exercised.

    The audit runs right after the "before" tab's teardown is confirmed and
    before the plugin comes back -- not at the very end, after a SECOND tab
    has been opened and deliberately left open. `_check_live_preview`'s
    watch_object side effect would put that second tab's own construction
    inside the checkpoint's scope with nothing left in this scenario ever
    releasing it, which is exactly the trap `close-tab`'s own "-remaining"
    check sidesteps by running after its audit rather than before it.
    """

    def open_it():
        _state["checkpoint"] = leakhooks.checkpoint()
        _state["tab"] = _open_tab(probe.window, "re-enable.md", "# Before\n\nBody.\n")
        _state["view"] = _state["tab"].get_view()

    def disable_it():
        _check_live_preview("re-enable-before", [_state["tab"]])
        from gi.repository import Peas

        _state["engine"] = Peas.Engine.get_default()
        _state["plugin"] = _state["engine"].get_plugin_info("xedown")
        _state["engine"].unload_plugin(_state["plugin"])

    def verify_disabled():
        _check_torn_down("re-enable", [_state["view"]])
        _audit("re-enable", since=_state["checkpoint"])
        _state["engine"].load_plugin(_state["plugin"])

    def verify_enabled_again():
        # A fresh tab, not the old one: peas does not re-activate a
        # ViewActivatable for a view that already existed when the plugin
        # was loaded, which is xed's behaviour and not xedown's to fix.
        _state["tab2"] = _open_tab(probe.window, "re-enable-2.md", "# After\n\nBody.\n")

    def verify_works():
        _check_live_preview("re-enable-after", [_state["tab2"]])

    return [
        (2500, open_it),
        (2000, disable_it),
        (1500, verify_disabled),
        (1500, verify_enabled_again),
        (2500, verify_works),
    ]


PHASE = os.environ.get("XEDOWN_SHUTDOWN_PHASE", "")


def _scenario_restart(probe):
    """Close xed, start it again, and check what did and did not survive.

    Phase 1 leaves two documents in different modes and grants remote
    images to one of them. Phase 2 relaunches against the same config
    directory and checks the modes came back and the grant did not.

    The grant assertion is a REGRESSION GUARD, not a bug hunt.
    `controller._remote_unblocked` is a plain instance field, so it already
    dies with the controller and today's behaviour is correct. It is
    asserted because that correctness is currently accidental: nothing
    records it as a requirement, and a change that moved the grant into the
    settings store would be a real security regression with no test to
    catch it.

    No `leakhooks._audit` anywhere in this scenario, for the same reason
    `move-tab` has none: documents 'a' and 'b' are left open for the whole
    of whichever phase is running -- nothing here is ever torn down -- so
    there is no checkpoint placement that both (a) includes anything
    meaningful and (b) doesn't guarantee a finding. Every connection either
    tab's own construction made is still alive and still unreleased at
    every point after it, precisely because it is still doing its job.
    """
    a_path = os.path.join(TMPDIR, "restart-a.md")
    b_path = os.path.join(TMPDIR, "restart-b.md")

    def phase_one_open():
        for path, title in ((a_path, "A"), (b_path, "B")):
            if not os.path.exists(path):
                with open(path, "w") as handle:
                    handle.write(
                        f"# {title}\n\n![remote](https://example.invalid/x.png)\n"
                    )
        _state["a"] = probe.window.create_tab_from_location(
            Gio.File.new_for_path(a_path), None, 0, False, True
        )
        _state["b"] = probe.window.create_tab_from_location(
            Gio.File.new_for_path(b_path), None, 0, False, True
        )

    def phase_one_arrange():
        from xedown import settings as xedown_settings
        from xedown.document_state import Mode

        # Load-bearing for this whole scenario: if remembering is off,
        # nothing set below ever reaches disk, and phase 2 would pass by
        # accident -- finding the *default* mode in both tabs and reading
        # that as "remembered" rather than confirming persistence at all.
        _record(
            "restart-remember-mode-per-file-on",
            xedown_settings.get_settings().get(xedown_settings.REMEMBER_MODE_PER_FILE),
            "REMEMBER_MODE_PER_FILE is off; phase 1's mode changes were never stored",
        )
        a = _controller(_state["a"])
        b = _controller(_state["b"])
        if a is not None:
            a.set_mode(Mode.PREVIEW)
            a._on_load_images_requested(None)
        if b is not None:
            b.set_mode(Mode.SOURCE)
        _record("restart-phase1-arranged", a is not None and b is not None)

    def phase_two_check():
        from xedown.document_state import Mode

        a = _controller(_state["a"])
        b = _controller(_state["b"])
        _record(
            "restart-remembered-preview",
            a is not None and a.state.mode is Mode.PREVIEW,
            f"a is {a and a.state.mode}",
        )
        _record(
            "restart-remembered-source",
            b is not None and b.state.mode is Mode.SOURCE,
            f"b is {b and b.state.mode}",
        )
        _record(
            "restart-remote-grant-did-not-persist",
            a is not None and not a._remote_unblocked,
            "a per-tab remote-image grant survived a restart",
        )

    if PHASE == "2":
        return [(3000, phase_one_open), (3000, phase_two_check)]
    return [(2500, phase_one_open), (2500, phase_one_arrange)]


def _scenario_cycle(probe):
    """Open and close a Markdown tab twenty times, then stand aside.

    The assertions that matter here are made by the runner, on the process
    tree, before and after. This scenario's own job is only to perform the
    churn and prove it actually happened -- a cycle test that silently
    failed to build any preview would leave a beautifully flat memory graph
    and prove nothing.
    """
    built = {"count": 0}

    def one_cycle():
        tab = _open_tab(probe.window, "cycle.md", "# Cycle\n\nBody.\n")
        _state["cycle_tab"] = tab

    def start():
        # Before the first cycle's own tab exists, so the audit in done()
        # is scoped to what this scenario's churn acquires -- not the
        # runner's own tab, already open in this window before the probe
        # did anything.
        _state["checkpoint"] = leakhooks.checkpoint()
        one_cycle()

    def close_cycle():
        tab = _state.get("cycle_tab")
        controller = _controller(tab) if tab is not None else None
        if controller is not None and controller.preview is not None:
            built["count"] += 1
        if tab is not None:
            probe.window.close_tab(tab)

    def done():
        _record(
            "cycle-previews-built",
            built["count"] >= 18,
            f"only {built['count']} of 20 cycles built a preview",
        )
        _audit("cycle", since=_state["checkpoint"])

    steps = [(2500, start)]
    for _ in range(19):
        steps.append((900, close_cycle))
        steps.append((900, one_cycle))
    steps.append((900, close_cycle))
    steps.append((1500, done))
    return steps


SCENARIOS = {
    "close-tab": _scenario_close_tab,
    "close-many-tabs": _scenario_close_many_tabs,
    "multi-window": _scenario_multi_window,
    "move-tab": _scenario_move_tab,
    "disable-plugin": _scenario_disable_plugin,
    "preview-active": _scenario_preview_active,
    "settings-window": _scenario_settings_window,
    "settings-configurable": _scenario_settings_configurable,
    "close-with-fetches-in-flight": _scenario_close_with_fetches_in_flight,
    "re-enable": _scenario_re_enable,
    "restart": _scenario_restart,
    "cycle": _scenario_cycle,
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
