"""Plugin entry point: registers xedown with xed's window and view lifecycle."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Xed", "1.0")

from gi.repository import GObject, Xed  # noqa: E402


class XedownWindowActivatable(GObject.Object, Xed.WindowActivatable):
    """Per-window hook: owns the menu entry and the toggle shortcut."""

    __gtype_name__ = "XedownWindowActivatable"

    window = GObject.Property(type=Xed.Window)

    def do_activate(self):
        raise NotImplementedError

    def do_deactivate(self):
        raise NotImplementedError

    def do_update_state(self):
        raise NotImplementedError

    def toggle_preview(self, *_args):
        """Swap the active tab between rendered and source mode."""
        raise NotImplementedError


class XedownViewActivatable(GObject.Object, Xed.ViewActivatable):
    """Per-view hook: binds one document to its preview widget."""

    __gtype_name__ = "XedownViewActivatable"

    view = GObject.Property(type=Xed.View)

    def do_activate(self):
        raise NotImplementedError

    def do_deactivate(self):
        raise NotImplementedError
