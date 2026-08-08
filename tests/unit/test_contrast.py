"""Every theme is legible, in both appearances. A hard gate, not a preference.

The thresholds follow the brief's own list of what must meet AA — body text,
links, muted text, code text, controls and focus indicators. Borders are not
on that list and are not checked: v0.1's 1px separators sit at 1.4:1 and are
not being redesigned under a rule that does not cover them.

Focus rings are checked at 3:1 because that is WCAG 1.4.11's threshold for
non-text contrast; holding a focus indicator to a text threshold would be
inventing a requirement.

Syntax tokens are checked at 4.5:1 for the themes xedown authors and at 3:1
for `repository`, whose palette is the vendored highlight.js one and is
pinned by "identical to v0.1". Its worst cases are 3.28:1 (light, built-in
names and symbols) and 3.27:1 (dark, section headings). Changing that means
changing what an upgrading user sees — a decision for a human, recorded in
docs/themes.md rather than quietly made here.

Selected text is held to 4.5:1 against its own highlight, like every other
text pair here. The highlight against the page is held to 1.5:1, which is a
floor chosen for "clearly visible" and deliberately not a WCAG claim: 1.4.11's
3:1 would force a highlight far louder than any real one — GTK's own and every
browser's sit near 1.5 — and inventing a requirement is exactly what the rest
of this file refuses to do.
"""

import re

import pytest
from xedown import themes, vendoring

from . import wcag
from .cssparse import declarations

APPEARANCES = ("light", "dark")

# (foreground token, background token, minimum ratio)
SEMANTIC_PAIRS = (
    ("--xedown-fg", "--xedown-bg", 4.5),
    ("--xedown-muted", "--xedown-bg", 4.5),
    ("--xedown-link", "--xedown-bg", 4.5),
    ("--xedown-muted", "--xedown-code-bg", 4.5),
    ("--xedown-error-fg", "--xedown-error-bg", 4.5),
    ("--xedown-focus-ring", "--xedown-bg", 3.0),
    ("--xedown-selection-fg", "--xedown-selection-bg", 4.5),
)

# Checked only where a theme declares them.
OPTIONAL_PAIRS = (
    ("--xedown-heading-fg", "--xedown-bg", 4.5),
    ("--xedown-code-fg", "--xedown-code-bg", 4.5),
)

SYNTAX_FOREGROUNDS = (
    "--xedown-syn-comment",
    "--xedown-syn-keyword",
    "--xedown-syn-string",
    "--xedown-syn-number",
    "--xedown-syn-function",
    "--xedown-syn-type",
    "--xedown-syn-variable",
    "--xedown-syn-meta",
)

SYNTAX_PAIRS = (
    ("--xedown-syn-addition-fg", "--xedown-syn-addition-bg"),
    ("--xedown-syn-deletion-fg", "--xedown-syn-deletion-bg"),
)

VENDORED_SYNTAX_FLOOR = 3.0
AUTHORED_SYNTAX_MINIMUM = 4.5

_HEX = re.compile(r"^#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$")


def palette(theme, appearance):
    """A theme's effective colour tokens for one appearance.

    Dark starts from the light block, so a theme may declare a token once
    when both appearances share it. Non-colour tokens are filtered out.
    """
    parsed, _ = declarations(vendoring.read_resource(theme.stylesheet))
    tokens = dict(parsed.get(":root", {}))
    if appearance == "dark":
        tokens.update(parsed.get("body.dark", {}))
    return {name: value for name, value in tokens.items() if _HEX.match(value)}


def vendored_token_colours(theme, appearance):
    """Every `.hljs-*` colour in a theme's vendored syntax stylesheet."""
    css = vendoring.read_resource(theme.syntax_stylesheet(appearance == "dark"))
    found = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        match = re.search(r"(?:^|;)\s*color\s*:\s*(#[0-9a-fA-F]{3,6})", body)
        if not match:
            continue
        for selector in selectors.split(","):
            selector = selector.strip()
            if selector.startswith(".hljs-"):
                found[selector] = match.group(1)
    return found


def cases():
    for theme in themes.THEMES:
        for appearance in APPEARANCES:
            yield pytest.param(theme, appearance, id=f"{theme.identifier}-{appearance}")


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_semantic_colours_meet_their_threshold(theme, appearance):
    tokens = palette(theme, appearance)
    for foreground, background, minimum in SEMANTIC_PAIRS:
        ratio = wcag.contrast_ratio(tokens[foreground], tokens[background])
        assert ratio >= minimum, (
            f"{theme.identifier}/{appearance}: {foreground} on {background} "
            f"is {ratio:.2f}:1, below {minimum}:1"
        )


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_code_text_meets_aa_against_the_code_surface(theme, appearance):
    # A theme may colour code separately; where it does not, body text is
    # what sits on the code surface.
    tokens = palette(theme, appearance)
    foreground = tokens.get("--xedown-code-fg", tokens["--xedown-fg"])
    ratio = wcag.contrast_ratio(foreground, tokens["--xedown-code-bg"])
    assert ratio >= 4.5, f"{theme.identifier}/{appearance}: {ratio:.2f}:1"


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_optional_tokens_meet_their_threshold_where_declared(theme, appearance):
    tokens = palette(theme, appearance)
    for foreground, background, minimum in OPTIONAL_PAIRS:
        if foreground not in tokens:
            continue
        ratio = wcag.contrast_ratio(tokens[foreground], tokens[background])
        assert (
            ratio >= minimum
        ), f"{theme.identifier}/{appearance}: {foreground} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_authored_syntax_tokens_meet_aa(theme, appearance):
    if theme.syntax_stylesheet(appearance == "dark") != themes.SHARED_SYNTAX_STYLESHEET:
        pytest.skip(f"{theme.identifier} uses a vendored syntax stylesheet")
    tokens = palette(theme, appearance)
    for name in SYNTAX_FOREGROUNDS:
        ratio = wcag.contrast_ratio(tokens[name], tokens["--xedown-code-bg"])
        assert (
            ratio >= AUTHORED_SYNTAX_MINIMUM
        ), f"{theme.identifier}/{appearance}: {name} is {ratio:.2f}:1"
    for foreground, background in SYNTAX_PAIRS:
        ratio = wcag.contrast_ratio(tokens[foreground], tokens[background])
        assert (
            ratio >= AUTHORED_SYNTAX_MINIMUM
        ), f"{theme.identifier}/{appearance}: {foreground} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_vendored_syntax_palettes_clear_the_readability_floor(theme, appearance):
    if theme.syntax_stylesheet(appearance == "dark") == themes.SHARED_SYNTAX_STYLESHEET:
        pytest.skip(f"{theme.identifier} authors its own syntax palette")
    sheet = theme.syntax_stylesheet(appearance == "dark")
    tokens = vendored_token_colours(theme, appearance)
    # This is the only check covering the vendored palette's 3:1 floor, and
    # `vendored_token_colours` parses a minified third-party stylesheet with a
    # regex. update-vendor.sh regenerates that file from upstream, so a future
    # refresh could reshape it into something the regex cannot read -- at which
    # point this test would pass having measured nothing. Fail loudly instead.
    assert tokens, f"no .hljs- colours parsed out of {sheet}"
    code_background = palette(theme, appearance)["--xedown-code-bg"]
    for selector, colour in tokens.items():
        ratio = wcag.contrast_ratio(colour, code_background)
        assert ratio >= VENDORED_SYNTAX_FLOOR, (
            f"{theme.identifier}/{appearance}: {selector} ({colour}) is "
            f"{ratio:.2f}:1, below the {VENDORED_SYNTAX_FLOOR}:1 floor"
        )


SELECTION_AGAINST_PAGE = 1.5


@pytest.mark.parametrize("theme,appearance", list(cases()))
def test_the_selection_highlight_is_visible_against_the_page(theme, appearance):
    tokens = palette(theme, appearance)
    ratio = wcag.contrast_ratio(tokens["--xedown-selection-bg"], tokens["--xedown-bg"])
    assert ratio >= SELECTION_AGAINST_PAGE, (
        f"{theme.identifier} {appearance}: selection sits at {ratio:.2f}:1 "
        f"against the page"
    )
