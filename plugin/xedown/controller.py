"""Orchestrates one tab: mode bar, preview, scroll memory, refresh, teardown."""

import os
import weakref

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import GLib, Gtk, Xed

from . import (
    a11y,
    direction,
    diskstate,
    errors,
    images,
    imagescheme,
    modestore,
    perflimits,
    remoteimages,
    renderer,
    settings,
    stylesheets,
    stylewatcher,
)
from .appearance import AppearanceWatcher
from .document_state import DocumentState, Mode, is_markdown_path, mode_from_setting
from .filewatch import FileWatch
from .links import LinkAction, classify_link
from .modebar import ModeBar
from .preview import PreviewView
from .search import SearchSession
from .searchbar import SearchBar

# xed's own Revert command, looked up by the name it is registered under
# rather than by its menu path: the path is UI XML a future xed is free to
# rearrange, while the name is what the command *is*.
REVERT_ACTION = "FileRevert"
EXTERNAL_CHANGE_MESSAGE = (
    "This file changed on disk. Your unsaved edits are still showing."
)
# The ellipsis is honest rather than decorative: xed's own confirmation
# dialog follows, and that dialog -- not xedown -- is what discards the
# user's work.
RELOAD_LABEL = "Reload…"

# Every controller currently alive in this process, so that the last one out
# can release the image-fetch resources `imagescheme` holds on everyone's
# behalf -- a thread pool with queued fetches in it, which nothing else in
# the plugin is positioned to shut down (a plugin disable, or the last window
# closing, must not leave workers dialling hosts for tabs that no longer
# exist). Added in `activate` and dropped in `deactivate`, which is the same
# pair of moments the view's own `_xedown_controller` attribute exists
# between, so this cannot go stale the way a second reference held elsewhere
# would: it is not another source of truth about *which* controller a view
# has, only a count of how many are still running. Weak, so a controller that
# somehow escapes teardown is still collectable and still leaves the set --
# strong references here would turn that into a leak for the life of xed.
_live_controllers = weakref.WeakSet()


class TabController:
    """One per view. Owns and disconnects everything it creates."""

    def __init__(self, view):
        self.view = view
        self.document = view.get_buffer()
        self.tab = Xed.Tab.get_from_document(self.document)
        self.frame = self.tab.get_children()[0] if self.tab is not None else None

        self.state = DocumentState()
        self.modebar = None
        self.searchbar = None
        self.search = SearchSession()
        self.preview = None
        self.appearance_watcher = None
        self._settings_token = None

        self._handlers = []  # (gobject, handler_id)
        self._refresh_source_id = 0
        self._built = False
        # False while an error page is loaded. `update_body` cannot reach one:
        # errors.error_page carries no preview.js, so `window.xedown` does not
        # exist in it and the script silently does nothing.
        self._page_is_document = False
        self._active = False
        self._dark = False
        self._style = None
        self._image_display = images.DISPLAY_PLACEHOLDER
        self._copy_buttons = True
        self._auto_refresh = True
        # Set by `_apply_size_guard`. `True` until a document has been
        # measured, so nothing is withheld from a tab that has not loaded.
        self._size_allows_live_refresh = True
        self._preview_deferred = False
        # The chip's label, computed once at the moment `_preview_deferred`
        # is set -- by `_build_if_markdown`, or by `_on_document_loaded` on
        # the build/load race described below -- and never touched again
        # while it stays true. `_apply_size_guard` runs on every keystroke,
        # so it only ever reads this rather than re-measuring the buffer --
        # see that method's docstring. A label that goes stale after
        # someone pastes megabytes into an already-deferred document is
        # accepted: it is a size hint offered once, not a live readout.
        self._deferred_size_label = None
        # Set by `_build_if_markdown`, to True exactly when it measured an
        # empty buffer -- the signature of losing its race against xed's
        # own asynchronous file read, not merely "this is the tab's first
        # `loaded` event". A document built via New -> Save As never gets
        # a `loaded` event of its own at all (`_on_document_saved` queues
        # the build directly), so *its* first `loaded` is a genuine later
        # revert; answering "was this the first `loaded`" instead of "did
        # the build see nothing" treated that revert as a raced initial
        # open and could switch a reader out of a Preview they were
        # actively reading. `_on_document_loaded` consumes this -- sets it
        # back to False -- the first time it checks it, win or lose, so
        # only the one `loaded` immediately following an empty-buffer
        # build is ever treated specially; see that method's docstring.
        self._awaiting_initial_content = False
        self._refresh_delay_ms = 250
        self._text_direction = direction.AUTO
        self._ui_direction = direction.LTR
        self._stylesheet_token = None
        self._info_bar = None
        # What the current bar's action button does, if it has one.
        self._info_bar_action = None
        # The external-change bar specifically, when it is the one in the
        # tab's single slot. Tracked apart from `_info_bar` so that retiring
        # it can never destroy a link-error bar showing in its place.
        self._external_bar = None
        # The text of the file on disk, as of the last settled external
        # change that differed from the buffer -- and None at every other
        # time. `_render_text` is the only reader; see its docstring for what
        # it means, and `_on_document_saved`/`_on_document_loaded` for the two
        # events that clear it.
        self._disk_text = None
        self._watch = None
        self._watch_external = True
        # Work that arrived while xed was mid-load or mid-save, waiting for
        # the tab to go quiet again. Two flags, not one: see
        # `_run_deferred_work`. See `_tab_is_quiet` for why either defers.
        self._settle_deferred = False
        self._modified_deferred = False
        # The path this tab's remembered mode is filed under. Compared on
        # save, so a Save As moves the entry instead of stranding it.
        self._remembered_path = None
        # The last non-None widget this window's "set-focus" reported, for
        # this tab. See _on_window_set_focus: GTK commonly emits
        # "set-focus(None)" between two widgets, so only a non-None value is
        # ever remembered here -- otherwise "previous" would read None at
        # exactly the moment it matters.
        self._last_focus = None
        # The window whose "set-focus" is currently being watched, and the
        # id of that one connection. Deliberately not in `self._handlers`:
        # this connection has to MOVE with the tab, not only be torn down
        # with it. See _attach_focus_watch.
        self._focus_window = None
        self._focus_handler_id = None
        # This tab's own permission to fetch the remote images its document
        # names, granted by the reader pressing Load. Per tab and per
        # session: it survives mode switches, reloads and reverts, a tab
        # close is what ends it, and it never extends to the same file open
        # in another tab -- which is the point, since the grant is about the
        # document the reader looked at and decided to trust.
        self._remote_unblocked = False

    # --- lifecycle ---------------------------------------------------------

    def activate(self):
        self._active = True
        _live_controllers.add(self)
        self._connect(self.document, "saved", self._on_document_saved)
        self._connect(self.document, "loaded", self._on_document_loaded)
        if self.tab is not None:
            self._connect(self.tab, "notify::state", self._on_tab_state_changed)
        GLib.idle_add(self._build_if_markdown)

    def deactivate(self):
        # Flip this first: a `_build_if_markdown` already queued via
        # GLib.idle_add (from activate(), or re-entrantly from a reload
        # handler) must see this and refuse to build after teardown.
        self._active = False
        self._cancel_refresh()
        self._stop_watch()
        self._disk_text = None
        self._settle_deferred = False
        self._modified_deferred = False
        for owner, handler_id in self._handlers:
            try:
                owner.disconnect(handler_id)
            except (TypeError, RuntimeError):
                pass
        self._handlers = []
        self._detach_focus_watch()
        # Also cleared by the line above; stated here so the guarantee that a
        # torn-down controller holds no other tab's view (and so no other
        # tab's buffer) does not depend on that call staying where it is.
        self._last_focus = None

        if self._settings_token is not None:
            settings.get_settings().disconnect(self._settings_token)
            self._settings_token = None

        if self._stylesheet_token is not None:
            stylewatcher.get_watcher().disconnect(self._stylesheet_token)
            self._stylesheet_token = None

        # The third process-wide registration this controller makes, and the
        # third that has to be given back here. Unconditional: the list
        # tolerates a callback that never listened, which is every tab that
        # was never built (`_build_if_markdown` is where it is added).
        imagescheme.forget_failure_listener(self._on_remote_image_failed)

        if self.appearance_watcher is not None:
            self.appearance_watcher.disconnect()
            self.appearance_watcher = None

        self._dismiss_info_bar()

        # Always hand the source editor back, whatever mode we were in.
        if self.frame is not None:
            self.frame.set_no_show_all(False)
            self.frame.show()

        if self.preview is not None:
            self.preview.widget.set_no_show_all(False)
            self.preview.destroy()
            self.preview = None
        if self.modebar is not None:
            self.modebar.destroy()
            self.modebar = None
        if self.searchbar is not None:
            self.searchbar.destroy()
            self.searchbar = None
        self._built = False

        # Last one out. Done after the WebView above is destroyed, so any
        # scheme request still outstanding is already orphaned by the time
        # the fetcher stops answering -- `imagescheme.shutdown()` cancels
        # queued fetches without answering their callbacks, and that is only
        # harmless for requests whose page has gone. The emptiness test is
        # what keeps a closing tab from tearing the pool out from under a
        # tab in another window: while any controller is still registered,
        # this does nothing. A later request cannot land on the fetcher this
        # tears down either -- `imagescheme._on_request` asks `get_fetcher()`
        # fresh every time, and that function builds a new one rather than
        # returning the shut-down instance, which is what makes a
        # disable/re-enable cycle work as well.
        _live_controllers.discard(self)
        if not _live_controllers:
            imagescheme.shutdown()

    def _connect(self, owner, signal, callback):
        self._handlers.append((owner, owner.connect(signal, callback)))

    def _untrack(self, owner):
        """Drop `owner`'s entries from `self._handlers`.

        Used when something this controller connected to is destroyed
        outside of `deactivate()` (the info bar, dismissed by its own Close
        button): `destroy()` already invalidates the widget's signal
        connections, so leaving the bookkeeping entry behind would make
        `deactivate()`'s bulk disconnect try to disconnect an id that no
        longer exists.
        """
        self._handlers = [(o, h) for o, h in self._handlers if o is not owner]

    def _attach_focus_watch(self, *_args):
        """Watch the "set-focus" of the window this tab is in *right now*.

        Why the signal is watched at all is `_on_window_set_focus`'s own
        docstring. Why it is tracked here instead of through `_connect` is
        the tab move: `Documents -> Move to New Window` (and dragging a tab
        out) re-parents the very same tab into another window, and this
        controller deliberately survives that -- see
        `XedownWindowActivatable._on_tab_removed`. A connection made once,
        to the window the tab happened to be in when the controller was
        built, would still be attached to the window the tab has left, and
        Escape would silently stop closing the search bar for that tab.

        So this connection is moved rather than only torn down: called
        again after the tab's toplevel changed (from `hierarchy-changed`,
        connected in `_build_if_markdown`), it drops the old connection and
        makes a new one against the new window. It is idempotent -- called
        for the window already watched, it does nothing -- and it takes the
        `hierarchy-changed` arguments it ignores, so it can be connected
        directly.

        No `GLib.idle_add` here, unlike `_on_tab_removed`: that handler has
        to *wait* to learn whether a move or a close happened, because
        "tab-removed" cannot tell them apart. This has nothing to wait for.
        `_toplevel()` answers the only question it asks, the answer is
        already correct at emission time (both halves of a move -- the
        unparent and the re-parent -- emit `hierarchy-changed` in turn,
        synchronously), and re-running it later can only produce the same
        answer. During the unparent half, and during teardown,
        `get_toplevel()` returns a widget that is no window at all;
        `_toplevel()` already answers None for that, which detaches and
        waits for the re-parent (or for `deactivate`).
        """
        window = self._toplevel()
        if window is self._focus_window:
            return
        self._detach_focus_watch()
        if window is None:
            return
        self._focus_window = window
        self._focus_handler_id = window.connect("set-focus", self._on_window_set_focus)

    def _detach_focus_watch(self):
        """Drop the "set-focus" connection, if one is live.

        Defensive about the window already being disposed, for the same
        reason `deactivate()`'s bulk disconnect loop is: this runs during
        teardown too, and a disconnect against a window GTK has already
        finalised raises rather than returning quietly.

        `_last_focus` goes with the connection that fed it. The watch is
        per-tab on a signal the whole *window* shares, so what it records is
        routinely some other tab's widget -- and a `Xed.View` held here is
        that tab's buffer held too. Dropping it is also the right answer for
        the tab move this method is half of: the widget last focused in the
        window the tab has left is no answer to any question the new window
        will ask.
        """
        if self._focus_window is not None and self._focus_handler_id is not None:
            try:
                self._focus_window.disconnect(self._focus_handler_id)
            except (TypeError, RuntimeError):
                pass
        self._focus_window = None
        self._focus_handler_id = None
        self._last_focus = None

    # --- construction ------------------------------------------------------

    @property
    def is_markdown(self):
        return is_markdown_path(self._document_path())

    @property
    def is_previewing(self):
        """The preview is the surface the user is looking at, in this tab."""
        return (
            self._built
            and self.preview is not None
            and self.state.mode is Mode.PREVIEW
            and self.is_markdown
        )

    def _document_path(self):
        location = self.document.get_location()
        return location.get_path() if location is not None else None

    def _base_dir(self):
        path = self._document_path()
        return os.path.dirname(path) if path else None

    def _build_if_markdown(self):
        """Non-Markdown documents get no mode bar constructed at all."""
        if not self._active or self._built or not self.is_markdown or self.tab is None:
            return False

        self.appearance_watcher = AppearanceWatcher()
        self._dark = self.appearance_watcher.current_dark()
        self.appearance_watcher.connect(self._on_appearance_changed)

        store = settings.get_settings()
        # Connected before the style is built, so `current()` is the value
        # this tab renders with and the value the watcher will report from.
        self._stylesheet_token = stylewatcher.get_watcher().connect(
            self._on_user_stylesheet_changed
        )
        self._style = stylesheets.PreviewStyle.from_settings(
            store, user=stylewatcher.get_watcher().current()
        )
        self._settings_token = store.connect(self._on_settings_changed)
        # `image_fallback`, not `remote_images`: the first is what to show in
        # place of an image that is not being displayed, the second is the
        # fetch policy and is read per render by `_fetch_remote`.
        self._image_display = images.coerce_display(store.get(settings.IMAGE_FALLBACK))
        self._copy_buttons = bool(store.get(settings.CODE_COPY_BUTTONS))
        self._auto_refresh = bool(store.get(settings.AUTO_REFRESH))
        self._refresh_delay_ms = int(store.get(settings.REFRESH_DELAY_MS))
        self._text_direction = store.get(settings.TEXT_DIRECTION)
        self._watch_external = bool(store.get(settings.WATCH_EXTERNAL_CHANGES))
        # The desktop's own direction, which xedown's chrome inside the page
        # follows -- the mode bar already gets this free from GTK. Read once:
        # a desktop's text direction is fixed at login, and nothing in xed
        # signals a change to it.
        self._ui_direction = (
            direction.RTL
            if Gtk.Widget.get_default_direction() == Gtk.TextDirection.RTL
            else direction.LTR
        )

        self.modebar = ModeBar()
        self.tab.pack_start(self.modebar, False, False, 0)
        self.tab.reorder_child(self.modebar, 0)
        self.modebar.show_all()
        self._connect(self.modebar, "mode-selected", self._on_mode_selected)
        self._connect(self.modebar, "refresh-requested", self._on_refresh_requested)
        self._connect(
            self.modebar, "load-images-requested", self._on_load_images_requested
        )
        self._connect(
            self.modebar, "build-preview-requested", self._on_build_preview_requested
        )

        # Before the WebView exists, because the handler is installed on the
        # default web context and a page can ask for a `xedown-image:` URL
        # from the moment it loads. `register_once` is idempotent for the
        # life of the process; the listener is added exactly once per built
        # tab (this method refuses to run twice, `_built` sees to that) and
        # removed again in `deactivate`.
        imagescheme.register_once()
        imagescheme.note_failure_listener(self._on_remote_image_failed)

        self.preview = PreviewView(
            on_link=self._on_link_activated,
            on_image_error=self._on_image_error,
            on_search=self._on_search_count,
        )
        self.tab.pack_start(self.preview.widget, True, True, 0)

        # Packed from the trailing edge, so it sits under the preview where
        # xed's own find bar sits. The mode bar keeps the top; nothing in
        # _enforce_visibility touches the end of the box.
        self.searchbar = SearchBar()
        self.tab.pack_end(self.searchbar, False, False, 0)
        self._connect(self.searchbar, "query-changed", self._on_search_query_changed)
        self._connect(self.searchbar, "step-requested", self._on_search_step)
        self._connect(self.searchbar, "close-requested", self._on_search_close)

        self._connect(self.document, "changed", self._on_buffer_changed)
        self._connect(self.document, "modified-changed", self._on_modified_changed)

        # See _on_window_set_focus's docstring: xed's own Escape handling
        # can hand focus straight to the hidden source view without ever
        # reaching this controller's own key routing. The watch follows the
        # tab from window to window (see _attach_focus_watch), so the tab's
        # own "hierarchy-changed" -- which is tracked normally, and so is
        # torn down with everything else -- is what re-points it.
        self._connect(self.tab, "hierarchy-changed", self._attach_focus_watch)
        self._attach_focus_watch()

        self._built = True
        self._remembered_path = self._document_path()
        # After `_built`, because `_on_file_settled` refuses to act before it.
        if self._watch_external:
            self._start_watch()
        initial = self._initial_mode()
        char_count = self._document_char_count()
        # Recorded before the decision below, not derived from it: this is
        # what `_on_document_loaded` reads to tell a raced initial load
        # apart from a later revert -- see `_awaiting_initial_content`'s
        # own comment in `__init__` for why "was the buffer empty" is the
        # right question and "was this the first `loaded` event" was not.
        self._awaiting_initial_content = char_count == 0
        # A document large enough that building its preview costs about a
        # second opens in Markdown mode instead, with the chip offering the
        # preview. The reader then pays that second knowingly. Only the
        # *initial* build is deferred: choosing Preview from the mode bar
        # afterwards is a request, and requests are honoured at any size.
        if initial is Mode.PREVIEW and perflimits.classify(char_count).defer_initial:
            self._preview_deferred = True
            # Computed once, here, rather than by `_apply_size_guard` on
            # every keystroke -- see `_deferred_size_label`'s own comment.
            self._deferred_size_label = perflimits.describe_bytes(
                len(self._render_text().encode("utf-8"))
            )
            initial = Mode.SOURCE
        self._apply_size_guard()
        self.set_mode(initial, initial=True)
        return False

    # --- mode switching ----------------------------------------------------

    def toggle(self):
        self.set_mode(Mode.SOURCE if self.state.mode is Mode.PREVIEW else Mode.PREVIEW)

    def _initial_mode(self):
        """The mode this file opens in.

        A remembered mode wins when remembering is on; otherwise the default.
        Anything unusable falls back silently: which mode a file opens in is
        not worth a dialog or a warning, so a value that cannot be determined
        is treated the same as one that was never set, rather than stopping
        the file from opening cleanly.
        """
        store = settings.get_settings()
        if store.get(settings.REMEMBER_MODE_PER_FILE):
            remembered = modestore.get_store().get(self._document_path())
            if remembered is not None:
                return remembered
        return mode_from_setting(store.get(settings.DEFAULT_MODE)) or Mode.PREVIEW

    def _remember_mode(self, mode):
        """File this tab's mode under its path, when remembering is on."""
        if not settings.get_settings().get(settings.REMEMBER_MODE_PER_FILE):
            return
        modestore.get_store().remember(self._document_path(), mode)

    def set_mode(self, mode, initial=False):
        """Show `mode`. `initial` is the build-time call, which is different.

        Going to the mode you are already in does nothing: re-running the
        branches below would re-grab focus and re-file the mode for no
        change anyone would see. The build-time call is exempt, because that
        is the call that first makes one of the two widgets visible.

        `initial` also suppresses three things that would each be a
        regression on a file opening in Markdown mode: restoring the source
        scroll (which applies fraction 0.0 and would scroll over the position
        xed just restored), grabbing focus (xed opens several tabs at once,
        and grabbing focus in a notebook page that is not current moves the
        window's focus off the tab the user is looking at), and writing to
        the mode store (opening a file must not rewrite the memory it was
        just read from).

        It also decides, before anything below moves focus, whether this
        switch gets a spoken announcement (see `_announce_mode`): both
        directions of Ctrl+Shift+M measured completely silent on their own
        (Task 5 of the Orca verification plan, once `row-97-focus-mode-bar`
        got a marker of its own -- Task 4's version of this same claim was
        inferred by subtracting a misattributed utterance from a
        contaminated window, not measured cleanly), which is the gap this
        checks for. `self.modebar.has_focus_inside()` is read first, ahead
        of every state change below, because it is only meaningful *before*
        the switch: if the user tabbed to a mode button and activated it,
        that focus is what makes Orca announce the toggle's own state
        change, and this must not add a second announcement on top of it.

        This is also the one place that clears `_preview_deferred`, because
        it is where every route into Preview converges -- the mode bar's own
        Preview segment (`_on_mode_selected`), Ctrl+Shift+M (`toggle()`), and
        the chip's own button (`_on_build_preview_requested`) all end up
        here rather than each having to remember to touch the flag
        themselves. The build-time call from `_build_if_markdown` cannot
        undo its own deferral by accident: when it defers, it passes
        `Mode.SOURCE`, never `Mode.PREVIEW`, to this method, so the guard
        below (`mode is Mode.PREVIEW`) never sees that call.
        """
        if not self._built:
            return
        if mode is self.state.mode and not initial:
            return
        if mode is Mode.PREVIEW and self._preview_deferred:
            self._preview_deferred = False
            self._apply_size_guard()
        announce = not initial and not self.modebar.has_focus_inside()
        self._remember_scroll(self.state.mode)
        self.state.mode = mode
        self.modebar.set_mode(mode)
        if not initial:
            self._remember_mode(mode)

        if mode is Mode.PREVIEW:
            if self.state.preview_stale:
                # A full reload is async; the scroll fraction is applied by
                # PreviewView once the new page actually finishes loading.
                self._reload_preview(restore_scroll=self.state.preview_scroll)
            else:
                self.preview.set_scroll(self.state.preview_scroll)
            self.frame.set_no_show_all(True)
            self.frame.hide()
            # Mirror the frame: clear no-show-all before show_all(), since
            # show_all() is itself blocked by the flag while it is set.
            self.preview.widget.set_no_show_all(False)
            self.preview.widget.show_all()
            if not initial:
                # Required for the selection the user makes to be the one
                # copy acts on, and it also fixes Page_Down scrolling a
                # hidden text view. Skipped on the build-time call: see the
                # docstring.
                self.preview.widget.grab_focus()
        else:
            # Before the widgets swap, not after: the marks come out of a page
            # that is still the visible one, and a bar left open would hang
            # over an editor it does not control.
            self.close_search(focus_preview=False)
            # Mirror the frame's mitigation on the other widget: without
            # this, a bare show_all() on the tab while in source mode would
            # re-reveal the WebView (packed expand=True) alongside the
            # source editor.
            self.preview.widget.set_no_show_all(True)
            self.preview.widget.hide()
            self.frame.set_no_show_all(False)
            self.frame.show()
            if not initial:
                self._restore_source_scroll()
                self.view.grab_focus()
        self._update_refresh_cue()
        if announce:
            self._announce_mode(mode)

    def _announce_mode(self, mode):
        """Tell a screen reader which mode is now showing.

        Only reached when `set_mode` decided, before it moved anything, that
        the mode bar did not already have focus -- see that method's own
        docstring for why the check has to happen that early. The text comes
        from `a11y.NAMES`, never a literal: `test_a11y.py`'s
        `test_every_accessible_name_in_the_host_modules_comes_from_names`
        exists specifically to catch an inlined string here.
        """
        key = a11y.mode_announcement_name(mode)
        if key is not None and self.modebar is not None:
            self.modebar.announce(a11y.NAMES[key])

    def refresh_now(self):
        """Re-render the preview from the document as it is now.

        Nothing to do in Markdown mode: the preview is already stale and
        switching to it renders. Rendering into a hidden WebView to reach the
        same state would be work the user cannot see happen -- exactly the
        eager, unseen rendering that turning `auto_refresh` off is meant to
        avoid, done anyway just with an extra step in front of it.
        """
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return
        # Refresh means "try again", and that includes the remote images that
        # did not arrive: the fetcher remembers failures precisely so that a
        # re-render every 250ms does not re-dial a dead host four times a
        # second, and this is one of the three moments (with the Load button
        # and a reconnect) at which a reader has said to forget them.
        # Successes are kept. Asked only of a tab that is actually fetching:
        # for a blocked document the answer could not change anything, and
        # `get_fetcher()` would build a thread pool to be told so.
        if self._fetch_remote():
            imagescheme.get_fetcher().invalidate_failures()
        self._cancel_refresh()
        self._refresh_body_now()

    def _update_refresh_cue(self):
        """Keep the bar's refresh control telling the truth.

        Visible only where clicking it would do something: `refresh_now`
        is a no-op outside Preview mode (typing in Markdown mode already
        leaves the preview stale, and switching back is what renders it),
        so a control that appeared there anyway would sit stale-marked and
        unresponsive for as long as the user kept editing.
        """
        if self.modebar is None:
            return
        self.modebar.set_refresh_visible(
            not self._live_refresh_allowed() and self.state.mode is Mode.PREVIEW
        )
        self.modebar.set_stale(self.state.preview_stale)

    def _document_char_count(self):
        """How long the document is, without copying it.

        `GtkTextBuffer.get_char_count` is O(1); `_render_text()` copies the
        whole buffer into a Python string. This is consulted on every
        keystroke, so the difference matters -- fetching a megabyte per
        keypress to decide whether a megabyte is too big to render would
        be its own performance bug, in the guard meant to prevent one.

        Defensive about the buffer being unavailable during teardown, and
        answers 0 there: an unmeasurable document is unconstrained, which
        is what `perflimits.classify` does with 0 anyway.
        """
        try:
            return int(self.document.get_char_count())
        except Exception:  # noqa: BLE001 - a guard must not raise into a render
            return 0

    def _apply_size_guard(self):
        """Ask `perflimits` about the document as it stands, and show the chip.

        Called from the build path, from `_on_document_loaded` (both its
        ordinary reload branch and the build/load race branch), and from
        every buffer change, because a document can cross a threshold by
        being typed into or pasted over -- the guard is about the text
        right now, not the file that was opened.

        Counted in characters: that is what the parser processes, and the
        count is free. The chip's label is *not* recomputed here -- it is
        `self._deferred_size_label`, set once, at the moment deferral
        happens. This method runs from `_on_buffer_changed`, i.e. on every
        keystroke while a document stays deferred, so it must never touch
        the buffer itself: `perflimits.describe_bytes`'s own docstring says
        that label is "built once, when the chip appears -- never on the
        per-keystroke path", and this is that path.
        """
        decision = perflimits.classify(self._document_char_count())
        self._size_allows_live_refresh = decision.live_refresh
        if self.modebar is not None:
            self.modebar.set_large_document(
                self._deferred_size_label if self._preview_deferred else None
            )
        return decision

    def _live_refresh_allowed(self):
        """Both the reader's preference and the size guard must agree.

        The guard overrides `AUTO_REFRESH` rather than consulting it: a
        reader who turned live refresh on expressed a preference about
        ordinary documents, not a request to have the editor freeze on a
        large one. The override is derived and per-tab, so it neither
        writes to the settings store nor persists -- the same reader
        opening a small document in the next tab gets live refresh as
        configured, and the refresh cue already says which state a tab is
        in.
        """
        return self._auto_refresh and self._size_allows_live_refresh

    def _on_refresh_requested(self, _bar):
        self.refresh_now()

    def _current_preview_scroll(self):
        """The scroll fraction to preserve across a reload while previewing.

        Distinct from `self.state.preview_scroll`, which is only updated on
        a mode switch away from preview — a reload triggered *while already
        in preview mode* (external reload, theme change, a render retry)
        needs the live position instead.
        """
        return (
            self.preview.last_scroll
            if self.preview is not None
            else self.state.preview_scroll
        )

    def _remember_scroll(self, mode):
        if mode is Mode.PREVIEW and self.preview is not None:
            self.state.store_scroll(Mode.PREVIEW, self.preview.last_scroll)
        elif mode is Mode.SOURCE:
            adjustment = self._source_adjustment()
            if adjustment is not None:
                span = adjustment.get_upper() - adjustment.get_page_size()
                self.state.store_scroll(
                    Mode.SOURCE, (adjustment.get_value() / span) if span > 0 else 0.0
                )

    def _source_adjustment(self):
        scroller = self.view.get_parent()
        return (
            scroller.get_vadjustment()
            if isinstance(scroller, Gtk.ScrolledWindow)
            else None
        )

    def _restore_source_scroll(self):
        def apply_scroll():
            if not self._built:
                return False
            adjustment = self._source_adjustment()
            if adjustment is not None:
                span = adjustment.get_upper() - adjustment.get_page_size()
                adjustment.set_value(max(0.0, span * self.state.source_scroll))
            return False

        GLib.idle_add(apply_scroll)

    # --- search ------------------------------------------------------------

    @property
    def is_searching(self):
        """The search bar is open in this tab."""
        return self.searchbar is not None and self.searchbar.get_visible()

    def focus_is_search_entry(self, widget):
        """`widget` is this tab's own search entry, not somebody else's."""
        return self.searchbar is not None and self.searchbar.owns_focus(widget)

    def open_search(self):
        """Show the bar and put the cursor in it.

        Re-runs whatever query the entry still holds: the bar keeps its text
        for the life of the tab, and reopening it over a query with no
        highlighting would look broken.
        """
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return
        self.searchbar.show()
        self.searchbar.focus_entry()
        self._request_search(
            self.searchbar.get_query(), self.searchbar.get_case_sensitive()
        )

    def close_search(self, focus_preview=True):
        """Hide the bar, take the marks out, and hand focus back.

        `focus_preview` is False for the one caller that is on its way
        somewhere else: a mode switch to Markdown, which grabs focus for the
        source view a moment later and must not have it taken back.
        """
        if self.searchbar is None or not self.searchbar.get_visible():
            return
        self.searchbar.hide()
        self.searchbar.set_status("")
        self.search.clear()
        if self.preview is not None:
            self.preview.clear_search()
            if focus_preview:
                self.preview.widget.grab_focus()

    def _request_search(self, query, case_sensitive):
        """Take a query from the bar and ask whoever can answer it."""
        if not self.search.set_query(query, case_sensitive):
            return
        if not self.search.active:
            if self.preview is not None:
                self.preview.clear_search()
            self.searchbar.set_status(self.search.status())
            return
        if not self._page_is_document:
            # An error page carries no preview.js, so there is nobody to ask
            # and the honest answer is none. Answering here rather than
            # refusing to open the bar is what keeps Ctrl+F behaving the same
            # way everywhere.
            self._report_search(0, False, self.search.token)
            return
        self.preview.search(
            self.search.query, self.search.case_sensitive, self.search.token
        )

    def _report_search(self, count, capped, token):
        if not self.search.report(count, capped, token):
            return  # an answer for a query the user has already replaced
        if self.search.index >= 0 and self.preview is not None:
            self.preview.set_search_index(self.search.index)
        if self.searchbar is not None:
            self.searchbar.set_status(self.search.status())

    def _on_search_count(self, count, capped, token):
        self._report_search(count, capped, token)

    def _on_search_query_changed(self, _bar, query, case_sensitive):
        # GtkSearchEntry debounces `search-changed` by ~150ms and does not
        # cancel a pending emission when the bar closes, so a keystroke can
        # land here after close_search() has already cleared the session and
        # the marks. Acting on it would re-mark a page the user has dismissed.
        if not self.is_searching:
            return
        self._request_search(query, case_sensitive)

    def _on_search_step(self, _bar, forward):
        index = self.search.step(forward)
        if index is None:
            return
        if self.preview is not None:
            self.preview.set_search_index(index)
        self.searchbar.set_status(self.search.status())

    def _on_search_close(self, _bar):
        self.close_search()

    # --- the verified host hazard -----------------------------------------

    def _on_tab_state_changed(self, *_args):
        """xed forces the frame visible on save and revert. Undo that.

        Also the moment work deferred by `_tab_is_quiet` gets its turn: the
        tab has just finished whatever it was doing, so a question that could
        not be answered honestly during a load or a save can be asked again
        now.
        """
        GLib.idle_add(self._enforce_visibility)
        if (self._settle_deferred or self._modified_deferred) and self._tab_is_quiet():
            GLib.idle_add(self._run_deferred_work)

    def _run_deferred_work(self):
        """Re-run what was skipped, each cause through its own handler.

        Two flags rather than one, because the two are not
        interchangeable: `_on_modified_changed`'s modified branch forces a
        body render so the bar's "your unsaved edits are still showing" is
        true when it appears, and `_on_file_settled` alone would raise the
        bar without it -- leaving that sentence over a preview still showing
        the file. Cleared before the call, so a tab that goes busy again
        mid-flight re-defers rather than losing the event: both handlers
        re-check `_tab_is_quiet` for themselves.

        With both flags set and the buffer clean, one call covers both:
        `_on_modified_changed`'s clean branch ends by asking
        `_on_file_settled` itself, and running it again in the same turn
        would re-read the file and re-render the body for an answer that
        cannot have changed. Harmless but not free -- a body render is a full
        Markdown conversion.
        """
        modified_deferred = self._modified_deferred
        settle_deferred = self._settle_deferred
        self._modified_deferred = False
        self._settle_deferred = False
        if modified_deferred:
            # Read before the call: the clean branch is the one that chains
            # into `_on_file_settled`, and the call itself can change what
            # `get_modified()` answers.
            chains_into_settle = not self.document.get_modified()
            self._on_modified_changed()
            if chains_into_settle:
                return False
        if settle_deferred:
            self._on_file_settled()
        return False

    def _tab_is_quiet(self):
        """True when the tab is not in the middle of one of xed's own jobs.

        Everything this feature does is founded on two things being settled:
        the buffer's text and the file's bytes. While xed is loading, saving,
        reverting or printing, **neither is** -- the loader replaces the
        buffer in pieces and toggles its modified flag as it goes, and the
        saver has not finished writing the file. Every conclusion drawn from
        that half-state is wrong, and one of them was actively destructive:
        a bar raised mid-revert replaced the `XedProgressInfoBar` xed had put
        in the tab's single info-bar slot, which broke xed's own save/load
        state machine and left the tab wedged in `SAVING_ERROR`, where every
        later save was refused. Confirmed live -- the CRITICAL landed in the
        same log turn as the `set_info_bar` call that caused it.

        The two states allowed are exactly the two in which the bar's own
        button can work: `FileRevert`'s sensitivity in xed is
        `(state == NORMAL || state == EXTERNALLY_MODIFIED_NOTIFICATION) &&
        !document_is_untitled`, and `_xed_tab_revert` asserts the same pair.
        Raising a bar whose Reload… xed would refuse would be worse than
        raising none.

        `EXTERNALLY_MODIFIED_NOTIFICATION` is deliberately allowed even
        though xed's own externally-modified bar sits in the slot there: xed
        raises no progress bar and calls no `info_bar_set_progress` in that
        state, so nothing is broken by replacing it, and xedown's bar carries
        the same warning and offers the same Revert. One consequence is worth
        knowing: xed's own bar is what returns the tab to `NORMAL`, so
        replacing it can leave the tab parked in this state, where
        `_xed_tab_save_async` ignores the modification time -- a later
        external change followed by a save would then not raise xed's "save
        anyway?" confirmation. Pre-existing rather than introduced here, and
        the user has been told about the divergence either way.
        """
        if self.tab is None:
            return False
        state = self.tab.get_state()
        return state in (
            Xed.TabState.STATE_NORMAL,
            Xed.TabState.STATE_EXTERNALLY_MODIFIED_NOTIFICATION,
        )

    def _enforce_visibility(self):
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return False
        if self.frame is not None and self.frame.get_visible():
            self.frame.set_no_show_all(True)
            self.frame.hide()
        if self.preview is not None:
            self.preview.widget.show_all()
        if self.modebar is not None and self.tab is not None:
            self.tab.reorder_child(self.modebar, 0)
        return False

    def _on_window_set_focus(self, _window, widget):
        """A second forced-state hazard, in the same family as save/revert
        forcing the frame visible: pressing Escape while xedown's own
        preview search bar (or xed's own native find bar, over the source
        view) has focus does not reach this controller's own key routing
        at all -- confirmed live, with an independent GTK signal witness
        connected directly to the window, that neither this controller's
        window-level handler nor the search entry's own `stop-search`
        binding ever fires. Whatever inside xed handles Escape for its own
        find bar operates underneath ordinary "key-press-event" dispatch,
        and it hands keyboard focus straight to `self.view` -- including
        while that view sits inside the hidden frame -- by some route that
        does not run the view's own "focus-in-event" either (confirmed live:
        a handler on that signal never fires here, even though
        `window.get_focus()` reports the view immediately afterwards).
        `Gtk.Window.set_focus()` is the one choke point every route to
        changing `window.get_focus()` has to go through -- it is what
        `get_focus()` itself reads back -- so this is the reliable place to
        catch it regardless of which internal path xed took.

        The source view legitimately holding focus is exactly what "Preview
        is showing" means it should never do, so the focus is always
        reclaimed for the preview when this fires. Closing the search bar
        over it is narrower: that only happens when the focus xed just
        stole was one of xedown's own widgets -- anywhere inside the search
        bar, or the preview itself -- which `_reclaim_focus_from_hidden_view`
        decides from `_last_focus` below. Focus arriving from anything else
        (xed's own find bar closing, a dialog dismissing, a mode-bar button)
        is not this tab's Escape to react to, and must leave an open search
        alone.
        """
        previous = self._last_focus
        if widget is not None:
            self._last_focus = widget
        if widget is not self.view:
            return
        GLib.idle_add(self._reclaim_focus_from_hidden_view, previous)

    def _reclaim_focus_from_hidden_view(self, previous_focus):
        """Take the focus back, and close the search if it was ours to close.

        "xedown's own" is the whole search bar, not only its entry: the case
        toggle, the two step buttons and the close button are all places a
        user can tab to and press Escape from, and closing the bar from one
        of them is what `shortcuts.route_key`'s own CLOSE_SEARCH branch does
        (it closes on any non-editable focus while searching). The two rules
        have to agree, because which of them runs is not this plugin's
        choice: on xed 3.8.9 Escape never reaches ordinary key dispatch at
        all, so this focus path is the live one -- a divergence here would
        be a divergence a user could see.
        """
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return False
        stolen_from_ours = previous_focus is not None and (
            (
                self.searchbar is not None
                and self.searchbar.contains_focus(previous_focus)
            )
            or (self.preview is not None and previous_focus is self.preview.widget)
        )
        if self.is_searching and stolen_from_ours:
            self.close_search()
        elif self.preview is not None:
            self.preview.widget.grab_focus()
        return False

    # --- changes made outside xed ------------------------------------------

    def _start_watch(self):
        """Watch this document's file, if there is one and none is watched.

        A document with no path cannot be Markdown (`is_markdown_path(None)`
        is False), so in practice this only declines for a tab being torn
        down -- and for a document that has never been saved, which has
        nothing on disk to watch.
        """
        if self._watch is not None:
            return
        path = self._document_path()
        if not path:
            return
        self._watch = FileWatch(path, self._on_file_settled)
        self._watch.start()

    def _stop_watch(self):
        """Drop the watch and its pending timer. Idempotent."""
        if self._watch is not None:
            self._watch.stop()
            self._watch = None

    def _document_charset(self):
        """The document's own encoding name, or None if xed has not set one."""
        encoding = self.document.get_encoding()
        return encoding.get_charset() if encoding is not None else None

    def _page_language(self):
        """The desktop's language as a BCP-47 tag, or None.

        `GLib.get_language_names()` returns the user's languages most
        specific first, so the first one that parses is the best answer.
        This is the *reader's* language rather than the document's -- xedown
        does not detect what language a document is written in, and guessing
        would be worse than the default voice. Documented as such.
        """
        for name in GLib.get_language_names():
            tag = a11y.lang_tag(name)
            if tag is not None:
                return tag
        return None

    def _on_file_settled(self):
        """The file stopped changing. Decide what that means, once.

        Reached from `FileWatch`, which has already coalesced a save's several
        file events into this one call, and from `_on_modified_changed` when
        the buffer goes clean. Everything that decides is in `diskstate`; this
        method does no comparing of its own.

        `UNCHANGED` usually does nothing beyond the bar dismissal below,
        silently: it is what a save from xed itself looks like, and what a
        `touch` looks like. The exception is a cached disk text, which means
        the file has come back into agreement with the buffer on its own --
        `git checkout --` on the open file, an agent undoing its own edit, a
        rebase landing where it started. That is as reconciling as a save,
        and the cache has to go with it: left in place it would keep the
        preview rendering an intermediate version that is now on neither disk
        nor buffer, with nothing to mark it stale, and the user's next
        keystroke would raise the bar over a file that matches what they
        already had.

        `UNCHANGED` also always dismisses the external-change bar, whether or
        not `_disk_text` was cached. It means disk and buffer agree right
        now, so a bar still claiming they differ can only be lying -- and
        that can happen with no cache to clear: the bar is raised by `WARN`,
        which never touches `_disk_text`, so a later write that reconciles
        the file with the modified buffer reaches here with the cache still
        None while the bar is still standing over a file that no longer
        disagrees with it.

        `UNREADABLE` does nothing in every case. A file mid-write, deleted, or
        moved away has agreed with nothing, and the brief requires all three to
        be handled without an error dialog and without leaving the preview
        stuck -- so the last good render stays. The next settle asks again, and
        the watch has already re-armed on the path by the time this runs, so a
        file that comes back is seen.

        Guarded on `_watch_external` here, and only here, so the one guard
        covers both callers: `FileWatch` cannot reach this while the setting
        is off, since `_start_watch` never runs, but `_on_modified_changed`
        calls this directly on every transition to unmodified regardless of
        the setting. Without this check, typing a character and undoing it
        after an external rewrite would still read the file, cache
        `_disk_text`, and arm a bar on the next keystroke -- with watching
        supposedly off.
        """
        if not self._built or not self._watch_external:
            return
        if not self._tab_is_quiet():
            # Mid-load or mid-save: the buffer and the file are both in
            # flight, so there is no honest answer to be had. Remembered
            # rather than dropped -- `_on_tab_state_changed` asks again the
            # moment the tab settles.
            self._settle_deferred = True
            return
        outcome, text = diskstate.evaluate(
            diskstate.read(self._document_path()),
            self._buffer_text(),
            self.document.get_modified(),
            self._document_charset(),
            self.document.get_implicit_trailing_newline(),
        )
        if outcome == diskstate.WARN:
            self._show_external_change_bar()
            return
        if outcome == diskstate.UNCHANGED:
            self._dismiss_external_bar()
            if self._disk_text is not None:
                self._disk_text = None
                self.state.preview_stale = True
                if self.state.mode is Mode.PREVIEW:
                    self._refresh_body_now()
                else:
                    self._update_refresh_cue()
            return
        if outcome != diskstate.UPDATE:
            return
        self._disk_text = text
        self._dismiss_external_bar()
        self.state.preview_stale = True
        if self.state.mode is Mode.PREVIEW:
            # In place, not a reload: the scroll position survives, which is
            # the whole value of watching a file being rewritten. That path
            # already falls back to a full reload when an error page is
            # showing, so that case needs nothing here.
            #
            # Deliberately not gated on `_auto_refresh`. That setting governs
            # re-rendering after a change to the buffer; a change on disk is
            # not one, and the documented rule for the reload-from-disk family
            # is that it always re-renders while the preview is showing.
            # `watch_external_changes` is this feature's own control.
            self._refresh_body_now()
        else:
            # Nothing is rendered while the source is showing. The staleness
            # set above is what makes the switch back render the new content.
            self._update_refresh_cue()

    def _show_external_change_bar(self):
        """Say the file changed, and offer xed's Revert.

        Re-entrant by design: `_on_file_settled` can reach `WARN` several
        times over a burst of writes, and `_on_modified_changed` can reach it
        for the same divergence from the other direction. Rebuilding an
        identical bar would take the focus out of whatever the user had it in,
        so a bar already saying exactly this is left where it is.

        The guard below is only trustworthy because `_on_info_bar_destroyed`
        keeps `_external_bar`/`_info_bar` pointing at a live widget or at
        None -- never at one already destroyed. See its docstring for the
        xed-side hazard that makes that promise necessary.
        """
        if self._external_bar is not None and self._external_bar is self._info_bar:
            return
        has_revert = self._find_revert_action() is not None
        self._external_bar = self._set_info_bar(
            EXTERNAL_CHANGE_MESSAGE,
            button=RELOAD_LABEL if has_revert else None,
            on_activate=self._reload_from_disk if has_revert else None,
        )

    def _dismiss_external_bar(self):
        """Retire the external-change bar, and only that bar."""
        if self._external_bar is not None and self._external_bar is self._info_bar:
            self._dismiss_info_bar()
        self._external_bar = None

    def _find_revert_action(self):
        """xed's own Revert command, or None on a build without it.

        Walks the window's action groups by name, the same route
        `XedownWindowActivatable` reaches its own actions by. A build where
        this is not found gets the bar without its button, rather than a
        button that does nothing.
        """
        window = self._toplevel()
        if window is None:
            return None
        manager = window.get_ui_manager()
        if manager is None:
            return None
        for group in manager.get_action_groups():
            action = group.get_action(REVERT_ACTION)
            if action is not None:
                return action
        return None

    def _reload_from_disk(self):
        """Hand off to xed's own Revert. xedown never discards the user's text.

        Guarded on this tab being the window's active one, because xed's
        revert command acts on `xed_window_get_active_tab` rather than on any
        tab handed to it -- activating it from a background tab would revert
        somebody else's document. In practice the bar is only clickable in the
        visible tab, so the guard costs nothing and forecloses the one way
        this could go badly wrong.

        Cancelling xed's dialog leaves everything as it was. The bar has
        already retired by the time that dialog opens, and the next settled
        change puts it back if the file still differs.
        """
        window = self._toplevel()
        action = self._find_revert_action()
        if window is None or action is None:
            return
        if window.get_active_tab() is not self.tab:
            return
        action.activate()

    def _on_modified_changed(self, *_args):
        """The buffer gained or lost unsaved edits.

        Both directions matter, and each covers a hole the other leaves.

        **Gaining them** turns an `UPDATE` the user has now overtaken with
        their own edit into a `WARN`. `_render_text` has already gone back to
        showing the buffer in the same turn, and without the bar the user
        would simply watch the preview change under them with no explanation.

        **Losing them** -- a revert, or an undo back to clean -- retires the
        bar and asks the question again from scratch, re-reading the file
        rather than trusting `_disk_text`, which may have moved on since.
        Without it, a user who undid their way back to a clean buffer would be
        left looking at a preview of text that is no longer anywhere.

        Neither direction means anything while xed is loading, saving or
        reverting: the loader sets and clears the modified flag as it
        replaces the buffer, so this signal fires several times during one
        revert with no user anywhere near it. Acting on those transient
        toggles is what raised a bar into the tab's info-bar slot mid-revert
        and wedged xed's own state machine -- see `_tab_is_quiet`.
        """
        if not self._built:
            return
        if not self._tab_is_quiet():
            self._modified_deferred = True
            return
        if self.document.get_modified():
            if self._disk_text is not None:
                if self.state.mode is Mode.PREVIEW:
                    # The bar text says "your unsaved edits are still
                    # showing", but nothing has re-rendered yet in this same
                    # turn: the preview is still displaying `_disk_text`
                    # until the debounce timer fires, and with
                    # `auto_refresh: false` it never would. This corrects a
                    # display already known to be wrong, not a debounced
                    # reaction to a keystroke, so it deliberately skips the
                    # `_auto_refresh` gate `_on_buffer_changed` uses.
                    self._refresh_body_now()
                self._show_external_change_bar()
            return
        self._dismiss_external_bar()
        self._on_file_settled()

    # --- content updates ---------------------------------------------------

    def _on_buffer_changed(self, *_args):
        self._apply_size_guard()
        self.state.preview_stale = True
        self._update_refresh_cue()
        if self.state.mode is not Mode.PREVIEW or not self._live_refresh_allowed():
            # No hidden rendering while the user types in source mode, and
            # nothing at all when the user has asked for manual refresh.
            return
        self._cancel_refresh()
        self._refresh_source_id = GLib.timeout_add(
            self._refresh_delay_ms, self._do_refresh
        )

    def _cancel_refresh(self):
        if self._refresh_source_id:
            GLib.source_remove(self._refresh_source_id)
            self._refresh_source_id = 0

    def _do_refresh(self):
        self._refresh_source_id = 0
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return False
        self._refresh_body_now()
        return False

    def _refresh_body_now(self):
        """Re-render the body in place. Shared by the debounce timer and an
        immediate save-time refresh (see `_on_document_saved`) — neither
        case wants a full page reload."""
        if not self._page_is_document:
            # An error page is showing. Swapping the body would post into a
            # page with no `window.xedown` and do nothing at all -- and the
            # line at the end of this method would then mark the preview
            # fresh, stranding the error page for good. A reload is the only
            # route back to a document.
            self._reload_preview(restore_scroll=self._current_preview_scroll())
            return
        text = self._render_text()
        stats = images.RenderStats()
        try:
            fragment = renderer.render_fragment(
                text,
                base_dir=self._base_dir(),
                image_display=self._image_display,
                fetch_remote=self._fetch_remote(),
                stats=stats,
            )
            # Inside the try with the render: under `auto` this reads the
            # same text, and a failure here must land on the same error page
            # rather than escape as an exception.
            resolved = direction.resolve(self._text_direction, text)
        except Exception as exc:  # noqa: BLE001 - never leave a blank pane
            self._reload_preview(
                error=exc, restore_scroll=self._current_preview_scroll()
            )
            return
        self.preview.update_body(fragment, resolved)
        # After the swap, never before: the counting happens as the body is
        # built, so a render that raised part-way through would leave a
        # partial count describing a page nobody will see. Nothing is needed
        # here for that case -- `render_fragment` only marks the stats
        # rendered on its way out, and the error page the branch above loads
        # brings its own unrendered stats, which withdraws the offer.
        self._note_remote_images(stats)
        self.state.preview_stale = False
        self._update_refresh_cue()

    def _reload_preview(self, error=None, restore_scroll=0.0):
        if self.preview is None:
            return
        # Built even for the error branch below, which never passes it to a
        # renderer: an unrendered stats object is exactly the "no document,
        # no offer" answer the chip needs, and it saves the caller having to
        # tell the two branches apart a second time.
        stats = images.RenderStats()
        if error is not None:
            html = errors.error_page(
                "Cannot render this document",
                errors.render_failure_detail(error),
                dark=self._dark,
                ui_direction=self._ui_direction,
            )
        else:
            html = renderer.render_document(
                self._render_text(),
                base_dir=self._base_dir(),
                dark=self._dark,
                style=self._style,
                image_display=self._image_display,
                code_copy_buttons=self._copy_buttons,
                text_direction=self._text_direction,
                ui_direction=self._ui_direction,
                lang=self._page_language(),
                fetch_remote=self._fetch_remote(),
                stats=stats,
            )
        base_dir = self._base_dir()
        self.preview.load_document(
            html,
            ("file://" + base_dir + "/") if base_dir else None,
            restore_scroll=restore_scroll,
        )
        # Asks the page actually being loaded, not the caller's own belief
        # about which branch produced it: render_document never raises, so
        # `error is None` is true even when it caught something internally
        # and returned an error page of its own.
        self._page_is_document = not errors.is_error_page(html)
        # Unconditional, because `stats.rendered` already carries the same
        # distinction the line above reads out of the HTML: it is False for
        # both error-page routes -- the caller's own, and the one
        # `render_document` takes internally after the body was already
        # counted -- so this withdraws the offer rather than leaving it
        # standing over a page that has no images in it.
        self._note_remote_images(stats)
        self.state.preview_stale = False
        self._update_refresh_cue()
        if not self._page_is_document and self.search.active:
            # The page that could have answered is gone. Bump the token first,
            # so a reply already in flight from that page cannot land after
            # this one and put a count back on a document nobody can see.
            token = self.search.invalidate()
            # Re-arm the page's pending request with the same new token --
            # not preview.search(), which would also ask the page right now.
            # load_html's navigation to the error page is asynchronous, so
            # at this exact point the OLD (still real) page can still be the
            # one actually loaded; asking it would come back with a real
            # answer carrying this same new token, which the session would
            # then accept and use to overwrite the "no matches" answer below.
            # rearm_search only updates the pending-request bookkeeping, so
            # the *next* page's own load is what reissues it, with a token
            # this session still believes.
            self.preview.rearm_search(
                self.search.query, self.search.case_sensitive, token
            )
            self._report_search(0, False, token)

    def _buffer_text(self):
        start, end = self.document.get_bounds()
        return self.document.get_text(start, end, False)

    def _render_text(self):
        """The user's version of this document.

        Their edits if they have any, the file on disk if they do not. With no
        external change the two are the same text, so this rule only has
        visible consequences after one -- and then it says the right thing in
        both directions: an untouched buffer follows the file, and the first
        keystroke takes the preview back to what the user is actually typing.

        `_disk_text` is deliberately *not* cleared by that keystroke. The
        `get_modified()` test below already stops it being rendered, and
        keeping it is what lets `_on_modified_changed` know the file diverged
        when an `UPDATE` turns into a `WARN`.
        """
        if self._disk_text is not None and not self.document.get_modified():
            return self._disk_text
        return self._buffer_text()

    def _on_document_saved(self, *_args):
        """A save does not change the buffer, so it never warrants a full
        page reload — that would re-parse the whole bundle and jump the
        preview back to the top for no reason. It can still be the moment a
        never-built tab first becomes eligible (Save As to a .md name), and
        it can still leave a change unrendered if the debounce window was
        still pending, so cover both without reloading the page itself."""
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        # A save reconciles the two: whatever the user has is now what is on
        # disk. The monitor will fire for xedown's own write, and `diskstate`
        # will answer UNCHANGED for it -- which is why no ignore-flag is
        # needed anywhere in this feature.
        self._disk_text = None
        self._dismiss_external_bar()
        path = self._document_path()
        if path != self._remembered_path:
            # A Save As. Follow the file rather than leaving an entry keyed
            # to a path it no longer has.
            if self._remembered_path and settings.get_settings().get(
                settings.REMEMBER_MODE_PER_FILE
            ):
                modestore.get_store().rename(self._remembered_path, path)
            self._remembered_path = path
            if self._watch is not None:
                self._watch.repoint(path)
        if self.state.preview_stale and self.state.mode is Mode.PREVIEW:
            self._refresh_body_now()

    def _on_document_loaded(self, *_args):
        """Fires after xed reverts or reloads — including after an external
        change — all of which genuinely replace the buffer contents, so
        (unlike a save) this always warrants a full reload when visible.

        Also fires for the tab's own *initial* file load, and that firing
        can land in either branch below: xed's file read is asynchronous,
        and nothing orders it against `activate()`'s own
        `GLib.idle_add(self._build_if_markdown)`. If the load wins, this
        runs first and hits `not self._built`, which just re-queues the
        build -- by the time it runs, the buffer already holds the real
        text, so `_build_if_markdown`'s own deferral decision is correct
        unaided, and `_awaiting_initial_content` comes out False. If the
        *build* wins instead, `_build_if_markdown` reads an empty buffer,
        `perflimits.classify(0)` comes back unconstrained, and a document
        large enough to defer opens straight into an unrequested Preview
        render of nothing -- and this is that same load landing
        afterwards, on an already-built tab, carrying the content that
        decision should have seen.

        `_awaiting_initial_content` (set by `_build_if_markdown`, consumed
        below) is deliberately not "was this the first `loaded` event
        this tab has seen" -- a document built via New -> Save As never
        gets a `loaded` event of its own at all, so *its* first one is a
        genuine later revert, and answering that question wrongly used to
        switch a reader out of a Preview they were actively reading. "Did
        the build measure an empty buffer" is the question that survives
        that lifecycle: such a document has content by the time
        `_on_document_saved` gets it built, so the flag comes out False
        and every `loaded` after that is treated as the plain revert it
        is.
        """
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        self._disk_text = None
        self._dismiss_external_bar()
        # No watch repoint here, unlike `_on_document_saved` just above:
        # `loaded` fires for a revert or reload, both of which reuse the
        # tab's existing path -- there is no Save-As-style path change for
        # the watch to follow.
        self.state.preview_stale = True
        # Consumed here, win or lose: only the one `loaded` immediately
        # following an empty-buffer build is ever a candidate for this --
        # a later revert of a document that has since grown real content
        # (typed, or reverted once already) must fall through to the
        # ordinary reload below, exactly as it did before this guard
        # existed.
        awaiting_initial_content = self._awaiting_initial_content
        self._awaiting_initial_content = False
        if (
            awaiting_initial_content
            and self.state.mode is Mode.PREVIEW
            and perflimits.classify(self._document_char_count()).defer_initial
        ):
            # The race described above, resolved the same way
            # `_build_if_markdown` would have resolved it outright: this
            # tab has shown nothing but an empty page so far, so there is
            # no real preview to pull the reader out of, only the one
            # `_build_if_markdown` would have deferred to begin with.
            # `initial=True` matches that build-time call for the same
            # reasons it uses it -- no stolen focus, no scroll restore, and
            # no write to the remembered mode for a choice the reader
            # never made.
            self._preview_deferred = True
            self._deferred_size_label = perflimits.describe_bytes(
                len(self._render_text().encode("utf-8"))
            )
            self._apply_size_guard()
            self.set_mode(Mode.SOURCE, initial=True)
            return
        self._apply_size_guard()
        if self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())

    def _on_appearance_changed(self, dark):
        self._dark = dark
        self.state.preview_stale = True
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())

    def _on_settings_changed(self, changed):
        """Apply a settings change to this tab, immediately.

        The store is a long-lived global holding a strong reference to every
        listener, so a missed disconnect keeps this controller — and the
        WebView, document and tab it references — alive for the life of the
        process. `deactivate()` owns that; nothing here may introduce state
        that outlives it.

        `CUSTOM_STYLESHEET` is deliberately absent. Both routes to a
        different user stylesheet — the setting moving, or the file changing —
        arrive through `stylewatcher` instead, so this handler never handles
        that key itself. And because both this handler and
        `_on_user_stylesheet_changed` rebuild `self._style` from the store
        rather than patching a single field, neither depends on arriving
        before the other: whichever runs second still rebuilds from current
        settings, so a single broadcast that moves several keys at once
        cannot leave a reload carrying stale metrics.

        A theme change needs the whole page again, because the stylesheet is
        inlined in <head> and `update_body` only swaps the article. Width and
        text size do not: they are two custom properties the loaded page
        already reads, so they are poked in place.

        `IMAGE_FALLBACK` and `CODE_COPY_BUTTONS` are handled here rather than
        through a reload: the first changes only the body, the second only
        the page's own config. Both are re-read before the theme branch, so
        a broadcast that moves several keys at once cannot leave a reload
        carrying the outgoing values.

        `TEXT_DIRECTION` joins them for the same reason: it is one attribute
        on the article, and no stylesheet changed, so there is nothing in
        <head> to rebuild. It costs one re-render of the Markdown, which is
        the right price for a setting nobody changes twice a day and reuses
        machinery that is already correct about mode and staleness.

        `REMOTE_IMAGES` — the other half of the pair of names `IMAGE_FALLBACK`
        was split from — behaves the opposite way to all three: it is the
        *fetch policy*, and a permitted page names the private image scheme
        in its own Content-Security-Policy, which is a <meta> in <head>.
        Only a whole new page can carry a new one, so it rides with the
        theme in the reload branch rather than with the body-only three.

        `AUTO_REFRESH` and `REFRESH_DELAY_MS` are cached rather than read at
        use time so the debounce path stays a timer schedule and nothing
        more. The delay is read when a change is scheduled, which is what
        makes a new value reach a tab that is already open; a timer already
        in flight keeps the delay it was scheduled with, and the observable
        difference is one render. Switching auto-refresh back on over a
        stale preview is itself a body render, so it shares the same
        multi-key-broadcast hazard as the theme reload above: a broadcast
        that also moves `REMOTE_IMAGES` or `TEXT_DIRECTION` must not render
        the body a second time for values the first render already carried.
        """
        if self._style is None:
            return
        store = settings.get_settings()
        # Rebuilt rather than mutated, so the numbers are re-coerced through
        # the same path a fresh tab uses.
        self._style = stylesheets.PreviewStyle.from_settings(
            store, user=self._style.user
        )
        previous_display = self._image_display
        previous_direction = self._text_direction
        self._image_display = images.coerce_display(store.get(settings.IMAGE_FALLBACK))
        self._copy_buttons = bool(store.get(settings.CODE_COPY_BUTTONS))
        was_auto = self._auto_refresh
        self._auto_refresh = bool(store.get(settings.AUTO_REFRESH))
        self._refresh_delay_ms = int(store.get(settings.REFRESH_DELAY_MS))
        self._text_direction = store.get(settings.TEXT_DIRECTION)
        was_watching = self._watch_external
        self._watch_external = bool(store.get(settings.WATCH_EXTERNAL_CHANGES))
        if self._watch_external and not was_watching:
            self._start_watch()
        elif was_watching and not self._watch_external:
            # Off means off: no monitor, no timer, no bar, no cached text.
            # What is already rendered stays rendered -- walking the preview
            # back to older buffer text, as the visible effect of turning a
            # watch *off*, would be the opposite of what was asked for.
            self._stop_watch()
            self._dismiss_external_bar()
            self._disk_text = None

        reloaded = False
        # Two independent branches below can each want a body render out of
        # one broadcast (the auto-refresh catch-up here, and the
        # image-display/direction branch further down) -- this flag is how
        # the second one knows the first already happened, so one broadcast
        # never renders the body twice.
        refreshed = False
        # `REMOTE_IMAGES` rides with the theme: both live in <head> (the
        # stylesheet and the CSP), and both are therefore a whole page or
        # nothing. Sharing the branch also means one broadcast that moves
        # both still reloads exactly once.
        if settings.PREVIEW_THEME in changed or settings.REMOTE_IMAGES in changed:
            self.state.preview_stale = True
            if self._built and self.state.mode is Mode.PREVIEW:
                self._reload_preview(restore_scroll=self._current_preview_scroll())
                reloaded = True

        metrics_moved = (
            settings.CONTENT_WIDTH_REM in changed or settings.TEXT_SIZE_PX in changed
        )
        # Skipped after a reload, which already carries the new values in its
        # own stylesheet -- and would otherwise run against the outgoing page,
        # since load_html is asynchronous.
        if metrics_moved and not reloaded and self.preview is not None:
            self.preview.set_metrics(
                self._style.content_width_rem, self._style.text_size_px
            )

        if not self._live_refresh_allowed():
            # A timer already in flight would render after the user asked for
            # manual refresh only.
            self._cancel_refresh()
        elif (
            not was_auto
            and not reloaded
            and self.state.preview_stale
            and self._built
            and self.state.mode is Mode.PREVIEW
        ):
            # Switched back on over a stale preview: catch up now rather than
            # wait for a change that may never come.
            self._refresh_body_now()
            refreshed = True

        if settings.REMEMBER_MODE_PER_FILE in changed and store.get(
            settings.REMEMBER_MODE_PER_FILE
        ):
            # Switched on: make it true of the tabs already open, not only of
            # ones opened later.
            self._remember_mode(self.state.mode)
        self._update_refresh_cue()

        if reloaded:
            # The reload already carried both values in its own config block
            # and re-rendered the body with them. Poking the outgoing page
            # would land on nothing: load_html is asynchronous.
            return

        if (
            settings.CODE_COPY_BUTTONS in changed or settings.IMAGE_FALLBACK in changed
        ) and self.preview is not None:
            self.preview.set_config(self._copy_buttons, self._image_display)

        # The two settings that change the emitted body, and only the body:
        # the CSS for every image mode is already in the loaded page, and the
        # direction is one attribute on the article. Neither needs a reload.
        # Skipped when the catch-up branch above already rendered: both
        # values were re-read before it ran, so it already carries them, and
        # a render here would only repeat that one for nothing.
        if (
            self._image_display != previous_display
            or self._text_direction != previous_direction
        ) and not refreshed:
            if self._built and self.state.mode is Mode.PREVIEW:
                self._refresh_body_now()
            else:
                self.state.preview_stale = True

    def _on_user_stylesheet_changed(self, user):
        """The user's stylesheet moved, or its file changed.

        A full reload, for the same reason a theme change is one: the
        stylesheet is inlined in <head>, and `update_body` only swaps the
        article.
        """
        if self._style is None:
            return
        # Rebuilt rather than patched, so a reload this triggers carries
        # current metrics even when this delivery races a settings broadcast
        # that also moved CONTENT_WIDTH_REM or TEXT_SIZE_PX (see
        # _on_settings_changed's docstring).
        self._style = stylesheets.PreviewStyle.from_settings(
            settings.get_settings(), user=user
        )
        self.state.preview_stale = True
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())

    def _on_mode_selected(self, _bar, mode_value):
        self.set_mode(Mode(mode_value))

    # --- link and image handling -------------------------------------------

    def _fetch_remote(self):
        """Whether this tab may fetch remote images right now.

        The global setting or this tab's own grant, in that order. Read from
        the store at render time rather than cached in a field like
        `_image_display`: it is asked once per render, not once per image,
        and a value that cannot be stale is one less thing for
        `_on_settings_changed` to keep in step.
        """
        return (
            settings.get_settings().get(settings.REMOTE_IMAGES) == "https"
            or self._remote_unblocked
        )

    def _note_remote_images(self, stats):
        """Offer to load what this render refused to fetch, or withdraw the
        offer.

        `stats.rendered` is the renderer's own witness that the HTML being
        shown is the document. It matters because the counts alone are not
        enough: a full-page render builds the body first and can still fail
        afterwards, so an error page arrives carrying a real count from a
        document nobody is looking at. Withdrawing the offer in that case is
        the point -- a "3 remote images [Load]" chip over a page with no
        images in it offers something that is not there.
        """
        if self.modebar is not None:
            self.modebar.set_remote_images(
                stats.blocked_remote if stats.rendered else 0
            )

    def _on_load_images_requested(self, _bar):
        """The reader has chosen to load this document's remote images.

        A full page reload rather than a body swap, because the permission
        is carried by the page's own Content-Security-Policy, which is a
        <meta> in <head>: a body full of `xedown-image:` sources swapped
        into a page that was loaded while blocked would be refused by that
        page's own policy, image by image. Outside Preview there is nothing
        loaded to reload -- the staleness below is what makes the switch
        back render with the new permission.
        """
        # A debounce timer armed a moment before the click would otherwise
        # fire into the page that is about to be replaced, swapping in a body
        # full of `xedown-image:` sources that the *old* page's CSP refuses
        # -- so the reader sees a raw private-scheme URL flash up in a
        # placeholder immediately after pressing Load. The reload below
        # renders the same text anyway; there is nothing to lose by dropping
        # the pending refresh.
        self._cancel_refresh()
        self._remote_unblocked = True
        # The offer has been accepted, so it stops being made now rather
        # than at the next render: with the permission granted there are no
        # blocked images left to count, and in Markdown mode no render is
        # coming until the reader switches back.
        if self.modebar is not None:
            self.modebar.set_remote_images(0)
        # A URL this document names may already be marked failed -- from
        # another tab, or from this one while it was offline. Pressing Load
        # is exactly the "try again" the cache's failure half is dropped
        # for; successes are kept.
        imagescheme.get_fetcher().invalidate_failures()
        self.state.preview_stale = True
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())
        else:
            self._update_refresh_cue()

    def _on_build_preview_requested(self, _bar):
        """The reader asked for the deferred preview. Give it to them.

        No special-casing of the flag here: `set_mode` is the funnel every
        route into Preview goes through (this button, the mode bar's own
        Preview segment, Ctrl+Shift+M), and clearing `_preview_deferred` --
        which is what hides the chip -- is its job, not this handler's. The
        size guard on *live refresh* is untouched -- a document big enough
        to defer is big enough to keep off the keystroke path, and
        `_live_refresh_allowed` still says so.
        """
        self.set_mode(Mode.PREVIEW)

    def _on_image_error(self, source):
        """The page says an image did not load. Say why, when xedown knows.

        For a local image there is nothing to add: the reason was decided at
        render time and the placeholder already carries it. A
        `xedown-image:` source is the case this exists for -- the page
        cannot know why a fetch failed, and "could not be loaded" is not an
        answer anyone can act on.

        The fetcher's own cache is asked rather than any record of this
        controller's: it already holds every failure, bounded by
        `CACHE_BYTES`, and it is the same answer whichever tab asks.

        This is the route that lands. `_on_remote_image_failed` below hears
        about the same failure earlier, but the page only builds the
        placeholder these messages are written into when the image's `error`
        event fires -- which is after the scheme request has been failed, so
        the earlier message usually has nothing to match yet. Here the
        placeholder certainly exists: the page posted this while creating
        it.
        """
        if self.preview is None:
            return
        url = remoteimages.parse_scheme_uri(source)
        if url is None:
            return
        result = imagescheme.get_fetcher().cached(url)
        if result is None or result.ok:
            # Still in flight, evicted, or a fetch that succeeded and then
            # would not decode. Nothing honest to say beyond what the page
            # already says for itself.
            return
        self.preview.set_image_message(
            source,
            errors.remote_image_failure_text(result.error, result.detail),
        )

    def _on_remote_image_failed(self, view, url, result):
        """Tell this tab's page why one of its images did not arrive.

        Routed by the WebView the request came from, so a failure lands in
        the tab that asked for it and nowhere else; a destroyed view reports
        None, which is the whole check needed. Both parts are an
        optimisation rather than a guard -- `imagescheme` records that
        finishing a destroyed view's request is safe, and this listener is
        dropped in `deactivate()`, so a torn-down controller is never
        reached at all.

        Writes the same sentence `_on_image_error` does, and the two are
        idempotent in either order: this one lands when the placeholder is
        already in the page, that one covers the ordinary case where it is
        not there yet.
        """
        if view is None or self.preview is None or view is not self.preview.widget:
            return
        self.preview.set_image_message(
            remoteimages.scheme_uri(url),
            errors.remote_image_failure_text(result.error, result.detail),
        )

    def _on_link_activated(self, uri):
        decision = classify_link(uri, self._base_dir())
        if decision.action is LinkAction.IN_PAGE_ANCHOR:
            self.preview.scroll_to_anchor(decision.target)
        elif decision.action is LinkAction.EXTERNAL_BROWSER:
            self._open_with_desktop(decision.target)
        elif decision.action is LinkAction.OPEN_IN_XED:
            self._open_in_xed(decision.target)
        elif decision.action is LinkAction.DESKTOP_HANDLER:
            self._open_with_desktop(decision.target)
        elif decision.action is LinkAction.CONFIRM_THEN_DESKTOP:
            if self._confirm(decision.reason):
                self._open_with_desktop(decision.target)
        else:
            self._show_error(decision.reason)

    def _open_with_desktop(self, uri):
        try:
            Gtk.show_uri_on_window(self._toplevel(), uri, Gtk.get_current_event_time())
        except GLib.Error as exc:
            self._show_error(f"Cannot open {uri}: {exc.message}")

    def _open_in_xed(self, uri):
        from gi.repository import Gio

        window = self._toplevel()
        if window is None:
            return
        try:
            window.create_tab_from_location(
                Gio.File.new_for_uri(uri), None, 0, False, True
            )
        except Exception as exc:  # noqa: BLE001 - never leave a click unanswered
            self._show_error(f"Cannot open {uri}: {exc}")

    def _toplevel(self):
        window = self.view.get_toplevel()
        return window if isinstance(window, Xed.Window) else None

    def _confirm(self, reason):
        dialog = Gtk.MessageDialog(
            transient_for=self._toplevel(),
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Open this file?",
        )
        dialog.format_secondary_text(reason)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.OK

    def _set_info_bar(self, message, button=None, on_activate=None):
        """Put one of xedown's own info bars in the tab's single slot.

        Two of xedown's own bars never coexist -- there is one slot, and
        `Xed.Tab.set_info_bar` is how it is filled -- so the newer replaces
        the older. xed fills the same slot with bars of its own, and whichever
        was set last is the one on screen; there is nothing to reconcile,
        because in the one case where both can appear they offer the same
        thing by the same route.

        Returns the bar, so a caller that needs to recognise its own later can
        keep hold of it. Returns None when there is no tab to put it in.
        """
        if self.tab is None:
            return None
        if not self._tab_is_quiet():
            # The slot is xed's while it is working: during a load or a save
            # it holds a `XedProgressInfoBar` that xed goes on calling
            # `info_bar_set_progress` against, and `Xed.Tab.set_info_bar`
            # destroys whatever is already there. Taking the slot mid-job
            # broke xed's state machine outright -- see `_tab_is_quiet`. The
            # callers above are the last line of defence; this is the choke
            # point that makes it true of every caller, including
            # `_show_error`.
            return None
        self._dismiss_info_bar()
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        bar.get_content_area().add(Gtk.Label(label=message))
        if button is not None:
            bar.add_button(button, Gtk.ResponseType.APPLY)
        # `add_button` hands back the button it just made. `Gtk.InfoBar` has
        # no `get_widget_for_response` -- that is a `Gtk.Dialog` method, and
        # calling it here raised `AttributeError` on every info bar the
        # plugin showed, including the one a refused link produces.
        close_button = bar.add_button("Close", Gtk.ResponseType.CLOSE)
        close_accessible = close_button.get_accessible()
        if close_accessible is not None:
            close_accessible.set_name(a11y.NAMES["info_bar_close"])
        self._connect(bar, "response", self._on_info_bar_response)
        # See `_on_info_bar_destroyed`: `Xed.Tab.set_info_bar` destroys
        # whatever bar already occupies the slot, including from xed's own
        # code, and that destroy emits no "response" signal.
        self._connect(bar, "destroy", self._on_info_bar_destroyed)
        self._info_bar = bar
        self._info_bar_action = on_activate
        self.tab.set_info_bar(bar)
        bar.show_all()
        if self.modebar is not None:
            self.tab.reorder_child(self.modebar, 0)
        return bar

    def _show_error(self, message):
        self._set_info_bar(message)

    def _on_info_bar_response(self, bar, response):
        # `Xed.Tab.set_info_bar` does not accept None (its `info_bar`
        # argument is marshaled as non-nullable), so the bar is retired by
        # destroying it directly rather than trying to clear the tab's
        # info-bar slot.
        action = self._info_bar_action if self._info_bar is bar else None
        if self._info_bar is bar:
            self._info_bar = None
            self._info_bar_action = None
        if self._external_bar is bar:
            self._external_bar = None
        self._untrack(bar)
        bar.destroy()
        # After the bar is gone, not before: an action can open a modal
        # dialog, and it can reload the document out from under this
        # controller. Neither should find a half-retired bar behind it.
        if action is not None and response == Gtk.ResponseType.APPLY:
            action()

    def _dismiss_info_bar(self):
        """Remove the info bar this controller created, if any is showing.

        Never touches an info bar this controller did not create.
        """
        if self._info_bar is not None:
            bar, self._info_bar = self._info_bar, None
            self._info_bar_action = None
            if self._external_bar is bar:
                self._external_bar = None
            self._untrack(bar)
            bar.destroy()

    def _on_info_bar_destroyed(self, bar):
        """Drop every field naming `bar`, however it came to be destroyed.

        `Xed.Tab.set_info_bar` destroys whatever bar already occupies the
        tab's one slot before storing a new one -- disassembly of
        `xed_tab_set_info_bar` shows a plain `gtk_widget_destroy` on the old
        bar, with no "response" signal involved. xed takes that route for
        bars of its *own* -- its "file changed on disk" bar appears the
        moment the source view takes keyboard focus (see the "source buffer
        keeps its old text" entry in docs/known-issues.md), which is exactly
        when a user switches to Markdown mode to look at xedown's bar -- and
        that silently destroys xedown's bar out from under it without ever
        running `_on_info_bar_response`. Left unhandled,
        `_info_bar` and `_external_bar` would go on pointing at a destroyed
        widget forever, and `_show_external_change_bar`'s idempotence guard
        (`self._external_bar is self._info_bar`) would keep comparing two
        equal dangling pointers and read "already showing" for the rest of
        the tab's life -- wedging every later warning off for good.

        Harmlessly re-entrant: `_on_info_bar_response` and `_dismiss_info_bar`
        both null these same fields out *before* calling `bar.destroy()`
        themselves, precisely so that this handler firing as part of that
        same call finds nothing left of `bar` to clear. It only ever has
        work to do when the destroy came from somewhere else. It only clears
        fields that already name `bar` -- it never assigns into them -- so it
        cannot resurrect a bar a newer one has already replaced.
        """
        if self._info_bar is bar:
            self._info_bar = None
            self._info_bar_action = None
        if self._external_bar is bar:
            self._external_bar = None
        self._untrack(bar)
