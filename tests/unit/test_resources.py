import re
import shutil
import subprocess

import pytest
from xedown import themes, vendoring

# Text-bearing blocks that must pick up their own base direction and
# start-relative alignment. `unicode-bidi` is not inherited, so this must be
# declared on each of these individually, not once on a shared ancestor.
_BIDI_TEXT_SELECTORS = (
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "blockquote",
    "td",
    "th",
)

# Code must be protected from the surrounding prose's detected direction,
# explicitly and unconditionally -- both the fenced-code and inline-code
# element.
_CODE_PROTECTED_SELECTORS = ("pre", "code")


def _rule_bodies_for(css, selector):
    """Declaration blocks of every CSS rule whose selector list includes
    exactly `selector` (e.g. the `td` in `th, td { ... }`)."""
    # Comments are stripped first: a `/* ... */` block sitting directly
    # before a rule (this stylesheet's convention) has no comma separating
    # its closing `*/` from the next selector, so without this a selector
    # like `pre` would only ever appear glued onto trailing comment text
    # (`*/\npre`) and never match on its own.
    without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    bodies = []
    for selector_group, body in re.findall(r"([^{}]+)\{([^{}]*)\}", without_comments):
        if selector in [part.strip() for part in selector_group.split(",")]:
            bodies.append(body)
    return bodies


@pytest.fixture
def preview_js():
    return vendoring.read_resource("preview.js")


@pytest.fixture
def preview_css():
    return vendoring.read_resource("preview.css")


@pytest.mark.parametrize("identifier", [t.identifier for t in themes.THEMES])
def test_every_theme_defines_a_light_and_a_dark_palette(identifier):
    css = vendoring.read_resource(themes.resolve(identifier).stylesheet)
    assert "--xedown-bg" in css
    assert "body.dark" in css


def test_stylesheet_caps_the_document_width(preview_css):
    assert "max-width" in preview_css


def test_stylesheet_lets_wide_content_scroll_itself(preview_css):
    assert "overflow-x" in preview_css


def test_stylesheet_defines_focus_visible_style(preview_css):
    # Rendered documents contain links; a keyboard user must be able to see
    # where focus is. This must not be suppressed anywhere in the sheet.
    assert ":focus-visible" in preview_css
    assert "outline: none" not in preview_css
    assert "outline:none" not in preview_css


def test_stylesheet_applies_bidi_plaintext_to_every_text_bearing_block(preview_css):
    # A document containing Arabic, Hebrew, or similar needs each of these
    # blocks to take its base direction from its own content rather than a
    # hardcoded left-to-right one, and to align using start/end rather than
    # left/right. `unicode-bidi` is not inherited, so a future rewrite that
    # collapses this back onto a single shared-ancestor rule would silently
    # stop protecting whichever selector it dropped -- this checks each one.
    for selector in _BIDI_TEXT_SELECTORS:
        bodies = _rule_bodies_for(preview_css, selector)
        assert any(
            "unicode-bidi" in body and "plaintext" in body for body in bodies
        ), f"{selector} must declare unicode-bidi: plaintext"
        assert any(
            "text-align" in body and "start" in body for body in bodies
        ), f"{selector} must declare text-align: start"


def test_stylesheet_no_longer_hardcodes_left_alignment_for_table_cells(preview_css):
    assert "text-align: left" not in preview_css
    assert "text-align:left" not in preview_css


def test_stylesheet_protects_code_with_explicit_ltr_isolation(preview_css):
    # Code must never follow the surrounding prose's detected direction: a
    # fenced block with Arabic comments must still read left-to-right, and
    # an inline `code` span inside an Arabic sentence must be isolated from
    # it in both directions. This is deliberately unconditional (not just
    # "not plaintext") -- `direction: ltr` plus `unicode-bidi: isolate` on
    # both selectors, checked independently so a future edit narrowing this
    # to only `pre` (missing inline `code`) is caught.
    for selector in _CODE_PROTECTED_SELECTORS:
        bodies = _rule_bodies_for(preview_css, selector)
        assert any(
            "direction" in body and "ltr" in body for body in bodies
        ), f"{selector} must declare direction: ltr"
        assert any(
            "unicode-bidi" in body and "isolate" in body for body in bodies
        ), f"{selector} must declare unicode-bidi: isolate"


def test_resources_reference_nothing_remote(preview_css, preview_js):
    for text in (preview_css, preview_js):
        assert "http://" not in text
        assert "https://" not in text
        assert "//cdn" not in text


def test_script_exposes_the_host_interface(preview_js):
    for symbol in (
        "replaceBody",
        "setScroll",
        "getScroll",
        "scrollToAnchor",
        "window.xedown",
    ):
        assert symbol in preview_js


def test_script_guards_unknown_highlight_languages(preview_js):
    # The bundle throws "Unknown language" for anything unregistered, so the
    # call must be guarded and fall back to an unhighlighted block.
    assert "getLanguage" in preview_js
    assert "try" in preview_js


def test_script_installs_image_error_handlers(preview_js):
    assert "error" in preview_js
    assert "img" in preview_js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_is_syntactically_valid():
    path = vendoring.RESOURCES_DIR / "preview.js"
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
