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
        "load-images-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
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

        # Packed from the trailing edge inward: each successive pack_end call
        # lands further inward than the one before it, so the button sits at
        # the very end of the bar and whatever is packed next sits just
        # inside it. Both are set_no_show_all so a show_all() on the tab
        # cannot reveal either -- the same mitigation the controller applies
        # to the source frame and the WebView, for the same reason.
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

        # Packed immediately after the refresh button -- deliberately, and
        # before the chip below -- so it stays adjacent to the button it
        # describes. The dot means "the preview is out of date, refresh it";
        # set_stale rewrites the refresh button's tooltip in the same call,
        # and the dot would be close to meaningless sitting apart from it.
        self._stale_dot = Gtk.Label(label="●")
        self._stale_dot.get_style_context().add_class("xedown-stale-dot")
        self._stale_dot.set_no_show_all(True)
        # Without a name this reads as "black circle" -- a description of a
        # shape rather than of what it means. It appears and disappears, so
        # the name is what makes its appearing mean something.
        self._name(self._stale_dot, a11y.NAMES["stale"])
        self.pack_end(self._stale_dot, False, False, 0)

        # Packed inward of the dot, so it reads left to right as
        # "<count> remote images [Load]" ahead of the refresh/stale pair.
        # Blocked is the safe default, so this is a quiet chip rather than a
        # warning bar: a document with one badge image should not raise an
        # alarm every time it is opened. `set_no_show_all` for the same
        # reason the refresh button has it.
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

        Checked by the controller before a mode switch takes effect: if the
        user tabbed to a mode button and activated it, Orca already
        announces the toggle's own state change ("Preview toggle button
        pressed."), and an `announce()` on top of that would make a focused
        user hear the mode twice. Deliberately narrower than "any focusable
        control in this bar": the refresh button is a plain `Gtk.Button`
        with no toggle state of its own, so a mode switch with *it* focused
        (auto-refresh off, correcting a stale preview via Ctrl+Shift+M with
        focus still on Refresh) gets no state-change speech from Orca either
        -- including it here would suppress the one announcement that does
        exist, leaving that switch completely silent, exactly the defect
        this mechanism exists to remove. The stale dot is not a candidate at
        all; it is a `Gtk.Label`, never focusable.

        Named `_inside`, not `has_focus`, on purpose: `Gtk.Widget.has_focus()`
        (called below, per button) means something narrower than the plain
        name suggests -- true only when the *toplevel window* currently
        holds real X11 input focus, not merely when a widget is the window's
        own focus widget. `tests/integration/xedown_probe/__init__.py`
        calls a check built on that "flaky by construction" for exactly this
        reason and prefers `is_focus()` for its own assertions, because a
        probe step can run with the window unfocused. That risk doesn't
        apply here: a mode switch only ever happens in reaction to a
        keystroke that just landed on this window, so real input focus is
        guaranteed at the moment `set_mode` reads this. But a name that
        could be mistaken for the stricter, well-known GTK method would be
        an easy trap for the next caller regardless of whether today's use
        is safe.
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
