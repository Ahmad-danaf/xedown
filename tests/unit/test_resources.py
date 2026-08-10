import re
import shutil
import subprocess

import pytest
from xedown import themes, vendoring

from .cssparse import declarations

# Text-bearing blocks that must pick up their own base direction and
# start-relative alignment. `unicode-bidi` is not inherited, so this must be
# declared on each of these individually, not once on a shared ancestor.
#
# `li` is deliberately absent -- see
# test_a_list_item_takes_its_direction_from_the_document_not_its_own_content.
_BIDI_TEXT_SELECTORS = (
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
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


def test_a_list_item_takes_its_direction_from_the_document_not_its_own_content(
    preview_css,
):
    # `li` is the one text-bearing block that must NOT get
    # `unicode-bidi: plaintext`, and this is a rendering constraint rather
    # than a stylistic choice.
    #
    # Under `plaintext` WebKit positions the list marker from the item's own
    # content-derived direction rather than the list's. Two things then go
    # wrong in a right-to-left document: an item whose content *begins* with
    # a bidi isolate -- which is exactly what `a { unicode-bidi: plaintext }`
    # below makes every link -- renders its bullet on top of the text or not
    # at all; and an item that resolves to the other direction puts its
    # bullet on the far side from every sibling's.
    #
    # A marker is layout, and layout follows the document: bullets, quote
    # bars and column order all move together. The text inside the item is
    # still reordered by the bidi algorithm, so an English item in an Arabic
    # list reads correctly -- it is aligned with its list rather than with
    # itself.
    for body in _rule_bodies_for(preview_css, "li"):
        assert "plaintext" not in body, (
            "li must not declare unicode-bidi: plaintext -- it misplaces the "
            "list marker; see this test's comment"
        )
    assert any(
        "text-align" in body and "start" in body
        for body in _rule_bodies_for(preview_css, "li")
    ), "li must still align to the start side"


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


# Properties that position something by a physical side. In a right-to-left
# document every one of them mirrors wrongly, so the logical counterpart is
# used instead: padding-inline-start, border-inline-start, inset-inline-end,
# and so on.
_PHYSICAL_PROPERTIES = frozenset(
    {
        "padding-left",
        "padding-right",
        "margin-left",
        "margin-right",
        "border-left",
        "border-right",
        "inset-left",
        "inset-right",
        "left",
        "right",
    }
)

# The only shorthand form whose two inline sides can differ. Two values means
# "block, inline"; three means "block-start, inline, block-end"; only four
# can say left and right separately -- which is exactly how
# `blockquote { padding: .1em 0 .1em 1em }` hid from a property-name check
# until brief 7 went looking for it.
_FOUR_VALUE_SHORTHANDS = frozenset({"padding", "margin", "inset", "border-width"})

# (selector, property) -> why this one may stay physical. Every entry is a
# square box being drawn, not a layout being aligned to a side.
_PHYSICAL_BY_DESIGN = {
    ('li.task-list-item > input[type="checkbox"]:checked::after', "left"): (
        "the tick is centred inside a square box, not aligned to either side"
    ),
    ('li.task-list-item > input[type="checkbox"]:checked::after', "margin"): (
        "the tick's own offset from that centre"
    ),
    ('li.task-list-item > input[type="checkbox"]:checked::after', "border-width"): (
        "two of the four borders are the checkmark's two strokes"
    ),
}


def _physical_declarations(name):
    parsed, _ = declarations(vendoring.read_resource(name))
    found = []
    for selector, properties in parsed.items():
        for prop, value in properties.items():
            if (selector, prop) in _PHYSICAL_BY_DESIGN:
                continue
            physical = (
                prop in _PHYSICAL_PROPERTIES
                or (prop in _FOUR_VALUE_SHORTHANDS and len(value.split()) == 4)
                or (prop == "text-align" and value in ("left", "right"))
            )
            if physical:
                found.append(f"{selector} {{ {prop}: {value} }}")
    return found


@pytest.mark.parametrize("name", OUR_STYLESHEETS)
def test_no_stylesheet_positions_anything_by_a_physical_side(name):
    # A right-to-left document mirrors only if every inline-axis property is
    # logical. One `padding-left` left behind puts a bullet, a quote bar or a
    # copy button on the wrong side, and nothing else in the suite would say
    # so -- the computed output for a left-to-right document is identical
    # either way, which is what makes this a gate rather than a test.
    assert _physical_declarations(name) == []


def test_every_physical_exception_is_actually_shipped():
    # A stale entry would leave the gate permanently relaxed for a
    # declaration nothing declares any more.
    shipped = set()
    for name in OUR_STYLESHEETS:
        parsed, _ = declarations(vendoring.read_resource(name))
        for selector, properties in parsed.items():
            for prop in properties:
                shipped.add((selector, prop))
    for key, reason in _PHYSICAL_BY_DESIGN.items():
        assert key in shipped, f"{key} is exempted for {reason!r} but is not declared"


def test_the_copy_button_sits_at_the_documents_own_end(preview_css):
    # The gate above only proves `right` is gone. Deleting the offset
    # altogether would also satisfy it, and would drop the button into the
    # corner of the block in both directions -- so the logical property has
    # to be asserted present, not merely the physical one absent.
    bodies = _rule_bodies_for(preview_css, ".xedown-copy")
    assert any("inset-inline-end" in body for body in bodies)


def test_the_list_indent_is_start_relative_in_every_theme():
    for theme in themes.THEMES:
        css = vendoring.read_resource(theme.stylesheet)
        assert "padding-inline-start" in css, f"{theme.identifier} indents no list"


def test_a_links_text_is_its_own_bidi_run(preview_css):
    # A URL or a path used as link text inside an Arabic sentence would
    # otherwise drag the sentence's neutrals -- its slashes, dots and colons
    # -- to the wrong end. `plaintext` rather than `isolate`: `isolate` takes
    # its base direction from the inherited `direction` property, so it would
    # read Arabic link text left-to-right inside a left-to-right document.
    # `plaintext` takes it from the link's own content, which is right in
    # both directions.
    bodies = _rule_bodies_for(preview_css, "a")
    assert any(
        "unicode-bidi" in body and "plaintext" in body for body in bodies
    ), "a must declare unicode-bidi: plaintext"
    assert not any("isolate" in body for body in bodies)


def test_the_footnote_backref_turns_around_in_a_right_to_left_document(preview_css):
    # U+21A9 is not a mirrored character, so the glyph has to be flipped
    # rather than left to the bidi algorithm. Targeted by href, not by class:
    # `class` is not an allowed attribute on `a`, so `footnote-backref` does
    # not survive the sanitizer -- but an in-page anchor passes through
    # resolve_uri untouched. Scoped to `.xedown-document[dir="rtl"]`, not bare
    # `[dir="rtl"]`: the bare form also matches an English article nested
    # inside `<html dir="rtl">` on a right-to-left desktop, which would
    # mirror the arrow for a document that isn't right-to-left at all.
    selector = '.xedown-document[dir="rtl"] .footnote a[href^="#fnref"]'
    bodies = _rule_bodies_for(preview_css, selector)
    assert bodies, f"no rule for {selector}"
    assert any("scaleX(-1)" in body for body in bodies)
    # A transform does nothing to an inline box.
    assert any("inline-block" in body for body in bodies)


def test_a_body_swap_carries_the_documents_direction(preview_js):
    # Under `auto` the direction is a function of the content, so typing
    # Arabic into an empty document has to flip the layout on the next
    # debounce -- without a page reload, which is what replaceBody exists to
    # avoid. Applied to the content element, which is what carries dir.
    body = preview_js[preview_js.index("function replaceBody(") :]
    assert "setAttribute" in body
    assert '"dir"' in body
    # Only the two real values, so a bad host call cannot write junk into the
    # attribute.
    assert '"rtl"' in body and '"ltr"' in body


def test_the_table_cue_reads_the_containers_own_direction(preview_js):
    # scrollLeft runs negative from a resting 0 in a right-to-left container,
    # so both cues would be wrong from the first frame: a wide Arabic table
    # would show "more content" against the edge that has none.
    body = preview_js[preview_js.index("function updateTableCue(") :]
    assert "Math.abs" in body
    assert "getComputedStyle" in preview_js
    assert "xedown-more-left" in body and "xedown-more-right" in body


def test_selection_is_themed_rather_than_left_to_the_engine(preview_css):
    parsed, _ = declarations(preview_css)
    rule = parsed.get("::selection", {})
    assert rule.get("background") == "var(--xedown-selection-bg)"
    assert rule.get("color") == "var(--xedown-selection-fg)"


def test_the_notice_bar_is_not_part_of_the_document_selection(preview_css):
    # A select-all in the preview selects the document, not xedown's own
    # message about a stylesheet that could not be used.
    parsed, _ = declarations(preview_css)
    assert parsed[".xedown-notice"]["user-select"] == "none"
    assert parsed[".xedown-notice"]["-webkit-user-select"] == "none"


def test_a_search_match_is_coloured_only_from_the_theme(preview_css):
    parsed, _ = declarations(preview_css)
    match = parsed["mark.xedown-match"]
    assert match["background"] == "var(--xedown-match-bg)"
    assert match["color"] == "var(--xedown-match-fg)"


def test_the_current_match_is_distinguished_by_more_than_its_colour(preview_css):
    # Hue alone would leave the current match indistinguishable to a reader
    # who cannot separate the two, so it also carries an edge.
    parsed, _ = declarations(preview_css)
    current = parsed["mark.xedown-match-current"]
    assert current["background"] == "var(--xedown-match-current-bg)"
    assert current["color"] == "var(--xedown-match-current-fg)"
    assert "outline" in current


def test_no_search_highlight_colour_is_hardcoded(preview_css):
    parsed, _ = declarations(preview_css)
    for selector in ("mark.xedown-match", "mark.xedown-match-current"):
        for name, value in parsed[selector].items():
            if name in ("background", "color", "outline"):
                assert "var(--xedown-" in value, f"{selector} {{ {name} }} is a literal"


def test_the_script_exposes_the_search_entry_points(preview_js):
    for symbol in ("search:", "setSearchIndex:", "clearSearch:"):
        assert symbol in preview_js


def test_the_search_walk_skips_the_copy_button(preview_js):
    # The copy button is the one thing inside the article that `user-select:
    # none` keeps out of a selection, and search covers exactly what
    # select-all would give you.
    assert "xedown-copy" in preview_js
    assert "FILTER_REJECT" in preview_js


def test_the_current_match_is_scrolled_to_without_animation(preview_js):
    # This fires on every keystroke while the reader types; smooth scrolling
    # would animate the page on each one.
    body = preview_js[preview_js.index("function setSearchIndex(") :]
    assert 'behavior: "auto"' in body
    assert "smooth" not in body[: body.index("function ", 10)]


def test_the_script_stops_marking_at_the_python_cap(preview_js):
    from xedown.search import MATCH_CAP

    assert f"MATCH_CAP = {MATCH_CAP}" in preview_js


def test_a_body_swap_reapplies_the_live_search(preview_js):
    # Auto-refresh replaces the body every 250 ms while the reader types; the
    # highlighting has to survive that rather than flicker away.
    body = preview_js[preview_js.index("function replaceBody(") :]
    assert "runSearch(" in body[: body.index("function scrollToAnchor(")]
