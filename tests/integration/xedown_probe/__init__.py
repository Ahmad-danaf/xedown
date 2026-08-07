"""Drives a real xed instance through the scenarios CI cannot reach.

This is a scripted `Xed.WindowActivatable`: each step runs on a
`GLib.timeout_add` callback, asserts something about the live widget tree,
writes the running report to disk (so a crash still leaves a partial
record), and schedules the next step. Nothing here ever calls
`window.destroy()` — that segfaults xed. Once the sequence reaches
"PASS done", the *runner* ends the process, gracefully (a real window close,
so shutdown/plugin-unload output gets captured too) if `wmctrl` is
available, and by signal otherwise -- never from inside a callback here.

Every step is wrapped by `_guard`, which turns an uncaught exception into a
FAIL line rather than silently ending the sequence.
"""

import json
import os
import sys
import tempfile
import traceback

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gio, GLib, GObject, Gtk, WebKit2, Xed

REPORT = os.environ.get("XEDOWN_PROBE_REPORT", "/tmp/xedown-probe-report.txt")
# Nested under the runner's own mktemp workdir when run through
# scripts/run-integration-tests.sh, so a single `rm -rf` of that workdir
# cleans up the probe's fixture files too, instead of leaving a fresh
# `xedown-probe-*` directory under /tmp behind on every run.
PROBE_TMPDIR = os.environ.get("XEDOWN_PROBE_TMPDIR")
results = []
# The move-tab assertion (see step_move_tab_open) creates a second Xed.Window
# to move a tab into. Plugins activate per-window, so this probe's own
# do_activate() fires again for that second window too; without this guard
# the whole scripted sequence would start a second, concurrent time against
# the wrong window (this is exactly what happened in early throwaway
# diagnostics for this fix, before the guard was added).
_sequence_started = False

# `TabController`, `Mode` and `ModeBar` are resolved lazily by `_lazy_imports`,
# not imported here at module load time. libpeas's python3 loader treats an
# already-present `sys.modules["xedown"]` entry as a name collision and
# refuses to load the real `xedown` plugin under it: since libpeas's plugin
# load order across the two `active-plugins` entries is not guaranteed to
# match the gsettings list order, an `import xedown...` at this module's own
# top level can race ahead of libpeas loading `xedown` itself and win that
# race, permanently breaking the very plugin this probe exists to drive. By
# the time `step_setup` runs (2500ms after activation), libpeas's own
# per-window plugin activation has long since finished for every entry in
# `active-plugins`, so `xedown` is already loaded under its own name and this
# module can safely reuse it.
TabController = None
Mode = None
ModeBar = None
xedown_settings = None


def _lazy_imports():
    global TabController, Mode, ModeBar, xedown_settings
    from xedown import settings as _settings
    from xedown.controller import TabController as _TabController
    from xedown.document_state import Mode as _Mode
    from xedown.modebar import ModeBar as _ModeBar

    TabController, Mode, ModeBar = _TabController, _Mode, _ModeBar
    xedown_settings = _settings


def _format_line(name, passed, detail):
    status = "PASS" if passed else "FAIL"
    suffix = f" - {detail}" if detail else ""
    return f"{status} {name}{suffix}"


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    line = _format_line(name, passed, detail)
    sys.stderr.write(f"PROBE: {line}\n")
    sys.stderr.flush()
    with open(REPORT, "w") as handle:
        handle.write("\n".join(_format_line(n, p, d) for n, p, d in results) + "\n")


_QUICK_MD = "# Quick\n\nOpened and closed quickly to exercise teardown.\n"
_TAB_B_MD = "# Tab B\n\nA second Markdown tab; its mode must stay independent.\n"
_PLAIN_TXT = (
    "Just plain text. Not Markdown. The menu action must be insensitive here.\n"
)
# A fence whose exact bytes the clipboard assertion compares against,
# including the Arabic comments -- the case most likely to regress, since
# code must stay left-to-right while its comments are right-to-left.
_COPY_CODE = "# هذه دالة بسيطة\n" "def total(items):\n" "    return sum(items)\n"
_COPY_MD = (
    "# Copy\n\n```python\n"
    + _COPY_CODE
    + "```\n\n"
    + "| a | b | c | d | e | f | g | h | i | j |\n"
    + "| - | - | - | - | - | - | - | - | - | - |\n"
    + "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |\n"
)


def _long_markdown():
    """Content tall enough to give a real scroll range at any window size."""
    paragraphs = "\n\n".join(
        f"Paragraph {i}. Filler text to build page height. " * 3 for i in range(120)
    )
    return "# Scroll Test\n\n" + paragraphs + "\n"


class XedownProbe(GObject.Object, Xed.WindowActivatable):
    __gtype_name__ = "XedownProbe"

    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        global _sequence_started
        if _sequence_started:
            return
        _sequence_started = True
        GLib.timeout_add(2500, self._guard(self.step_setup))

    def do_deactivate(self):
        pass

    def do_update_state(self):
        pass

    # --- infrastructure ------------------------------------------------

    def _guard(self, fn):
        def run():
            try:
                return fn()
            except Exception:  # noqa: BLE001 - a crash must become a FAIL, not silence
                record(f"probe-crashed-in-{fn.__name__}", False, traceback.format_exc())
                return False

        return run

    def _schedule(self, delay_ms, fn):
        GLib.timeout_add(delay_ms, self._guard(fn))
        return False

    def _controller_for(self, view):
        return getattr(view, "_xedown_controller", None) if view is not None else None

    def _main_controller(self):
        return self._controller_for(self.view)

    def _preview_visible_for(self, controller):
        return (
            controller is not None
            and controller.preview is not None
            and controller.preview.widget.get_visible()
            and not controller.frame.get_visible()
        )

    def _preview_visible(self):
        return self._preview_visible_for(self._main_controller())

    def _buffer_text(self, document=None):
        document = document or self.document
        start, end = document.get_bounds()
        return document.get_text(start, end, False)

    def _children_types(self):
        return [type(child).__name__ for child in self.tab.get_children()]

    def _find_action(self, name):
        for group in self.window.get_ui_manager().get_action_groups():
            action = group.get_action(name)
            if action is not None:
                return action
        return None

    def _activate_named_action(self, name):
        action = self._find_action(name)
        if action is not None:
            action.activate()
        return action

    # --- setup -----------------------------------------------------------

    def step_setup(self):
        _lazy_imports()
        self.tab = self.window.get_active_tab()
        self.view = self.tab.get_view()
        self.document = self.tab.get_document()
        self._tmpdir = tempfile.mkdtemp(dir=PROBE_TMPDIR, prefix="xedown-probe-")

        controller = self._main_controller()
        record("controller-created", controller is not None)
        record(
            "controller-is-tabcontroller-instance",
            isinstance(controller, TabController),
        )
        record("preview-is-default", self._preview_visible())
        record("modebar-at-index-0", self.tab.get_children()[0] is controller.modebar)
        self._schedule(500, self.step_save)
        return False

    # --- host-state hazard: save -----------------------------------------

    def step_save(self):
        self.document.set_text("# Probe\n\nEdited by the integration probe.\n")
        Xed.commands_save_document(self.window, self.document)
        self._schedule(2000, self.step_after_save)
        return False

    def step_after_save(self):
        controller = self._main_controller()
        record("save-frame-hidden", not controller.frame.get_visible())
        record("save-preview-visible", controller.preview.widget.get_visible())
        record(
            "save-modebar-index0",
            self.tab.get_children()[0] is controller.modebar,
        )
        self._activate_named_action("FileRevert")
        self._schedule(2500, self.step_after_revert)
        return False

    # --- host-state hazard: revert -----------------------------------------

    def step_after_revert(self):
        controller = self._main_controller()
        record("revert-frame-hidden", not controller.frame.get_visible())
        record("revert-preview-visible", controller.preview.widget.get_visible())
        record(
            "revert-modebar-index0",
            self.tab.get_children()[0] is controller.modebar,
        )
        self._schedule(400, self.step_showall_preview)
        return False

    # --- host-state hazard: tab.show_all() in PREVIEW mode -----------------

    def step_showall_preview(self):
        self.tab.show_all()
        controller = self._main_controller()
        record("showall-preview-frame-hidden", not controller.frame.get_visible())
        record(
            "showall-preview-widget-visible", controller.preview.widget.get_visible()
        )
        self._schedule(300, self.step_switch_to_source)
        return False

    # --- host-state hazard: tab.show_all() in MARKDOWN/SOURCE mode ---------

    def step_switch_to_source(self):
        self._main_controller().toggle()
        self._schedule(400, self.step_showall_source)
        return False

    def step_showall_source(self):
        self.tab.show_all()
        controller = self._main_controller()
        preview_hidden = not controller.preview.widget.get_visible()
        frame_visible = controller.frame.get_visible()
        record("showall-source-preview-hidden", preview_hidden)
        record("showall-source-frame-visible", frame_visible)
        record(
            "showall-source-no-split",
            not (
                controller.frame.get_visible()
                and controller.preview.widget.get_visible()
            ),
        )
        self._schedule(300, self.step_back_to_preview)
        return False

    def step_back_to_preview(self):
        self._main_controller().toggle()
        self._schedule(500, self.step_anchor_link_setup)
        return False

    # --- real link click: F1 regression guard -------------------------------
    #
    # WebKit never delivers a bare `#fragment` for an in-page anchor click --
    # it resolves the href against the page's own URI first, which used to
    # make every anchor link (including every footnote reference, since the
    # footnotes extension is on by default) get misrouted to the desktop
    # file opener instead of scrolling in place. `PreviewView.scroll_to_anchor`
    # and `TabController._open_with_desktop` are instrumented rather than
    # called directly, because the whole point is to prove a REAL click
    # through the WebView's own `decide-policy` round-trips correctly --
    # `run_javascript("...click();")` can script exactly that.

    def step_anchor_link_setup(self):
        controller = self._main_controller()
        self._anchor_scroll_calls = []
        self._anchor_desktop_calls = []
        self._anchor_original_scroll_to_anchor = controller.preview.scroll_to_anchor
        self._anchor_original_open_with_desktop = controller._open_with_desktop

        def _record_scroll(name):
            self._anchor_scroll_calls.append(name)
            return self._anchor_original_scroll_to_anchor(name)

        def _record_desktop(uri):
            self._anchor_desktop_calls.append(uri)

        controller.preview.scroll_to_anchor = _record_scroll
        controller._open_with_desktop = _record_desktop

        self.document.set_text(
            "# Anchor Click Test\n\n"
            "[Jump to section](#section)\n\n"
            "See the note.[^1]\n\n"
            + ("Filler paragraph to add page height. " * 20 + "\n\n") * 4
            + "## Section\n\nLanded here.\n\n"
            "[^1]: A footnote, auto-generating `#fn:1` / `#fnref:1` anchors.\n"
        )
        self._schedule(900, self.step_anchor_link_click)
        return False

    def step_anchor_link_click(self):
        controller = self._main_controller()
        controller.preview.widget.run_javascript(
            "document.querySelector('a[href=\"#section\"]').click();",
            None,
            None,
            None,
        )
        self._schedule(500, self.step_footnote_link_click)
        return False

    def step_footnote_link_click(self):
        controller = self._main_controller()
        controller.preview.widget.run_javascript(
            "document.querySelector('a[href=\"#fn:1\"]').click();",
            None,
            None,
            None,
        )
        self._schedule(500, self.step_anchor_link_check)
        return False

    def step_anchor_link_check(self):
        controller = self._main_controller()
        controller.preview.scroll_to_anchor = self._anchor_original_scroll_to_anchor
        controller._open_with_desktop = self._anchor_original_open_with_desktop
        record(
            "real-anchor-click-scrolls-in-page",
            self._anchor_scroll_calls == ["section", "fn:1"],
            f"scroll_to_anchor calls: {self._anchor_scroll_calls!r}",
        )
        record(
            "real-anchor-click-never-hits-desktop-handler",
            not self._anchor_desktop_calls,
            f"desktop handler calls: {self._anchor_desktop_calls!r}",
        )
        self._schedule(300, self.step_search)
        return False

    # --- host-state hazard: search / go-to-line while previewing -----------

    def step_search(self):
        # NOTE: in xed 3.8.9, none of the three checks below can currently
        # fail. Activating SearchFind does not force the source frame
        # visible the way save/revert do (there is no notify::state hazard
        # here to catch), and search-children-unchanged inspects the *tab's*
        # children while xed's search bar lives inside XedViewFrame, so it
        # would not see a floating search bar even if one appeared. Left in
        # as structural placeholders in case a future xed version changes
        # this, but nobody should read a green run here as live coverage of
        # "the revealer doesn't float over the preview".
        #
        # Deliberately does NOT also activate SearchGoToLine: confirmed by
        # isolated testing (SearchFind alone vs. SearchGoToLine alone, no
        # xedown installed at all) that invoking SearchGoToLine outside of a
        # real button-press event leaves xed's window in a state that
        # produces a cascade of unrelated Gtk-CRITICAL/Gdk-CRITICAL
        # assertion failures (gtk_widget_has_default, gdk_device_manager_*)
        # when the window is later closed -- a real xed-core bug, entirely
        # independent of this plugin, that would otherwise poison every
        # run's shutdown-log check with noise unrelated to what is being
        # tested here.
        children_before = self._children_types()
        self._activate_named_action("SearchFind")
        controller = self._main_controller()
        record("search-frame-hidden", not controller.frame.get_visible())
        record("search-preview-visible", controller.preview.widget.get_visible())
        record(
            "search-children-unchanged",
            self._children_types() == children_before,
            f"{children_before!r} -> {self._children_types()!r}",
        )
        self._schedule(400, self.step_infobar)
        return False

    # --- info bar: Close button must not reintroduce set_info_bar(None) ----

    def step_infobar(self):
        controller = self._main_controller()
        # Drives the internal hook directly rather than a real WebView click
        # (see step_anchor_link_setup above for that): an actual
        # `badscheme://` href would never survive the sanitizer's URI
        # allowlist to reach the DOM, so there is no real link to click here.
        # This exercises the exact path
        # _on_link_activated -> classify_link -> _show_error that a REFUSE
        # decision takes in real use.
        controller._on_link_activated("badscheme://example")
        self._info_bar = controller._info_bar
        record("infobar-created-on-refused-link", self._info_bar is not None)
        if self._info_bar is not None:
            # Simulate a real Close click: emit the InfoBar's own "response"
            # signal, exactly what GTK does internally on a button press.
            # Never call tab.set_info_bar(None) here -- that argument is
            # marshaled non-nullable and raises TypeError (the regression
            # this check exists to catch).
            self._info_bar.response(Gtk.ResponseType.CLOSE)
        self._schedule(300, self.step_infobar_check)
        return False

    def step_infobar_check(self):
        controller = self._main_controller()
        record("infobar-close-removes-bar", controller._info_bar is None)
        record(
            "infobar-close-no-leftover-child",
            not any(isinstance(c, Gtk.InfoBar) for c in self.tab.get_children()),
        )
        self._schedule(300, self.step_external_change)
        return False

    # --- external modification must not trigger a silent reload -----------

    def step_external_change(self):
        # The assertion deliberately does NOT run in this same callback.
        # Any reload path is necessarily async (a file monitor callback, at
        # minimum a main-loop turn), so a same-callback check is structurally
        # incapable of ever observing one and would pass even if the plugin
        # silently reloaded on its own. Confirmed by mutation: with a real
        # GFileMonitor-based auto-reload temporarily added to TabController,
        # asserting here still printed PASS while a diagnostic 400ms later
        # showed the buffer had, in fact, been reloaded. step_external_change_check
        # runs a full second later instead, giving a real reload time to land.
        location = self.document.get_location()
        with open(location.get_path(), "a") as handle:
            handle.write("\nAppended outside the editor.\n")
        self._schedule(1200, self.step_external_change_check)
        return False

    def step_external_change_check(self):
        record(
            "no-independent-reload",
            "Appended outside" not in self._buffer_text(),
            "the plugin must not reload the buffer on its own",
        )
        self._schedule(400, self.step_content_integrity)
        return False

    # --- content integrity: viewing never mutates the buffer ---------------

    def step_content_integrity(self):
        controller = self._main_controller()
        controller.toggle()
        record("toggle-to-source-shows-frame", controller.frame.get_visible())
        text_before = self._buffer_text()
        controller.toggle()
        record("toggle-to-preview-shows-webview", self._preview_visible())
        record("text-unchanged-by-viewing", self._buffer_text() == text_before)
        self._schedule(500, self.step_scroll_setup)
        return False

    # --- scroll round trip ---------------------------------------------

    def step_scroll_setup(self):
        # A tall document while still in Preview mode: the buffer-changed
        # signal schedules an in-place body refresh (not a reload), so this
        # does not by itself perturb scroll reporting.
        self.document.set_text(_long_markdown())
        self._schedule(700, self.step_scroll_set)
        return False

    def step_scroll_set(self):
        self._main_controller().preview.set_scroll(0.5)
        self._schedule(700, self.step_scroll_read)
        return False

    def step_scroll_read(self):
        controller = self._main_controller()
        self._scroll_baseline = controller.preview.last_scroll
        record(
            "scroll-set-succeeded",
            0.3 <= self._scroll_baseline <= 0.7,
            f"last_scroll={self._scroll_baseline!r}",
        )
        Xed.commands_save_document(self.window, self.document)
        self._schedule(900, self.step_scroll_after_save)
        return False

    def step_scroll_after_save(self):
        # load_document() unconditionally resets last_scroll to 0.0, so if a
        # save ever triggers a full page reload this immediately shows up
        # here as a drop to 0.0 rather than "near" the baseline.
        controller = self._main_controller()
        current = controller.preview.last_scroll
        record(
            "save-preserves-preview-scroll",
            current > 0.05 and abs(current - self._scroll_baseline) < 0.2,
            f"baseline={self._scroll_baseline!r} current={current!r}",
        )
        controller.toggle()  # -> SOURCE
        self._schedule(400, self.step_scroll_edit)
        return False

    def step_scroll_edit(self):
        self.document.insert_at_cursor("X", -1)
        self._schedule(300, self.step_scroll_toggle_back)
        return False

    def step_scroll_toggle_back(self):
        self._main_controller().toggle()  # -> PREVIEW, forces a full reload
        self._schedule(1600, self.step_scroll_verify)
        return False

    def step_scroll_verify(self):
        controller = self._main_controller()
        current = controller.preview.last_scroll
        record(
            "scroll-round-trip-preserved",
            current > 0.05 and abs(current - self._scroll_baseline) < 0.25,
            f"baseline={self._scroll_baseline!r} current={current!r}",
        )
        self._schedule(400, self.step_quick_tab_open)
        return False

    # --- lifecycle: open a tab and close it quickly -------------------

    def step_quick_tab_open(self):
        path = os.path.join(self._tmpdir, "quick.md")
        with open(path, "w") as handle:
            handle.write(_QUICK_MD)
        self._quick_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._quick_view = self._quick_tab.get_view()
        self._schedule(400, self.step_quick_tab_close)
        return False

    def step_quick_tab_close(self):
        self.window.close_tab(self._quick_tab)
        self._schedule(600, self.step_quick_tab_verify)
        return False

    def step_quick_tab_verify(self):
        # The tab widget is gone; get_children() can no longer be asked
        # about it. The equivalent, checkable fact is that
        # XedownViewActivatable.do_deactivate() ran during teardown: the
        # controller attribute is fully removed (delattr, not None) from
        # the view object, which itself remains a valid Python object after
        # the underlying GTK widget is destroyed.
        record(
            "quick-tab-controller-cleaned-up",
            not hasattr(self._quick_view, "_xedown_controller"),
        )
        self._schedule(300, self.step_move_tab_open)
        return False

    # --- moving a tab to another window must NOT tear the controller down --
    #
    # xed emits "tab-removed" on the SOURCE window both for a real close and
    # for Documents -> Move to New Window / dragging a tab out
    # (xed_notebook_move_tab): the tab is re-added to the destination
    # window's notebook, synchronously, and the view survives. An earlier
    # version of the tab-removed fix above did not distinguish the two and
    # silently destroyed the preview on every move -- trading the close-time
    # leak it fixed for an equally silent regression. This is the assertion
    # that would have caught it (and does, against that earlier version: it
    # prints FAIL controller-survives-tab-move / widgets after move:
    # ['XedViewFrame'] instead of the three widgets below).

    def step_move_tab_open(self):
        path = os.path.join(self._tmpdir, "movable.md")
        with open(path, "w") as handle:
            handle.write("# Movable\n\nMoved to another window mid-sequence.\n")
        self._move_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._move_view = self._move_tab.get_view()
        self._schedule(1000, self.step_move_tab_prepare_destination)
        return False

    def step_move_tab_prepare_destination(self):
        record(
            "move-tab-controller-present-before-move",
            hasattr(self._move_view, "_xedown_controller"),
        )
        # A second real window is the only way to exercise a genuine
        # Notebook.move_tab(); nothing here calls window.destroy() on either
        # window, so this stays inside the "never destroy from a callback"
        # rule. XedownProbe.do_activate() also fires for this new window,
        # guarded off by the module-level _sequence_started flag above.
        app = Xed.App.get_default()
        self._move_dest_window = app.create_window(None)
        self._move_dest_window.show_all()
        seed_path = os.path.join(self._tmpdir, "move-dest-seed.md")
        with open(seed_path, "w") as handle:
            handle.write("# Destination window seed\n")
        self._move_dest_seed_tab = self._move_dest_window.create_tab_from_location(
            Gio.File.new_for_path(seed_path), None, 0, False, True
        )
        self._schedule(1000, self.step_move_tab_execute)
        return False

    def step_move_tab_execute(self):
        source_notebook = self._move_tab.get_parent()
        dest_notebook = self._move_dest_seed_tab.get_parent()
        record(
            "move-tab-notebooks-found",
            source_notebook is not None and dest_notebook is not None,
        )
        if source_notebook is not None and dest_notebook is not None:
            source_notebook.move_tab(dest_notebook, self._move_tab, -1)
        self._schedule(1500, self.step_move_tab_verify)
        return False

    def step_move_tab_verify(self):
        has_attr = hasattr(self._move_view, "_xedown_controller")
        record(
            "controller-survives-tab-move",
            has_attr,
            "a moved tab's controller must survive the source window's "
            "tab-removed signal, exactly like a real close must not leak it",
        )
        if has_attr:
            controller = self._move_view._xedown_controller
            widgets = [type(c).__name__ for c in self._move_tab.get_children()]
            record(
                "move-tab-widgets-intact",
                {"ModeBar", "WebView", "XedViewFrame"} <= set(widgets),
                f"widgets after move: {widgets!r}",
            )
            record(
                "move-tab-still-in-preview-mode",
                self._preview_visible_for(controller),
                "the mode, not just the controller object, must survive too",
            )
        self._schedule(400, self.step_multi_tab_open)
        return False

    # --- multiple independent Markdown tabs -----------------------------

    def step_multi_tab_open(self):
        path = os.path.join(self._tmpdir, "tabb.md")
        with open(path, "w") as handle:
            handle.write(_TAB_B_MD)
        self._tab_b = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(1200, self.step_multi_tab_check)
        return False

    def step_multi_tab_check(self):
        view_b = self._tab_b.get_view()
        controller_a = self._main_controller()
        controller_b = self._controller_for(view_b)
        record(
            "multi-tab-distinct-controllers",
            isinstance(controller_b, TabController)
            and controller_b is not controller_a,
        )
        controller_b.toggle()  # tab B -> SOURCE; tab A must stay PREVIEW
        record(
            "multi-tab-mode-independence",
            controller_a.state.mode is Mode.PREVIEW
            and controller_b.state.mode is Mode.SOURCE,
            f"a={controller_a.state.mode!r} b={controller_b.state.mode!r}",
        )
        self._schedule(400, self.step_settings_broadcast)
        return False

    # --- settings reach every open tab, in every window --------------------
    #
    # The claim unit tests structurally cannot make: that every controller
    # alive in this process is actually subscribed to the one shared store.
    # Subscription is checked by the identity of each listener's bound-method
    # owner rather than by counting, because the destination window the
    # move-tab check created has controllers of its own -- a count would pass
    # while the wrong controllers were subscribed.
    #
    # The handler itself has no body yet (brief 2 fills it in), so there is
    # nothing observable to assert about a controller *receiving* a change.
    # A probe-owned listener therefore proves the broadcast runs, and the
    # identity check proves who is on it. Together that is the real claim;
    # neither half is worth reading on its own.

    def step_settings_broadcast(self):
        store = xedown_settings.get_settings()
        self._settings_store = store

        controllers = [
            self._main_controller(),
            self._controller_for(self._tab_b.get_view()),
            self._controller_for(self._move_view),
        ]
        controllers = [c for c in controllers if c is not None]
        record(
            "settings-three-controllers-alive",
            len(controllers) == 3,
            f"{len(controllers)} of 3 controllers found",
        )
        subscribed = [
            controller
            for controller in controllers
            if any(
                getattr(callback, "__self__", None) is controller
                for callback in store._listeners.values()
            )
        ]
        record(
            "settings-every-open-tab-subscribed",
            len(subscribed) == len(controllers),
            f"{len(subscribed)} of {len(controllers)} controllers subscribed",
        )

        deliveries = []
        token = store.connect(deliveries.append)
        changed = store.set(xedown_settings.CONTENT_WIDTH_REM, 61)
        store.disconnect(token)

        record("settings-set-reports-a-change", changed is True, f"set -> {changed!r}")
        record(
            "settings-broadcast-delivered",
            deliveries == [frozenset({xedown_settings.CONTENT_WIDTH_REM})],
            f"deliveries: {deliveries!r}",
        )
        record(
            "settings-value-readable-after-set",
            store.get(xedown_settings.CONTENT_WIDTH_REM) == 61,
            f"value: {store.get(xedown_settings.CONTENT_WIDTH_REM)!r}",
        )
        record(
            "settings-written-to-the-scratch-store",
            store.write_error is None and store.path.exists(),
            f"write_error={store.write_error!r} path={store.path}",
        )
        self._schedule(400, self.step_theme_switch)
        return False

    # --- a theme change reaches every open preview, in every window --------
    #
    # Brief 2's real claim, and the one unit tests structurally cannot make:
    # every live controller picks the new theme up, and the page in the
    # WebView actually carries it. Reading the class back out is
    # asynchronous, so it lands in the step after this one -- the field
    # changing on its own would not prove the page reloaded.
    #
    # This is also where the store is put back to its defaults. Brief 1's
    # broadcast step leaves content_width_rem at 61, which is inert while
    # nothing reads it and would quietly render every later step at a
    # non-default width once brief 4 lands.

    def step_theme_switch(self):
        store = xedown_settings.get_settings()
        store.set(xedown_settings.PREVIEW_THEME, "focused")
        controllers = [
            self._main_controller(),
            self._controller_for(self._tab_b.get_view()),
            self._controller_for(self._move_view),
        ]
        controllers = [c for c in controllers if c is not None]
        switched = [
            c
            for c in controllers
            if getattr(getattr(c, "_style", None), "theme", None) == "focused"
        ]
        record(
            "theme-every-open-tab-switched",
            len(controllers) == 3 and len(switched) == 3,
            f"{len(switched)} of {len(controllers)} controllers on focused",
        )
        self._schedule(700, self.step_theme_switch_check)
        return False

    def step_theme_switch_check(self):
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record("theme-page-carries-the-theme-class", False, "no preview")
            self._schedule(300, self.step_metrics_live)
            return False

        def on_result(webview, result, _user_data):
            try:
                value = webview.run_javascript_finish(result)
                class_name = value.get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                class_name = f"<error: {exc}>"
            record(
                "theme-page-carries-the-theme-class",
                "xedown-theme-focused" in class_name,
                f"body class: {class_name!r}",
            )
            self._schedule(300, self.step_metrics_live)

        preview.widget.run_javascript("document.body.className", None, on_result, None)
        return False

    # --- width and size reach the loaded page without a reload -------------
    #
    # The one thing that cannot be asserted from Python: whether WebKit's CSP
    # lets a nonce-only style-src coexist with a programmatic CSSOM write.
    # Reading the *computed* value back is the difference between observing
    # that and merely claiming it.

    def step_metrics_live(self):
        store = xedown_settings.get_settings()
        store.set(xedown_settings.CONTENT_WIDTH_REM, 72)
        controllers = [
            self._main_controller(),
            self._controller_for(self._tab_b.get_view()),
            self._controller_for(self._move_view),
        ]
        controllers = [c for c in controllers if c is not None]
        applied = [
            c
            for c in controllers
            if getattr(getattr(c, "_style", None), "content_width_rem", None) == 72
        ]
        record(
            "metrics-every-open-tab-updated",
            len(controllers) == 3 and len(applied) == 3,
            f"{len(applied)} of {len(controllers)} controllers at 72rem",
        )
        self._schedule(600, self.step_metrics_check)
        return False

    def step_metrics_check(self):
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record("metrics-page-reflowed-without-a-reload", False, "no preview")
            self._schedule(300, self.step_stylesheet_apply)
            return False

        def on_result(webview, result, _user_data):
            try:
                value = webview.run_javascript_finish(result)
                computed = value.get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                computed = f"<error: {exc}>"
            record(
                "metrics-page-reflowed-without-a-reload",
                "72rem" in computed,
                f"--xedown-content-width: {computed!r}",
            )
            self._schedule(300, self.step_stylesheet_apply)

        preview.widget.run_javascript(
            "getComputedStyle(document.documentElement)"
            ".getPropertyValue('--xedown-content-width').trim()",
            None,
            on_result,
            None,
        )
        return False

    # --- a custom stylesheet applies, re-applies on save, and fails safely --

    def _probe_stylesheet_path(self):
        store = xedown_settings.get_settings()
        return store.path.parent / "probe.css"

    def _write_probe_stylesheet(self, marker):
        """Write the probe stylesheet the way an editor does: rename over it.

        Most editors save by writing a temporary file and renaming it onto
        the target, which replaces the inode. If the watcher only ever saw
        writes in place, this is the case that would quietly stop working.
        """
        target = self._probe_stylesheet_path()
        temp = target.with_name(target.name + ".tmp")
        temp.write_text(
            f".xedown-document {{ --xedown-probe: {marker}; }}\n", encoding="utf-8"
        )
        os.replace(temp, target)
        return target

    def step_stylesheet_apply(self):
        target = self._write_probe_stylesheet("first")
        store = xedown_settings.get_settings()
        store.set(xedown_settings.CUSTOM_STYLESHEET, str(target))
        self._schedule(800, self.step_stylesheet_check)
        return False

    def step_stylesheet_check(self):
        self._read_probe_marker(
            "stylesheet-applied-over-the-theme", "first", self.step_stylesheet_resave
        )
        return False

    def step_stylesheet_resave(self):
        self._write_probe_stylesheet("second")
        # The watcher debounces 150ms, then reloads the page; load_html is
        # itself asynchronous. This waits for both.
        self._schedule(1200, self.step_stylesheet_resave_check)
        return False

    def step_stylesheet_resave_check(self):
        self._read_probe_marker(
            "stylesheet-resave-refreshed-the-preview",
            "second",
            self.step_stylesheet_delete,
        )
        return False

    def _read_probe_marker(self, name, expected, next_step):
        """Read --xedown-probe out of the live page, then continue."""
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record(name, False, "no preview")
            self._schedule(300, next_step)
            return

        def on_result(webview, result, _user_data):
            try:
                value = webview.run_javascript_finish(result)
                marker = value.get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                marker = f"<error: {exc}>"
            record(name, marker.strip() == expected, f"--xedown-probe: {marker!r}")
            self._schedule(300, next_step)

        preview.widget.run_javascript(
            "getComputedStyle(document.getElementById('xedown-content'))"
            ".getPropertyValue('--xedown-probe').trim()",
            None,
            on_result,
            None,
        )

    def step_stylesheet_delete(self):
        removed, detail = True, ""
        try:
            self._probe_stylesheet_path().unlink()
        except OSError as exc:
            removed, detail = False, str(exc)
        # Recorded either way: a line that only appears on failure makes a
        # green report and a step that never ran look identical.
        record("stylesheet-probe-file-removed", removed, detail)
        self._schedule(1200, self.step_stylesheet_deleted_check)
        return False

    def step_stylesheet_deleted_check(self):
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record("stylesheet-deletion-shows-a-notice", False, "no preview")
            self._restore_settings()
            return False

        def on_result(webview, result, _user_data):
            notice, children, failure = "", 0, ""
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
                notice = payload.get("notice") or ""
                children = payload.get("children") or 0
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                failure = f"<error: {exc}>"
            record(
                "stylesheet-deletion-shows-a-notice",
                "probe.css" in notice and "not applied" in notice,
                f"notice: {notice!r}{failure}",
            )
            # The article is always emitted, and the notice is its sibling, so a
            # child count of zero means the document itself did not render --
            # which is also what an error page looks like. Reading the notice
            # text alone could not tell those apart from a blank page: the JS
            # degrades to '' rather than throwing, so the old assertion passed
            # for exactly the failure it was named after.
            record(
                "stylesheet-deletion-leaves-the-document-rendered",
                children > 0 and not failure,
                f"content children: {children}{failure}",
            )
            self._restore_settings()

        preview.widget.run_javascript(
            "JSON.stringify({"
            "notice: (document.querySelector('.xedown-notice') || {}).textContent || '',"
            "children: (document.getElementById('xedown-content')"
            " || {children: []}).children.length"
            "})",
            None,
            on_result,
            None,
        )
        return False

    def _restore_settings(self):
        """Hand the store back at its defaults, then carry on."""
        store = xedown_settings.get_settings()
        store.reset()
        width = xedown_settings.CONTENT_WIDTH_REM
        sheet = xedown_settings.CUSTOM_STYLESHEET
        record(
            "theme-settings-restored-to-defaults",
            store.get(xedown_settings.PREVIEW_THEME) == "repository"
            and store.get(width) == xedown_settings.by_name(width).default
            and store.get(sheet) is None,
            f"theme={store.get(xedown_settings.PREVIEW_THEME)!r} "
            f"width={store.get(width)!r} stylesheet={store.get(sheet)!r}",
        )
        self._schedule(300, self.step_copy_tab_open)

    # --- the copy button: the clipboard round trip cannot be unit-tested ---

    def step_copy_tab_open(self):
        path = os.path.join(self._tmpdir, "copy.md")
        with open(path, "w") as handle:
            handle.write(_COPY_MD)
        self._copy_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(1500, self.step_copy_click)
        return False

    def _copy_preview(self):
        view = self._copy_tab.get_view()
        controller = getattr(view, "_xedown_controller", None)
        return controller.preview if controller is not None else None

    def step_copy_click(self):
        preview = self._copy_preview()
        if preview is None:
            record("copy-button-present", False, "no preview")
            self._schedule(300, self.step_txt_tab_open)
            return False

        def on_result(webview, result, _user_data):
            found = ""
            try:
                found = webview.run_javascript_finish(result).get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                found = f"<error: {exc}>"
            record("copy-button-present", found == "1", f"buttons: {found}")
            self._schedule(900, self.step_copy_verify)

        # Clicked from script rather than synthesised as a pointer event:
        # what is under test is the message round trip, not GTK's hit
        # testing. The count is returned so a missing button fails here
        # rather than silently passing the clipboard check below.
        preview.widget.run_javascript(
            "(function () {"
            "  var b = document.querySelectorAll('.xedown-copy');"
            "  if (b.length) { b[0].click(); }"
            "  return String(b.length);"
            "})()",
            None,
            on_result,
            None,
        )
        return False

    def step_copy_verify(self):
        preview = self._copy_preview()
        clipboard = Gtk.Clipboard.get_default(preview.widget.get_display())
        copied = clipboard.wait_for_text() or ""
        # Byte for byte, including the Arabic comment. The fence's closing
        # newline is a delimiter, not code, so it is not copied.
        record(
            "clipboard-holds-exactly-the-authors-code",
            copied == _COPY_CODE.rstrip("\n"),
            f"copied {copied!r}",
        )

        def on_result(webview, result, _user_data):
            payload, failure = {}, ""
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                failure = f"<error: {exc}>"
            record(
                "copy-button-never-joins-a-selection",
                "Copy" not in (payload.get("selection") or "") and not failure,
                f"selection length: {len(payload.get('selection') or '')}{failure}",
            )
            record(
                "a-wide-table-scrolls-inside-its-own-area",
                bool(payload.get("tableOverflows")) and not failure,
                f"table: {payload.get('tableScroll')} > {payload.get('tableClient')}"
                f"{failure}",
            )
            record(
                "a-wide-table-never-scrolls-the-page-sideways",
                bool(payload.get("pageFits")) and not failure,
                f"page: {payload.get('pageScroll')} <= {payload.get('pageWidth')}"
                f"{failure}",
            )
            self._schedule(300, self.step_copy_disable)

        preview.widget.run_javascript(
            "(function () {"
            "  document.execCommand('selectAll');"
            "  var s = String(window.getSelection());"
            "  window.getSelection().removeAllRanges();"
            "  var w = document.querySelector('.xedown-table-scroll') ||"
            "          {scrollWidth: 0, clientWidth: 0};"
            "  var d = document.documentElement;"
            "  return JSON.stringify({"
            "    selection: s,"
            "    tableScroll: w.scrollWidth, tableClient: w.clientWidth,"
            "    tableOverflows: w.scrollWidth > w.clientWidth,"
            "    pageScroll: d.scrollWidth, pageWidth: window.innerWidth,"
            "    pageFits: d.scrollWidth <= window.innerWidth + 1"
            "  });"
            "})()",
            None,
            on_result,
            None,
        )
        return False

    def step_copy_disable(self):
        xedown_settings.get_settings().set(xedown_settings.CODE_COPY_BUTTONS, False)
        self._schedule(600, self.step_copy_disabled_check)
        return False

    def step_copy_disabled_check(self):
        preview = self._copy_preview()

        def on_result(webview, result, _user_data):
            found = ""
            try:
                found = webview.run_javascript_finish(result).get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                found = f"<error: {exc}>"
            # Removed from the DOM, not merely hidden: nothing left to
            # focus, find or copy. And with no reload -- this page was
            # never loaded again.
            record(
                "copy-buttons-off-removes-them-live", found == "0", f"buttons: {found}"
            )
            xedown_settings.get_settings().set(xedown_settings.CODE_COPY_BUTTONS, True)
            self.window.close_tab(self._copy_tab)
            self._schedule(500, self.step_txt_tab_open)

        preview.widget.run_javascript(
            "String(document.querySelectorAll('.xedown-copy').length)",
            None,
            on_result,
            None,
        )
        return False

    # --- menu sensitivity: is_sensitive(), never get_sensitive() -----------

    def step_txt_tab_open(self):
        path = os.path.join(self._tmpdir, "plain.txt")
        with open(path, "w") as handle:
            handle.write(_PLAIN_TXT)
        self._txt_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(800, self.step_txt_tab_activate)
        return False

    def step_txt_tab_activate(self):
        self.window.set_active_tab(self._txt_tab)
        self._txt_tab.get_view().grab_focus()
        self._schedule(700, self.step_txt_sensitivity)
        return False

    def step_txt_sensitivity(self):
        action = self._find_action("XedownToggleAction")
        record("xedown-action-exists", action is not None)
        if action is not None:
            # get_sensitive() always reads True regardless of menu state --
            # only is_sensitive() reflects the action GROUP sensitivity that
            # do_update_state() actually toggles.
            record("menu-insensitive-on-txt", not action.is_sensitive())
        self.window.set_active_tab(self.tab)
        self.view.grab_focus()
        self._schedule(700, self.step_md_sensitivity)
        return False

    def step_md_sensitivity(self):
        action = self._find_action("XedownToggleAction")
        if action is not None:
            record("menu-sensitive-on-md", action.is_sensitive())
        self._schedule(400, self.step_disable_prep_infobar)
        return False

    # --- disable the plugin for real, via the same gsettings key users use -

    def step_disable_prep_infobar(self):
        # By the time step_disable_check used to run, the probe's earlier
        # info bar (step_infobar, ~20s and many steps back) had long since
        # been closed, so "no leftover info bar" only ever checked an
        # already-empty state -- it could not fail even with
        # _dismiss_info_bar() deleted from TabController.deactivate()
        # (confirmed by mutation: that deletion still printed
        # PASS disable-no-info-bar). Raise a genuinely live bar right before
        # disabling so the check has something real to fail on.
        controller = self._main_controller()
        controller._on_link_activated("badscheme://before-disable")
        self._pre_disable_info_bar = controller._info_bar
        record(
            "infobar-live-immediately-before-disable",
            self._pre_disable_info_bar is not None,
        )
        self._schedule(300, self.step_disable_plugin)
        return False

    def step_disable_plugin(self):
        settings = Gio.Settings.new("org.x.editor.plugins")
        active = settings.get_strv("active-plugins")
        settings.set_strv("active-plugins", [p for p in active if p != "xedown"])
        self._schedule(1800, self.step_disable_check)
        return False

    def step_disable_check(self):
        record(
            "controller-attr-absent-after-disable",
            not hasattr(self.view, "_xedown_controller"),
        )
        # The controller is gone, so the source frame -- xed's own view
        # container, not something xedown created -- has to be re-found by
        # position rather than through a (now torn down) controller.
        children = self.tab.get_children()
        frame = children[0] if children else None
        record("disable-frame-visible", frame is not None and frame.get_visible())
        record(
            "disable-noshowall-cleared",
            frame is not None and not frame.get_no_show_all(),
        )
        record(
            "disable-no-xedown-widget",
            not any(isinstance(c, (WebKit2.WebView, ModeBar)) for c in children),
        )
        # Checks the SPECIFIC bar the probe raised in
        # step_disable_prep_infobar by identity (destroyed widgets report no
        # parent), not "is any Gtk.InfoBar present" -- xed shows its own
        # info bars too (e.g. "file changed on disk"), so a type-only check
        # would both miss a real leftover xedown bar sitting behind one of
        # those, and false-positive on a legitimate xed prompt that has
        # nothing to do with this plugin.
        bar = getattr(self, "_pre_disable_info_bar", None)
        record(
            "disable-no-info-bar",
            bar is not None and bar.get_parent() is None,
        )
        # Every controller in every window is torn down by a plugin disable,
        # so nothing may still be subscribed. The store is a long-lived
        # global: anything left here is a controller (and its WebView,
        # document and tab) leaked for the life of the process. This is the
        # only place that fact is observable.
        store = getattr(self, "_settings_store", None)
        record(
            "disable-no-settings-listeners-left",
            store is not None and not store._listeners,
            f"listeners left: {sorted(getattr(store, '_listeners', {}))!r}",
        )
        self._schedule(300, self.step_settle_before_exit)
        return False

    def step_settle_before_exit(self):
        # The scroll-round-trip step (step_scroll_edit) deliberately left
        # `self.document` modified, and it is never saved again afterwards.
        # The runner asks xed to close for real once this sequence finishes,
        # so it can capture window-close/plugin-unload output too -- but
        # closing a window with unsaved documents pops up xed's own "save
        # changes?" dialog, which nothing here can dismiss, hanging the
        # close indefinitely until the runner's SIGTERM fallback kills it.
        # Save everything, in both windows the move-tab check created, so
        # the close the runner requests next can actually complete.
        Xed.commands_save_all_documents(self.window)
        if getattr(self, "_move_dest_window", None) is not None:
            Xed.commands_save_all_documents(self._move_dest_window)
        self._schedule(500, self.step_close_secondary_window)
        return False

    def step_close_secondary_window(self):
        # `.close()` (a graceful "please close" request through xed's normal
        # delete-event path -- the same thing a click on the window's own
        # close button sends, and NOT `.destroy()`, which segfaults xed from
        # inside a callback) rather than leaving the move-tab check's second
        # window open for the runner to deal with. Tidies up this test's own
        # footprint before the runner asks the (one, now) remaining window
        # to close for real, rather than leaving multiple windows for it to
        # juggle for no reason relevant to any assertion above.
        dest = getattr(self, "_move_dest_window", None)
        if dest is not None:
            dest.close()
        self._schedule(500, self.step_done)
        return False

    def step_done(self):
        record("done", True)
        return False
