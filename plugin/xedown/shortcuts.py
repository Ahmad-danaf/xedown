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
SETTINGS = "XedownSettingsAction"


class Action:
    """One entry in the View menu, and the key that reaches it.

    `aliases` are accelerators that mean the same thing as `accelerator` but
    are never shown anywhere -- no menu label, no tooltip, nothing a user
    reads. They exist because GDK translates a physical key press through
    the keymap BEFORE comparing it against a registered accelerator: on a
    layout where Shift+1 produces "!" (US, UK, and most Latin QWERTY
    layouts), a real Ctrl+Shift+1 press never arrives as digit "1" with
    Shift held -- Shift was already spent producing "!" -- so
    `<Ctrl><Shift>1` can never match what GTK actually receives.
    `<Ctrl><Shift>exclam` is the spelling that does. The digit stays the
    documented, displayed primary (what a user reads and presses); the
    alias is what makes that press actually fire. On a layout where the
    digit arrives unshifted, the primary matches directly and the alias is
    simply never consulted. xed itself does the same thing, registering
    `<shift><control>question` alongside `<control>slash`. Do not delete an
    alias as redundant with its primary -- on the layouts where it matters,
    the alias is the ONLY one of the two that ever fires.
    """

    def __init__(
        self, name, label, accelerator, tooltip, aliases=(), requires_markdown=True
    ):
        self.name = name
        self.label = label
        self.accelerator = accelerator
        self.tooltip = tooltip
        self.aliases = aliases
        # False for the one entry that must stay usable on a file xedown does
        # not preview -- which is exactly when a user goes looking for the
        # settings that decide what it previews.
        self.requires_markdown = requires_markdown


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
        # See Action's docstring: this is the shifted-symbol spelling that
        # actually reaches GTK when Shift+1 produces "!".
        aliases=("<Ctrl><Shift>exclam",),
    ),
    Action(
        MARKDOWN_MODE,
        "_Markdown Mode",
        "<Ctrl><Shift>2",
        "Show the Markdown source",
        # See Action's docstring: this is the shifted-symbol spelling that
        # actually reaches GTK when Shift+2 produces "@".
        aliases=("<Ctrl><Shift>at",),
    ),
    Action(
        REFRESH,
        "_Refresh Preview",
        "<Ctrl><Shift>R",
        "Re-render the preview from the document as it is now",
    ),
    Action(
        SETTINGS,
        "Markdown Preview _Settings",
        # No accelerator on purpose. The other four are all about the preview
        # surface and are pressed while reading; this one is opened once in a
        # while, and the keyboard is already crowded.
        None,
        "Change how xedown previews Markdown",
        requires_markdown=False,
    ),
)


class KeyAction(enum.Enum):
    """What a key press the host would otherwise have taken should do."""

    COPY = "copy"
    SELECT_ALL = "select-all"
    FIND = "find"
    CLOSE_SEARCH = "close-search"


# Copy's legacy alias, consulted only while the preview is showing. GDK names
# the key `Insert`, but the GTK layer lowercases it before calling
# `route_key`, which is why this is lowercase.
COPY_KEYS = ("c", "insert")
SELECT_ALL_KEYS = ("a",)
FIND_KEYS = ("f",)
HANDLED_KEYS = frozenset(COPY_KEYS + SELECT_ALL_KEYS + FIND_KEYS)

# The one key xedown answers for with no modifier, and only while the preview
# is showing AND its own search bar is open -- a state the user asked for.
# `__init__.py` short-circuits on this set, so a key added here is one xedown
# starts inspecting on every unmodified press.
CLOSE_KEYS = ("escape",)
UNMODIFIED_KEYS = frozenset(CLOSE_KEYS)


def route_key(
    key_name,
    *,
    control_only,
    focus_is_editable,
    previewing,
    focus_in_preview_search=False,
    search_open=False,
    no_modifier=False,
):
    """What this key press means, or None to leave it to the host.

    The order of the guards is the design, cheapest first, and returning None
    for everything else is what makes "no key is ever stolen while the user is
    editing text" a property of this function's shape rather than of care
    taken elsewhere.

    `key_name` arrives already lowercased by the caller (the GTK layer applies
    `Gdk.keyval_to_lower` before calling this function).

    `focus_in_preview_search` is focus inside xedown's own search entry, which
    is a GtkEditable like any other -- so it is always accompanied by
    `focus_is_editable`, and it is what tells "our entry" apart from xed's
    find bar. `search_open` is the bar being visible in the tab being looked
    at.
    """
    if no_modifier:
        # The only unmodified key xedown ever answers for, and only in the one
        # state where the host has nothing better to do with it.
        if key_name not in CLOSE_KEYS:
            return None
        if not previewing or not search_open:
            return None
        if focus_is_editable and not focus_in_preview_search:
            return None
        return KeyAction.CLOSE_SEARCH
    if not control_only:
        return None
    if key_name in FIND_KEYS:
        # Find is the one Ctrl key that is still ours while focus sits in an
        # editable, because that editable can be our own search entry.
        if not previewing:
            return None
        if focus_is_editable and not focus_in_preview_search:
            return None
        return KeyAction.FIND
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
