"""Per-tab view state. Pure logic — no GTK imports belong in this module."""

import enum
import os

MARKDOWN_SUFFIXES = (".md", ".markdown")


class Mode(enum.Enum):
    SOURCE = "source"
    PREVIEW = "preview"


# The spelling settings.json and modes.json use. `Mode.SOURCE.value` is
# "source", which is xedown's own word for the mode; "markdown" is the
# user's, and it is the one that reaches a file a user opens.
MODE_SETTING_NAMES = {"preview": Mode.PREVIEW, "markdown": Mode.SOURCE}


def mode_from_setting(value):
    """The mode `value` names, or None when it names nothing.

    Never raises. Both files this reads for -- settings.json and modes.json --
    are hand-editable, and an unusable value has to fall back to a default
    rather than stop a tab from building.
    """
    if not isinstance(value, str):
        return None
    return MODE_SETTING_NAMES.get(value.strip().lower())


def setting_name(mode):
    """The name `mode` is stored under."""
    return "markdown" if mode is Mode.SOURCE else "preview"


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
