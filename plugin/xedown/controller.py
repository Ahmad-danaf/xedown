"""Orchestrates one tab: mode bar, preview, scroll memory, refresh, teardown."""

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import GLib, Gtk, Xed

from . import errors, renderer
from .document_state import DocumentState, Mode, is_markdown_path
from .links import LinkAction, classify_link
from .modebar import ModeBar
from .preview import PreviewView
from .theme import ThemeWatcher

REFRESH_DELAY_MS = 250


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
        self.theme_watcher = None

        self._handlers = []  # (gobject, handler_id)
        self._refresh_source_id = 0
        self._built = False
        self._dark = False

    # --- lifecycle ---------------------------------------------------------

    def activate(self):
        self._connect(self.document, "saved", self._on_document_reloaded)
        self._connect(self.document, "loaded", self._on_document_reloaded)
        if self.tab is not None:
            self._connect(self.tab, "notify::state", self._on_tab_state_changed)
        GLib.idle_add(self._build_if_markdown)

    def deactivate(self):
        self._cancel_refresh()
        for owner, handler_id in self._handlers:
            try:
                owner.disconnect(handler_id)
            except (TypeError, RuntimeError):
                pass
        self._handlers = []

        if self.theme_watcher is not None:
            self.theme_watcher.disconnect()
            self.theme_watcher = None

        # Always hand the source editor back, whatever mode we were in.
        if self.frame is not None:
            self.frame.set_no_show_all(False)
            self.frame.show()

        if self.preview is not None:
            self.preview.destroy()
            self.preview = None
        if self.modebar is not None:
            self.modebar.destroy()
            self.modebar = None
        self._built = False

    def _connect(self, owner, signal, callback):
        self._handlers.append((owner, owner.connect(signal, callback)))

    # --- construction ------------------------------------------------------

    @property
    def is_markdown(self):
        return is_markdown_path(self._document_path())

    def _document_path(self):
        location = self.document.get_location()
        return location.get_path() if location is not None else None

    def _base_dir(self):
        path = self._document_path()
        return os.path.dirname(path) if path else None

    def _build_if_markdown(self):
        """Non-Markdown documents get no mode bar constructed at all."""
        if self._built or not self.is_markdown or self.tab is None:
            return False

        self.theme_watcher = ThemeWatcher()
        self._dark = self.theme_watcher.current_dark()
        self.theme_watcher.connect(self._on_theme_changed)

        self.modebar = ModeBar()
        self.tab.pack_start(self.modebar, False, False, 0)
        self.tab.reorder_child(self.modebar, 0)
        self.modebar.show_all()
        self._connect(self.modebar, "mode-selected", self._on_mode_selected)

        self.preview = PreviewView(
            on_link=self._on_link_activated, on_image_error=self._on_image_error
        )
        self.tab.pack_start(self.preview.widget, True, True, 0)

        self._connect(self.document, "changed", self._on_buffer_changed)

        self._built = True
        self.set_mode(Mode.PREVIEW)  # preview is the default
        return False

    # --- mode switching ----------------------------------------------------

    def toggle(self):
        self.set_mode(Mode.SOURCE if self.state.mode is Mode.PREVIEW else Mode.PREVIEW)

    def set_mode(self, mode):
        if not self._built:
            return
        self._remember_scroll(self.state.mode)
        self.state.mode = mode
        self.modebar.set_mode(mode)

        if mode is Mode.PREVIEW:
            if self.state.preview_stale:
                self._reload_preview()
            self.frame.set_no_show_all(True)
            self.frame.hide()
            self.preview.widget.show_all()
            self.preview.set_scroll(self.state.preview_scroll)
        else:
            self.preview.widget.hide()
            self.frame.set_no_show_all(False)
            self.frame.show()
            self._restore_source_scroll()
            self.view.grab_focus()

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
        if self.state.mode is not Mode.PREVIEW:
            return  # no hidden rendering while the user types in source mode
        self._cancel_refresh()
        self._refresh_source_id = GLib.timeout_add(REFRESH_DELAY_MS, self._do_refresh)

    def _cancel_refresh(self):
        if self._refresh_source_id:
            GLib.source_remove(self._refresh_source_id)
            self._refresh_source_id = 0

    def _do_refresh(self):
        self._refresh_source_id = 0
        if not self._built or self.state.mode is not Mode.PREVIEW:
            return False
        try:
            fragment = renderer.render_fragment(
                self._buffer_text(), base_dir=self._base_dir()
            )
        except Exception as exc:  # noqa: BLE001 - never leave a blank pane
            self._reload_preview(error=exc)
            return False
        self.preview.update_body(fragment)
        self.state.preview_stale = False
        return False

    def _reload_preview(self, error=None):
        if self.preview is None:
            return
        if error is not None:
            html = errors.error_page(
                "Cannot render this document",
                errors.render_failure_detail(error),
                dark=self._dark,
            )
        else:
            html = renderer.render_document(
                self._buffer_text(), base_dir=self._base_dir(), dark=self._dark
            )
        base_dir = self._base_dir()
        self.preview.load_document(
            html, ("file://" + base_dir + "/") if base_dir else None
        )
        self.state.preview_stale = False

    def _buffer_text(self):
        start, end = self.document.get_bounds()
        return self.document.get_text(start, end, False)

    def _on_document_reloaded(self, *_args):
        """Fires after xed saves or reloads — including after an external change."""
        if not self._built:
            GLib.idle_add(self._build_if_markdown)
            return
        self.state.preview_stale = True
        if self.state.mode is Mode.PREVIEW:
            self._reload_preview()

    def _on_theme_changed(self, dark):
        self._dark = dark
        if self._built and self.state.mode is Mode.PREVIEW:
            self._reload_preview()

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
        bar = Gtk.InfoBar()
        bar.set_message_type(Gtk.MessageType.WARNING)
        bar.get_content_area().add(Gtk.Label(label=message))
        bar.add_button("Close", Gtk.ResponseType.CLOSE)
        bar.connect("response", lambda widget, _r: self.tab.set_info_bar(None))
        self.tab.set_info_bar(bar)
        bar.show_all()
        if self.modebar is not None:
            self.tab.reorder_child(self.modebar, 0)
