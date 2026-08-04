"""WebKit-backed preview widget that replaces the source view inside a tab."""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gtk, WebKit2  # noqa: E402


class PreviewView(Gtk.ScrolledWindow):
    """Scrollable web view showing the rendered document."""

    __gtype_name__ = "XedownPreviewView"

    def __init__(self, renderer, link_handler):
        super().__init__()
        self.renderer = renderer
        self.link_handler = link_handler
        self.webview = WebKit2.WebView()

    def load(self, source: str, base_uri: str | None = None):
        """Render markdown and display it."""
        raise NotImplementedError

    def refresh(self, source: str):
        """Re-render while keeping the current scroll position."""
        raise NotImplementedError

    def get_scroll_fraction(self) -> float:
        raise NotImplementedError

    def set_scroll_fraction(self, fraction: float):
        raise NotImplementedError
