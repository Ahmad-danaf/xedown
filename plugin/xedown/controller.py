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

# So the last controller out can release the image-fetch thread pool
# `imagescheme` holds on everyone's behalf; nothing else in the plugin is
# positioned to stop workers still dialling hosts for tabs that are gone.
# Weak, so a controller that escapes teardown leaves the set anyway rather
# than leaking for the life of xed. A count, never a source of truth about
# which controller a view has.
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
        # Computed once when `_preview_deferred` is set, never re-measured:
        # `_apply_size_guard` runs on every keystroke. A label that goes stale
        # after a huge paste is accepted -- it is a hint offered once, not a
        # live readout.
        self._deferred_size_label = None
        # Whether Preview has ever shown this reader real content, which
        # `_on_document_loaded` must know before switching anyone out of
        # Preview. Set once by `_note_preview_shown` from the text actually
        # rendered. Three earlier attempts inferred it instead -- from event
        # order, from the buffer's state at one instant, from the buffer's
        # length -- and each missed a lifecycle the others caught. Ask
        # directly; do not infer.
        self._preview_has_shown_content = False
        self._refresh_delay_ms = 250
        self._text_direction = direction.AUTO
        self._ui_direction = direction.LTR
        self._stylesheet_token = None
        self._info_bar = None
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

        # Last one out, and only after the WebView above is destroyed:
        # `imagescheme.shutdown()` cancels queued fetches without answering
        # their callbacks, which is harmless only once their page is gone.
        # The emptiness test keeps a closing tab from tearing the pool out
        # from under a tab in another window.
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

        Tracked here rather than through `_connect` because the connection
        has to MOVE with the tab: a tab dragged into another window keeps
        this controller, and a connection left on the window it came from
        would silently stop Escape closing that tab's search bar. Called
        again from `hierarchy-changed`, it is idempotent, and `_toplevel()`
        answers None mid-move, which detaches until the re-parent arrives.
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

        Defensive about a disposed window, because this also runs during
        teardown, where disconnecting raises rather than returning quietly.
        `_last_focus` goes with it: the watch is per-tab on a window-wide
        signal, so what it holds is routinely another tab's view -- and that
        is that tab's buffer held too.
        """
        if self._focus_window is not None and self._focus_handler_id is not None:
            try:
                self._focus_window.disconnect(self._focus_handler_id)
            except (TypeError, RuntimeError):
                pass
        self._focus_window = None
        self._focus_handler_id = None
        self._last_focus = None

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
        # Read once: a desktop's text direction is fixed at login, and
        # nothing in xed signals a change to it.
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

        # Before the WebView exists: the handler lives on the default web
        # context, and a page can ask for a `xedown-image:` URL the moment it
        # loads. `register_once` is idempotent for the life of the process.
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

        # "hierarchy-changed" is what re-points the focus watch after a tab
        # is moved between windows; see `_attach_focus_watch`.
        self._connect(self.tab, "hierarchy-changed", self._attach_focus_watch)
        self._attach_focus_watch()

        self._built = True
        self._remembered_path = self._document_path()
        # After `_built`, because `_on_file_settled` refuses to act before it.
        if self._watch_external:
            self._start_watch()
        initial = self._initial_mode()
        char_count = self._document_char_count()
        # A document large enough that building its preview costs about a
        # second opens in Markdown mode instead, with the chip offering the
        # preview. The reader then pays that second knowingly. Only the
        # *initial* build is deferred: choosing Preview from the mode bar
        # afterwards is a request, and requests are honoured at any size.
        if initial is Mode.PREVIEW and perflimits.classify(char_count).defer_initial:
            self._preview_deferred = True
            self._deferred_size_label = perflimits.describe_bytes(
                len(self._render_text().encode("utf-8"))
            )
            initial = Mode.SOURCE
        self._apply_size_guard()
        self.set_mode(initial, initial=True)
        return False

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

        `initial` suppresses three things that would each be a regression on
        a file opening in Markdown mode: restoring the source scroll (which
        would apply fraction 0.0 over the position xed just restored),
        grabbing focus (xed opens several tabs at once, and grabbing focus in
        a non-current notebook page moves the window's focus off the tab the
        user is looking at), and writing to the mode store (opening a file
        must not rewrite the memory it was just read from).

        `has_focus_inside()` is read ahead of every state change that could
        move focus, because it is only meaningful *before* the switch: focus
        on a mode button is what makes Orca announce the toggle's own state
        change, and this must not speak a second time on top of it.

        The one place `_preview_deferred` is cleared, because every route
        into Preview converges here.
        """
        if not self._built:
            return
        if mode is self.state.mode and not initial:
            return
        if mode is Mode.PREVIEW and self._preview_deferred:
            self._preview_deferred = False
            # Cleared with the flag it belongs to rather than relying on
            # deferral being once-only per tab, which is an invariant two
            # files away from here.
            self._deferred_size_label = None
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
                # So the selection the user makes is the one copy acts on;
                # also stops Page_Down scrolling the hidden text view.
                self.preview.widget.grab_focus()
        else:
            # Before the widgets swap, not after: the marks come out of a page
            # that is still the visible one, and a bar left open would hang
            # over an editor it does not control.
            self.close_search(focus_preview=False)
            # Without this, a bare show_all() in source mode would re-reveal
            # the WebView (packed expand=True) beside the source editor.
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

        The text comes from `a11y.NAMES`, never a literal: `test_a11y.py`'s
        `test_every_accessible_name_in_the_host_modules_comes_from_names`
        exists specifically to catch an inlined string here.
        """
        key = a11y.mode_announcement_name(mode)
        if key is not None and self.modebar is not None:
            self.modebar.announce(a11y.NAMES[key])

    def refresh_now(self):
        """Re-render the preview from the document as it is now.

        Nothing to do in Markdown mode: the preview is already stale and
        switching to it renders. Rendering into a hidden WebView would be
        exactly the eager, unseen work turning `auto_refresh` off avoids.
        """
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return
        # Refresh means "try again", including images that did not arrive:
        # the fetcher caches failures so a 250ms re-render does not re-dial a
        # dead host, and this is one of the moments a reader says to forget
        # them. Asked only of a fetching tab, so a blocked one does not build
        # a thread pool just to be told nothing can change.
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

        `get_char_count` is O(1) where `_render_text()` copies the whole
        buffer, and this runs on every keystroke: fetching a megabyte per
        keypress to decide whether a megabyte is too big would be its own
        performance bug, inside the guard meant to prevent one. Answers 0
        during teardown, which `perflimits.classify` treats as unconstrained.
        """
        try:
            return int(self.document.get_char_count())
        except Exception:  # noqa: BLE001 - a guard must not raise into a render
            return 0

    def _apply_size_guard(self):
        """Ask `perflimits` about the document as it stands, and show the chip.

        Runs on every buffer change too, because a document can cross the
        live-refresh threshold by being typed into: the guard is about the
        text right now, not the file that was opened. Only
        `decision.live_refresh` is acted on here; `defer_initial` matters
        only where a mode is still being chosen.

        This is the per-keystroke path, so it must never touch the buffer:
        the chip's label is read from `_deferred_size_label`, never
        recomputed.
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
        ordinary documents, not a request to freeze the editor on a large
        one. Derived and per-tab, so nothing is written to the settings
        store and the next small document refreshes as configured.
        """
        return self._auto_refresh and self._size_allows_live_refresh

    def _note_preview_shown(self, text):
        """Record that Preview has now shown the reader real content.

        `text` is the text the caller just rendered, handed in rather than
        re-derived, and that is the whole point of the argument: the buffer
        is not that text. `_render_text` returns `_disk_text` whenever the
        buffer is clean and the file has moved on, so a reader can be looking
        at 300k characters that `get_char_count` truthfully reports as zero.
        Asking the buffer here left the flag False over exactly that preview,
        and the reader's next Reload then read as "never showed anything" and
        switched them out of Preview.

        An empty string sets nothing: a blank page is not a preview.
        """
        if text and self.state.mode is Mode.PREVIEW:
            self._preview_has_shown_content = True

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

        While xed is loading, saving, reverting or printing, neither the
        buffer's text nor the file's bytes are settled, and conclusions drawn
        from that half-state are wrong. One was destructive: a bar raised
        mid-revert replaced the `XedProgressInfoBar` in the tab's single
        info-bar slot, breaking xed's save/load state machine and wedging the
        tab in `SAVING_ERROR`, where every later save was refused.

        The two states allowed are exactly the two in which the bar's own
        Reload… can work -- `FileRevert`'s sensitivity in xed is
        `(NORMAL || EXTERNALLY_MODIFIED_NOTIFICATION) && !untitled`.

        Allowing `EXTERNALLY_MODIFIED_NOTIFICATION` replaces xed's own bar,
        which is safe (no progress bar lives there) but can park the tab in
        that state, where `_xed_tab_save_async` ignores the modification time
        and a later save skips xed's "save anyway?" confirmation.
        Pre-existing, and documented for the user either way.
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
        """Catch xed handing focus to the hidden source view.

        On xed 3.8.9, Escape in a find bar never reaches ordinary
        "key-press-event" dispatch and hands focus straight to `self.view`
        without running its "focus-in-event" either -- both confirmed live.
        `Gtk.Window.set_focus()` is the one choke point every route to
        changing `window.get_focus()` must pass through, so it is the only
        reliable place to catch this whatever path xed took.

        Focus is always reclaimed for the preview. Closing the search bar is
        narrower and happens only when what xed stole focus from was one of
        xedown's own widgets: focus arriving from xed's own find bar or a
        dialog is not this tab's Escape to react to.
        """
        previous = self._last_focus
        if widget is not None:
            self._last_focus = widget
        if widget is not self.view:
            return
        GLib.idle_add(self._reclaim_focus_from_hidden_view, previous)

    def _reclaim_focus_from_hidden_view(self, previous_focus):
        """Take the focus back, and close the search if it was ours to close.

        "xedown's own" is the whole search bar, not only its entry: every
        control in it is somewhere a user can press Escape from. This rule
        must agree with `shortcuts.route_key`'s CLOSE_SEARCH branch, because
        which of the two runs is not this plugin's choice -- and on xed
        3.8.9 it is this focus path that runs.
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

    def _start_watch(self):
        """Watch this document's file, if there is one and none is watched.

        Declines for a document that has never been saved, which has nothing
        on disk to watch.
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

        `GLib.get_language_names()` is most-specific first, so the first tag
        that parses is the best answer. This is the *reader's* language, not
        the document's: xedown does not detect what a document is written in,
        and guessing would be worse than the default voice.
        """
        for name in GLib.get_language_names():
            tag = a11y.lang_tag(name)
            if tag is not None:
                return tag
        return None

    def _on_file_settled(self):
        """The file stopped changing. Decide what that means, once.

        All the deciding is in `diskstate`; this method compares nothing.

        `UNCHANGED` clears any cached `_disk_text`, because the file has come
        back into agreement with the buffer on its own (`git checkout --`, an
        agent undoing its edit). Left in place the cache would keep rendering
        an intermediate version now on neither disk nor buffer. It also always
        dismisses the external-change bar, cache or not: `WARN` raises that
        bar without touching `_disk_text`, so a reconciling write can arrive
        with the cache None and the bar still standing.

        `UNREADABLE` does nothing at all -- a file mid-write, deleted or moved
        has agreed with nothing, so the last good render stays and the next
        settle asks again.

        Guarded on `_watch_external` here so the one guard covers both
        callers: `_on_modified_changed` calls in on every transition to
        unmodified regardless of the setting, so without this, typing a
        character and undoing it would arm a bar with watching switched off.
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
            # In place, not a reload, so the scroll position survives -- the
            # whole value of watching a file being rewritten. Deliberately not
            # gated on `_auto_refresh`: that setting governs re-rendering
            # after a *buffer* change, and `watch_external_changes` is this
            # feature's own control.
            self._refresh_body_now()
        else:
            # Nothing is rendered while the source is showing. The staleness
            # set above is what makes the switch back render the new content.
            self._update_refresh_cue()

    def _show_external_change_bar(self):
        """Say the file changed, and offer xed's Revert.

        Re-entrant by design: a burst of writes reaches `WARN` repeatedly,
        and rebuilding an identical bar would take focus out of whatever the
        user had it in. The guard is only trustworthy because
        `_on_info_bar_destroyed` keeps these pointing at a live widget or
        None, never at a destroyed one.
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

        Guarded on this tab being the window's active one: xed's revert acts
        on `xed_window_get_active_tab`, not on any tab handed to it, so
        activating it from a background tab would revert somebody else's
        document.
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

        **Gaining** edits turns an `UPDATE` the user has overtaken into a
        `WARN`, so the preview does not change under them unexplained.

        **Losing** them re-reads the file rather than trusting `_disk_text`,
        which may have moved on; otherwise undoing back to a clean buffer
        leaves a preview of text that is no longer anywhere.

        Neither means anything mid-load or mid-save: the loader toggles the
        modified flag as it replaces the buffer, so this fires several times
        during one revert with no user near it. Acting on those transient
        toggles is what wedged xed's state machine -- see `_tab_is_quiet`.
        """
        if not self._built:
            return
        if not self._tab_is_quiet():
            self._modified_deferred = True
            return
        if self.document.get_modified():
            if self._disk_text is not None:
                if self.state.mode is Mode.PREVIEW:
                    # The bar claims the user's edits are showing while the
                    # preview is still on `_disk_text`, and with
                    # `auto_refresh: false` nothing would ever fix that. This
                    # corrects a display already known wrong, so it skips the
                    # `_auto_refresh` gate.
                    self._refresh_body_now()
                self._show_external_change_bar()
            return
        self._dismiss_external_bar()
        self._on_file_settled()

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
            # An error page has no `window.xedown`, so a body swap would do
            # nothing while still marking the preview fresh -- stranding the
            # error page for good. A reload is the only route back.
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
        # `text`, not the buffer: under an external change they are two
        # different strings. See `_note_preview_shown`.
        self._note_preview_shown(text)
        # After the swap: a render that raised part-way would otherwise leave
        # a partial count describing a page nobody will see.
        self._note_remote_images(stats)
        self.state.preview_stale = False
        self._update_refresh_cue()

    def _reload_preview(self, error=None, restore_scroll=0.0):
        if self.preview is None:
            return
        # Built even for the error branch: an unrendered stats object is
        # exactly the "no document, no offer" answer the chip needs.
        stats = images.RenderStats()
        if error is not None:
            # The empty string tells `_note_preview_shown` that an error page
            # showed the reader nothing of their document.
            text = ""
            html = errors.error_page(
                "Cannot render this document",
                errors.render_failure_detail(error),
                dark=self._dark,
                ui_direction=self._ui_direction,
            )
        else:
            text = self._render_text()
            html = renderer.render_document(
                text,
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
        # Asks the page, not the caller's belief about which branch made it:
        # `render_document` never raises, so `error is None` stays true even
        # when it caught something and returned an error page itself.
        self._page_is_document = not errors.is_error_page(html)
        if self._page_is_document:
            # Both guards earn their place: `text` is empty on the error
            # branch, and this also catches the page `render_document` turned
            # into an error internally, where `text` was real but nothing of
            # it reached the reader.
            self._note_preview_shown(text)
        # Unconditional: `stats.rendered` is False for both error-page routes,
        # so this withdraws the offer rather than leaving it standing.
        self._note_remote_images(stats)
        self.state.preview_stale = False
        self._update_refresh_cue()
        if not self._page_is_document and self.search.active:
            # The page that could have answered is gone. Bump the token first,
            # so a reply already in flight from that page cannot land after
            # this one and put a count back on a document nobody can see.
            token = self.search.invalidate()
            # Re-arm rather than `preview.search()`, which would ask *now*:
            # navigation to the error page is async, so the old page can still
            # be loaded and would answer with this new token, overwriting the
            # "no matches" below. This only updates bookkeeping, so the next
            # page's own load reissues it.
            self.preview.rearm_search(
                self.search.query, self.search.case_sensitive, token
            )
            self._report_search(0, False, token)

    def _buffer_text(self):
        start, end = self.document.get_bounds()
        return self.document.get_text(start, end, False)

    def _render_text(self):
        """The user's version of this document.

        Their edits if they have any, the file on disk if they do not, which
        only diverges after an external change.

        `_disk_text` is deliberately *not* cleared by the first keystroke: the
        `get_modified()` test already stops it being rendered, and keeping it
        is what lets `_on_modified_changed` turn an `UPDATE` into a `WARN`.
        """
        if self._disk_text is not None and not self.document.get_modified():
            return self._disk_text
        return self._buffer_text()

    def _on_document_saved(self, *_args):
        """Handle a save without reloading the page.

        A save does not change the buffer, so a full reload would only jump
        the preview back to the top. It can still be when a never-built tab
        becomes eligible (Save As to a .md name), or leave a debounced change
        unrendered.
        """
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        # A save reconciles buffer and disk. The monitor still fires for
        # xed's own write and `diskstate` answers UNCHANGED, which is why this
        # feature needs no ignore-flag anywhere.
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

        Also fires for the tab's *initial* load, which is unordered against
        `activate()`'s queued build. If the build wins that race it measures
        an empty buffer, so a document large enough to defer opens straight
        into an unrequested Preview render of nothing -- and this is that
        load arriving afterwards with the content the decision needed.

        `_preview_has_shown_content` is what separates that race from an
        ordinary revert of a tab the reader has been looking at.
        """
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        self._disk_text = None
        self._dismiss_external_bar()
        # No watch repoint: `loaded` fires for a revert or reload, which
        # reuse the tab's existing path.
        self.state.preview_stale = True
        if (
            not self._preview_has_shown_content
            and self.state.mode is Mode.PREVIEW
            and perflimits.classify(self._document_char_count()).defer_initial
        ):
            # The race above, resolved as `_build_if_markdown` would have:
            # nothing real has been shown, so there is no preview to pull the
            # reader out of. `initial=True` for the same reasons the build
            # call uses it -- no stolen focus, no scroll restore, and no
            # remembered mode written for a choice nobody made.
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
        listener, so a missed disconnect keeps this controller -- and the
        WebView, document and tab it references -- alive for the life of the
        process. `deactivate()` owns that.

        What needs a whole new page: the theme (its stylesheet is inlined in
        <head>) and `REMOTE_IMAGES` (a permitted page names the private image
        scheme in its CSP <meta>). What does not: width and text size are
        custom properties the page already reads, and `IMAGE_FALLBACK`,
        `CODE_COPY_BUTTONS` and `TEXT_DIRECTION` touch only the body.

        Every key is re-read before the reload branch, so one broadcast
        moving several keys cannot leave a reload carrying outgoing values,
        or render the body twice for values the first render already had.

        `CUSTOM_STYLESHEET` is deliberately absent: both routes to it arrive
        through `stylewatcher`. Both handlers rebuild `self._style` from the
        store rather than patching a field, so neither depends on arriving
        first.
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
        # Two branches below can each want a body render out of one
        # broadcast; this is how the second knows the first already ran.
        refreshed = False
        # `REMOTE_IMAGES` rides with the theme: both live in <head>, so both
        # are a whole page or nothing, and one branch reloads exactly once.
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

        if (
            settings.REMEMBER_MODE_PER_FILE in changed
            and store.get(settings.REMEMBER_MODE_PER_FILE)
            and not self._preview_deferred
        ):
            # Switched on: make it true of tabs already open. Except a
            # deferred one, whose SOURCE mode the size guard chose, not the
            # reader: filing that would make `_initial_mode` return SOURCE
            # next time, so the deferral never fires and the chip offering
            # the preview never appears for that file again.
            self._remember_mode(self.state.mode)
        self._update_refresh_cue()

        if reloaded:
            # The reload already carried these values; poking the outgoing
            # page would land on nothing, since load_html is asynchronous.
            return

        if (
            settings.CODE_COPY_BUTTONS in changed or settings.IMAGE_FALLBACK in changed
        ) and self.preview is not None:
            self.preview.set_config(self._copy_buttons, self._image_display)

        # Body-only: the CSS for every image mode is already in the page and
        # direction is one attribute. Skipped when the catch-up branch above
        # rendered, which already carried both values.
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
        # Rebuilt rather than patched, so a reload carries current metrics
        # even when this races a broadcast that also moved them.
        self._style = stylesheets.PreviewStyle.from_settings(
            settings.get_settings(), user=user
        )
        self.state.preview_stale = True
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())

    def _on_mode_selected(self, _bar, mode_value):
        self.set_mode(Mode(mode_value))

    def _fetch_remote(self):
        """Whether this tab may fetch remote images right now.

        Read from the store at render time rather than cached: it is asked
        once per render, not per image, and a value that cannot go stale is
        one less thing for `_on_settings_changed` to keep in step.
        """
        return (
            settings.get_settings().get(settings.REMOTE_IMAGES) == "https"
            or self._remote_unblocked
        )

    def _note_remote_images(self, stats):
        """Offer to load what this render refused to fetch, or withdraw the
        offer.

        `stats.rendered` is the renderer's witness that the HTML on screen is
        the document: counts alone are not enough, because a full-page render
        builds the body first and can still fail after, leaving an error page
        carrying a real count. A "3 remote images [Load]" chip over a page
        with no images in it offers something that is not there.
        """
        if self.modebar is not None:
            self.modebar.set_remote_images(
                stats.blocked_remote if stats.rendered else 0
            )

    def _on_load_images_requested(self, _bar):
        """The reader has chosen to load this document's remote images.

        A full reload, not a body swap: the permission is carried by the
        page's own CSP <meta>, so `xedown-image:` sources swapped into a page
        loaded while blocked would be refused image by image.
        """
        # A debounce timer armed just before the click would swap that body
        # into the *old* page, whose CSP refuses it -- flashing a raw
        # private-scheme URL in a placeholder. The reload renders the same
        # text anyway.
        self._cancel_refresh()
        self._remote_unblocked = True
        # Withdrawn now rather than at the next render: in Markdown mode no
        # render is coming until the reader switches back.
        if self.modebar is not None:
            self.modebar.set_remote_images(0)
        # A URL here may already be marked failed, from another tab or from
        # this one while offline. Load is exactly the "try again" the
        # failure half of the cache is dropped for.
        imagescheme.get_fetcher().invalidate_failures()
        self.state.preview_stale = True
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview(restore_scroll=self._current_preview_scroll())
        else:
            self._update_refresh_cue()

    def _on_build_preview_requested(self, _bar):
        """The reader asked for the deferred preview. Give it to them.

        No special-casing of the flag: clearing `_preview_deferred` is
        `set_mode`'s job, as the funnel every route into Preview goes
        through. The *live refresh* guard stays on -- a document big enough
        to defer is big enough to keep off the keystroke path.
        """
        self.set_mode(Mode.PREVIEW)

    def _on_image_error(self, source):
        """The page says an image did not load. Say why, when xedown knows.

        A local image needs nothing added: its reason was decided at render
        time and the placeholder already carries it. This exists for a
        `xedown-image:` source, where the page cannot know why a fetch failed.

        This is the route that usually lands: `_on_remote_image_failed` hears
        the same failure earlier, before the page has built the placeholder
        to write into. Here the placeholder certainly exists, because the
        page posted this while creating it.
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

        Routed by the WebView the request came from, so a failure lands only
        in the tab that asked for it. Writes the same sentence
        `_on_image_error` does, and the two are idempotent in either order.
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

        There is one slot, so the newer bar replaces the older -- xed's own
        included, and in the one case where both can appear they offer the
        same thing by the same route. Returns the bar so a caller can
        recognise its own later, or None when there is no tab.
        """
        if self.tab is None:
            return None
        if not self._tab_is_quiet():
            # The slot is xed's while it works: it holds a
            # `XedProgressInfoBar` it keeps calling into, and `set_info_bar`
            # destroys whatever is there. Taking it mid-job broke xed's state
            # machine outright -- see `_tab_is_quiet`. This is the choke point
            # that makes that true of every caller.
            return None
        self._dismiss_info_bar()
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        bar.get_content_area().add(Gtk.Label(label=message))
        if button is not None:
            bar.add_button(button, Gtk.ResponseType.APPLY)
        # `Gtk.InfoBar` has no `get_widget_for_response` -- that is a
        # `Gtk.Dialog` method, and calling it raised `AttributeError` on every
        # info bar the plugin showed. `add_button` hands the button back.
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
        # `Xed.Tab.set_info_bar` marshals its argument as non-nullable, so a
        # bar is retired by destroying it, not by clearing the slot.
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

        `xed_tab_set_info_bar` plain `gtk_widget_destroy`s the bar already in
        the slot, with no "response" signal -- and xed takes that route for
        bars of its own, destroying xedown's out from under it. Left
        unhandled, these fields would point at a destroyed widget forever and
        `_show_external_change_bar`'s idempotence guard would compare two
        dangling pointers, reading "already showing" and wedging every later
        warning off for the life of the tab.

        Harmlessly re-entrant: the two callers null these fields *before*
        calling `bar.destroy()`, so this finds nothing left to clear. It only
        clears fields already naming `bar`, never assigns, so it cannot
        resurrect a bar a newer one replaced.
        """
        if self._info_bar is bar:
            self._info_bar = None
            self._info_bar_action = None
        if self._external_bar is bar:
            self._external_bar = None
        self._untrack(bar)
