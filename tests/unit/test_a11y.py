"""The accessibility standard, written down once so two places can share it.

`a11y.NAMES` is what the widgets set themselves to and what the live audit
checks them against, so a control renamed in one place and not the other is a
failing test rather than a silent regression.
"""

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


def test_a_focusable_but_invisible_node_is_reported():
    problems = a11y.check_node(node(visible=False))
    assert len(problems) == 1
    assert "invisible" in problems[0]


def test_an_unfocusable_invisible_node_is_fine():
    assert a11y.check_node(node(focusable=False, visible=False)) == []


def test_a_node_with_no_role_is_reported():
    assert a11y.check_node(node(role="")) != []


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
