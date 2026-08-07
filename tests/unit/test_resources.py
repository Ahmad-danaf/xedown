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
        "setMetrics",
        "window.xedown",
    ):
        assert symbol in preview_js


def test_the_metrics_setter_writes_the_two_variables_the_base_sheet_reads(preview_js):
    # Poked through the CSSOM rather than re-rendered: these are two custom
    # properties, so the page reflows without re-parsing the Markdown or
    # re-running highlight.js. The names must match preview.css exactly or
    # the poke lands on nothing and fails silently.
    assert "--xedown-content-width" in preview_js
    assert "--xedown-text-size" in preview_js
    assert "documentElement" in preview_js


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


OUR_STYLESHEETS = ("preview.css", "syntax.css") + tuple(
    theme.stylesheet for theme in themes.THEMES
)


@pytest.mark.parametrize("name", OUR_STYLESHEETS)
def test_our_stylesheets_reference_nothing_remote(name):
    # The vendored highlight stylesheets are deliberately excluded: they are
    # the vendoring script's output and carry a project URL in their licence
    # header, exactly as the highlight bundle does.
    css = vendoring.read_resource(name)
    assert "http://" not in css
    assert "https://" not in css
    assert "@import" not in css
    for reference in re.findall(r"url\(\s*['\"]?([^)'\"]*)", css):
        assert reference.startswith("data:"), f"{name} loads {reference!r}"


@pytest.mark.parametrize("name", OUR_STYLESHEETS)
def test_our_stylesheets_never_suppress_the_focus_outline(name):
    css = vendoring.read_resource(name)
    assert "outline: none" not in css
    assert "outline:none" not in css


@pytest.mark.parametrize("name", OUR_STYLESHEETS)
def test_every_font_stack_ends_in_a_generic_family(name):
    # Themes may only use fonts already on the machine, so every stack needs
    # a family the system is guaranteed to resolve.
    generics = ("serif", "sans-serif", "monospace", "cursive", "fantasy")
    css = vendoring.read_resource(name)
    for stack in re.findall(r"font-family\s*:([^;}]*)", css):
        last = stack.split(",")[-1].strip().strip("\"'")
        assert last in generics, f"{name}: {stack.strip()!r} ends in {last!r}"


@pytest.mark.parametrize("name", OUR_STYLESHEETS)
def test_no_stylesheet_pins_a_font_size_in_pixels(name):
    # --xedown-text-size lands on the root font size, so every em and rem in
    # every sheet follows the user's text size and the whole document scales
    # together. One `font-size: 13px` anywhere would pin a single element
    # while everything around it moved, and the hierarchy would come apart at
    # the ends of the range. Border widths and corner radii in px are
    # deliberately untouched: a 1px rule should stay 1px at every text size.
    css = vendoring.read_resource(name)
    offenders = [
        declaration.strip()
        for declaration in re.findall(r"font-size\s*:[^;}]*", css)
        if re.search(r"\d\s*px", declaration)
    ]
    assert offenders == [], f"{name}: {offenders}"


def test_the_notice_bar_is_coloured_only_from_the_error_tokens(preview_css):
    # One rule in the base sheet, driven by tokens every theme declares, so
    # the notice works in all four themes and both appearances without four
    # copies. Its contrast is already gated: error-fg on error-bg is a row in
    # test_contrast.py's table.
    bodies = _rule_bodies_for(preview_css, ".xedown-notice")
    assert bodies, "preview.css must style .xedown-notice"
    body = bodies[0]
    for token in (
        "--xedown-error-fg",
        "--xedown-error-bg",
        "--xedown-error-border",
    ):
        assert token in body, f".xedown-notice must use {token}"
    assert "#" not in body, "the notice must not hardcode a colour"


def test_the_notice_bar_cannot_push_the_page_sideways(preview_css):
    # It carries a filesystem path, which can be long and has no spaces.
    bodies = _rule_bodies_for(preview_css, ".xedown-notice")
    assert any("overflow-wrap" in body for body in bodies)


def test_task_list_checkboxes_are_drawn_rather_than_native(preview_css):
    bodies = _rule_bodies_for(preview_css, 'li.task-list-item > input[type="checkbox"]')
    assert any("appearance" in body and "none" in body for body in bodies)
    # A disabled control is dimmed and given a "no entry" cursor. These are
    # read-only on purpose, not unavailable, and must not look broken.
    assert any("opacity: 1" in body for body in bodies)
    assert any("cursor: default" in body for body in bodies)


def test_a_checked_task_item_is_distinguishable_without_the_tick(preview_css):
    # The tick is drawn by a pseudo-element on a replaced element, which is
    # the least certain rule in this stylesheet. The fill is what actually
    # carries the state, so it must be declared independently of the tick.
    bodies = _rule_bodies_for(
        preview_css, 'li.task-list-item > input[type="checkbox"]:checked'
    )
    assert bodies, "no :checked rule"
    assert any("background" in body for body in bodies)


def test_no_checkbox_colour_is_hardcoded(preview_css):
    for selector in (
        'li.task-list-item > input[type="checkbox"]',
        'li.task-list-item > input[type="checkbox"]:checked',
    ):
        for body in _rule_bodies_for(preview_css, selector):
            assert "#" not in body, f"{selector} declares a colour literal"


def test_a_wide_table_overflows_rather_than_compresses(preview_css):
    bodies = _rule_bodies_for(preview_css, "table")
    # width: 100% would cap the table at the container and force the
    # browser to squeeze columns instead of letting the wrapper scroll.
    assert any("width: auto" in body for body in bodies)
    assert any("min-width: 100%" in body for body in bodies)


def test_table_cells_have_a_width_floor(preview_css):
    for selector in ("th", "td"):
        assert any(
            "min-width" in body for body in _rule_bodies_for(preview_css, selector)
        ), f"{selector} has no minimum width"


def test_the_table_edge_cue_is_an_inset_shadow_from_the_theme(preview_css):
    # Inset shadows paint on the container's own box and do not scroll with
    # its content, which is what makes this an edge marker rather than a
    # stripe that slides out of view.
    for selector in (
        ".xedown-table-scroll.xedown-more-left",
        ".xedown-table-scroll.xedown-more-right",
    ):
        bodies = _rule_bodies_for(preview_css, selector)
        assert bodies, f"no rule for {selector}"
        for body in bodies:
            assert "inset" in body
            assert "var(--xedown-shadow)" in body


def test_the_script_keeps_the_table_cue_in_step_with_scrolling(preview_js):
    assert "xedown-more-left" in preview_js
    assert "xedown-more-right" in preview_js
    assert "scrollLeft" in preview_js
    assert "ResizeObserver" in preview_js


def test_a_tall_image_is_capped_without_losing_its_ratio(preview_css):
    bodies = _rule_bodies_for(preview_css, "img:not([width]):not([height])")
    assert bodies, "no cap for images the author did not size"
    for body in bodies:
        assert "max-height" in body
        # Both dimensions auto is what makes the browser's own constraint
        # algorithm shrink the image proportionally. Capping height while
        # width stays fixed is exactly how an aspect ratio gets broken.
        assert "width: auto" in body


def test_the_cap_leaves_an_author_sized_image_alone(preview_css):
    # The selector, not a second rule, is what excludes them: an author who
    # wrote width= or height= already said what size they wanted.
    assert ":not([width]):not([height])" in preview_css


def test_images_are_never_enlarged(preview_css):
    # img:not([width]):not([height]) is the rule that could plausibly
    # acquire a min-height (it already caps max-height for tall images), so
    # it needs the same check as the bare `img` selector.
    for selector in ("img", "img:not([width]):not([height])"):
        for body in _rule_bodies_for(preview_css, selector):
            assert "min-width" not in body
            assert "min-height" not in body


def test_alt_text_shown_in_place_of_an_image_is_visibly_not_the_document(preview_css):
    bodies = _rule_bodies_for(preview_css, ".xedown-image-alt")
    assert bodies, "no rule for alt-only placeholders"
    for body in bodies:
        assert "italic" in body
        assert "var(--xedown-muted)" in body


def test_the_script_exposes_the_two_new_host_entry_points(preview_js):
    for symbol in ("setConfig", "copyResult", "xedownConfig"):
        assert symbol in preview_js


def test_the_copy_button_can_never_join_a_selection(preview_css):
    bodies = _rule_bodies_for(preview_css, ".xedown-copy")
    assert bodies, "no rule for the copy button"
    assert any("user-select: none" in body for body in bodies)


def test_showing_the_copy_button_cannot_move_the_code_block(preview_css):
    # Absolutely positioned inside a relatively positioned wrapper: it is
    # out of flow, so revealing it changes no layout at all.
    assert any(
        "position: relative" in body
        for body in _rule_bodies_for(preview_css, ".xedown-code-block")
    )
    assert any(
        "position: absolute" in body
        for body in _rule_bodies_for(preview_css, ".xedown-copy")
    )


def test_the_copy_button_is_reachable_by_keyboard(preview_css):
    # opacity, not display or visibility: those would take it out of the tab
    # order entirely. The focus rule is what makes it visible once reached.
    assert ".xedown-copy:focus-visible" in preview_css
    assert any(
        "opacity: 0" in body for body in _rule_bodies_for(preview_css, ".xedown-copy")
    )


def test_the_copy_button_reports_a_failure_rather_than_pretending(preview_js):
    assert "Copy failed" in preview_js
    assert "Copied" in preview_js
    # The host may be absent entirely -- post() no-ops then -- so a click
    # with no answer has to resolve by itself.
    assert "setTimeout" in preview_js


def test_the_copied_text_is_captured_before_highlighting(preview_js):
    # highlight() rewrites each block's innerHTML, so capturing after it
    # would copy whatever the highlighter left behind rather than what the
    # author wrote. What matters is the order of the CALLS inside
    # decorate() -- not the order the functions happen to be defined in,
    # which is what a naive search of the whole file measures instead.
    body = preview_js[preview_js.index("function decorate(") :]
    assert body.index("captureSources(root)") < body.index("highlight(root)")
