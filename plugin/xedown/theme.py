"""Resolves whether the preview should render dark, and tracks changes."""


def prefers_dark(theme_name, prefer_dark_flag):
    """Decide from GTK's settings whether the preview should be dark."""
    if prefer_dark_flag:
        return True
    return "dark" in (theme_name or "").lower()


class ThemeWatcher:
    """Watches GTK settings and reports light/dark changes.

    Imports GTK lazily so this module stays importable in CI.
    """

    def __init__(self):
        from gi.repository import Gtk

        self._settings = Gtk.Settings.get_default()
        self._handlers = []
        self._callback = None

    def current_dark(self):
        if self._settings is None:
            return False
        return prefers_dark(
            self._settings.get_property("gtk-theme-name"),
            self._settings.get_property("gtk-application-prefer-dark-theme"),
        )

    def connect(self, callback):
        """Call `callback(is_dark)` whenever the desktop theme changes."""
        if self._settings is None:
            return
        self._callback = callback
        for prop in ("gtk-theme-name", "gtk-application-prefer-dark-theme"):
            self._handlers.append(
                self._settings.connect("notify::" + prop, self._on_changed)
            )

    def _on_changed(self, *_args):
        if self._callback is not None:
            self._callback(self.current_dark())

    def disconnect(self):
        for handler in self._handlers:
            self._settings.disconnect(handler)
        self._handlers = []
        self._callback = None
