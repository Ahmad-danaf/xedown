"""xedown — Markdown preview for xed, rendered and source modes in one tab.

The peas loader imports this module by name, which forces GTK/Xed imports here.
Those types ship with xed itself and are unavailable in CI, so the import is
guarded and the activatable classes are defined only when the host is present.
"""

import sys

__version__ = "0.1.0"

try:
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Xed", "1.0")
    _HOST_AVAILABLE = True
except (ImportError, ValueError) as exc:  # pragma: no cover - host-only path
    _HOST_AVAILABLE = False
    sys.stderr.write(
        f"xedown: xed/GTK typelibs unavailable ({exc}); plugin hooks not registered\n"
    )

if _HOST_AVAILABLE:
    from gi.repository import Gdk, GLib, GObject, Gtk, Xed

    from . import shortcuts
    from .controller import TabController
    from .document_state import Mode

    MENU_PATH = "/MenuBar/ViewMenu/ViewOps_1"
    _CONTROLLER_ATTRIBUTE = "_xedown_controller"

    def _deactivate_view(view):
        """Tear down `view`'s controller, if it still has one.

        Shared by two paths that both need to end up in the same state:
        `XedownViewActivatable.do_deactivate()` (peas calling this when the
        whole plugin is disabled) and `XedownWindowActivatable`'s
        `tab-removed` handler below (a closed tab). xed does not deactivate
        a `ViewActivatable` when its tab is simply closed — only when the
        plugin itself is unloaded — so without the second path every closed
        Markdown tab would leak its `TabController`, WebView and signal
        handlers for the life of the window. Safe to call twice on the same
        view (double-close, or a tab-removed cleanup followed later by a
        plugin-disable sweep): the attribute is gone after the first call,
        so the second is a no-op.
        """
        controller = getattr(view, _CONTROLLER_ATTRIBUTE, None)
        if controller is not None:
            controller.deactivate()
        if hasattr(view, _CONTROLLER_ATTRIBUTE):
            delattr(view, _CONTROLLER_ATTRIBUTE)

    def _focus_is_editable(window):
        """True when this keystroke belongs to something the user types into.

        xed's find bar, the file browser's rename entry and any dialog entry
        are `GtkEditable`s; the source view is a `GtkTextView`. Copy in any of
        them is theirs, not the preview's.
        """
        focus = window.get_focus()
        return isinstance(focus, (Gtk.Editable, Gtk.TextView))

    class XedownWindowActivatable(GObject.Object, Xed.WindowActivatable):
        """Owns the View-menu entry, the toggle accelerator, and the
        per-tab-close cleanup safety net (see `_deactivate_view`)."""

        __gtype_name__ = "XedownWindowActivatable"

        window = GObject.Property(type=Xed.Window)

        def __init__(self):
            GObject.Object.__init__(self)
            self._action_group = None
            self._ui_id = None
            self._tab_removed_handler_id = None
            self._key_press_handler_id = None

        def do_activate(self):
            manager = self.window.get_ui_manager()
            self._action_group = Gtk.ActionGroup(name="XedownActions")
            handlers = {
                shortcuts.TOGGLE: self.toggle_preview,
                shortcuts.PREVIEW_MODE: self.show_preview,
                shortcuts.MARKDOWN_MODE: self.show_markdown,
                shortcuts.REFRESH: self.refresh_preview,
            }
            self._action_group.add_actions(
                [
                    (
                        action.name,
                        None,
                        action.label,
                        action.accelerator,
                        action.tooltip,
                        handlers[action.name],
                    )
                    for action in shortcuts.ACTIONS
                ]
            )
            manager.insert_action_group(self._action_group)
            self._ui_id = manager.new_merge_id()
            # One merge id for all four, so do_deactivate takes them out the
            # same way it always did -- together.
            for action in shortcuts.ACTIONS:
                manager.add_ui(
                    self._ui_id,
                    MENU_PATH,
                    action.name,
                    action.name,
                    Gtk.UIManagerItemType.MENUITEM,
                    False,
                )
            self._tab_removed_handler_id = self.window.connect(
                "tab-removed", self._on_tab_removed
            )
            # Connected rather than connected-after on purpose: GtkWindow's
            # own class handler is what activates accelerators, and for a
            # RUN_LAST signal it runs after ordinary handlers. Returning True
            # from here is the only way to stop xed's Ctrl+C from reaching
            # the hidden source buffer while the preview is what the user is
            # looking at.
            self._key_press_handler_id = self.window.connect(
                "key-press-event", self._on_key_press
            )

        def do_deactivate(self):
            if self._key_press_handler_id is not None:
                self.window.disconnect(self._key_press_handler_id)
                self._key_press_handler_id = None
            if self._tab_removed_handler_id is not None:
                self.window.disconnect(self._tab_removed_handler_id)
                self._tab_removed_handler_id = None
            manager = self.window.get_ui_manager()
            # The manager can already be gone during window teardown.
            if manager is None or self._ui_id is None:
                return
            manager.remove_ui(self._ui_id)
            manager.remove_action_group(self._action_group)
            manager.ensure_update()
            self._ui_id = None
            self._action_group = None

        def _on_tab_removed(self, _window, tab):
            # "tab-removed" fires on the SOURCE window both for a real close
            # and for Documents -> Move to New Window / dragging a tab out
            # (xed_notebook_move_tab): in a move the same tab is re-added to
            # the destination window's notebook, synchronously, and its view
            # must keep its controller. Deciding "is this a close" one
            # main-loop turn later, once the move (if any) has already
            # completed, is reliable: a moved tab already has a new parent
            # by then, while a closed tab's widgets are being torn down and
            # it has none. Tearing down unconditionally here (the first cut
            # of this fix) silently destroyed the preview on every tab move,
            # trading the close-time leak for a worse, silent regression.
            GLib.idle_add(self._maybe_deactivate_tab, tab)

        def _maybe_deactivate_tab(self, tab):
            if tab.get_parent() is not None:
                return False  # moved to another notebook, not closed
            view = tab.get_view()
            if view is not None:
                _deactivate_view(view)
            return False

        def do_update_state(self):
            """No preview controls for non-Markdown files."""
            if self._action_group is None:
                return
            controller = self._active_controller()
            self._action_group.set_sensitive(
                controller is not None and controller.is_markdown
            )

        def _active_controller(self):
            view = self.window.get_active_view()
            return getattr(view, _CONTROLLER_ATTRIBUTE, None) if view else None

        def _on_key_press(self, _window, event):
            """Give copy and select-all to whichever surface is visible.

            Two cheap tests before anything else is looked at, because this
            sees every key press in the window; `shortcuts.route_key` remains
            the authority on what the press means.
            """
            key_name = (
                Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or ""
            ).lower()
            control_only = (
                event.state & Gtk.accelerator_get_default_mod_mask()
            ) == Gdk.ModifierType.CONTROL_MASK
            if not control_only or key_name not in shortcuts.HANDLED_KEYS:
                return False

            controller = self._active_controller()
            action = shortcuts.route_key(
                key_name,
                control_only=control_only,
                focus_is_editable=_focus_is_editable(self.window),
                previewing=controller is not None and controller.is_previewing,
            )
            if action is None:
                return False
            if action is shortcuts.KeyAction.COPY:
                controller.preview.copy_selection()
            else:
                controller.preview.select_all()
            return True

        def _markdown_controller(self):
            controller = self._active_controller()
            return (
                controller
                if controller is not None and controller.is_markdown
                else None
            )

        def toggle_preview(self, *_args):
            controller = self._markdown_controller()
            if controller is not None:
                controller.toggle()

        def show_preview(self, *_args):
            controller = self._markdown_controller()
            if controller is not None:
                controller.set_mode(Mode.PREVIEW)

        def show_markdown(self, *_args):
            controller = self._markdown_controller()
            if controller is not None:
                controller.set_mode(Mode.SOURCE)

        def refresh_preview(self, *_args):
            controller = self._markdown_controller()
            if controller is not None:
                controller.refresh_now()

    class XedownViewActivatable(GObject.Object, Xed.ViewActivatable):
        """One controller per view — this is the per-tab ownership boundary.

        Deliberately does not also cache the controller on `self`: the
        view's `_CONTROLLER_ATTRIBUTE` is the single source of truth (it is
        what `_deactivate_view` and the rest of the plugin read), and peas
        does not dispose this object when a tab is merely closed (only when
        the whole plugin is disabled -- see `_on_tab_removed` above), so a
        second, separately-tracked reference on `self` would go stale
        exactly then: cleared on the view's attribute but left dangling
        here, keeping the torn-down controller (and the view/document/tab/
        frame it references) alive for no reason for the life of the
        window.
        """

        __gtype_name__ = "XedownViewActivatable"

        view = GObject.Property(type=Xed.View)

        def do_activate(self):
            controller = TabController(self.view)
            setattr(self.view, _CONTROLLER_ATTRIBUTE, controller)
            controller.activate()

        def do_deactivate(self):
            _deactivate_view(self.view)
