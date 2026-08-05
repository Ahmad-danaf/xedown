"""xedown — Markdown preview for xed, rendered and source modes in one tab.

The peas loader imports this module by name, which forces GTK/Xed imports here.
Those types ship with xed itself and are unavailable in CI, so the import is
guarded and the activatable classes are defined only when the host is present.
"""

import sys

__version__ = "0.1.0"

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Xed", "1.0")
    _HOST_AVAILABLE = True
except (ImportError, ValueError) as exc:  # pragma: no cover - host-only path
    _HOST_AVAILABLE = False
    sys.stderr.write(
        f"xedown: xed/GTK typelibs unavailable ({exc}); plugin hooks not registered\n"
    )

if _HOST_AVAILABLE:
    from gi.repository import GObject, Gtk, Xed

    from .controller import TabController

    MENU_PATH = "/MenuBar/ViewMenu/ViewOps_1"
    _CONTROLLER_ATTRIBUTE = "_xedown_controller"

    class XedownWindowActivatable(GObject.Object, Xed.WindowActivatable):
        """Owns the View-menu entry and the toggle accelerator."""

        __gtype_name__ = "XedownWindowActivatable"

        window = GObject.Property(type=Xed.Window)

        def __init__(self):
            GObject.Object.__init__(self)
            self._action_group = None
            self._ui_id = None

        def do_activate(self):
            manager = self.window.get_ui_manager()
            self._action_group = Gtk.ActionGroup(name="XedownActions")
            self._action_group.add_actions(
                [
                    (
                        "XedownToggleAction",
                        None,
                        "Toggle Markdown _Preview",
                        "<Ctrl><Shift>M",
                        "Switch between the rendered preview and the Markdown source",
                        self.toggle_preview,
                    )
                ]
            )
            manager.insert_action_group(self._action_group)
            self._ui_id = manager.new_merge_id()
            manager.add_ui(
                self._ui_id,
                MENU_PATH,
                "XedownToggleAction",
                "XedownToggleAction",
                Gtk.UIManagerItemType.MENUITEM,
                False,
            )

        def do_deactivate(self):
            manager = self.window.get_ui_manager()
            # The manager can already be gone during window teardown.
            if manager is None or self._ui_id is None:
                return
            manager.remove_ui(self._ui_id)
            manager.remove_action_group(self._action_group)
            manager.ensure_update()
            self._ui_id = None
            self._action_group = None

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

        def toggle_preview(self, *_args):
            controller = self._active_controller()
            if controller is not None and controller.is_markdown:
                controller.toggle()

    class XedownViewActivatable(GObject.Object, Xed.ViewActivatable):
        """One controller per view — this is the per-tab ownership boundary."""

        __gtype_name__ = "XedownViewActivatable"

        view = GObject.Property(type=Xed.View)

        def __init__(self):
            GObject.Object.__init__(self)
            self._controller = None

        def do_activate(self):
            self._controller = TabController(self.view)
            setattr(self.view, _CONTROLLER_ATTRIBUTE, self._controller)
            self._controller.activate()

        def do_deactivate(self):
            if self._controller is not None:
                self._controller.deactivate()
                self._controller = None
            if hasattr(self.view, _CONTROLLER_ATTRIBUTE):
                delattr(self.view, _CONTROLLER_ATTRIBUTE)
