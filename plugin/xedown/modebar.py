"""The slim segmented Preview | Markdown control at the top of the tab."""

from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GObject, Gtk

from . import a11y
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
.xedown-modebar .xedown-stale-dot {
  font-size: .8em;
  padding: 0 .3em;
}
"""

_provider_installed = False


def _ensure_provider():
    """Install the CSS provider once, globally."""
    global _provider_installed
    if _provider_installed:
        return

    # Attempt to get a screen to install the provider on.
    screen = Gdk.Screen.get_default()
    if screen is None:
        # No display; CSS styling will not apply, but widget construction continues.
        _provider_installed = True
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(_STYLE)
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _provider_installed = True


class ModeBar(Gtk.Box):
    """Two joined segments. Emits a signal; holds no policy of its own."""

    __gtype_name__ = "XedownModeBar"

    __gsignals__: ClassVar = {
        "mode-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.get_style_context().add_class("xedown-modebar")

        _ensure_provider()

        segments = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        segments.get_style_context().add_class("linked")

        self._updating = False
        self._buttons = {}
        for mode, label, icon, key in (
            (Mode.PREVIEW, "Preview", "view-reveal-symbolic", "mode_preview"),
            (Mode.SOURCE, "Markdown", "text-x-generic-symbolic", "mode_source"),
        ):
            button = Gtk.ToggleButton()
            button.add(self._make_content(label, icon))
            # The visible label stays "Markdown" -- short, and the bar is a
            # segmented pair where the context is obvious. The accessible
            # name is "Markdown source", because read aloud on its own
            # "Markdown" does not say what the button shows.
            self._name(button, a11y.NAMES[key])
            button.connect("toggled", self._on_toggled, mode)
            segments.pack_start(button, False, False, 0)
            self._buttons[mode] = button

        self.pack_start(segments, False, False, 0)

        # Packed from the trailing edge inward, so the button sits at the end
        # of the bar and the dot immediately before it. Both are
        # set_no_show_all so a show_all() on the tab cannot reveal either --
        # the same mitigation the controller applies to the source frame and
        # the WebView, for the same reason.
        self._refresh_button = Gtk.Button()
        self._refresh_button.add(self._make_content("Refresh", "view-refresh-symbolic"))
        self._refresh_button.set_no_show_all(True)
        self._refresh_button.set_tooltip_text("Refresh the preview (Ctrl+Shift+R)")
        # The tooltip keeps the shortcut for sighted users; the accessible
        # name is the plain description, because a screen reader announces
        # the shortcut itself from the accelerator.
        self._name(self._refresh_button, a11y.NAMES["refresh"])
        self._refresh_button.connect("clicked", self._on_refresh_clicked)
        self.pack_end(self._refresh_button, False, False, 0)

        self._stale_dot = Gtk.Label(label="●")
        self._stale_dot.get_style_context().add_class("xedown-stale-dot")
        self._stale_dot.set_no_show_all(True)
        # Without a name this reads as "black circle" -- a description of a
        # shape rather than of what it means. It appears and disappears, so
        # the name is what makes its appearing mean something.
        self._name(self._stale_dot, a11y.NAMES["stale"])
        self.pack_end(self._stale_dot, False, False, 0)

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

    @staticmethod
    def _name(widget, name):
        """An accessible name, which a tooltip is not.

        The same helper `searchbar.py` carries, for the same reason: a
        `Gtk.Button` whose label is wrapped in a `Gtk.Box` alongside an icon
        may or may not expose that label as its name, and "may or may not" is
        not a standard.
        """
        accessible = widget.get_accessible()
        if accessible is not None:
            accessible.set_name(name)

    def set_mode(self, mode):
        """Reflect `mode` without emitting mode-selected."""
        self._updating = True
        for candidate, button in self._buttons.items():
            button.set_active(candidate is mode)
        self._updating = False

    def set_refresh_visible(self, visible):
        """Show the manual refresh control. Only ever true with auto off."""
        self._refresh_button.set_visible(visible)
        if not visible:
            self._stale_dot.set_visible(False)

    def set_stale(self, stale):
        """Mark the preview as behind the document, or caught up.

        The dot never appears without the button: with automatic refresh on,
        staleness is a state that lasts a quarter of a second and is not
        worth telling anyone about.
        """
        showing = bool(stale) and self._refresh_button.get_visible()
        self._stale_dot.set_visible(showing)
        self._refresh_button.set_tooltip_text(
            "The preview is out of date — refresh it (Ctrl+Shift+R)"
            if showing
            else "Refresh the preview (Ctrl+Shift+R)"
        )

    def _on_refresh_clicked(self, _button):
        self.emit("refresh-requested")

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
