"""Markdown to HTML conversion and the HTML document shell handed to the preview."""


class Renderer:
    """Converts markdown source into a standalone HTML page."""

    def __init__(self, settings=None):
        self.settings = settings

    def render(self, source: str, base_uri: str | None = None) -> str:
        """Return a full HTML document for the given markdown source."""
        raise NotImplementedError

    def render_fragment(self, source: str) -> str:
        """Return only the rendered body, without the HTML shell."""
        raise NotImplementedError

    def stylesheet(self) -> str:
        """Return the CSS applied to rendered output."""
        raise NotImplementedError
