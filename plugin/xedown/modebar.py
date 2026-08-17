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
.xedown-modebar .xedown-remote-notice {
  color: alpha(currentColor, 0.6);
  padding: 0 .5em;
}
.xedown-modebar .xedown-large-notice {
  color: alpha(currentColor, 0.6);
  padding: 0 .5em;
}
"""

_provider_installed = False


def _ensure_provider():
    """Install the CSS provider once, globally."""
    global _provider_installed
    if _provider_installed:
        return

    screen = Gdk.Screen.get_default()
    if screen is None:
        # No display: styling will not apply, but construction continues.
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
        "load-images-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "build-preview-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
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

        # Packed from the trailing edge inward, so each later pack_end lands
        # further in. `set_no_show_all` so a show_all() on the tab cannot
        # reveal either, as the controller does for the frame and WebView.
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

        # Immediately after the refresh button, and before the chip below, so
        # it stays adjacent to the button it describes: `set_stale` rewrites
        # that button's tooltip in the same call.
        self._stale_dot = Gtk.Label(label="●")
        self._stale_dot.get_style_context().add_class("xedown-stale-dot")
        self._stale_dot.set_no_show_all(True)
        # Without a name a screen reader reads this as "black circle", a
        # shape rather than a meaning.
        self._name(self._stale_dot, a11y.NAMES["stale"])
        self.pack_end(self._stale_dot, False, False, 0)

        # Inward of the dot, reading "<count> remote images [Load]" ahead of
        # the refresh/stale pair. A quiet chip rather than a warning bar,
        # because blocking is the safe default and a document with one badge
        # image should not raise an alarm every time it opens.
        self._remote_button = Gtk.Button(label="Load")
        self._remote_button.set_no_show_all(True)
        self._name(self._remote_button, a11y.NAMES["load_images"])
        self._remote_button.connect(
            "clicked", lambda _b: self.emit("load-images-requested")
        )
        self.pack_end(self._remote_button, False, False, 0)

        self._remote_label = Gtk.Label()
        self._remote_label.set_no_show_all(True)
        self._remote_label.get_style_context().add_class("xedown-remote-notice")
        self._name(self._remote_label, a11y.NAMES["remote_images_notice"])
        self.pack_end(self._remote_label, False, False, 0)

        # Packed inward of the remote-images chip, so a document that is
        # both large and has blocked images reads outward as
        # "<size> [Preview] <count> remote images [Load]". Same shape as
        # that chip deliberately -- a quiet label plus an action, not a
        # warning bar. A large document is an ordinary thing to open.
        self._large_button = Gtk.Button(label="Preview")
        self._large_button.set_no_show_all(True)
        self._name(self._large_button, a11y.NAMES["build_preview"])
        self._large_button.connect(
            "clicked", lambda _b: self.emit("build-preview-requested")
        )
        self.pack_end(self._large_button, False, False, 0)

        self._large_label = Gtk.Label()
        self._large_label.set_no_show_all(True)
        self._large_label.get_style_context().add_class("xedown-large-notice")
        self._name(self._large_label, a11y.NAMES["large_document_notice"])
        self.pack_end(self._large_label, False, False, 0)

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

    def has_focus_inside(self):
        """True when keyboard focus is on one of this bar's own mode buttons.

        Checked before a mode switch takes effect: if the user tabbed to a
        mode button and activated it, Orca already announces the toggle's own
        state change, and announcing again would say the mode twice.

        Deliberately narrower than "any focusable control in this bar". The
        refresh button is a plain `Gtk.Button` with no toggle state, so a
        switch made with *it* focused gets no state-change speech from Orca
        -- including it here would leave that switch completely silent, which
        is the defect this mechanism exists to remove.

        Named `_inside`, not `has_focus`, because `Gtk.Widget.has_focus()`
        (used below) is true only when the toplevel window holds real input
        focus, not merely when a widget is the window's focus widget. That is
        safe here, since a mode switch always follows a keystroke on this
        window, but the stricter GTK method's name would be a trap for the
        next caller.
        """
        return any(
            button.has_focus()
            for button in (self._buttons[Mode.PREVIEW], self._buttons[Mode.SOURCE])
        )

    def announce(self, text):
        """Speak `text` through `Atk.Object`'s `announcement` signal.

        Measured live against a real Orca session (see
        docs/orca-verification/measurements.md) to reach Orca 46.1
        unconditionally: whether or not the emitting object currently has
        focus, and regardless of GTK's "layout only" classification -- the
        same classification that silently swallows the WebView's own focus
        event on a switch to Preview (see that document's
        row-96-switch-back-to-preview entry). This bar's own accessible
        object is used because it is always realized and visible for the
        life of a built tab, unlike the source view or the WebView, either
        of which can be hidden at the moment a switch happens.

        Never raises. An accessibility nicety that could break a mode
        switch would not be one, and the accessible object can be
        legitimately unavailable -- the AT-SPI bridge not running, the
        widget not yet realized -- with nothing this method can do about
        either.
        """
        try:
            accessible = self.get_accessible()
            if accessible is not None:
                accessible.emit("announcement", text)
        except Exception:  # noqa: BLE001 - never let an a11y nicety break a switch
            return

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

    def set_remote_images(self, count):
        """Offer to load `count` blocked remote images, or hide the offer.

        The count goes into the accessible name as well as the visible label:
        the chip appearing is what makes it mean anything, and a screen reader
        gets no other signal that it did.
        """
        showing = bool(count)
        if showing:
            words = "1 remote image" if count == 1 else f"{count} remote images"
            self._remote_label.set_text(words)
            accessible = self._remote_label.get_accessible()
            if accessible is not None:
                accessible.set_name(f"{a11y.NAMES['remote_images_notice']}: {words}")
            self._remote_button.set_tooltip_text(
                "Load these images. The websites they come from will see your "
                "IP address."
            )
        self._remote_label.set_visible(showing)
        self._remote_button.set_visible(showing)

    def set_large_document(self, size_label):
        """Offer to build a deferred preview, or hide the offer.

        `size_label` is already-formatted text from
        `perflimits.describe_bytes`; the bar holds no policy about what
        counts as large, exactly as it holds none about which images were
        blocked. Falsy hides the chip.

        The size goes into the accessible name as well as the visible
        label, for the same reason the remote-images chip's count does:
        the chip appearing is what makes it mean anything, and a screen
        reader gets no other signal that it did.
        """
        showing = bool(size_label)
        if showing:
            words = f"Large document ({size_label})"
            self._large_label.set_text(words)
            accessible = self._large_label.get_accessible()
            if accessible is not None:
                accessible.set_name(
                    f"{a11y.NAMES['large_document_notice']}: {size_label}"
                )
            self._large_button.set_tooltip_text(
                "Build the preview. A document this large takes a moment to "
                "render, and the editor will not respond while it does."
            )
        self._large_label.set_visible(showing)
        self._large_button.set_visible(showing)

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
