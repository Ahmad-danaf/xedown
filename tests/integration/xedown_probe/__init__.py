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

gi.require_version("Atk", "1.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Atk, Gdk, Gio, GLib, GObject, Gtk, WebKit2, Xed

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
xedown_a11y = None
xedown_prefs = None
xedown_settings = None
xedown_shortcuts = None
xedown_stylewatcher = None
XedownWindowActivatable = None


def _lazy_imports():
    global TabController, Mode, ModeBar, xedown_a11y, xedown_prefs, xedown_settings
    global xedown_shortcuts, xedown_stylewatcher, XedownWindowActivatable
    from xedown import XedownWindowActivatable as _XedownWindowActivatable
    from xedown import a11y as _a11y
    from xedown import prefs as _prefs
    from xedown import settings as _settings
    from xedown import shortcuts as _shortcuts
    from xedown import stylewatcher as _stylewatcher
    from xedown.controller import TabController as _TabController
    from xedown.document_state import Mode as _Mode
    from xedown.modebar import ModeBar as _ModeBar

    TabController, Mode, ModeBar = _TabController, _Mode, _ModeBar
    xedown_a11y = _a11y
    xedown_prefs = _prefs
    xedown_settings = _settings
    xedown_shortcuts = _shortcuts
    xedown_stylewatcher = _stylewatcher
    XedownWindowActivatable = _XedownWindowActivatable


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
# Deliberately titled "Round Trip", not "Copy": step_copy_verify asserts the
# word "Copy" is absent from a select-all, which is what proves the button's
# `user-select: none` actually works (confirmed live: with that CSS removed,
# the same select-all picks up a second "Copy" from the button label).
# A heading that itself says "Copy" would make that assertion fail on every
# run regardless of whether the CSS is doing its job -- caught by an
# out-of-probe repro against this exact fixture before this comment was
# written, which is also how the CSS-removed case above was confirmed.
_COPY_MD = (
    "# Round Trip\n\n```python\n"
    + _COPY_CODE
    + "```\n\n"
    + "| a | b | c | d | e | f | g | h | i | j |\n"
    + "| - | - | - | - | - | - | - | - | - | - |\n"
    + "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |\n"
)


def _long_markdown():
    """Content tall enough to give a real scroll range at any window size.

    The emphasised phrase is for the search steps: in the DOM it is three
    nodes (`An `, `<strong>emphasised</strong>`, ` phrase...`), so finding
    "emphasised phrase" is only possible if the search flattens the text
    across inline boundaries rather than matching within one text node.

    The trailing fenced block is also for the search steps: highlight.js
    wraps "42" and "100" each in their own `<span>`, which leaves the four
    spaces between them as an isolated whitespace-only text node -- exactly
    the shape `search-crosses-an-inline-boundary`'s emphasis phrase is not:
    that gap sits between two elements with nothing of the query's own text
    on either side of it. Confirmed against the vendored highlight.js
    bundle (not just read from its source) that "42    100" renders as
    `<span class="hljs-number">42</span>    <span class="hljs-number">
    100</span>` -- the middle four spaces belonging to no span at all --
    and that a search for the collapsed query below marks it as three
    `<mark>` elements whose concatenated text is the original nine
    characters, spaces included. Plain digits, not "Paragraph"/"Filler", so
    it changes neither count the search steps already pin.

    The `İstanbul` line is for one specific hazard, and it sits ahead of
    everything else deliberately. U+0130 is the only character in Unicode
    whose UTF-16 length changes under `String.prototype.toLowerCase` (it
    becomes two units), so a case-insensitive search that lowercased the
    whole flattened text at once left the haystack one unit longer than the
    per-character map and shifted every match position after it. The count
    stayed correct, which is what made it invisible -- so putting this line
    FIRST puts every other search assertion in this fixture downstream of the
    shift as well, and `step_dotted_capital_check` below is the one that
    compares the marked text itself rather than only counting it. "sentinel"
    appears nowhere else in this document, and the line contains neither
    "Paragraph" nor "Filler", so it moves no count already pinned.
    """
    paragraphs = "\n\n".join(
        f"Paragraph {i}. Filler text to build page height. " * 3 for i in range(120)
    )
    return (
        "# Scroll Test\n\nAn **emphasised** phrase for the search.\n\n"
        "İstanbul stands before this sentinel.\n\n"
        + paragraphs
        + "\n\n```python\n42    100\n```\n"
    )


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

    def _window_activatable_attr(self):
        """The XedownWindowActivatable driving this window.

        Read from the attribute the plugin sets on the window: xed keeps its
        WindowActivatables in a PeasExtensionSet with no public accessor, and
        an explicit hook beats guessing at one.
        """
        return getattr(self.window, "_xedown_window_activatable", None)

    def _find_window_activatable(self):
        """The live `XedownWindowActivatable` for this probe's window.

        Neither `Xed.Window` nor `Peas.Engine` exposes the per-window
        extension set peas builds it from -- checked directly against both
        introspected APIs, nothing on either even hints at one -- so `gc` is
        the only route from here to the object Fix 2's teardown assertions
        need: the one holding the window-level key-press handler id and the
        alias accelerator bookkeeping. Same spirit as the rest of this probe
        reaching past behaviour into internal state, just one level further
        out, since the object under test lives outside this probe's own
        reference graph entirely.
        """
        import gc

        for obj in gc.get_objects():
            if isinstance(obj, XedownWindowActivatable) and obj.window is self.window:
                return obj
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
            # `info_bar_close` is otherwise unaudited: `_accessible_nodes`
            # only reaches controls that exist for the life of the tab, and
            # an info bar does not. This is the one moment a real bar --
            # not a mock, the actual widget `_set_info_bar` built -- exists
            # to be asked about, before the Close click below destroys it.
            self._audit_info_bar_close(self._info_bar)
            # Simulate a real Close click: emit the InfoBar's own "response"
            # signal, exactly what GTK does internally on a button press.
            # Never call tab.set_info_bar(None) here -- that argument is
            # marshaled non-nullable and raises TypeError (the regression
            # this check exists to catch).
            self._info_bar.response(Gtk.ResponseType.CLOSE)
        self._schedule(300, self.step_infobar_check)
        return False

    def _audit_info_bar_close(self, bar):
        """Audit the one button `step_infobar` already raises a real bar for.

        `_set_info_bar` gives this button its name from
        `a11y.NAMES["info_bar_close"]` explicitly -- it is also the one
        control whose naming crashed on this branch's first live run
        (`Gtk.InfoBar` has no `get_widget_for_response`), which is exactly
        the kind of thing `_accessible_nodes` never had a chance to catch:
        it only ever looked at controls that live for the whole tab. A
        refused link's bar (the one `step_infobar` raises) carries exactly
        one button, so the first child of its action area is unambiguous.
        """
        buttons = bar.get_action_area().get_children()
        if not buttons:
            record("a11y-info-bar-close-passes-the-standard", False, "no button found")
            record("a11y-info-bar-close-names-match-the-standard", False, "no button")
            return
        nodes = self._visible_state_nodes(bar, [("info_bar_close", buttons[0])])
        self._record_audit("a11y-info-bar-close", nodes)

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
        self._schedule(400, self.step_external_watch_setup)
        return False

    # --- changes made outside xed reach the preview, and only the preview ---
    #
    # Every write below goes through the filesystem and every assertion runs
    # a full settle window later (FileWatch.SETTLE_DELAY_MS is 300ms), for the
    # reason step_external_change already records: an update that lands
    # asynchronously cannot be observed from the callback that triggered it.

    def _document_file(self):
        return self.document.get_location().get_path()

    def _write_document_file(self, body):
        with open(self._document_file(), "w") as handle:
            handle.write(body)

    def _preview_text(self, name, needle, present, then):
        """Assert `needle` is (or is not) in the rendered document."""
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record(name, False, "no preview")
            self._schedule(300, then)
            return

        def on_result(webview, result, _user_data):
            try:
                value = webview.run_javascript_finish(result)
                body = value.get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                # A failed run_javascript must FAIL outright, not flow into
                # the `present` comparison below: with `present=False`, an
                # error string containing neither `needle` gives `(needle in
                # body) is present` == True, recording a false PASS against a
                # WebView that never actually answered.
                record(name, False, f"run_javascript failed: {exc}")
                self._schedule(300, then)
                return
            record(
                name,
                (needle in body) is present,
                f"{'expected' if present else 'did not expect'} {needle!r}",
            )
            self._schedule(300, then)

        # `textContent`, not `innerText`: it does not depend on the element
        # having been laid out, so an assertion cannot fail merely because
        # the WebView had not painted yet.
        preview.widget.run_javascript(
            "document.body.textContent", None, on_result, None
        )

    def _reconcile_without_saving(self):
        """Leave the buffer clean and the file matching it, byte for byte.

        Emphatically NOT `Xed.commands_save_document`, which the first cut of
        these steps used and which cannot work here. Every step in this
        section writes the document's file from outside, and xed's saver
        refuses to overwrite a file whose modification time has moved since
        it was loaded: it raises its own "the file has changed on disk"
        confirmation instead and parks the tab in
        `XED_TAB_STATE_SAVING_ERROR`, where `_xed_tab_save_async` refuses
        every later save for the rest of the session. That is xed behaving
        correctly -- confirmed live, twice, as a CRITICAL in xed's own log
        plus a document that could never be saved again.

        Writing the buffer's text to the file and clearing the modified flag
        by hand reaches the same end state a save would have reached, without
        asking xed to do the one thing it is entitled to refuse. The trailing
        newline is added because the buffer's implicit one is stripped on
        load and restored on save, so a file without it would not compare
        equal -- which is exactly what `diskstate.normalize` exists for.
        """
        self._write_document_file(self._buffer_text() + "\n")
        self.document.set_modified(False)

    def step_external_watch_setup(self):
        # A clean buffer whose file matches it is what makes the next write an
        # UPDATE rather than a WARN, and step_external_change deliberately
        # left the file ahead of the buffer. This gives every assertion below
        # a known starting point, whatever ran before.
        self._main_controller().set_mode(Mode.PREVIEW)
        self._reconcile_without_saving()
        self._schedule(1200, self.step_external_watch_write)
        return False

    def step_external_watch_write(self):
        record(
            "external-setup-buffer-is-clean",
            not self.document.get_modified(),
            "the reconcile did not take; later assertions would test the wrong branch",
        )
        self._write_document_file("# Rewritten outside\n\nBy something else.\n")
        self._schedule(1200, self.step_external_watch_check)
        return False

    def step_external_watch_check(self):
        record(
            "external-buffer-untouched",
            "Rewritten outside" not in self._buffer_text(),
            "the buffer must not follow the file",
        )
        self._preview_text(
            "external-preview-followed",
            "Rewritten outside",
            True,
            self.step_external_scroll_setup,
        )
        return False

    # --- the scroll survives, which is the point of an in-place update ------

    def step_external_scroll_setup(self):
        self._write_document_file("# Tall\n\n" + ("A paragraph of prose.\n\n" * 120))
        self._schedule(1400, self.step_external_scroll_set)
        return False

    def step_external_scroll_set(self):
        self._main_controller().preview.set_scroll(0.5)
        self._schedule(900, self.step_external_scroll_rewrite)
        return False

    def step_external_scroll_rewrite(self):
        self._scroll_before = self._main_controller().preview.last_scroll
        self._write_document_file(
            "# Tall\n\n" + ("A paragraph of prose.\n\n" * 120) + "Appended tail.\n"
        )
        self._schedule(1400, self.step_external_scroll_check)
        return False

    def step_external_scroll_check(self):
        after = self._main_controller().preview.last_scroll
        record(
            "external-scroll-preserved",
            abs(after - self._scroll_before) < 0.05,
            f"{self._scroll_before:.3f} -> {after:.3f}",
        )
        self._schedule(300, self.step_external_typing)
        return False

    # --- the user's own edits win, and the bar says so ---------------------

    def step_external_typing(self):
        # The explicit -1 length keeps this working whatever PyGObject does
        # with the argument's default.
        self.document.insert(self.document.get_end_iter(), "\nTyped by the user.\n", -1)
        self._schedule(1000, self.step_external_typing_check)
        return False

    def step_external_typing_check(self):
        controller = self._main_controller()
        record(
            "external-typing-shows-bar",
            controller._external_bar is not None,
            "typing over a silently-updated preview must be explained",
        )
        self._preview_text(
            "external-typing-preview-follows-buffer",
            "Typed by the user",
            True,
            self.step_external_undo,
        )
        return False

    def step_external_undo(self):
        # Back to a clean buffer without xedown touching it: the undo is the
        # document's own, exactly as a user pressing Ctrl+Z would drive it.
        self.document.undo()
        self._schedule(1000, self.step_external_undo_check)
        return False

    def step_external_undo_check(self):
        controller = self._main_controller()
        record(
            "external-undo-retires-bar",
            controller._external_bar is None,
            "a bar must not outlive the divergence it warned about",
        )
        self._schedule(300, self.step_external_reload_type)
        return False

    # --- reloading is the other way the divergence ends --------------------
    #
    # The undo above proves `_on_modified_changed`. This proves
    # `_on_document_loaded`, which is where the bar's own Reload... button
    # ends up: xed's Revert replaces the buffer, and the bar has nothing left
    # to say. No fresh external write is needed -- the undo step left
    # `_disk_text` set, so one keystroke is enough to diverge again.
    #
    # Deliberately NOT a save. Every step in this section has written the
    # document's file from outside, so xed's saver would refuse to overwrite
    # it without its own confirmation (see `_reconcile_without_saving`) --
    # which is xed working correctly, and which no scripted step can answer.
    # The modified flag is cleared by hand first for the same reason xed's
    # own revert asks before discarding: with it set, FileRevert raises a
    # modal dialog nothing here can dismiss.

    def step_external_reload_type(self):
        self.document.insert(self.document.get_end_iter(), "\nMine wins.\n", -1)
        self._schedule(900, self.step_external_reload_do)
        return False

    def step_external_reload_do(self):
        controller = self._main_controller()
        record(
            "external-typing-shows-bar-again",
            controller._external_bar is not None,
            "the bar must come back for a second divergence",
        )
        # xed's revert command acts on `xed_window_get_active_tab`, not on any
        # tab handed to it, and earlier steps in this sequence leave a second
        # tab open. Making this tab active first is what aims the command at
        # the document these assertions are about.
        self.window.set_active_tab(self.tab)
        self.document.set_modified(False)
        action = self._activate_named_action("FileRevert")
        record(
            "external-reload-action-was-usable",
            action is not None and action.get_sensitive(),
            f"action={action!r}, "
            f"active_tab_is_ours={self.window.get_active_tab() is self.tab}",
        )
        self._schedule(2000, self.step_external_reload_retired)
        return False

    def step_external_reload_retired(self):
        controller = self._main_controller()
        record(
            "external-reload-retires-bar",
            controller._external_bar is None
            # The discriminating half: `modified` was cleared by hand a
            # moment ago, so only the buffer's content proves the revert
            # actually happened rather than the flag merely being false.
            and "Mine wins" not in self._buffer_text(),
            f"bar {controller._external_bar!r}, "
            f"modified {self.document.get_modified()}, "
            f"reverted {'Mine wins' not in self._buffer_text()}",
        )
        record(
            "external-reload-clears-the-disk-cache",
            controller._disk_text is None,
            f"after a reload the buffer is the truth again; "
            f"buffer starts {self._buffer_text()[:30]!r}, "
            f"reverted={'Mine wins' not in self._buffer_text()}",
        )
        self._schedule(300, self.step_external_burst)
        return False

    # --- a burst settles once ----------------------------------------------

    def step_external_burst(self):
        controller = self._main_controller()
        self._renders = 0
        self._render_original = controller._refresh_body_now

        def counting():
            self._renders += 1
            return self._render_original()

        controller._refresh_body_now = counting
        for index in range(10):
            self._write_document_file(f"# Burst {index}\n\nWrite number {index}.\n")
        self._schedule(1500, self.step_external_burst_check)
        return False

    def step_external_burst_check(self):
        controller = self._main_controller()
        controller._refresh_body_now = self._render_original
        record(
            "external-burst-settles-once",
            self._renders == 1,
            f"{self._renders} renders for ten writes",
        )
        self._preview_text(
            "external-burst-shows-the-last-write",
            "Burst 9",
            True,
            self.step_external_delete,
        )
        return False

    # --- delete, and come back ---------------------------------------------

    def step_external_delete(self):
        os.unlink(self._document_file())
        self._schedule(1400, self.step_external_delete_check)
        return False

    def step_external_delete_check(self):
        controller = self._main_controller()
        record(
            "external-delete-leaves-no-bar",
            controller._info_bar is None,
            "a deleted file is not an error to report",
        )
        record(
            "external-delete-keeps-the-document-page",
            controller._page_is_document,
            "a deleted file must not produce an error page",
        )
        self._preview_text(
            "external-delete-is-quiet",
            "Burst 9",
            True,
            self.step_external_restore,
        )
        return False

    def step_external_restore(self):
        self._write_document_file("# Restored\n\nThe file came back.\n")
        self._schedule(1400, self.step_external_restore_check)
        return False

    def step_external_restore_check(self):
        self._preview_text(
            "external-restore-catches-up",
            "The file came back",
            True,
            self.step_external_returned_setup,
        )
        return False

    # --- the file coming back to what the buffer holds ---------------------
    #
    # The case a review caught in the design: an agent that undoes its own
    # edit, or `git checkout -- file.md`, leaves disk matching the buffer
    # again. That answers UNCHANGED, and if the cached disk text survived it
    # the preview would go on showing an intermediate version that is now on
    # neither disk nor buffer, with nothing left to mark it stale -- and the
    # next keystroke would raise the bar over a file the user already has.

    def step_external_returned_setup(self):
        # A known buffer to come back to, with the file matching it, so the
        # write below is a genuine divergence and the one after it a genuine
        # return.
        self.document.set_text("# Round trip\n\nThe buffer's own text.\n")
        self._reconcile_without_saving()
        self._schedule(1400, self.step_external_returned_diverge)
        return False

    def step_external_returned_diverge(self):
        self._write_document_file("# Interloper\n\nWritten by something else.\n")
        self._schedule(1400, self.step_external_returned_check_diverged)
        return False

    def step_external_returned_check_diverged(self):
        controller = self._main_controller()
        record(
            "external-returned-cached-the-divergence",
            controller._disk_text is not None,
            "the setup did not reach UPDATE; the return below would prove nothing",
        )
        self._preview_text(
            "external-returned-shows-the-interloper",
            "Interloper",
            True,
            self.step_external_returned_restore,
        )
        return False

    def step_external_returned_restore(self):
        # Byte for byte what the setup wrote, so diskstate answers UNCHANGED.
        # Built from the buffer rather than repeating the literal: the setup
        # went through `_reconcile_without_saving`, which appends the implicit
        # trailing newline, and a hand-written literal that omitted it read as
        # an UPDATE of the same visible text -- the preview looked right while
        # the cache silently stayed set.
        self._write_document_file(self._buffer_text() + "\n")
        self._schedule(1400, self.step_external_returned_final)
        return False

    def step_external_returned_final(self):
        controller = self._main_controller()
        record(
            "external-returned-drops-the-cache",
            controller._disk_text is None,
            "a file back in agreement with the buffer must not stay cached",
        )
        self._preview_text(
            "external-returned-preview-follows-back",
            "Interloper",
            False,
            self.step_external_returned_no_false_bar,
        )
        return False

    def step_external_returned_no_false_bar(self):
        # The second symptom: typing must NOT raise "this file changed on
        # disk" when the file matches what the user already had.
        self.document.insert(self.document.get_end_iter(), "\nA fresh edit.\n", -1)
        self._schedule(900, self.step_external_returned_no_false_bar_check)
        return False

    def step_external_returned_no_false_bar_check(self):
        controller = self._main_controller()
        record(
            "external-returned-no-false-warning",
            controller._external_bar is None,
            "typing over a file that matches the buffer must not warn",
        )
        # Leave the buffer clean for the steps that follow.
        self._reconcile_without_saving()
        self._schedule(1400, self.step_external_repoint)
        return False

    # --- Save As moves the watch -------------------------------------------
    #
    # The mechanical contract only. A real Save As goes through xed's file
    # chooser, which nothing here can drive; the end-to-end path is a row in
    # docs/manual-smoke-test.md instead. What is asserted here is what
    # `_on_document_saved` calls into: that repoint moves the path and builds
    # a new monitor, and that the old one is cancelled rather than left live.

    def step_external_repoint(self):
        watch = self._main_controller()._watch
        if watch is None:
            record("external-repoint-re-arms", False, "no watch")
            self._schedule(300, self.step_external_watch_off)
            return False
        before = watch._monitor
        original = watch.path
        moved = os.path.join(os.path.dirname(original), "moved-under-the-watch.md")
        with open(moved, "w") as handle:
            handle.write("# Moved\n")
        watch.repoint(moved)
        record(
            "external-repoint-re-arms",
            watch.path == moved
            and watch._monitor is not None
            and watch._monitor is not before,
            f"path {watch.path!r}, monitor replaced: {watch._monitor is not before}",
        )
        # Put it back, so the assertions after this one watch the file this
        # tab's document actually has.
        watch.repoint(original)
        os.unlink(moved)
        self._schedule(500, self.step_external_watch_off)
        return False

    # --- off means off ------------------------------------------------------

    def step_external_watch_off(self):
        store = xedown_settings.get_settings()
        store.set(xedown_settings.WATCH_EXTERNAL_CHANGES, False)
        controller = self._main_controller()
        record(
            "external-watch-off-drops-the-monitor",
            controller._watch is None,
            "the setting must reach a tab that is already open",
        )
        self._write_document_file("# Never seen\n\nWatching is off.\n")
        self._schedule(1400, self.step_external_watch_off_check)
        return False

    def step_external_watch_off_check(self):
        self._preview_text(
            "external-watch-off-is-inert",
            "Never seen",
            False,
            self.step_external_watch_restore,
        )
        return False

    def step_external_watch_restore(self):
        # Leave the setting and the tab as the rest of the sequence expects
        # to find them, and leave the buffer clean: step_content_integrity
        # asserts that viewing does not change the text.
        store = xedown_settings.get_settings()
        store.set(xedown_settings.WATCH_EXTERNAL_CHANGES, True)
        controller = self._main_controller()
        record(
            "external-watch-on-re-arms",
            controller._watch is not None,
            "switching the setting back on must restart the watch",
        )
        self._schedule(300, self.step_a11y_tree)
        return False

    # --- the accessibility standard, checked against the live tree ---------
    #
    # `Gtk.Widget.get_accessible()` returns the ATK object the at-spi bridge
    # would hand to Orca -- the same object, before it crosses a bus. So this
    # needs no bridge, no `toolkit-accessibility` gsetting and no second
    # process: it walks the widgets this probe already built.
    #
    # What it cannot do is hear anything. Whether Orca *speaks* a mode change
    # is a manual row in docs/manual-smoke-test.md, and the documentation
    # says which claims rest on which.

    def _tab_order_index(self, root, widget):
        """`widget`'s position in a depth-first walk of `root`'s own tree.

        Not `enumerate()` over a Python list: that stays 0, 1, 2, 3 no
        matter what the real widget tree does, which is exactly why the
        tab-order rule this feeds could never fail before. `get_children()`
        is verified live (not merely read from the docs) to already return
        each container's children in *visual* order rather than call
        order: two `pack_end` calls -- `modebar._refresh_button` first,
        `modebar._stale_dot` second -- come back dot-then-button, matching
        what actually renders (the dot sits immediately before the button,
        both anchored to the trailing edge). Walking that depth-first from
        a shared ancestor gives every widget below a real, comparable
        position, so a future change that reorders the real tree without
        updating the list a caller passes to `a11y.check_tree` shows up as
        a genuine "does not follow visual order" failure instead of two
        indices that were never anything but their place in a list.
        """
        order = []

        def visit(node):
            order.append(node)
            if isinstance(node, Gtk.Container):
                for child in node.get_children():
                    visit(child)

        visit(root)
        return order.index(widget) if widget in order else -1

    def _visible_state_nodes(self, root, entries):
        """`a11y.node` dicts for `[(key, widget), ...]`, real state throughout.

        `focusable` ANDs `can_focus` with `get_visible()` for the reason
        `a11y.check_node`'s own comment gives: GTK leaves `can_focus` True on
        a hidden widget even though its focus chain skips it regardless, so
        `can_focus` alone overstates what a real Tab key-press can reach.
        `index` comes from `_tab_order_index` against `root` -- a real
        position in the tree this probe is actually driving, not a
        placeholder.
        """
        nodes = []
        for key, widget in entries:
            accessible = widget.get_accessible()
            nodes.append(
                xedown_a11y.node(
                    key=key,
                    name=accessible.get_name() if accessible else "",
                    role=accessible.get_role().value_nick if accessible else "",
                    focusable=widget.get_can_focus() and widget.get_visible(),
                    visible=widget.get_visible(),
                    index=self._tab_order_index(root, widget),
                )
            )
        return nodes

    def _record_audit(self, prefix, nodes):
        """`check_tree` plus "every name came from NAMES", under one prefix.

        Shared by every audit below the main one: the pass/fail shape is
        identical each time, only which controls and which moment in the
        sequence differ.
        """
        problems = xedown_a11y.check_tree(nodes)
        record(
            f"{prefix}-passes-the-standard",
            not problems,
            "; ".join(problems) if problems else f"{len(nodes)} controls checked",
        )
        mismatched = [
            f"{item['key']}={item['name']!r}"
            for item in nodes
            if item["name"] != xedown_a11y.NAMES[item["key"]]
        ]
        record(
            f"{prefix}-names-match-the-standard",
            not mismatched,
            "; ".join(mismatched) if mismatched else "every name came from NAMES",
        )

    def _accessible_nodes(self):
        """xedown's own controls, as `a11y.node` dicts in tab order.

        `stale`, the five `search_*` names and `info_bar_close` are
        deliberately absent here: every one of them is hidden, closed or
        simply nonexistent at the point in the sequence `step_a11y_tree`
        runs. Each is audited later instead, at the step that already puts
        it on screen for its own reason -- `_audit_stale_and_refresh`,
        `_audit_search_bar`, `_audit_info_bar_close` -- rather than forced
        into visibility here just to be checked.
        """
        controller = self._main_controller()
        modebar = controller.modebar
        buttons = [modebar._buttons[Mode.PREVIEW], modebar._buttons[Mode.SOURCE]]
        entries = [
            ("mode_preview", buttons[0]),
            ("mode_source", buttons[1]),
            ("refresh", modebar._refresh_button),
            ("preview", controller.preview.widget),
        ]
        return self._visible_state_nodes(self.tab, entries)

    def step_a11y_tree(self):
        controller = self._main_controller()
        controller.set_mode(Mode.PREVIEW)
        nodes = self._accessible_nodes()
        problems = xedown_a11y.check_tree(nodes)
        record(
            "a11y-tree-passes-the-standard",
            not problems,
            "; ".join(problems) if problems else f"{len(nodes)} controls checked",
        )
        mismatched = [
            f"{item['key']}={item['name']!r}"
            for item in nodes
            if item["name"] != xedown_a11y.NAMES[item["key"]]
        ]
        record(
            "a11y-names-match-the-standard",
            not mismatched,
            "; ".join(mismatched) if mismatched else "every name came from NAMES",
        )
        self._schedule(300, self.step_a11y_focus)
        return False

    def step_a11y_focus(self):
        # "Switching to Preview puts focus where arrow keys and Page Down
        # scroll the document" -- the brief. A user must not have to click
        # the preview before they can scroll it.
        controller = self._main_controller()
        controller.set_mode(Mode.SOURCE)
        controller.set_mode(Mode.PREVIEW)
        record(
            "a11y-preview-takes-focus-on-switch",
            self.window.get_focus() is controller.preview.widget,
            f"focus is {self.window.get_focus()!r}",
        )
        self._schedule(300, self.step_a11y_checked_state)
        return False

    def step_a11y_checked_state(self):
        # The second of the two announcement mechanisms the design names: a
        # toggle's checked state. This asserts the state *changes* -- whether
        # Orca speaks it is the manual row.
        controller = self._main_controller()
        preview_button = controller.modebar._buttons[Mode.PREVIEW]
        # ATK's accessor for a widget's state is `ref_state_set` -- a
        # `ref_`-prefixed getter, unlike almost everything else in the API --
        # and the object it returns is queried with `contains_state`, not
        # `contains`. Verified directly against this machine's GTK: neither
        # `get_state_set` nor `contains` exists on these objects, and both
        # got this wrong the first time it was written, which reads
        # plausibly either way until it is actually run.
        before = (
            preview_button.get_accessible()
            .ref_state_set()
            .contains_state(Atk.StateType.CHECKED)
        )
        controller.set_mode(Mode.SOURCE)
        after = (
            preview_button.get_accessible()
            .ref_state_set()
            .contains_state(Atk.StateType.CHECKED)
        )
        record(
            "a11y-mode-switch-changes-checked-state",
            before and not after,
            f"checked before={before} after={after}",
        )
        controller.set_mode(Mode.PREVIEW)
        self._schedule(400, self.step_a11y_page)
        return False

    def step_a11y_page(self):
        controller = self._main_controller()
        preview = controller.preview if controller is not None else None
        if preview is None:
            record("a11y-page-has-a-landmark", False, "no preview")
            record("a11y-page-has-a-language", False, "no preview")
            self._schedule(300, self.step_content_integrity)
            return False

        # The independent answer to compare the page against: exactly what
        # `_reload_preview` called to decide the `lang` this same page was
        # rendered with, read again here rather than guessed at from the
        # locale rules directly. Comparing the page against a *fixed*
        # expectation ("a tag, or nothing") is what let a `_page_language()`
        # that silently started returning the wrong thing -- or nothing, on
        # a machine that plainly has a locale -- go on recording PASS
        # forever: an empty `lang` is only a legitimate answer when this
        # call also returns None, never merely when it returns *something*.
        expected_lang = controller._page_language() or ""

        def on_result(webview, result, _user_data):
            try:
                value = webview.run_javascript_finish(result)
                found = value.get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                found = f"<error: {exc}>"
            if "|" not in found:
                # The round trip failed, so both halves are unknown -- and an
                # unknown language must not read as "no language known". An
                # empty `lang` is a legitimate answer when the desktop names
                # no language, which is exactly why it cannot also be the
                # answer when the question never got asked. `check_tree`
                # encodes the same rule: an audit that learned nothing is not
                # a pass.
                record("a11y-page-has-a-landmark", False, found)
                record("a11y-page-has-a-language", False, found)
                self._schedule(300, self.step_content_integrity)
                return
            role, _, lang = found.partition("|")
            # `main`, not `document`: a document-structure role is not a
            # landmark, and this is the one place that would have kept
            # passing throughout the whole time the page shipped the wrong
            # one -- the DOM was never asked what role actually landed.
            record("a11y-page-has-a-landmark", role == "main", f"role={role!r}")
            record(
                "a11y-page-has-a-language",
                lang == expected_lang,
                f"lang={lang!r} expected={expected_lang!r}",
            )
            self._schedule(300, self.step_content_integrity)

        preview.widget.run_javascript(
            # Written without optional chaining: this string is evaluated by
            # whatever WebKit the host ships, and the probe should not be the
            # thing that discovers a syntax floor.
            "(function () {"
            "  var a = document.querySelector('.xedown-document');"
            "  var role = a ? (a.getAttribute('role') || '') : '';"
            "  var lang = document.documentElement.getAttribute('lang') || '';"
            "  return role + '|' + lang;"
            "})()",
            None,
            on_result,
            None,
        )
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
        # Without this, the assertion above passes *vacuously* if the save
        # never happened: no save means no reload, and no reload means the
        # scroll trivially matches. That is not hypothetical -- the external
        # section above rewrites this document's file from outside, and xed
        # refuses to overwrite a file whose modification time has moved
        # unless its own externally-modified notification has been raised
        # first. Reorder the steps above and this save starts being refused
        # while the scroll assertion goes on passing.
        record(
            "scroll-save-actually-saved",
            not self.document.get_modified()
            and self.tab.get_state() == Xed.TabState.STATE_NORMAL,
            f"modified={self.document.get_modified()} state={self.tab.get_state()}",
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
        # Which window this tab's focus watch is on, and the id of that one
        # connection, BEFORE the move -- captured here because after the
        # move there is nothing left to read it from. Recorded as a check of
        # its own so the post-move assertions below cannot pass vacuously
        # against a pair that was never set in the first place. See
        # TabController._attach_focus_watch, and
        # escape-still-closes-the-search-after-a-tab-move near the end.
        moving = self._controller_for(self._move_view)
        self._move_source_focus_id = (
            moving._focus_handler_id if moving is not None else None
        )
        record(
            "move-tab-focus-watch-starts-on-the-source-window",
            moving is not None
            and moving._focus_window is self.window
            and self._move_source_focus_id is not None,
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
        if preview is None:
            record("clipboard-holds-exactly-the-authors-code", False, "no preview")
            self._schedule(300, self.step_txt_tab_open)
            return False
        clipboard = Gtk.Clipboard.get_default(preview.widget.get_display())
        copied = clipboard.wait_for_text() or ""
        # Strip exactly one trailing newline, mirroring preview.js's
        # captureSources ("if the last char is '\n', slice it off") rather
        # than rstrip("\n"), which would strip every trailing newline and
        # only coincidentally agree with the fence here because it happens
        # to have exactly one.
        expected_code = _COPY_CODE.removesuffix("\n")
        record(
            "clipboard-holds-exactly-the-authors-code",
            copied == expected_code,
            f"copied {copied!r}",
        )

        def on_result(webview, result, _user_data):
            payload, failure = {}, ""
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                failure = f"<error: {exc}>"
            # Matched against the button's OWN current label, not a fixed
            # guess: the copy round trip is an in-process message hop with
            # no I/O, so by the time this runs (900ms after the click) the
            # label already reads "Copied", not "Copy"
            # (COPY_ANSWER_MS/COPY_REVERT_MS are both 1500ms in preview.js),
            # and "Copy" is not a substring of "Copied" -- English drops the
            # "y" before "-ed" -- so a fixed "Copy" search could never have
            # caught the button's text leaking into the selection here (it
            # did not: confirmed live against this exact deployed step,
            # see the task report). Reading the label live instead of
            # guessing its text works whatever it currently says.
            #
            # This also replaces an earlier attempt at this fix that used
            # `Selection.containsNode(button, true)`: verified, in
            # isolation, to return true for this button regardless of
            # whether `user-select: none` is present or removed, because
            # the button sits inside the DOM range a full-page select-all
            # spans either way -- CSS does not move it out of that range,
            # it only changes whether the *text* extracted from the range
            # includes it. containsNode answers "is this node structurally
            # within the selection", not "would copying the selection
            # include what this node shows" -- a different question, and
            # the wrong one to ask here.
            #
            # buttonPresent still has to be true and the label non-empty:
            # an absent button, or an empty label, would make this pass for
            # having nothing to find rather than for the CSS actually
            # working.
            button_present = bool(payload.get("buttonPresent"))
            label = payload.get("buttonLabel") or ""
            selection_text = payload.get("selection") or ""
            leaked = bool(label) and label in selection_text
            # A select-all that actually selected nothing (or something
            # truncated) would leave selection_text == "", which made leaked
            # False and this pass for having nothing to find -- wrong twice
            # for two different reasons. Requiring text from both ends of
            # the fixture (the heading and inside the fenced code block)
            # closes that: an empty or partial selection now fails loudly.
            selected_the_document = (
                "Round Trip" in selection_text and "def total(items)" in selection_text
            )
            record(
                "copy-button-never-joins-a-selection",
                button_present
                and bool(label)
                and selected_the_document
                and not leaked
                and not failure,
                f"button present: {button_present} label: {label!r} selected-document: "
                f"{selected_the_document} leaked: {leaked} selection: {selection_text!r}"
                f"{failure}",
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
            "  var button = document.querySelector('.xedown-copy');"
            "  var label = button ? button.textContent : '';"
            "  document.execCommand('selectAll');"
            "  var s = String(window.getSelection());"
            "  window.getSelection().removeAllRanges();"
            "  var w = document.querySelector('.xedown-table-scroll') ||"
            "          {scrollWidth: 0, clientWidth: 0};"
            "  var d = document.documentElement;"
            "  return JSON.stringify({"
            "    selection: s,"
            "    buttonPresent: !!button,"
            "    buttonLabel: label,"
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
        if preview is None:
            record("copy-buttons-off-removes-them-live", False, "no preview")
            # Undo what this chain segment changed even on the short-circuit
            # path: leaving CODE_COPY_BUTTONS at False would silently affect
            # every later step's rendering for the rest of the process.
            xedown_settings.get_settings().set(xedown_settings.CODE_COPY_BUTTONS, True)
            if getattr(self, "_copy_tab", None) is not None:
                self.window.close_tab(self._copy_tab)
            self._schedule(500, self.step_txt_tab_open)
            return False

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
        # Expected sensitivity comes from each action's own
        # requires_markdown, not a second hardcoded list of names -- so an
        # action added to ACTIONS later is covered here automatically
        # instead of silently falling through unchecked the way the
        # settings action originally did.
        for entry in xedown_shortcuts.ACTIONS:
            action = self._find_action(entry.name)
            record(f"action-exists-{entry.name}", action is not None)
            if action is None:
                continue
            # get_sensitive() always reads True regardless of menu state
            # -- only is_sensitive() reflects the action GROUP
            # sensitivity that do_update_state() actually toggles.
            if entry.requires_markdown:
                record(
                    f"menu-insensitive-on-txt-{entry.name}", not action.is_sensitive()
                )
            else:
                # The settings action is the one entry that must stay
                # usable on a file xedown does not preview -- exactly when
                # a user goes looking for the settings that decide what it
                # previews.
                record(f"menu-sensitive-on-txt-{entry.name}", action.is_sensitive())
        self.window.set_active_tab(self.tab)
        self.view.grab_focus()
        self._schedule(700, self.step_md_sensitivity)
        return False

    def step_md_sensitivity(self):
        action = self._find_action("XedownToggleAction")
        if action is not None:
            record("menu-sensitive-on-md", action.is_sensitive())
        self._schedule(400, self.step_error_page_setup)
        return False

    # --- an error page must be refreshable back into a document ------------

    def step_error_page_setup(self):
        controller = self._main_controller()
        # A render failure the probe can cause on demand: the same call the
        # controller makes when rendering actually raises.
        controller._reload_preview(
            error=RuntimeError("probe-forced failure"), restore_scroll=0.0
        )
        self._schedule(900, self.step_error_page_refresh)
        return False

    def step_error_page_refresh(self):
        controller = self._main_controller()
        controller.refresh_now()
        self._schedule(900, self.step_error_page_check)
        return False

    def step_error_page_check(self):
        preview = self._main_controller().preview

        def on_result(webview, result, _user_data):
            found = ""
            try:
                found = webview.run_javascript_finish(result).get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                found = f"<error: {exc}>"
            # Before the fix this stayed "false" for ever: update_body posts
            # into a page with no window.xedown, and nothing reloads it.
            record(
                "error-page-recovers-on-refresh", found == "true", f"content: {found}"
            )
            self._schedule(400, self.step_manual_refresh_setup)

        preview.widget.run_javascript(
            "String(!!document.getElementById('xedown-content'))", None, on_result, None
        )
        return False

    # --- automatic refresh off: the button, the dot, and the manual path ---

    def step_manual_refresh_setup(self):
        controller = self._main_controller()
        if controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        xedown_settings.get_settings().set(xedown_settings.AUTO_REFRESH, False)
        self._schedule(500, self.step_manual_refresh_bar)
        return False

    def step_manual_refresh_bar(self):
        bar = self._main_controller().modebar
        record(
            "refresh-button-appears-when-auto-is-off",
            bar is not None and bar._refresh_button.get_visible(),
        )
        # A buffer change while the preview is showing is exactly what
        # automatic refresh would have picked up.
        document = self._main_controller().document
        document.insert(document.get_end_iter(), "\n\nmanual refresh marker\n")
        self._schedule(700, self.step_manual_refresh_stale)
        return False

    def step_manual_refresh_stale(self):
        controller = self._main_controller()
        bar = controller.modebar
        record("stale-dot-shows-when-behind", bar._stale_dot.get_visible())
        # With automatic refresh off, nothing rendered it.
        record("no-render-while-auto-is-off", controller.state.preview_stale)
        # `stale` and `refresh` are both hidden everywhere `_accessible_nodes`
        # runs (auto-refresh is on by default there), so their `focusable`
        # rules never actually fired against real state until now: this is
        # the one point in the sequence both are genuinely visible, auto-off
        # and behind, which is the only combination that shows either at
        # all.
        self._audit_stale_and_refresh(bar)
        controller.refresh_now()
        self._schedule(900, self.step_manual_refresh_check)
        return False

    def _audit_stale_and_refresh(self, bar):
        """`stale` before `refresh`: that is the real order the box packs
        them in (both anchored `pack_end`, with the dot packed second so it
        lands immediately to the button's left) -- verified live via
        `_tab_order_index`'s own docstring, not assumed from the packing
        calls alone.
        """
        nodes = self._visible_state_nodes(
            bar, [("stale", bar._stale_dot), ("refresh", bar._refresh_button)]
        )
        self._record_audit("a11y-stale-and-refresh", nodes)

    def step_manual_refresh_check(self):
        controller = self._main_controller()
        preview = controller.preview

        def on_result(webview, result, _user_data):
            found = ""
            try:
                found = webview.run_javascript_finish(result).get_js_value().to_string()
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                found = f"<error: {exc}>"
            record(
                "manual-refresh-updates-the-page", found == "true", f"found: {found}"
            )
            record(
                "stale-dot-clears-after-refresh",
                not controller.modebar._stale_dot.get_visible(),
            )
            # Restore the default before anything later renders against it.
            xedown_settings.get_settings().set(xedown_settings.AUTO_REFRESH, True)
            self._schedule(500, self.step_refresh_button_hidden)

        preview.widget.run_javascript(
            "String(document.body.textContent.indexOf('manual refresh marker') >= 0)",
            None,
            on_result,
            None,
        )
        return False

    def step_refresh_button_hidden(self):
        bar = self._main_controller().modebar
        record(
            "refresh-button-hidden-when-auto-is-on",
            bar is not None and not bar._refresh_button.get_visible(),
        )
        self._schedule(400, self.step_remember_mode_setup)
        return False

    # --- the mode a file opens in ------------------------------------------

    def step_remember_mode_setup(self):
        path = os.path.join(self._tmpdir, "remembered.md")
        with open(path, "w") as handle:
            handle.write("# Remembered\n\nA file with a mode to remember.\n")
        self._remember_path = path
        self._remember_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(1200, self.step_remember_mode_set)
        return False

    def step_remember_mode_set(self):
        controller = getattr(self._remember_tab.get_view(), "_xedown_controller", None)
        record(
            "remembered-file-opens-in-the-default",
            controller is not None and controller.state.mode is Mode.PREVIEW,
        )
        controller.set_mode(Mode.SOURCE)
        self.window.close_tab(self._remember_tab)
        self._schedule(900, self.step_remember_mode_reopen)
        return False

    def step_remember_mode_reopen(self):
        self._remember_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(self._remember_path), None, 0, False, True
        )
        self._schedule(1400, self.step_remember_mode_check)
        return False

    def step_remember_mode_check(self):
        controller = getattr(self._remember_tab.get_view(), "_xedown_controller", None)
        record(
            "reopened-file-restores-its-mode",
            controller is not None and controller.state.mode is Mode.SOURCE,
        )
        self.window.close_tab(self._remember_tab)
        xedown_settings.get_settings().set(
            xedown_settings.REMEMBER_MODE_PER_FILE, False
        )
        self._schedule(900, self.step_remember_off_reopen)
        return False

    def step_remember_off_reopen(self):
        self._remember_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(self._remember_path), None, 0, False, True
        )
        self._schedule(1400, self.step_remember_off_check)
        return False

    def step_remember_off_check(self):
        controller = getattr(self._remember_tab.get_view(), "_xedown_controller", None)
        record(
            "remembering-off-uses-the-default-mode",
            controller is not None and controller.state.mode is Mode.PREVIEW,
        )
        self.window.close_tab(self._remember_tab)
        xedown_settings.get_settings().set(xedown_settings.REMEMBER_MODE_PER_FILE, True)
        self._schedule(700, self.step_default_mode_setup)
        return False

    def step_default_mode_setup(self):
        # A file never opened before, so nothing is remembered for it and the
        # default is the only thing that can decide.
        xedown_settings.get_settings().set(xedown_settings.DEFAULT_MODE, "markdown")
        path = os.path.join(self._tmpdir, "fresh.md")
        with open(path, "w") as handle:
            handle.write("# Fresh\n\nNever opened before.\n")
        self._fresh_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(1400, self.step_default_mode_check)
        return False

    def step_default_mode_check(self):
        controller = getattr(self._fresh_tab.get_view(), "_xedown_controller", None)
        record(
            "default-mode-decides-a-new-file",
            controller is not None and controller.state.mode is Mode.SOURCE,
        )
        # The source view must be the visible one, not merely the recorded
        # one. `controller.frame` is captured in `__init__` before the
        # ModeBar is packed, so it stays a correct reference to xed's own
        # source-view container no matter how tab children are later
        # reordered -- unlike `self._fresh_tab.get_children()[0]`, which is
        # always the ModeBar once a tab is built (see modebar-at-index-0),
        # and so is always visible regardless of mode.
        record(
            "default-markdown-shows-the-source",
            controller is not None and controller.frame.get_visible(),
        )
        self.window.close_tab(self._fresh_tab)
        xedown_settings.get_settings().set(xedown_settings.DEFAULT_MODE, "preview")
        self._schedule(700, self.step_saveas_setup)
        return False

    # --- Save As moves the remembered entry; it does not copy it -----------
    #
    # `Xed.commands_save_document_as` opens a modal file chooser and cannot
    # be driven from here without blocking on a dialog nothing in this probe
    # may block on. `Xed.Document.set_location`, followed by the same
    # `Xed.commands_save_document` step_save already uses for an ordinary
    # save, is the actual non-interactive route this host exposes: confirmed
    # by direct probing (not by reading the C source, which is not on this
    # machine) that it writes to the new path with no dialog and no hang --
    # exactly the mechanism `_on_document_saved` is written to react to,
    # since it is keyed off `self._document_path()` changing underneath it,
    # not off which xed command produced the change.

    def step_saveas_setup(self):
        path = os.path.join(self._tmpdir, "saveas-original.md")
        with open(path, "w") as handle:
            handle.write("# Save As Original\n\nStarts in Markdown mode.\n")
        self._saveas_original_path = path
        self._saveas_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(path), None, 0, False, True
        )
        self._schedule(1200, self.step_saveas_set_mode)
        return False

    def step_saveas_set_mode(self):
        controller = getattr(self._saveas_tab.get_view(), "_xedown_controller", None)
        # Files an entry under the ORIGINAL path -- this is what the rename
        # on save has to move rather than strand.
        controller.set_mode(Mode.SOURCE)
        self._schedule(500, self.step_saveas_move)
        return False

    def step_saveas_move(self):
        new_path = os.path.join(self._tmpdir, "saveas-moved.md")
        self._saveas_new_path = new_path
        document = self._saveas_tab.get_document()
        document.set_location(Gio.File.new_for_path(new_path))
        Xed.commands_save_document(self.window, document)
        self._schedule(1500, self.step_saveas_close)
        return False

    def step_saveas_close(self):
        self.window.close_tab(self._saveas_tab)
        self._schedule(700, self.step_saveas_reopen_new)
        return False

    def step_saveas_reopen_new(self):
        self._saveas_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(self._saveas_new_path), None, 0, False, True
        )
        self._schedule(1400, self.step_saveas_check_new)
        return False

    def step_saveas_check_new(self):
        controller = getattr(self._saveas_tab.get_view(), "_xedown_controller", None)
        record(
            "saveas-new-path-opens-in-the-remembered-mode",
            controller is not None and controller.state.mode is Mode.SOURCE,
        )
        self.window.close_tab(self._saveas_tab)
        self._schedule(700, self.step_saveas_reopen_original)
        return False

    def step_saveas_reopen_original(self):
        # The same file `step_saveas_setup` wrote and never touched again --
        # still on disk under its original name, since a Save As does not
        # delete the file it moved away from.
        self._saveas_orig_tab = self.window.create_tab_from_location(
            Gio.File.new_for_path(self._saveas_original_path), None, 0, False, True
        )
        self._schedule(1400, self.step_saveas_check_original)
        return False

    def step_saveas_check_original(self):
        controller = getattr(
            self._saveas_orig_tab.get_view(), "_xedown_controller", None
        )
        record(
            "saveas-original-path-uses-the-default-not-a-stale-entry",
            controller is not None and controller.state.mode is Mode.PREVIEW,
        )
        self.window.close_tab(self._saveas_orig_tab)
        self._schedule(700, self.step_accel_map)
        return False

    # --- the four shortcuts, pressed for real ------------------------------

    def _press(self, keyval, state, window=None):
        """Deliver a real key press to the window, as the keyboard would.

        `hardware_keycode` is not decoration: GTK's accelerator lookup goes
        through its key hash by keycode, so an event without one activates
        nothing at all and every assertion below would be vacuous.

        `window` defaults to this probe's own; the moved-tab checks near the
        end of this file press into the second window instead, which is
        where that tab now lives.
        """
        window = window or self.window
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
        # Confirmed live (not merely inferred) that a device is equally
        # load-bearing: without one, xed's own log fills with
        # `Gdk-WARNING: Event with type 8 not holding a GdkDevice` and every
        # mode-change assertion below fails -- not because the accelerator
        # was wrong, but because an event with no device never reaches GTK's
        # key-press handling at all. Every real GdkEventKey carries one;
        # this attaches the display's actual keyboard so the synthetic
        # event is a genuine one, not a shortcut around xed's real event
        # pipeline.
        seat = window.get_display().get_default_seat()
        if seat is not None:
            keyboard = seat.get_keyboard()
            if keyboard is not None:
                event.set_device(keyboard)
        Gtk.main_do_event(event)

    def step_accel_map(self):
        ours = set()
        for action in xedown_shortcuts.ACTIONS:
            # Aliases too, not just the primary -- an alias that collided
            # with something already in xed's own accel map would be just
            # as broken, and it is the spelling that actually fires on the
            # layouts where the alias exists at all.
            for accel in (action.accelerator, *action.aliases):
                # The settings action (Task 6) has accelerator=None by
                # design -- it has no primary, only a possible future alias
                # -- and Gtk.accelerator_parse rejects None outright, so
                # skip it here rather than skip the whole action: an action
                # with no primary could still carry aliases that do need
                # checking.
                if accel is None:
                    continue
                # Two values, not three: PyGObject returns (key, mods) here.
                key, mods = Gtk.accelerator_parse(accel)
                ours.add((key, int(mods)))
        clashes = []

        def visit(_data, accel_path, accel_key, accel_mods, _changed):
            if accel_path.startswith("<Actions>/XedownActions/"):
                return  # our own registrations
            if (accel_key, int(accel_mods)) in ours:
                clashes.append(accel_path)

        seen = []

        def count(_data, accel_path, _key, _mods, _changed):
            seen.append(accel_path)

        Gtk.AccelMap.foreach_unfiltered(None, count)
        # A map this small means nothing was read, which would make the
        # assertion below pass while proving nothing.
        record("accel-map-is-populated", len(seen) >= 10, f"paths: {len(seen)}")
        Gtk.AccelMap.foreach_unfiltered(None, visit)
        record("no-accelerator-clash-with-the-live-xed", not clashes, f"{clashes!r}")
        self._schedule(400, self.step_shortcut_to_markdown)
        return False

    def step_shortcut_to_markdown(self):
        controller = self._main_controller()
        if controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        self.view.grab_focus()
        self._press(
            Gdk.KEY_2, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        self._schedule(600, self.step_shortcut_to_markdown_check)
        return False

    def step_shortcut_to_markdown_check(self):
        controller = self._main_controller()
        record("ctrl-shift-2-shows-the-source", controller.state.mode is Mode.SOURCE)
        # Again, from the mode it is already in: a no-op, not a toggle.
        self._press(
            Gdk.KEY_2, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        self._schedule(500, self.step_shortcut_repeat_check)
        return False

    def step_shortcut_repeat_check(self):
        controller = self._main_controller()
        record(
            "going-to-the-current-mode-does-nothing",
            controller.state.mode is Mode.SOURCE,
        )
        self._press(
            Gdk.KEY_1, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        self._schedule(600, self.step_shortcut_to_preview_check)
        return False

    def step_shortcut_to_preview_check(self):
        controller = self._main_controller()
        record("ctrl-shift-1-shows-the-preview", controller.state.mode is Mode.PREVIEW)
        # With focus inside the WebView this time, which is the case v0.1
        # could not serve.
        controller.preview.widget.grab_focus()
        self._press(
            Gdk.KEY_m, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        )
        self._schedule(600, self.step_shortcut_from_preview_focus_check)
        return False

    def step_shortcut_from_preview_focus_check(self):
        controller = self._main_controller()
        record(
            "shortcuts-work-with-focus-in-the-preview",
            controller.state.mode is Mode.SOURCE,
        )
        controller.set_mode(Mode.PREVIEW)
        self._schedule(500, self.step_menu_entries)
        return False

    def step_menu_entries(self):
        for action in xedown_shortcuts.ACTIONS:
            found = self._find_action(action.name)
            record(f"menu-entry-exists-{action.name}", found is not None)
            if found is not None:
                record(
                    f"menu-entry-sensitive-on-md-{action.name}", found.is_sensitive()
                )
        self._schedule(400, self.step_preview_copy_setup)
        return False

    # --- copy lands on the surface the user can see ------------------------

    def step_preview_copy_setup(self):
        controller = self._main_controller()
        if controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        # The probe's document (`_long_markdown`) opens "# Scroll Test", so
        # the rendered surface holds "Scroll Test" and the source holds
        # "# Scroll Test". Whatever the clipboard ends up with, it came from
        # one surface or the other and the two cannot be confused.
        Gtk.Clipboard.get_default(self.window.get_display()).set_text("<none>", -1)
        controller.preview.widget.grab_focus()
        self._press(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK)
        self._schedule(500, self.step_preview_copy)
        return False

    def step_preview_copy(self):
        self._press(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK)
        self._schedule(900, self.step_preview_copy_check)
        return False

    def step_preview_copy_check(self):
        text = (
            Gtk.Clipboard.get_default(self.window.get_display()).wait_for_text() or ""
        )
        record(
            "preview-copy-produces-rendered-text",
            "Scroll Test" in text,
            f"clipboard: {text[:60]!r}",
        )
        record(
            "preview-copy-is-not-the-markdown-source",
            "# " not in text,
            f"clipboard: {text[:60]!r}",
        )
        self._schedule(400, self.step_source_copy_setup)
        return False

    def step_source_copy_setup(self):
        controller = self._main_controller()
        controller.set_mode(Mode.SOURCE)
        self.view.grab_focus()
        Gtk.Clipboard.get_default(self.window.get_display()).set_text("<none>", -1)
        self._schedule(500, self.step_source_copy)
        return False

    def step_source_copy(self):
        self._press(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK)
        self._press(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK)
        self._schedule(900, self.step_source_copy_check)
        return False

    def step_source_copy_check(self):
        text = (
            Gtk.Clipboard.get_default(self.window.get_display()).wait_for_text() or ""
        )
        # Markdown mode keeps xed's own behaviour exactly: hashes and all.
        record(
            "markdown-copy-still-produces-source",
            "# " in text,
            f"clipboard: {text[:60]!r}",
        )
        controller = self._main_controller()
        controller.set_mode(Mode.PREVIEW)
        self._schedule(600, self.step_preview_focus_check)
        return False

    def step_preview_focus_check(self):
        controller = self._main_controller()
        # is_focus(), not has_focus(): the claim here is that entering
        # Preview moves the TAB's focus to the WebView, which is exactly
        # "is this widget its toplevel's focus widget" -- independent of
        # which window the window manager currently considers active.
        # has_focus() also requires real X11 input focus on the toplevel,
        # which anything can hold at the moment this step runs (in this
        # harness, the move-tab test's own second window; in ordinary use,
        # literally anything else on the desktop) -- a check built on it is
        # flaky by construction, not a stronger assertion.
        record(
            "entering-preview-focuses-the-preview",
            controller.preview.widget.is_focus(),
        )
        self._schedule(400, self.step_search_reset)
        return False

    # --- find in the preview ------------------------------------------------

    def _marks(self, on_result, controller=None):
        """Ask the page what its search marks currently look like.

        `controller` defaults to the main tab's; the moved-tab checks near
        the end of this file are the one caller that asks a different tab.
        """
        preview = (controller or self._main_controller()).preview

        def finished(webview, result, _user_data):
            payload = {"total": -1, "current": -1, "text": ""}
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                payload = {"total": -1, "current": -1, "text": f"<error: {exc}>"}
            on_result(payload)

        preview.widget.run_javascript(
            "JSON.stringify({"
            "total: document.querySelectorAll('mark.xedown-match').length,"
            "current: document.querySelectorAll('mark.xedown-match-current').length,"
            "text: (document.querySelector('mark.xedown-match-current')"
            " || {textContent: ''}).textContent"
            "})",
            None,
            finished,
            None,
        )

    def step_search_reset(self):
        # Every count below is a count of what is in THIS text, and earlier
        # steps have edited the buffer (step_content_integrity types an "X"
        # into it). Putting the fixture back is what makes 1 mean 1 and 360
        # mean 360 rather than "whatever survived the last twenty steps".
        controller = self._main_controller()
        if controller.state.mode is not Mode.PREVIEW:
            controller.set_mode(Mode.PREVIEW)
        self.document.set_text(_long_markdown())
        # Past the 250 ms debounce, so the body being searched is the body
        # this text renders to.
        self._schedule(900, self.step_search_open)
        return False

    def step_search_open(self):
        controller = self._main_controller()
        controller.preview.widget.grab_focus()
        self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        self._schedule(600, self.step_search_open_check)
        return False

    def step_search_open_check(self):
        controller = self._main_controller()
        record(
            "ctrl-f-opens-the-preview-search",
            controller.is_searching
            and controller.searchbar.owns_focus(self.window.get_focus()),
        )
        # The five `search_*` names -- and `search_status`, the label the
        # session status text lands in -- are otherwise unaudited: every
        # one of them is hidden everywhere `_accessible_nodes` runs, since
        # that step runs before the bar is ever opened. The bar is
        # genuinely open here (a real `Ctrl+F` a moment ago), which is the
        # one state where any of this can be checked at all.
        self._audit_search_bar(controller)
        # "Paragraph 7" alone would also match "Paragraph 70" through
        # "Paragraph 79", which is exactly the kind of accident that makes a
        # count assertion meaningless -- the trailing period rules those out.
        # It does not rule out three: each paragraph's own sentence is
        # itself written `* 3` above, so "Paragraph 7." appears three times
        # in paragraph 7's own block, not once. Confirmed directly against
        # this fixture's rendered output, not assumed.
        controller.searchbar.set_query("Paragraph 7.")
        self._schedule(900, self.step_search_count_check)
        return False

    def _audit_search_bar(self, controller):
        """The bar's own six controls, in the real order the row packs them.

        `search_status` (the "N of M" label) is not focusable and so never
        trips `check_node`'s role/name rules, but it is still walked here:
        the mismatch check below is what actually pins its name against
        `NAMES["search_status"]` -- the one this brief's Finding 4 moved out
        of a bare string literal -- regardless of whether anything can tab
        to it.
        """
        bar = controller.searchbar
        entries = [
            ("search_entry", bar._entry),
            ("search_case", bar._case),
            ("search_previous", bar._previous),
            ("search_next", bar._next),
            ("search_status", bar._status),
            ("search_close", bar._close),
        ]
        nodes = self._visible_state_nodes(bar, entries)
        self._record_audit("a11y-search-bar", nodes)

    def step_search_count_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "search-marks-every-match",
                payload["total"] == 3 and controller.search.total == 3,
                f"page: {payload['total']}, session: {controller.search.total}",
            )
            record(
                "search-marks-one-current-match",
                payload["current"] == 1,
                f"current marks: {payload['current']}",
            )
            record(
                "search-counts-from-one",
                controller.searchbar.get_query() == "Paragraph 7."
                and controller.search.status() == "1 of 3",
                f"status: {controller.search.status()!r}",
            )
            controller.searchbar.set_query("Filler")
            self._schedule(900, self.step_search_step)

        self._marks(check)
        return False

    def step_search_step(self):
        controller = self._main_controller()
        # 360 of them: three per paragraph, 120 paragraphs.
        record(
            "search-finds-every-repeat",
            controller.search.total == 360,
            f"total: {controller.search.total}",
        )
        # A real Return, through the entry that still holds focus: the window
        # hook leaves an unmodified Return alone, GTK delivers it to the
        # focused entry, and the entry's `activate` is what steps.
        self._press(Gdk.KEY_Return, Gdk.ModifierType(0))
        self._schedule(600, self.step_search_wrap)
        return False

    def step_search_wrap(self):
        controller = self._main_controller()
        record(
            "enter-steps-to-the-next-match",
            controller.search.index == 1,
            f"index: {controller.search.index}",
        )
        # Back twice from match 2: to the first, then past it. Emitted rather
        # than typed because Shift+Return through a synthetic event depends on
        # the entry holding focus through the step above, and what is being
        # checked here is the wrap, not the key.
        controller.searchbar.emit("step-requested", False)
        controller.searchbar.emit("step-requested", False)
        self._schedule(600, self.step_search_wrap_check)
        return False

    def step_search_wrap_check(self):
        controller = self._main_controller()
        record(
            "search-wraps-past-the-last-match",
            controller.search.index == 359,
            f"index: {controller.search.index}",
        )
        # Every occurrence in the fixture is capitalised, so a case-sensitive
        # search for the lowercase spelling must find none of them.
        controller.searchbar.set_case_sensitive(True)
        controller.searchbar.set_query("filler")
        self._schedule(900, self.step_search_case_check)
        return False

    def step_search_case_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "search-is-case-sensitive-when-asked",
                controller.search.total == 0 and payload["total"] == 0,
                f"session: {controller.search.total}, page: {payload['total']}",
            )
            record(
                "search-says-when-there-is-nothing",
                controller.search.status() == "No matches",
                f"status: {controller.search.status()!r}",
            )
            controller.searchbar.set_case_sensitive(False)
            controller.searchbar.set_query("emphasised phrase")
            self._schedule(900, self.step_search_inline_check)

        self._marks(check)
        return False

    def step_search_inline_check(self):
        controller = self._main_controller()

        def check(payload):
            # `An **emphasised** phrase` renders as three DOM nodes. Finding
            # it proves the flattened index, and one match wrapped in two
            # marks proves they are grouped by match number rather than
            # counted as two.
            record(
                "search-crosses-an-inline-boundary",
                controller.search.total == 1 and payload["total"] == 2,
                f"session: {controller.search.total}, marks: {payload['total']}",
            )
            self._press(Gdk.KEY_Escape, Gdk.ModifierType(0))
            self._schedule(700, self.step_search_escape_check)

        self._marks(check)
        return False

    def step_search_escape_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "escape-clears-every-mark",
                payload["total"] == 0 and not controller.is_searching,
                f"marks left: {payload['total']}",
            )
            record(
                "escape-returns-focus-to-the-preview",
                controller.preview.widget.is_focus(),
            )
            self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
            self._schedule(600, self.step_escape_from_preview_setup)

        self._marks(check)
        return False

    # --- Escape closes the search from the preview too, not just the entry -
    #
    # _on_window_set_focus's narrowing only closes the bar when the focus
    # xed just stole was one of xedown's own widgets. The entry is one of
    # them (escape-clears-every-mark, above); the preview WebView is the
    # other, and the brief promises both -- a reader is at least as likely
    # to press Escape while sitting in the rendered preview as while typing
    # in the entry.

    def step_escape_from_preview_setup(self):
        controller = self._main_controller()
        controller.searchbar.set_query("Filler")
        self._schedule(900, self.step_escape_from_preview_focus)
        return False

    def step_escape_from_preview_focus(self):
        controller = self._main_controller()
        controller.preview.widget.grab_focus()
        self._schedule(300, self.step_escape_from_preview_press)
        return False

    def step_escape_from_preview_press(self):
        self._press(Gdk.KEY_Escape, Gdk.ModifierType(0))
        self._schedule(700, self.step_escape_from_preview_check)
        return False

    def step_escape_from_preview_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "escape-from-the-preview-also-closes-the-search",
                payload["total"] == 0 and not controller.is_searching,
                f"marks left: {payload['total']}, is_searching: {controller.is_searching}",
            )
            self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
            self._schedule(600, self.step_unrelated_focus_setup)

        self._marks(check)
        return False

    # --- an unrelated focus move must leave a live search exactly alone ----
    #
    # The check that pins the narrowing itself: without it, a later change
    # could quietly widen _on_window_set_focus back to closing on ANY focus
    # arriving at the hidden view, and nothing above would notice. Neither
    # the mode-bar button focus below nor the direct grab_focus() that
    # follows it is the entry or the preview, so the search must survive
    # both -- only focus is reclaimed for the preview, exactly as it would
    # be if searching were not even active.

    def step_unrelated_focus_setup(self):
        controller = self._main_controller()
        controller.searchbar.set_query("Filler")
        self._schedule(900, self.step_unrelated_focus_move)
        return False

    def step_unrelated_focus_move(self):
        controller = self._main_controller()
        # Neither the entry nor the preview: a real, focusable widget in
        # this tab's own tree standing in for "focus moved for some reason
        # that has nothing to do with our search."
        controller.modebar._buttons[Mode.SOURCE].grab_focus()
        self._schedule(300, self.step_unrelated_focus_steal)
        return False

    def step_unrelated_focus_steal(self):
        # Simulates the same hazard a real Escape triggers -- xed handing
        # focus straight to the hidden source view -- without pressing a
        # key at all, so this pins the narrowing's own logic rather than
        # re-testing Escape delivery (already covered above).
        self.view.grab_focus()
        self._schedule(700, self.step_unrelated_focus_check)
        return False

    def step_unrelated_focus_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "an-unrelated-focus-move-leaves-the-search-open",
                payload["total"] > 0
                and controller.is_searching
                and controller.preview.widget.is_focus(),
                f"marks left: {payload['total']}, is_searching: {controller.is_searching}, "
                f"preview_is_focus: {controller.preview.widget.is_focus()}",
            )
            self._schedule(500, self.step_search_mode_switch)

        self._marks(check)
        return False

    def step_search_mode_switch(self):
        controller = self._main_controller()
        controller.set_mode(Mode.SOURCE)
        self._schedule(600, self.step_search_mode_switch_check)
        return False

    def step_search_mode_switch_check(self):
        controller = self._main_controller()
        record("markdown-mode-closes-the-search", not controller.is_searching)
        controller.set_mode(Mode.PREVIEW)
        self._schedule(500, self.step_reload_search_setup)
        return False

    # --- search survives a full page reload ---------------------------------
    #
    # PreviewView remembers the live query and re-issues it on
    # LoadEvent.FINISHED (see `_search_request` in preview.py) precisely
    # because a fresh page is a fresh JS context with no memory of its own.
    # Nothing above exercises that: the theme/revert/save reload steps all
    # run before the search bar ever opens, and every search step after that
    # only swaps the body in place. This is the one path that puts both
    # together -- a live search, then a reload that is not a body swap.

    def step_reload_search_setup(self):
        controller = self._main_controller()
        controller.preview.widget.grab_focus()
        self._press(Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK)
        self._schedule(600, self.step_reload_search_query)
        return False

    def step_reload_search_query(self):
        controller = self._main_controller()
        controller.searchbar.set_query("Filler")
        self._schedule(900, self.step_reload_search_go)
        return False

    def step_reload_search_go(self):
        controller = self._main_controller()
        self._reload_baseline_total = controller.search.total
        # The same mechanism step_theme_switch uses above: a settings change
        # that forces a full `load_html` reload (a fresh JS context) rather
        # than the in-place `replaceBody` every other search step exercises.
        xedown_settings.get_settings().set(xedown_settings.PREVIEW_THEME, "focused")
        # A full reload of this fixture, not an in-place update: matches
        # step_scroll_toggle_back's own wait for the same-sized document
        # rather than the shorter waits the in-place search steps above use.
        self._schedule(1600, self.step_reload_search_check)
        return False

    def step_reload_search_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "search-survives-a-full-reload",
                self._reload_baseline_total == 360
                and payload["total"] == 360
                and controller.search.total == 360
                and controller.searchbar.get_query() == "Filler",
                f"before: {self._reload_baseline_total}, "
                f"page marks: {payload['total']}, session: {controller.search.total}",
            )
            self._schedule(400, self.step_error_search_setup)

        self._marks(check)
        return False

    # --- a render failure must settle the count, not leave a stale one -----
    #
    # `_reload_preview` bumps the search token before answering 0 for an
    # error page precisely so a reply already in flight from the page being
    # replaced cannot land afterwards and overwrite that answer (see the
    # comment above `self.search.invalidate()` in controller.py). It also
    # re-arms `PreviewView._search_request` with that same new token, so the
    # reissue `_on_load_changed` fires once a real document loads again
    # carries a token this session still accepts -- without that, a bare
    # `refresh_now()` would fix the render but never bring the count back,
    # because `SearchSession.set_query` only re-asks the page when the text
    # or the case flag actually changes, and neither does here. This drives
    # the whole path for real: a live search with real matches, a forced
    # failure, a second look after a further beat to prove nothing crept
    # back in, and then a plain refresh to prove the recovery is automatic.

    def step_error_search_setup(self):
        controller = self._main_controller()
        self._error_search_baseline_total = controller.search.total
        controller._reload_preview(
            error=RuntimeError("probe-forced search failure"), restore_scroll=0.0
        )
        self._schedule(900, self.step_error_search_settled)
        return False

    def step_error_search_settled(self):
        controller = self._main_controller()
        record(
            "an-error-page-settles-on-no-matches",
            controller.searchbar._status.get_text() == "No matches"
            and controller.search.total == 0,
            f"bar: {controller.searchbar._status.get_text()!r}, "
            f"session total: {controller.search.total!r}",
        )
        self._schedule(900, self.step_error_search_stays)
        return False

    def step_error_search_stays(self):
        controller = self._main_controller()
        record(
            "error-page-search-stays-at-no-matches",
            controller.searchbar._status.get_text() == "No matches"
            and controller.search.total == 0,
            f"bar: {controller.searchbar._status.get_text()!r}, "
            f"session total: {controller.search.total!r}",
        )
        # No further search interaction from here: restoring the document
        # is the whole action, and the count is expected to come back on
        # its own.
        controller.refresh_now()
        # A full reload (recovering from the error page back to a real
        # document) -- same margin as step_reload_search_go above.
        self._schedule(1600, self.step_error_search_recovered)
        return False

    def step_error_search_recovered(self):
        controller = self._main_controller()
        record(
            "error-page-search-recovers-after-restore",
            controller.search.total == self._error_search_baseline_total
            and controller.searchbar._status.get_text() != "No matches",
            f"before: {self._error_search_baseline_total}, "
            f"after: {controller.search.total}, "
            f"bar: {controller.searchbar._status.get_text()!r}",
        )
        self._schedule(400, self.step_showall_search_setup)
        return False

    # --- a stray show_all() must not raise a search bar nobody asked for ---

    def step_showall_search_setup(self):
        controller = self._main_controller()
        controller.close_search()
        self._schedule(400, self.step_showall_search_check)
        return False

    def step_showall_search_check(self):
        controller = self._main_controller()
        # Mirrors step_showall_preview above, for the search bar rather than
        # the frame/WebView: xed forces widgets visible on save and revert,
        # and the bar pins no_show_all precisely to survive that.
        self.tab.show_all()
        record(
            "a-stray-show-all-cannot-raise-the-search-bar",
            not controller.is_searching and not controller.searchbar.get_visible(),
            f"is_searching={controller.is_searching} "
            f"bar_visible={controller.searchbar.get_visible()}",
        )
        self._schedule(400, self.step_shift_return_setup)
        return False

    # --- Shift+Return steps backward exactly once, not twice ---------------
    #
    # The entry's own `activate` also fires on a bare Return, whether or not
    # Shift is held; `_on_entry_key` has to consume the event before that
    # happens or a single Shift+Return would step back AND forward, netting
    # to no move at all. Starting from match 0 and landing on the last match
    # after one press is what a double-fire could not produce by accident.

    def step_shift_return_setup(self):
        controller = self._main_controller()
        # Reuses whatever the entry still holds ("Filler", left over from the
        # error-recovery check above) -- open_search() re-runs it exactly as
        # a real reopen would.
        controller.open_search()
        self._schedule(900, self.step_shift_return_press)
        return False

    def step_shift_return_press(self):
        controller = self._main_controller()
        self._shift_return_index_before = controller.search.index
        self._shift_return_total = controller.search.total
        self._press(Gdk.KEY_Return, Gdk.ModifierType.SHIFT_MASK)
        self._schedule(600, self.step_shift_return_check)
        return False

    def step_shift_return_check(self):
        controller = self._main_controller()
        expected = (self._shift_return_index_before - 1) % self._shift_return_total
        record(
            "shift-return-steps-backward-once",
            self._shift_return_total > 1 and controller.search.index == expected,
            f"before: {self._shift_return_index_before}, "
            f"after: {controller.search.index}, expected: {expected}, "
            f"total: {self._shift_return_total}",
        )
        self._schedule(400, self.step_whitespace_match_setup)
        return False

    # --- a match covers a whole run of spaces, not one character of it -----
    #
    # Pins the task 5 fix: a collapsed space's map entry used to record only
    # its first character, so a match landing on an isolated whitespace text
    # node (here, the four spaces highlight.js leaves between "42" and "100"
    # once it wraps each in its own <span>) was marked one character short.
    # The query is typed with a single space -- collapse() would fold four
    # into one regardless, but typing it pre-collapsed is what a person
    # actually does, and is not what is under test here.

    def step_whitespace_match_setup(self):
        controller = self._main_controller()
        controller.open_search()
        self._schedule(600, self.step_whitespace_match_query)
        return False

    def step_whitespace_match_query(self):
        controller = self._main_controller()
        controller.searchbar.set_query("42 100")
        self._schedule(900, self.step_whitespace_match_check)
        return False

    def step_whitespace_match_check(self):
        controller = self._main_controller()
        preview = controller.preview

        def on_result(webview, result, _user_data):
            payload, failure = {}, ""
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                failure = f"<error: {exc}>"
            record(
                "a-match-covers-a-whole-run-of-spaces",
                controller.search.total == 1
                and payload.get("marks") == 3
                and payload.get("matchText") == "42    100"
                and not failure,
                f"session total: {controller.search.total}, "
                f"marks: {payload.get('marks')}, "
                f"matched text: {payload.get('matchText')!r}{failure}",
            )
            self._schedule(400, self.step_dotted_capital_query)

        preview.widget.run_javascript(
            "JSON.stringify({"
            "marks: document.querySelectorAll('mark.xedown-match').length,"
            "matchText: Array.prototype.map.call("
            "document.querySelectorAll('mark.xedown-match-current'),"
            "function (m) { return m.textContent; }"
            ").join('')"
            "})",
            None,
            on_result,
            None,
        )
        return False

    # --- a dotted capital must not shift the marks off the match -----------
    #
    # U+0130 is the one character whose UTF-16 length changes under
    # toLowerCase, so folding the whole flattened string at once left every
    # match position after one a character out of step with the map those
    # positions are turned back into DOM ranges through -- while still
    # reporting the right count, because the count is computed in haystack
    # coordinates. A count-only assertion therefore cannot see it at all:
    # this one reads the marked text back and compares it with the query.
    # `İstanbul` sits at the top of the fixture (see _long_markdown), so the
    # shift is upstream of every other search assertion here too.

    def step_dotted_capital_query(self):
        controller = self._main_controller()
        # The bar is still open from the whitespace step above, and still
        # case-insensitive -- step_search_case_check put the toggle back.
        # Case-insensitive is the whole point: the case-sensitive path never
        # folds anything and was never affected.
        controller.searchbar.set_query("sentinel")
        self._schedule(900, self.step_dotted_capital_check)
        return False

    def step_dotted_capital_check(self):
        controller = self._main_controller()
        preview = controller.preview

        def on_result(webview, result, _user_data):
            payload, failure = {}, ""
            try:
                value = webview.run_javascript_finish(result)
                payload = json.loads(value.get_js_value().to_string())
            except Exception as exc:  # noqa: BLE001 - a probe never crashes xed
                failure = f"<error: {exc}>"
            record(
                "a-dotted-capital-does-not-shift-the-marks",
                controller.search.total == 1
                and payload.get("marks") == 1
                and payload.get("markText") == "sentinel"
                and not failure,
                f"session total: {controller.search.total}, "
                f"marks: {payload.get('marks')}, "
                f"marked text: {payload.get('markText')!r}{failure}",
            )
            self._schedule(400, self.step_debounce_escape_setup)

        preview.widget.run_javascript(
            "JSON.stringify({"
            "marks: document.querySelectorAll('mark.xedown-match').length,"
            "markText: Array.prototype.map.call("
            "document.querySelectorAll('mark.xedown-match'),"
            "function (m) { return m.textContent; }"
            ").join('')"
            "})",
            None,
            on_result,
            None,
        )
        return False

    # --- a keystroke landing after Escape must not re-mark a closed search --
    #
    # GtkSearchEntry debounces `search-changed` by ~150 ms and cancels
    # nothing when the bar closes, so a query typed and then abandoned inside
    # that window arrives at the controller after close_search() has already
    # cleared the session and taken the marks out -- and used to be acted on,
    # because a non-empty query against an empty session is a new search.
    # Every other Escape check here waits out the debounce by construction,
    # which is exactly why none of them can see it: the typing and the Escape
    # below happen in the SAME main-loop turn, with no _schedule between.

    def step_debounce_escape_setup(self):
        controller = self._main_controller()
        # Focus in the entry, which is where a user typing a query is.
        controller.searchbar.focus_entry()
        self._schedule(400, self.step_debounce_escape_race)
        return False

    def step_debounce_escape_race(self):
        controller = self._main_controller()
        controller.searchbar.set_query("Paragraph")
        self._press(Gdk.KEY_Escape, Gdk.ModifierType(0))
        # Well past the entry's ~150 ms debounce, and past the page search it
        # would have provoked.
        self._schedule(900, self.step_debounce_escape_check)
        return False

    def step_debounce_escape_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "a-debounced-keystroke-cannot-re-mark-a-closed-search",
                payload["total"] == 0 and not controller.is_searching,
                f"marks left: {payload['total']}, "
                f"is_searching: {controller.is_searching}",
            )
            self._schedule(400, self.step_bar_button_escape_setup)

        self._marks(check)
        return False

    # --- Escape closes the bar from the bar's own buttons too --------------
    #
    # The bar is asked whether the focus xed stole was anywhere inside it,
    # not only whether it was the entry. Tabbing from the entry to the case
    # toggle and pressing Escape used to reclaim focus for the preview and
    # leave the bar open -- and on xed 3.8.9 this focus path is the live one,
    # so `shortcuts.route_key`'s own (wider) rule never got the chance to
    # disagree.

    def step_bar_button_escape_setup(self):
        controller = self._main_controller()
        # Re-runs whatever the entry still holds ("Paragraph", from the
        # abandoned keystroke above), so there is real highlighting to lose.
        controller.open_search()
        self._schedule(900, self.step_bar_button_escape_focus)
        return False

    def step_bar_button_escape_focus(self):
        controller = self._main_controller()
        # Neither the entry nor the preview: the bar's own case toggle, which
        # is exactly what one Tab press from the entry reaches.
        controller.searchbar._case.grab_focus()
        self._schedule(300, self.step_bar_button_escape_press)
        return False

    def step_bar_button_escape_press(self):
        self._press(Gdk.KEY_Escape, Gdk.ModifierType(0))
        self._schedule(700, self.step_bar_button_escape_check)
        return False

    def step_bar_button_escape_check(self):
        controller = self._main_controller()

        def check(payload):
            record(
                "escape-from-a-bar-button-also-closes-the-search",
                payload["total"] == 0 and not controller.is_searching,
                f"marks left: {payload['total']}, "
                f"is_searching: {controller.is_searching}",
            )
            self._schedule(400, self.step_moved_tab_search_open)

        self._marks(check)
        return False

    # --- Escape still closes the search after the tab changed windows ------
    #
    # Everything above presses Escape in the window this probe started in.
    # The tab moved back at step_move_tab_execute is the interesting one:
    # it kept the same TabController (that is what controller-survives-tab-
    # move asserts) but it lives in the second window now, and the whole
    # reason Escape closes the bar at all is a connection to ONE window's
    # "set-focus" (see TabController._attach_focus_watch, and
    # _on_window_set_focus for why that signal). A watch left behind on the
    # window the tab has left fails in perfect silence -- no error, no log
    # line, the bar simply stops closing for that tab -- so it takes a check
    # in the window the tab actually ended up in to see it at all.

    def step_moved_tab_search_open(self):
        controller = self._controller_for(self._move_view)
        window = self._move_dest_window
        # The move already leaves this tab current in the destination
        # window; asked rather than assumed, and only set when it is not,
        # so this does not switch the active tab for no reason (that exact
        # sequence -- move, then switch -- is what provokes the allowlisted
        # xed-core assertion, and it is the shutdown harness's job to
        # exercise it, not this check's).
        if window.get_active_tab() is not self._move_tab:
            window.set_active_tab(self._move_tab)
        window.present()
        # Focuses the entry, which is a "set-focus" in the DESTINATION
        # window -- the one the watch has to be on by now for _last_focus to
        # record it, and _last_focus is what tells the Escape below that the
        # focus xed steals was one of xedown's own widgets.
        controller.open_search()
        controller.searchbar.set_query("Moved")
        self._schedule(900, self.step_moved_tab_search_check)
        return False

    def step_moved_tab_search_check(self):
        controller = self._controller_for(self._move_view)

        def check(payload):
            # movable.md's body says "Moved to another window mid-sequence."
            # exactly once; its heading ("Movable") is not a match for it.
            record(
                "the-moved-tab-still-marks-its-matches",
                payload["total"] == 1 and controller.is_searching,
                f"marks: {payload['total']}, is_searching: {controller.is_searching}",
            )
            self._press(
                Gdk.KEY_Escape, Gdk.ModifierType(0), window=self._move_dest_window
            )
            self._schedule(700, self.step_moved_tab_escape_check)

        self._marks(check, controller)
        return False

    def step_moved_tab_escape_check(self):
        controller = self._controller_for(self._move_view)

        def check(payload):
            record(
                "escape-still-closes-the-search-after-a-tab-move",
                payload["total"] == 0 and not controller.is_searching,
                f"marks left: {payload['total']}, "
                f"is_searching: {controller.is_searching}",
            )
            # The mechanism behind it, checked separately so a failure says
            # which half broke: the watch is on the destination window now,
            # and the connection to the window this tab left is gone rather
            # than merely superseded.
            record(
                "the-focus-watch-moved-to-the-destination-window",
                controller._focus_window is self._move_dest_window
                and controller._focus_handler_id is not None,
                f"watching: {controller._focus_window!r}",
            )
            old_id = self._move_source_focus_id
            record(
                "the-focus-watch-let-go-of-the-window-the-tab-left",
                old_id is not None and not self.window.handler_is_connected(old_id),
            )
            self._schedule(400, self.step_settings_open)

        self._marks(check, controller)
        return False

    # --- the settings window, both ways in ---------------------------------

    def step_settings_open(self):
        """Open it the way a user would: the View-menu action.

        Through the action rather than by constructing the window directly, so
        the menu wiring is what gets exercised -- a window this probe built
        itself would pass even if the menu entry were never merged.
        """
        self._settings_file_before = xedown_settings.default_path().exists()
        action = self._find_action(xedown_shortcuts.SETTINGS)
        record("settings-action-is-in-the-menu", action is not None)
        if action is None:
            self._schedule(300, self.step_disable_prep_infobar)
            return False
        action.activate()
        self._schedule(600, self.step_settings_audit)
        return False

    def step_settings_audit(self):
        activatable = self._window_activatable_attr()
        window = getattr(activatable, "_settings_window", None)
        record("settings-window-opened", window is not None)
        if window is None:
            self._schedule(300, self.step_disable_prep_infobar)
            return False
        self._settings_window = window

        # Brief 13's standard over the real tree: names, roles, and focus
        # order following visual order.
        entries = window.accessible_entries()
        nodes = self._visible_state_nodes(window, entries)
        self._record_audit("a11y-settings-window", nodes)
        record(
            "settings-window-audited-every-control",
            len(nodes) == len(xedown_prefs.rows()) + 3,
            f"{len(nodes)} controls, expected {len(xedown_prefs.rows()) + 3}",
        )

        # Opening it must not have written anything.
        path = xedown_settings.default_path()
        record(
            "opening-the-settings-window-writes-nothing",
            path.exists() == self._settings_file_before,
            f"file existed before: {self._settings_file_before}, now: {path.exists()}",
        )
        self._schedule(300, self.step_settings_apply)
        return False

    def step_settings_apply(self):
        """A change made in the window reaches every open preview."""
        store = xedown_settings.get_settings()
        # step_reload_search_go, earlier in this same sequence, leaves the
        # store on "focused" already. GTK's combo box returns early without
        # emitting `changed` when `set_active_id` is given the id already
        # active, so flipping straight to "focused" from there would never
        # run the panel's own commit-and-broadcast path at all -- the checks
        # below would pass on stale state, not on anything this step did.
        # Force a genuinely different starting point first, through the
        # store directly: that's setup, not the thing under test.
        store.set(xedown_settings.PREVIEW_THEME, "repository")
        record(
            "settings-apply-precondition-not-already-focused",
            store.get(xedown_settings.PREVIEW_THEME) != "focused",
            f"theme before the panel change: "
            f"{store.get(xedown_settings.PREVIEW_THEME)!r}",
        )
        # Settings._notify delivers synchronously, so the panel's own combo
        # already reads "repository" here -- driven through the panel's
        # control, not the store, so it is the window's write path under
        # test, not the store's (already covered elsewhere).
        panel = self._settings_window.panel
        panel.control_for(xedown_settings.PREVIEW_THEME).set_active_id("focused")
        self._schedule(700, self.step_settings_apply_check)
        return False

    def step_settings_apply_check(self):
        store = xedown_settings.get_settings()
        record(
            "the-window-wrote-the-theme-to-the-store",
            store.get(xedown_settings.PREVIEW_THEME) == "focused",
            store.get(xedown_settings.PREVIEW_THEME),
        )
        # The same three controllers `step_theme_switch` names, enumerated the
        # same way rather than through a second helper that could disagree
        # with it.
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
            "every-open-preview-followed-the-window",
            len(controllers) == 3 and len(switched) == 3,
            f"{len(switched)} of {len(controllers)} controllers on focused",
        )
        self._schedule(300, self.step_settings_configurable)
        return False

    def step_settings_configurable(self):
        """The plugin manager's route, through peas rather than around it.

        This calls exactly what libpeas-gtk's Preferences button calls. It
        does NOT drive xed's Preferences dialog and click that button -- that
        last hop is a manual smoke-test row, and no claim is made about it
        here.
        """
        from gi.repository import Peas, PeasGtk

        engine = Peas.Engine.get_default()
        info = engine.get_plugin_info("xedown")
        record("peas-knows-xedown", info is not None)
        if info is None:
            self._schedule(300, self.step_settings_close)
            return False
        provides = engine.provides_extension(info, PeasGtk.Configurable.__gtype__)
        record(
            "the-plugin-manager-preferences-button-is-available",
            provides,
            "peas reports xedown provides PeasGtk.Configurable",
        )
        if provides:
            extension = engine.create_extension(
                info, PeasGtk.Configurable.__gtype__, [], []
            )
            widget = extension.create_configure_widget()
            entries = widget.accessible_entries() if widget else []
            record(
                "the-configure-widget-is-the-same-panel",
                len(entries) == len(xedown_prefs.rows()) + 2,
                f"{len(entries)} controls",
            )
            # Destroyed here rather than left to the garbage collector: this
            # panel holds a settings token, and the shutdown scenarios would
            # find it.
            if widget is not None:
                widget.destroy()
        self._schedule(300, self.step_settings_close)
        return False

    def step_settings_close(self):
        window = self._settings_window
        panel = window.panel
        window.destroy()
        record(
            "closing-the-settings-window-releases-its-subscription",
            panel._settings_token is None,
            f"token: {panel._settings_token!r}",
        )
        record(
            "closing-the-settings-window-leaves-no-armed-timer",
            not panel._settle,
            f"timers: {panel._settle!r}",
        )
        activatable = self._window_activatable_attr()
        record(
            "the-window-lets-go-of-the-settings-window",
            getattr(activatable, "_settings_window", "unset") is None,
        )
        # Put the theme back so later steps see the state they expect.
        xedown_settings.get_settings().set(xedown_settings.PREVIEW_THEME, "repository")
        self._settings_window = None
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
        # Captured now, held on the probe rather than re-found after
        # disable: do_deactivate() clears this object's own bookkeeping but
        # does not stop existing, so a reference taken here is what lets
        # step_disable_check still ask it anything once the plugin is gone.
        self._window_activatable = self._find_window_activatable()
        record(
            "window-activatable-found-before-disable",
            self._window_activatable is not None,
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
        # Same claim as the settings store above, for the stylesheet watcher:
        # it is the other long-lived global every controller subscribes to,
        # and a missed disconnect there is just as much of a leak.
        watcher = xedown_stylewatcher.get_watcher()
        record(
            "disable-no-stylewatcher-listeners-left",
            not watcher._listeners,
            f"listeners left: {sorted(watcher._listeners)!r}",
        )
        # The accelerator-closure leak Fix 2 exists to catch: a leaked alias
        # closure holds a bound method of XedownWindowActivatable, which
        # holds the window, and none of it shows up as terminal output --
        # the shutdown harness proving the log stays silent cannot tell that
        # apart from this actually being torn down. Checked on the instance
        # captured before disable, since the object itself has no reason to
        # stop existing just because do_deactivate() ran.
        activatable = getattr(self, "_window_activatable", None)
        record(
            "disable-key-press-handler-cleared",
            activatable is not None and activatable._key_press_handler_id is None,
        )
        record(
            "disable-alias-accels-cleared",
            activatable is not None and not activatable._alias_accels,
            f"aliases left: {getattr(activatable, '_alias_accels', None)!r}",
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
