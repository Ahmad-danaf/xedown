"""The accessibility standard: the names, and what "passes" means.

Pure logic — no GTK imports belong in this module. That is what lets CI test
every rule below without a display, and it is why the rules take plain dicts
rather than ATK objects: the live audit converts the tree it walks into these
dicts and hands them over.

The names live here rather than in the widgets because they are needed twice.
A widget sets its accessible name *from* `NAMES`; the audit checks the live
tree *against* `NAMES`. Renaming a control in one place and not the other is
then a failing test instead of a regression nobody notices.

Nothing here claims anything about a screen reader. These rules are the
measurable half of the brief -- names, roles, focusability, order. Whether
Orca actually speaks a mode change is now an automated check
(`scripts/run-orca-tests.sh`), not a manual one.
"""

import re

from .document_state import Mode

# WCAG 1.4.11 (non-text contrast). Deliberately not the 4.5:1 used for text:
# a focus ring is a user-interface component, not something anybody reads.
FOCUS_RING_MINIMUM = 3.0

NAMES = {
    "mode_preview": "Preview",
    "mode_source": "Markdown source",
    "refresh": "Refresh the preview",
    "stale": "Preview is out of date",
    "remote_images_notice": "Remote images not loaded",
    "load_images": "Load remote images for this document",
    "large_document_notice": "Large document, preview not built",
    "build_preview": "Build the preview for this large document",
    "preview": "Markdown preview",
    "search_entry": "Find in preview",
    "search_case": "Match case",
    "search_next": "Next match",
    "search_previous": "Previous match",
    "search_close": "Close search",
    "search_status": "Match count",
    "info_bar_close": "Close",
    # The settings window. Every one of these is a visible label as well as
    # an accessible name: `prefs.Row.label` reads them straight out of here,
    # so the string a user sees and the string a reader speaks cannot drift.
    "prefs_default_mode": "Open Markdown files in",
    "prefs_remember_mode": "Remember the mode each file was left in",
    "prefs_theme": "Theme",
    "prefs_stylesheet": "Custom stylesheet",
    "prefs_stylesheet_browse": "Choose a stylesheet file",
    "prefs_content_width": "Content width",
    "prefs_text_size": "Text size",
    "prefs_text_direction": "Text direction",
    "prefs_copy_buttons": "Show a copy button on code blocks",
    "prefs_auto_refresh": "Update the preview automatically",
    "prefs_refresh_delay": "Wait before updating",
    "prefs_remote_images": "Load images from websites",
    "prefs_image_fallback": "When an image cannot be shown",
    "prefs_watch_external": "Notice changes made outside xed",
    "prefs_restore_defaults": "Restore defaults",
    "prefs_close": "Close",
}

# Which NAMES key announces each mode when a switch takes effect. Kept as a
# plain mapping over `Mode` -- not the widgets that emit it -- so which name
# gets chosen is unit-testable without a display; `controller.py:set_mode` is
# the host-bound half that decides *whether* to announce (focus elsewhere,
# not initial build) and `modebar.py:ModeBar.announce` is the half that
# actually reaches AT-SPI, neither of which CI can reach.
_MODE_ANNOUNCEMENT_NAMES = {
    Mode.PREVIEW: "mode_preview",
    Mode.SOURCE: "mode_source",
}


def mode_announcement_name(mode):
    """The `NAMES` key that announces `mode`, or None for anything else."""
    return _MODE_ANNOUNCEMENT_NAMES.get(mode)


# A name has to survive being read aloud with no screen in front of you, so
# it must contain something pronounceable. This is the rule that catches the
# bullet the stale indicator used to be: a screen reader reads "●" as
# "black circle", which is a description of a shape rather than of a meaning.
_PRONOUNCEABLE = re.compile(r"\w", re.UNICODE)

# Every ATK role has a non-empty `value_nick` -- `Atk.Role.UNKNOWN.value_nick`
# is `"unknown"`, not `""`, and `Atk.Role.INVALID.value_nick` is `"invalid"`.
# Checking only for an empty string meant "no accessible role" could only
# ever fire when `get_accessible()` itself returned None, which happens on
# effectively no live GTK widget -- these two are what a widget the toolkit
# could not classify, or an ATK object that has already gone bad, actually
# reports, and they mean the same thing an empty string would.
_NO_ROLE = frozenset({"", "unknown", "invalid"})

# A POSIX locale name: language, optional territory, optional codeset and
# optional modifier, both of which are dropped.
_LOCALE = re.compile(r"^([A-Za-z]{2,3})(?:[_-]([A-Za-z]{2}|[0-9]{3}))?(?:[.@].*)?$")

# Locales that name no language at all. `C.UTF-8` is included because its
# language is still C: a codeset does not make one.
_NO_LANGUAGE = frozenset({"c", "posix"})


def node(key, name, role, focusable=True, visible=True, index=0):
    """One accessible object, as the rules below want to see it.

    A constructor rather than a bare dict so the audit and the tests agree on
    the shape without repeating it, and so a missing field is a TypeError at
    the call site rather than a KeyError three rules later.
    """
    return {
        "key": key,
        "name": name,
        "role": role,
        "focusable": focusable,
        "visible": visible,
        "index": index,
    }


def check_node(item):
    """Every way one control can fall short, as readable sentences.

    Returns a list so a single control can fail more than one rule and report
    all of them at once -- an audit that stops at the first problem makes the
    second one somebody else's next run.
    """
    problems = []
    key = item["key"]
    name = (item["name"] or "").strip()
    focusable = item["focusable"]

    if focusable and not name:
        problems.append(f"{key}: focusable with no accessible name")
    elif focusable and not _PRONOUNCEABLE.search(name):
        problems.append(f"{key}: accessible name {name!r} has nothing a reader can say")

    # Deliberately NOT a rule: an accessible name equal to the widget's
    # tooltip. For an icon-only button the tooltip is exactly the right name,
    # and `searchbar.py` sets both to the same string on purpose. The defect
    # worth catching -- a control described only by a tooltip, with no
    # accessible name -- is the first rule above.

    # Deliberately NOT a rule: `focusable and not item["visible"]`. GTK
    # leaves `can_focus` True on a hidden widget, but its focus chain skips
    # invisible widgets regardless, so that combination is not a defect --
    # it is what a normal `set_no_show_all(True)` control looks like while
    # hidden. `focusable` here is meant to describe *effective*
    # focusability (the live audit ANDs `can_focus` with `get_visible()`
    # before building this dict), so a focusable-and-invisible node cannot
    # legitimately arise at all. This rule existed once, fired exactly
    # once -- against the refresh button, which is correct, deliberately
    # hidden code -- and was removed rather than the button changed.

    if focusable and (item["role"] or "").strip().lower() in _NO_ROLE:
        problems.append(f"{key}: no accessible role")

    return problems


def check_tree(items):
    """`check_node` over every control, plus the rules that need all of them.

    An empty tree is itself a failure. An audit that walked nothing and
    reported nothing looks exactly like an audit that passed, and the second
    is the more dangerous of the two to believe.
    """
    if not items:
        return ["the audit found no controls at all, which is not a pass"]

    problems = []
    for item in items:
        problems.extend(check_node(item))

    indices = [item["index"] for item in items]
    if len(set(indices)) != len(indices):
        problems.append("tab order: two controls share a position")
    elif indices != sorted(indices):
        problems.append(
            "tab order: focus order does not follow visual order "
            f"({[item['key'] for item in items]})"
        )
    return problems


def lang_tag(locale_name):
    """A BCP-47 language tag for `locale_name`, or None. Never raises.

    `en_GB.UTF-8` becomes `en-GB`; the codeset and any `@modifier` are
    dropped, because neither is part of a language tag.

    The modifier is dropped rather than resolved, and that is a real gap,
    not merely a simplification: BCP-47 gives some modifiers -- `latin`
    among them -- their own script subtag, so `sr_RS@latin` (Serbian Latin)
    loses information becoming `sr-RS`, which BCP-47 readers default to
    Cyrillic. The language itself is still right either way, which is
    what keeps this an acceptable trade under "absent beats wrong": a
    screen reader mispronouncing a script is a smaller failure than one
    reading the wrong language outright, but it is not a free pass, and no
    measurement has been taken of how a real reader handles it.

    None is returned for anything that names no language -- `C`, `POSIX`, an
    empty value, or something unparseable. That is deliberate: a missing
    `lang` leaves a screen reader on its own default voice, while a wrong one
    makes it read the document in a language it is not written in. Absent
    beats wrong.
    """
    if not locale_name or not isinstance(locale_name, str):
        return None
    text = locale_name.strip()
    if not text or text.split(".")[0].split("@")[0].lower() in _NO_LANGUAGE:
        return None
    match = _LOCALE.match(text)
    if match is None:
        return None
    language, territory = match.group(1), match.group(2)
    return f"{language.lower()}-{territory.upper()}" if territory else language.lower()
