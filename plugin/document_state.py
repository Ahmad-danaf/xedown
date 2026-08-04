"""Per-document state: current mode, scroll sync, and cached render input."""

import enum


class Mode(enum.Enum):
    SOURCE = "source"
    RENDERED = "rendered"


class DocumentState:
    """Tracks what a single tab is showing and where it was scrolled."""

    def __init__(self, document, mode: Mode = Mode.SOURCE):
        self.document = document
        self.mode = mode
        self.source_scroll = 0.0
        self.preview_scroll = 0.0

    def toggle(self) -> Mode:
        """Flip between source and rendered mode."""
        raise NotImplementedError

    def is_markdown(self) -> bool:
        """True when the document should be handled by xedown."""
        raise NotImplementedError


class DocumentStateRegistry:
    """Keeps one DocumentState per open document."""

    def __init__(self):
        self._states = {}

    def get(self, document) -> DocumentState:
        raise NotImplementedError

    def discard(self, document):
        raise NotImplementedError
