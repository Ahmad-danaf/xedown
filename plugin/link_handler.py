"""Decides what happens when a link inside the preview is activated."""


class LinkHandler:
    """Routes preview link clicks to xed, the browser, or an anchor jump."""

    def __init__(self, window, settings=None):
        self.window = window
        self.settings = settings

    def handle(self, uri: str) -> bool:
        """Return True when the click was handled and navigation should stop."""
        raise NotImplementedError

    def open_external(self, uri: str):
        """Hand an http(s) or mailto link to the desktop."""
        raise NotImplementedError

    def open_local(self, path: str):
        """Open a relative file link in a xed tab."""
        raise NotImplementedError

    def scroll_to_anchor(self, anchor: str):
        """Jump to an in-document heading anchor."""
        raise NotImplementedError
