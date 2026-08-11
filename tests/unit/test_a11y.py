"""The accessibility standard, written down once so two places can share it.

`a11y.NAMES` is what the widgets set themselves to and what the live audit
checks them against, so a control renamed in one place and not the other is a
failing test rather than a silent regression.
"""

import pathlib
import re

import pytest
from xedown import a11y


def node(**overrides):
    """A passing node, with only what a test cares about overridden."""
    base = {
        "key": "mode_preview",
        "name": "Preview",
        "role": "toggle button",
        "focusable": True,
        "visible": True,
        "index": 0,
    }
    base.update(overrides)
    return base


# --- the names are a single source of truth ----------------------------


def test_every_name_is_a_non_empty_string():
    assert a11y.NAMES
    for key, name in a11y.NAMES.items():
        assert isinstance(name, str) and name.strip(), key


def test_the_controls_this_brief_names_are_all_present():
    for key in (
        "mode_preview",
        "mode_source",
        "refresh",
        "stale",
        "preview",
    ):
        assert key in a11y.NAMES, key


def test_the_webview_name_is_the_mode_announcement():
    """Focus lands here on every switch, so this name IS what gets read."""
    assert a11y.NAMES["preview"] == "Markdown preview"


def test_the_stale_indicator_says_what_it_means():
    assert a11y.NAMES["stale"] == "Preview is out of date"


# --- check_node -------------------------------------------------------


def test_a_well_formed_node_has_no_complaints():
    assert a11y.check_node(node()) == []


def test_a_focusable_node_without_a_name_is_reported():
    problems = a11y.check_node(node(name=""))
    assert len(problems) == 1
    assert "mode_preview" in problems[0]


def test_whitespace_is_not_a_name():
    assert a11y.check_node(node(name="   ")) != []


def test_a_symbol_is_not_a_name():
    """The bullet the stale indicator used to carry, read as 'black circle'."""
    assert a11y.check_node(node(name="●")) != []


def test_punctuation_alone_is_not_a_name():
    assert a11y.check_node(node(name="...")) != []


def test_a_name_matching_a_tooltip_is_not_a_defect():
    """An icon-only button's tooltip IS its right name.

    `searchbar.py`'s `_icon_button` sets both to the same string on purpose,
    and that is correct practice rather than an oversight. An earlier draft of
    this module reported it, which would have condemned working code; the
    defect it was aiming at -- a control described only by a tooltip and
    carrying no accessible name at all -- is caught by the rule above.
    """
    assert a11y.check_node(node(name="Match case")) == []


def test_an_unfocusable_node_needs_no_name():
    """A decorative label is fine unnamed, so long as nothing can focus it."""
    assert a11y.check_node(node(name="", focusable=False)) == []


def test_an_invisible_widget_is_not_reported_for_being_focusable():
    """GTK leaves `can_focus` True on hidden widgets and skips them anyway.

    The refresh button is hidden whenever auto-refresh is on, and the live
    audit reported it until this rule was removed -- a false finding against
    correct code, which is the more damaging direction for a check whose
    output becomes somebody's task list.

    This is the actual claim: `focusable=True` while `visible=False` is the
    exact combination the removed rule used to flag, and only this case
    pins its absence. The other two combinations (both consistent, both
    inconsistent) pass whether or not the rule exists, so neither says
    anything about whether it has really been removed.
    """
    assert a11y.check_node(node(focusable=True, visible=False)) == []


def test_a_node_with_no_role_is_reported():
    assert a11y.check_node(node(role="")) != []


def test_atk_unknown_role_is_treated_as_no_role():
    """`Atk.Role.UNKNOWN.value_nick` is `"unknown"`, not `""`.

    Without this, the "no accessible role" rule could only ever fire when
    `get_accessible()` itself returned None -- which is not a live GTK
    widget's behaviour -- because every other role, including the one ATK
    hands back for a widget it cannot classify, has a non-empty nick.
    """
    assert a11y.check_node(node(role="unknown")) != []


def test_atk_invalid_role_is_treated_as_no_role():
    """`Atk.Role.INVALID.value_nick` is `"invalid"`: an ATK object gone bad."""
    assert a11y.check_node(node(role="invalid")) != []


def test_role_case_is_not_what_makes_unknown_and_invalid_special():
    assert a11y.check_node(node(role="UNKNOWN")) != []
    assert a11y.check_node(node(role="Invalid")) != []


# --- check_tree -------------------------------------------------------


def test_an_empty_tree_is_reported_rather_than_passing_silently():
    """A tree that found nothing is a broken audit, not a clean one."""
    assert a11y.check_tree([]) != []


def test_a_well_formed_tree_has_no_complaints():
    assert a11y.check_tree([node(index=0), node(key="refresh", index=1)]) == []


def test_tree_problems_accumulate_across_nodes():
    problems = a11y.check_tree([node(name=""), node(key="refresh", name="", index=1)])
    assert len(problems) == 2


def test_tab_order_out_of_visual_order_is_reported():
    problems = a11y.check_tree(
        [node(key="refresh", index=1), node(key="mode_preview", index=0)]
    )
    assert any("order" in problem for problem in problems)


def test_duplicate_indices_are_reported():
    problems = a11y.check_tree([node(index=0), node(key="refresh", index=0)])
    assert any("order" in problem for problem in problems)


# --- lang_tag ---------------------------------------------------------


@pytest.mark.parametrize(
    ("locale_name", "expected"),
    [
        ("en_GB.UTF-8", "en-GB"),
        ("en_GB", "en-GB"),
        ("en", "en"),
        ("ar_EG.UTF-8", "ar-EG"),
        ("pt_BR@latin", "pt-BR"),
        ("zh_CN.GB2312", "zh-CN"),
    ],
)
def test_a_posix_locale_becomes_a_bcp47_tag(locale_name, expected):
    assert a11y.lang_tag(locale_name) == expected


@pytest.mark.parametrize("locale_name", ["C", "POSIX", "", "   ", None, "C.UTF-8"])
def test_an_unusable_locale_gives_no_tag(locale_name):
    """An absent lang is better than a wrong one: the reader keeps its default."""
    assert a11y.lang_tag(locale_name) is None


def test_a_malformed_locale_gives_no_tag():
    assert a11y.lang_tag("!!!") is None
    assert a11y.lang_tag("123_45") is None


def test_the_focus_ring_minimum_is_the_non_text_threshold():
    """WCAG 1.4.11, deliberately not the 4.5:1 used for text."""
    assert a11y.FOCUS_RING_MINIMUM == 3.0


# --- every accessible name set in the host modules comes from NAMES ----
#
# `modebar.py`, `searchbar.py`, `preview.py` and `controller.py` all import
# `gi` at module level, which is what makes them unreachable by every other
# test in this file: CI has no display and no typelibs, so nothing here can
# construct a `ModeBar` or a `SearchBar` and ask it what name it actually
# set. `searchbar.py`'s `self._name(self._status, "Match count")` shipped
# on this branch and read exactly as plausible as
# `self._name(self._status, a11y.NAMES["search_status"])` -- both compile,
# both run, and only one keeps the promise `NAMES` exists to make. Reading
# the files as text is the one thing CI *can* still do to catch the next
# one of these before a live probe run has to.

_PLUGIN_DIR = (
    pathlib.Path(__file__).resolve().parent.parent.parent / "plugin" / "xedown"
)

_HOST_MODULES_SETTING_NAMES = (
    "modebar.py",
    "searchbar.py",
    "preview.py",
    "controller.py",
)

# `(?<![\w])` keeps this from matching inside `new_from_icon_name(` (its own
# `_name(` is immediately preceded by the word character 'n') or any other
# identifier that merely ends in `_name` -- only a call that is *exactly*
# `_name(...)` or `set_name(...)` counts.
_NAME_CALL = re.compile(r"(?<!\w)(?:set_name|_name)\(([^)]*)\)")


def _name_call_sites(path):
    """`(lineno, line, name_argument)` for every `set_name(`/`_name(` call.

    The `_name` helper's own `def` line is excluded: it is the place the
    forwarded `name` parameter is declared, not a place an accessible name
    is chosen, and its own body (`accessible.set_name(name)`) is a bare
    identifier -- never a literal -- so it needs no exclusion of its own.
    """
    sites = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("def _name("):
            continue
        for match in _NAME_CALL.finditer(line):
            args = [part.strip() for part in match.group(1).split(",")]
            sites.append((lineno, line.strip(), args[-1]))
    return sites


def test_every_accessible_name_in_the_host_modules_comes_from_names():
    all_sites = []
    violations = []
    for filename in _HOST_MODULES_SETTING_NAMES:
        for lineno, line, name_argument in _name_call_sites(_PLUGIN_DIR / filename):
            all_sites.append((filename, lineno))
            if name_argument.startswith(('"', "'")):
                violations.append(f"{filename}:{lineno}: {line!r}")
    # An audit that found nothing is not a pass -- the same principle
    # `a11y.check_tree` enforces for the live probe. If this ever drops to
    # zero, the scan itself broke (a moved file, a renamed helper), not the
    # code it is meant to be watching.
    assert len(all_sites) >= 8, f"only found {len(all_sites)} call sites: {all_sites!r}"
    assert not violations, (
        "accessible name set to a string literal instead of an "
        "a11y.NAMES[...] entry:\n" + "\n".join(violations)
    )
