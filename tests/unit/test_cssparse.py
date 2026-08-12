"""Tests for the CSS parser helper.

The parser is a guard that the parity test rests on. These tests pin its
documented behaviour: what the docstring in cssparse.py promises.
"""

from .cssparse import declarations


def test_grouped_selectors_are_split():
    """Grouped selectors contribute to all of them."""
    css = "pre, code { direction: ltr; }"
    out, duplicates = declarations(css)
    assert duplicates == []
    assert out["pre"]["direction"] == "ltr"
    assert out["code"]["direction"] == "ltr"


def test_at_rule_preludes_fold_into_the_key():
    """A selector inside @media does not merge with the same selector at top level."""
    css = ".xedown-document { padding: 1rem; } @media (max-width: 40rem) { .xedown-document { padding: 2rem; } }"
    out, duplicates = declarations(css)
    assert duplicates == []
    # They should be different keys due to the @media prefix
    assert out[".xedown-document"]["padding"] == "1rem"
    assert out["@media (max-width: 40rem) .xedown-document"]["padding"] == "2rem"


def test_comments_are_stripped():
    """Comments are removed, including those containing braces or colons."""
    css = ".xedown-document { /* { : } */ padding: 1rem; /* comment */ }"
    out, duplicates = declarations(css)
    assert duplicates == []
    assert out[".xedown-document"]["padding"] == "1rem"


def test_duplicate_at_top_level_is_reported():
    """Same selector, same property, twice at top level."""
    css = ".xedown-document { padding: 1rem; padding: 2rem; }"
    out, duplicates = declarations(css)
    assert (".xedown-document", "padding") in duplicates
    # The last value wins
    assert out[".xedown-document"]["padding"] == "2rem"


def test_duplicate_inside_at_rule_is_reported():
    """Same selector and property declared twice within the same at-rule block."""
    css = "@media (max-width: 40rem) { .xedown-document { padding: 1rem; padding: 2rem; } }"
    out, duplicates = declarations(css)
    assert ("@media (max-width: 40rem) .xedown-document", "padding") in duplicates
    assert out["@media (max-width: 40rem) .xedown-document"]["padding"] == "2rem"


def test_duplicate_across_at_rule_blocks_is_reported():
    """Same property declared for same selector across two separate at-rule blocks.

    This is the regression test for the at-rule merge bug: when two @media blocks
    declare the same property for the same selector, it must be detected and
    reported. This happens when two stylesheets are concatenated, as in _shipped().
    """
    base = (
        "@media (max-width: 40rem) { .xedown-document { padding: 2rem 1.1rem 4rem; } }"
    )
    theme = "@media (max-width: 40rem) { .xedown-document { padding: 999px; } }"
    out, duplicates = declarations(base + "\n" + theme)
    # The bug would make duplicates == [] and out only have the theme value
    assert ("@media (max-width: 40rem) .xedown-document", "padding") in duplicates
    # The last value (theme) wins
    assert out["@media (max-width: 40rem) .xedown-document"]["padding"] == "999px"


def test_duplicate_across_concatenated_sheets():
    """A property declared twice for the same selector across concatenated sheets."""
    sheet1 = ".xedown-document { color: black; }"
    sheet2 = ".xedown-document { color: white; }"
    out, duplicates = declarations(sheet1 + "\n" + sheet2)
    assert (".xedown-document", "color") in duplicates
    assert out[".xedown-document"]["color"] == "white"


def test_value_with_colon():
    """Values containing colons are handled correctly.

    The parser does not support semicolons inside values (per its documented
    scope), but colons are fine — they appear in URLs, gradients, etc.
    """
    css = ".gradient { background: linear-gradient(to: right, black, white); }"
    out, duplicates = declarations(css)
    assert duplicates == []
    # The value should be preserved, colons included
    assert out[".gradient"]["background"] == "linear-gradient(to: right, black, white)"


def test_final_declaration_without_trailing_semicolon():
    """A final declaration with no trailing semicolon is parsed."""
    css = ".xedown-document { padding: 1rem }"
    out, duplicates = declarations(css)
    assert duplicates == []
    assert out[".xedown-document"]["padding"] == "1rem"
