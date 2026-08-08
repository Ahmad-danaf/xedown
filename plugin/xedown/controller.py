"""Orchestrates one tab: mode bar, preview, scroll memory, refresh, teardown."""

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import GLib, Gtk, Xed

from . import (
    direction,
    errors,
    images,
    modestore,
    renderer,
    settings,
    stylesheets,
    stylewatcher,
)
from .appearance import AppearanceWatcher
from .document_state import DocumentState, Mode, is_markdown_path, mode_from_setting
from .links import LinkAction, classify_link
from .modebar import ModeBar
from .preview import PreviewView


class TabController:
    """One per view. Owns and disconnects everything it creates."""

    def __init__(self, view):
        self.view = view
        self.document = view.get_buffer()
        self.tab = Xed.Tab.get_from_document(self.document)
        self.window = self.tab.get_toplevel() if self.tab is not None else None
        self.frame = self.tab.get_children()[0] if self.tab is not None else None

        self.state = DocumentState()
        self.modebar = None
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
        self._refresh_delay_ms = 250
        self._text_direction = direction.AUTO
        self._ui_direction = direction.LTR
        self._stylesheet_token = None
        self._info_bar = None
        # The path this tab's remembered mode is filed under. Compared on
        # save, so a Save As moves the entry instead of stranding it.
        self._remembered_path = None

    # --- lifecycle ---------------------------------------------------------

    def activate(self):
        self._active = True
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
        for owner, handler_id in self._handlers:
            try:
                owner.disconnect(handler_id)
            except (TypeError, RuntimeError):
                pass
        self._handlers = []

        if self._settings_token is not None:
            settings.get_settings().disconnect(self._settings_token)
            self._settings_token = None

        if self._stylesheet_token is not None:
            stylewatcher.get_watcher().disconnect(self._stylesheet_token)
            self._stylesheet_token = None

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
        self._built = False

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
        self._image_display = images.coerce_display(store.get(settings.REMOTE_IMAGES))
        self._copy_buttons = bool(store.get(settings.CODE_COPY_BUTTONS))
        self._auto_refresh = bool(store.get(settings.AUTO_REFRESH))
        self._refresh_delay_ms = int(store.get(settings.REFRESH_DELAY_MS))
        self._text_direction = store.get(settings.TEXT_DIRECTION)
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

        self.preview = PreviewView(
            on_link=self._on_link_activated, on_image_error=self._on_image_error
        )
        self.tab.pack_start(self.preview.widget, True, True, 0)

        self._connect(self.document, "changed", self._on_buffer_changed)

        self._built = True
        self._remembered_path = self._document_path()
        self.set_mode(self._initial_mode(), initial=True)
        return False

    # --- mode switching ----------------------------------------------------

    def toggle(self):
        self.set_mode(Mode.SOURCE if self.state.mode is Mode.PREVIEW else Mode.PREVIEW)

    def _initial_mode(self):
        """The mode this file opens in.

        A remembered mode wins when remembering is on; otherwise the default.
        Anything unusable falls back silently -- the brief's rule is that a
        mode which cannot be determined must not interrupt the user.
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

        Going to the mode you are already in does nothing: the brief says so,
        and re-running the branches below would re-grab focus and re-file the
        mode for no reason. The build-time call is exempt, because that is
        the call that first makes one of the two widgets visible.

        `initial` also suppresses three things that would each be a
        regression on a file opening in Markdown mode: restoring the source
        scroll (which applies fraction 0.0 and would scroll over the position
        xed just restored), grabbing focus (xed opens several tabs at once,
        and grabbing focus in a notebook page that is not current moves the
        window's focus off the tab the user is looking at), and writing to
        the mode store (opening a file must not rewrite the memory it was
        just read from).
        """
        if not self._built:
            return
        if mode is self.state.mode and not initial:
            return
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
        else:
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

    def refresh_now(self):
        """Re-render the preview from the document as it is now.

        Nothing to do in Markdown mode: the preview is already stale and
        switching to it renders. Rendering into a hidden WebView to reach the
        same state would be the hidden re-rendering the brief forbids.
        """
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return
        self._cancel_refresh()
        self._refresh_body_now()

    def _update_refresh_cue(self):
        """Keep the bar's refresh control telling the truth."""
        if self.modebar is None:
            return
        self.modebar.set_refresh_visible(not self._auto_refresh)
        self.modebar.set_stale(self.state.preview_stale)

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

    # --- the verified host hazard -----------------------------------------

    def _on_tab_state_changed(self, *_args):
        """xed forces the frame visible on save and revert. Undo that."""
        GLib.idle_add(self._enforce_visibility)

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

    # --- content updates ---------------------------------------------------

    def _on_buffer_changed(self, *_args):
        self.state.preview_stale = True
        self._update_refresh_cue()
        if self.state.mode is not Mode.PREVIEW or not self._auto_refresh:
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
        text = self._buffer_text()
        try:
            fragment = renderer.render_fragment(
                text,
                base_dir=self._base_dir(),
                image_display=self._image_display,
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
        self.state.preview_stale = False
        self._update_refresh_cue()

    def _reload_preview(self, error=None, restore_scroll=0.0):
        if self.preview is None:
            return
        if error is not None:
            html = errors.error_page(
                "Cannot render this document",
                errors.render_failure_detail(error),
                dark=self._dark,
                ui_direction=self._ui_direction,
            )
        else:
            html = renderer.render_document(
                self._buffer_text(),
                base_dir=self._base_dir(),
                dark=self._dark,
                style=self._style,
                image_display=self._image_display,
                code_copy_buttons=self._copy_buttons,
                text_direction=self._text_direction,
                ui_direction=self._ui_direction,
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
        self.state.preview_stale = False
        self._update_refresh_cue()

    def _buffer_text(self):
        start, end = self.document.get_bounds()
        return self.document.get_text(start, end, False)

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
        path = self._document_path()
        if path != self._remembered_path:
            # A Save As. Follow the file rather than leaving an entry keyed
            # to a path it no longer has.
            if self._remembered_path and settings.get_settings().get(
                settings.REMEMBER_MODE_PER_FILE
            ):
                modestore.get_store().rename(self._remembered_path, path)
            self._remembered_path = path
        if self.state.preview_stale and self.state.mode is Mode.PREVIEW:
            self._refresh_body_now()

    def _on_document_loaded(self, *_args):
        """Fires after xed reverts or reloads — including after an external
        change — all of which genuinely replace the buffer contents, so
        (unlike a save) this always warrants a full reload when visible."""
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        self.state.preview_stale = True
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

        `REMOTE_IMAGES` and `CODE_COPY_BUTTONS` are handled here rather than
        through a reload: the first changes only the body, the second only
        the page's own config. Both are re-read before the theme branch, so
        a broadcast that moves several keys at once cannot leave a reload
        carrying the outgoing values.

        `TEXT_DIRECTION` joins them for the same reason: it is one attribute
        on the article, and no stylesheet changed, so there is nothing in
        <head> to rebuild. It costs one re-render of the Markdown, which is
        the right price for a setting nobody changes twice a day and reuses
        machinery that is already correct about mode and staleness.

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
        self._image_display = images.coerce_display(store.get(settings.REMOTE_IMAGES))
        self._copy_buttons = bool(store.get(settings.CODE_COPY_BUTTONS))
        was_auto = self._auto_refresh
        self._auto_refresh = bool(store.get(settings.AUTO_REFRESH))
        self._refresh_delay_ms = int(store.get(settings.REFRESH_DELAY_MS))
        self._text_direction = store.get(settings.TEXT_DIRECTION)

        reloaded = False
        # Two independent branches below can each want a body render out of
        # one broadcast (the auto-refresh catch-up here, and the
        # image-display/direction branch further down) -- this flag is how
        # the second one knows the first already happened, so one broadcast
        # never renders the body twice.
        refreshed = False
        if settings.PREVIEW_THEME in changed:
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

        if not self._auto_refresh:
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
            settings.CODE_COPY_BUTTONS in changed or settings.REMOTE_IMAGES in changed
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

    def _on_image_error(self, _source):
        # The placeholder is already in the page; nothing further is required.
        return

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

    def _show_error(self, message):
        if self.tab is None:
            return
        self._dismiss_info_bar()
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        bar.get_content_area().add(Gtk.Label(label=message))
        bar.add_button("Close", Gtk.ResponseType.CLOSE)
        self._connect(bar, "response", self._on_info_bar_response)
        self._info_bar = bar
        self.tab.set_info_bar(bar)
        bar.show_all()
        if self.modebar is not None:
            self.tab.reorder_child(self.modebar, 0)

    def _on_info_bar_response(self, bar, _response):
        # `Xed.Tab.set_info_bar` does not accept None (its `info_bar`
        # argument is marshaled as non-nullable), so the bar is retired by
        # destroying it directly rather than trying to clear the tab's
        # info-bar slot.
        if self._info_bar is bar:
            self._info_bar = None
        self._untrack(bar)
        bar.destroy()

    def _dismiss_info_bar(self):
        """Remove the info bar this controller created, if any is showing.

        Never touches an info bar this controller did not create.
        """
        if self._info_bar is not None:
            bar, self._info_bar = self._info_bar, None
            self._untrack(bar)
            bar.destroy()
