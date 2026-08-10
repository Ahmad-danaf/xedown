import pathlib

import pytest
from xedown import vendoring
from xedown.mdext import find_list_interrupt, make_extensions


@pytest.fixture
def convert():
    markdown_module = vendoring.import_markdown()

    def _convert(text):
        md = markdown_module.Markdown(
            extensions=list(vendoring.MARKDOWN_EXTENSIONS)
            + make_extensions(markdown_module)
        )
        return md.convert(text)

    return _convert


def test_unchecked_task_becomes_a_disabled_checkbox(convert):
    html = convert("- [ ] buy milk")
    assert "<input" in html
    assert "checked" not in html
    assert "buy milk" in html
    assert "[ ]" not in html


def test_checked_task_becomes_a_checked_checkbox(convert):
    html = convert("- [x] done thing")
    assert "checked" in html
    assert "done thing" in html
    assert "[x]" not in html


def test_uppercase_checked_marker_is_accepted(convert):
    assert "checked" in convert("- [X] done")


def test_task_items_carry_marker_classes(convert):
    html = convert("- [ ] a\n- [x] b")
    assert "task-list" in html


def test_ordinary_list_items_are_untouched(convert):
    html = convert("- plain item")
    assert "<input" not in html
    assert "plain item" in html


def test_bracket_text_that_is_not_a_task_is_left_alone(convert):
    html = convert("- [link](http://example.com) trailing")
    assert "<input" not in html
    assert 'href="http://example.com"' in html


def test_strikethrough_becomes_del(convert):
    html = convert("~~gone~~")
    assert "<del>gone</del>" in html


def test_single_tildes_are_not_strikethrough(convert):
    assert "<del>" not in convert("a ~b~ c")


def test_strikethrough_inside_a_list_item_works(convert):
    assert "<del>x</del>" in convert("- ~~x~~")


def test_tables_and_fenced_code_still_work_alongside(convert):
    html = convert("| a |\n|---|\n| 1 |\n\n```python\nx=1\n```")
    assert "<table>" in html
    assert 'class="language-python"' in html


# --- What must not change (brief 16) ---
#
# These pass against the parser as it was before a list could interrupt a
# paragraph, and must still pass after. They are the blast-radius check for
# the block processor registered at priority 12: setext headings, rules,
# fences, indented code, tables and nested lists are all claimed by
# processors above it, and this is what keeps that claim honest.


def test_setext_h2_under_a_paragraph(convert):
    assert "<h2" in convert("Heading Text\n---\n\nbody")


def test_setext_h1_under_a_paragraph(convert):
    assert "<h1" in convert("Heading Text\n===\n\nbody")


def test_a_single_hyphen_is_still_a_setext_underline(convert):
    # The hyphen-only line the brief warns about, in its shortest form.
    assert "<h2" in convert("Heading\n-\n\nbody")


def test_a_rule_between_blank_lines_is_still_a_rule(convert):
    html = convert("para\n\n---\n\npara two")
    assert "<hr" in html
    assert "<h2" not in html


def test_a_spaced_rule_under_a_paragraph_is_still_a_rule(convert):
    # `- - -` has a marker, a space and content, and is a rule regardless.
    # Priority 12 is why this never has to be special-cased: `hr` (50) takes
    # the block first.
    html = convert("Some text\n- - -\n\nafter")
    assert "<hr" in html
    assert "<ul>" not in html


def test_list_shaped_lines_inside_a_fence_stay_code(convert):
    html = convert("Text.\n\n```\n- not a list\n---\n```\n")
    assert "<ul>" not in html
    assert "<hr" not in html
    assert "- not a list" in html


def test_a_fence_opening_directly_under_a_paragraph_stays_code(convert):
    html = convert("Text.\n```\n- not a list\n```\n")
    assert "<ul>" not in html
    assert "- not a list" in html


def test_indented_code_containing_a_marker_stays_code(convert):
    html = convert("Text.\n\n    code line\n    - not a list\n")
    assert "<ul>" not in html
    assert "<code>" in html


def test_a_nested_list_stays_tight(convert):
    # A blank line inserted before the nested list would make the outer list
    # loose and wrap every item in <p>. This is the test that would catch a
    # preprocessor-shaped mistake.
    #
    # Four spaces, not two: tab_length is 4, so a two-space sub-item is not
    # nested at all -- it is a third top-level sibling, and this test would
    # then pass without ever producing a nested list.
    html = convert("- item one\n    - nested\n- item two")
    assert "<p>" not in html
    assert html.count("<ul>") == 2, "the nested list did not nest"


def test_a_nested_list_under_a_continuation_line_stays_tight(convert):
    html = convert("- item one\n    continuation\n    - nested")
    assert "<p>" not in html
    assert html.count("<ul>") == 2, "the nested list did not nest"


def test_a_marker_line_under_a_table_row_stays_in_the_table(convert):
    html = convert("| a | b |\n|---|---|\n| 1 | 2 |\n- item")
    assert "<ul>" not in html
    assert "<td>- item</td>" in html


def test_lazy_continuation_still_belongs_to_its_item(convert):
    # The literal substring, not a tag count: if the continuation escaped the
    # item and became its own paragraph, <ul> would still be present and the
    # <li> count would still be 1.
    html = convert("- item one\nlazy continuation")
    assert "<li>item one\nlazy continuation</li>" in html


def test_an_ordered_list_starting_at_three_does_not_interrupt(convert):
    assert "<ol" not in convert("Text.\n3. one\n4. two")


def test_wrapped_prose_starting_with_a_year_stays_prose(convert):
    # GFM's reason for restricting interruption to `1.`. sane_lists sets
    # LAZY_OL = False, so the permissive rule would not merely mis-parse this
    # -- it would render <ol start="1985">.
    html = convert("The winning year was\n1985. What a year.")
    assert "<ol" not in html
    assert "1985." in html


def test_a_marker_with_no_content_does_not_start_a_list(convert):
    assert "<ul>" not in convert("Text.\nmore text\n- ")


def test_a_deeply_indented_marker_does_not_interrupt(convert):
    assert "<ul>" not in convert("Some text\n    - deep")


# --- The rule itself (brief 16) ---


def test_a_marker_on_the_first_line_is_not_an_interrupt():
    # Line 0 is never a candidate: a block that begins with a marker is
    # already a list. Note this is about line 0 only -- "- a\n- b" returns 1,
    # because line 1 does start a list. That block never reaches the
    # processor: `ulist` claims it at priority 30, well above 12.
    assert find_list_interrupt("- only item") is None


def test_the_first_interrupting_line_is_found():
    assert find_list_interrupt("Text.\n- item") == 1
    assert find_list_interrupt("Text.\nmore text\n1. item") == 2


def test_every_unordered_marker_is_recognised():
    for marker in ("-", "*", "+"):
        assert find_list_interrupt(f"Text.\n{marker} item") == 1


def test_only_an_ordered_list_starting_at_one_is_recognised():
    assert find_list_interrupt("Text.\n1. item") == 1
    assert find_list_interrupt("Text.\n2. item") is None


def test_up_to_three_spaces_of_indent_are_tolerated():
    # Three is the vendored list processors' own tolerance. Four is a
    # continuation line, not a marker.
    assert find_list_interrupt("Text.\n   - item") == 1
    assert find_list_interrupt("Text.\n    - item") is None


def test_a_marker_needs_content_after_it():
    assert find_list_interrupt("Text.\n- ") is None
    assert find_list_interrupt("Text.\n-item") is None


def test_an_empty_block_has_no_interrupt():
    assert find_list_interrupt("") is None


# --- The fix (brief 16) ---


def test_an_unordered_list_interrupts_a_paragraph(convert):
    # The example from the brief.
    html = convert("Some paragraph text.\n- item one\n- item two")
    assert "<p>Some paragraph text.</p>" in html
    assert html.count("<li>") == 2


def test_each_unordered_marker_interrupts(convert):
    for marker in ("-", "*", "+"):
        assert "<ul>" in convert(f"Text.\n{marker} item"), marker


def test_an_ordered_list_interrupts_a_paragraph(convert):
    html = convert("Text.\n1. one\n2. two")
    assert "<p>Text.</p>" in html
    assert "<ol>" in html
    assert html.count("<li>") == 2


def test_an_indented_marker_still_interrupts(convert):
    assert "<ul>" in convert("Text.\n   - item")


def test_a_task_list_interrupting_a_paragraph_still_gets_checkboxes(convert):
    # The task-list treeprocessor and this block processor meet on the same
    # list. Neither is aware of the other, so this is worth pinning.
    html = convert("Text.\n- [ ] todo\n- [x] done")
    assert "<p>Text.</p>" in html
    assert 'class="task-list"' in html
    assert html.count("<input") == 2


# --- Reach, residual, and fixture parity (brief 16) ---
#
# Blockquotes, list items and footnote definitions each re-parse their own
# contents through the same block processor chain, so registering once fixes
# a paragraph anywhere one can occur. That reach is what makes it honest to
# delete the README limitation outright instead of narrowing it.


def test_a_list_interrupts_a_paragraph_inside_a_blockquote(convert):
    html = convert("> quote text\n> - item\n> - item two")
    assert "<blockquote>" in html
    assert "<ul>" in html
    assert html.count("<li>") == 2


def test_a_list_interrupts_a_paragraph_inside_a_list_item(convert):
    html = convert("- item\n\n    text in item\n    - nested")
    assert html.count("<ul>") == 2


def test_a_list_interrupts_a_paragraph_inside_a_footnote(convert):
    html = convert("Body[^1]\n\n[^1]: Footnote text\n    - item\n    - item two")
    assert "<ul>" in html
    assert html.count("<li>") >= 2


def test_an_unclosed_fence_does_not_protect_a_marker_line(convert):
    # Recorded, not endorsed -- see section 8 of the design. An unclosed
    # fence is not matched by fenced_code's preprocessor, so its lines reach
    # block parsing. Nothing regresses: these lines were not code before this
    # brief either, they were one paragraph. Teaching this processor about
    # fences is exactly the coupling priority 12 exists to avoid.
    assert "<ul>" in convert("Text.\n```\n- item")


FIXTURES_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

# Every fixture that must render byte-identically. edge-cases.md is
# deliberately absent: it is the one document this brief changes.
CLEAN_FIXTURES = (
    "showcase.md",
    "rtl.md",
    "mixed-direction.md",
    "linked.md",
    "README.md",
)


def _convert_without_list_interrupt(markdown_module, text):
    """Convert with every xedown extension except this brief's."""
    extensions = make_extensions(markdown_module)
    kept = [e for e in extensions if type(e).__name__ != "ListInterruptExtension"]
    # Without this, a renamed class would silently filter nothing and leave
    # the parity test below comparing a converter to itself, passing forever.
    assert len(kept) == len(extensions) - 1, "ListInterruptExtension was not found"
    md = markdown_module.Markdown(extensions=list(vendoring.MARKDOWN_EXTENSIONS) + kept)
    return md.convert(text)


def test_the_clean_fixtures_render_identically_without_this_extension(convert):
    # "Renders identically to before", made checkable without a frozen
    # baseline that would rot: the comparison is against the same parser with
    # this brief's extension filtered out, in the same run.
    markdown_module = vendoring.import_markdown()
    for name in CLEAN_FIXTURES:
        text = (FIXTURES_DIR / name).read_text(encoding="utf-8")
        assert convert(text) == _convert_without_list_interrupt(
            markdown_module, text
        ), name


def test_the_edge_cases_fixture_is_the_one_document_that_changes(convert):
    # The other half of the claim. If this ever passes as "identical", the
    # fixture's paragraph-and-list section has been edited away.
    markdown_module = vendoring.import_markdown()
    text = (FIXTURES_DIR / "edge-cases.md").read_text(encoding="utf-8")
    assert convert(text) != _convert_without_list_interrupt(markdown_module, text)
