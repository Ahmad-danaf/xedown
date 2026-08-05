"""The slim segmented Preview | Markdown control at the top of the tab."""

from typing import ClassVar

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GObject, Gtk

from .document_state import Mode

_STYLE = b"""
.xedown-modebar {
  padding: 4px 8px;
  border-bottom: 1px solid alpha(currentColor, 0.12);
}
.xedown-modebar button {
  padding: 2px 12px;
  font-size: 0.9em;
}
"""


class ModeBar(Gtk.Box):
    """Two joined segments. Emits a signal; holds no policy of its own."""

    __gtype_name__ = "XedownModeBar"

    __gsignals__: ClassVar = {
        "mode-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,))
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.get_style_context().add_class("xedown-modebar")

        provider = Gtk.CssProvider()
        provider.load_from_data(_STYLE)
        Gtk.StyleContext.add_provider_for_screen(
            self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        segments = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        segments.get_style_context().add_class("linked")

        self._updating = False
        self._buttons = {}
        for mode, label, icon in (
            (Mode.PREVIEW, "Preview", "view-reveal-symbolic"),
            (Mode.SOURCE, "Markdown", "text-x-generic-symbolic"),
        ):
            button = Gtk.ToggleButton()
            button.add(self._make_content(label, icon))
            button.connect("toggled", self._on_toggled, mode)
            segments.pack_start(button, False, False, 0)
            self._buttons[mode] = button

        self.pack_start(segments, False, False, 0)
        self.set_mode(Mode.PREVIEW)

    @staticmethod
    def _make_content(label, icon_name):
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        theme = Gtk.IconTheme.get_default()
        if theme is not None and theme.has_icon(icon_name):
            content.pack_start(
                Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU),
                False,
                False,
                0,
            )
        content.pack_start(Gtk.Label(label=label), False, False, 0)
        return content

    def set_mode(self, mode):
        """Reflect `mode` without emitting mode-selected."""
        self._updating = True
        for candidate, button in self._buttons.items():
            button.set_active(candidate is mode)
        self._updating = False

    def _on_toggled(self, button, mode):
        if self._updating:
            return
        if not button.get_active():
            # Re-clicking the active segment must not deselect both.
            if not any(b.get_active() for b in self._buttons.values()):
                self._updating = True
                button.set_active(True)
                self._updating = False
            return
        self.set_mode(mode)
        self.emit("mode-selected", mode.value)
