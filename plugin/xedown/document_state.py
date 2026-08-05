"""Per-tab view state. Pure logic — no GTK imports belong in this module."""

import enum
import os

MARKDOWN_SUFFIXES = (".md", ".markdown")


class Mode(enum.Enum):
    SOURCE = "source"
    PREVIEW = "preview"


def is_markdown_path(path):
    """True when a path should be handled by xedown, matched case-insensitively."""
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in MARKDOWN_SUFFIXES


class DocumentState:
    """What one tab is showing, and where each mode was scrolled to."""

    def __init__(self, mode=Mode.PREVIEW):
        self.mode = mode
        self.preview_scroll = 0.0
        self.source_scroll = 0.0
        self.preview_stale = True

    def toggle(self):
        self.mode = Mode.SOURCE if self.mode is Mode.PREVIEW else Mode.PREVIEW
        return self.mode

    def store_scroll(self, mode, value):
        if mode is Mode.PREVIEW:
            self.preview_scroll = value
        else:
            self.source_scroll = value

    def scroll_for(self, mode):
        return self.preview_scroll if mode is Mode.PREVIEW else self.source_scroll
