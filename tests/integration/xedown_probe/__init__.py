"""Drives a real xed instance through the scenarios CI cannot reach.

This is a scripted `Xed.WindowActivatable`: each step runs on a
`GLib.timeout_add` callback, asserts something about the live widget tree,
writes the running report to disk (so a crash still leaves a partial
record), and schedules the next step. Nothing here ever calls
`window.destroy()` — that segfaults xed; `timeout(1)` in the runner ends the
process instead.

Every step is wrapped by `_guard`, which turns an uncaught exception into a
FAIL line rather than silently ending the sequence.
"""

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
results = []

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


def _lazy_imports():
    global TabController, Mode, ModeBar
    from xedown.controller import TabController as _TabController
    from xedown.document_state import Mode as _Mode
    from xedown.modebar import ModeBar as _ModeBar

    TabController, Mode, ModeBar = _TabController, _Mode, _ModeBar


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
        self._tmpdir = tempfile.mkdtemp(prefix="xedown-probe-")

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
        self._schedule(500, self.step_search)
        return False

    # --- host-state hazard: search / go-to-line while previewing -----------

    def step_search(self):
        children_before = self._children_types()
        self._activate_named_action("SearchFind")
        self._activate_named_action("SearchGoToLine")
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
        # Drives the internal hook directly: there is no practical way to
        # script a real WebView link click from here. This exercises the
        # exact path _on_link_activated -> classify_link -> _show_error that
        # a REFUSE decision takes in real use.
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
        location = self.document.get_location()
        with open(location.get_path(), "a") as handle:
            handle.write("\nAppended outside the editor.\n")
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
        self._schedule(300, self.step_multi_tab_open)
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
        self._schedule(400, self.step_txt_tab_open)
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
        self._schedule(400, self.step_disable_plugin)
        return False

    # --- disable the plugin for real, via the same gsettings key users use -

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
        record(
            "disable-no-info-bar",
            not any(isinstance(c, Gtk.InfoBar) for c in children),
        )
        record("done", True)
        return False
