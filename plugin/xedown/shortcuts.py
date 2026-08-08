"""xedown's four accelerators, and what a key press in the preview means.

Pure logic — no GTK imports belong in this module. `__init__.py` translates a
`GdkEventKey` into the primitives `route_key` takes, and builds its action
group by iterating `ACTIONS`; the same tuple is what the clash test reads, so
the menu and the check cannot disagree about what xedown binds.
"""

import enum
import re

TOGGLE = "XedownToggleAction"
PREVIEW_MODE = "XedownPreviewModeAction"
MARKDOWN_MODE = "XedownMarkdownModeAction"
REFRESH = "XedownRefreshAction"


class Action:
    """One entry in the View menu, and the key that reaches it."""

    def __init__(self, name, label, accelerator, tooltip):
        self.name = name
        self.label = label
        self.accelerator = accelerator
        self.tooltip = tooltip


ACTIONS = (
    # Name, label and accelerator unchanged from v0.1: an upgrading user's
    # menu entry and muscle memory must not move.
    Action(
        TOGGLE,
        "Toggle Markdown _Preview",
        "<Ctrl><Shift>M",
        "Switch between the rendered preview and the Markdown source",
    ),
    Action(
        PREVIEW_MODE,
        "Previe_w Mode",
        "<Ctrl><Shift>1",
        "Show the rendered preview",
    ),
    Action(
        MARKDOWN_MODE,
        "_Markdown Mode",
        "<Ctrl><Shift>2",
        "Show the Markdown source",
    ),
    Action(
        REFRESH,
        "_Refresh Preview",
        "<Ctrl><Shift>R",
        "Re-render the preview from the document as it is now",
    ),
)


class KeyAction(enum.Enum):
    """What a key press the host would otherwise have taken should do."""

    COPY = "copy"
    SELECT_ALL = "select-all"


# `Insert` is copy's legacy alias. It costs one key name and is only ever
# consulted while the preview is the visible surface. GDK names this key
# `Insert` (capitalised), but the GTK layer lowercases it before passing to
# route_key, which is why the tuple holds "insert" (lowercase).
COPY_KEYS = ("c", "insert")
SELECT_ALL_KEYS = ("a",)
HANDLED_KEYS = frozenset(COPY_KEYS + SELECT_ALL_KEYS)


def route_key(key_name, *, control_only, focus_is_editable, previewing):
    """What this key press means, or None to leave it to the host.

    The order of the guards is the design, cheapest first, and returning None
    for everything else is what makes "no key is ever stolen while the user is
    editing text" a property of this function's shape rather than of care
    taken elsewhere.

    `key_name` arrives already lowercased by the caller (the GTK layer applies
    `Gdk.keyval_to_lower` before calling this function).
    """
    if not control_only:
        return None
    if key_name in COPY_KEYS:
        action = KeyAction.COPY
    elif key_name in SELECT_ALL_KEYS:
        action = KeyAction.SELECT_ALL
    else:
        return None
    if focus_is_editable or not previewing:
        return None
    return action


_MODIFIER = re.compile(r"<([^<>]+)>")
_MODIFIER_ALIASES = {"primary": "control", "ctrl": "control", "mod1": "alt"}


def parse_accelerator(text):
    """`(frozenset(modifiers), key)` for an accelerator, however it is spelt.

    `<Primary>`, `<ctrl>` and `<Control>` are one modifier, modifier order
    carries no meaning, and a single-character key is compared case-blind,
    because `<Control>a` and `<Control>A` are the same accelerator. A named
    key keeps its spelling, which is what keeps `<Control>slash` and
    `<Control>s` distinct.
    """
    modifiers = set()
    for name in _MODIFIER.findall(text):
        name = name.strip().lower()
        modifiers.add(_MODIFIER_ALIASES.get(name, name))
    key = _MODIFIER.sub("", text).strip()
    if len(key) == 1:
        key = key.lower()
    return frozenset(modifiers), key
