import pathlib

import pytest
from xedown import vendoring
from xedown.mdext import (
    fence_lang,
    find_list_interrupt,
    make_extensions,
    normalize_list_indentation,
)


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


# --- Fenced code: info string and indentation (task 13 / F2, F3) ---
#
# The vendored `FENCED_BLOCK_RE` (fenced_code.py:56-67) is `^`-anchored,
# with no leading-whitespace tolerance, and its info-string branch is a
# single *bare word* (`[\w#.+-]*`). A comma, a space or a brace anywhere in
# the info string makes the whole opening-fence match fail -- the fence
# never opens, the text becomes an ordinary paragraph, and the *closing*
# fence is left unmatched to open one of its own for whatever follows it
# (F2). An indented fence (1-3 spaces) is invisible to the same anchor,
# for an unrelated reason (F3). Both are widened from `mdext.py`, not the
# vendored copy.


def test_a_comma_in_the_info_string_still_opens_a_fence(convert):
    html = convert("```rust,no_run\nfn main() {}\n```\n")
    assert '<pre><code class="language-rust">' in html
    assert "no_run" not in html


def test_a_quoted_attribute_in_the_info_string_still_opens_a_fence(convert):
    html = convert('```js title="x"\ncode\n```\n')
    assert '<pre><code class="language-js">' in html
    assert "title" not in html


def test_a_plus_sign_in_the_lang_still_works(convert):
    # Already a bare word under the vendored regex -- pinned so the
    # widened one does not regress it.
    html = convert("```c++\nint main(){}\n```\n")
    assert 'class="language-c++"' in html


def test_a_hyphenated_lang_still_works(convert):
    html = convert("```shell-session\n$ ls\n```\n")
    assert 'class="language-shell-session"' in html


def test_a_bare_fence_with_no_info_string_has_no_language_class(convert):
    html = convert("```\nplain text\n```\n")
    assert "<pre><code>plain text" in html
    assert "language-" not in html


def test_a_tilde_fence_still_works(convert):
    html = convert("~~~python\nx = 1\n~~~\n")
    assert '<pre><code class="language-python">x = 1' in html


# --- Fenced code: `{attrs}` (task 13 review, fix round 1) ---
#
# `attr_list` is loaded (`vendoring.MARKDOWN_EXTENSIONS`), and
# "```{.python #myid}" is how a document sets an id on a fenced block --
# live syntax, not dead code like the bare `hl_lines="..."` branch. The
# widened `(?P<info>[^\n]*)` alternative would otherwise swallow the whole
# "{.python #myid}" as info-string text, losing the id and (before the
# language-token validation below existed) surfacing "{.python" itself as a
# malformed class.


def test_curly_attrs_set_both_id_and_language_class(convert):
    # The exact shape rendered at 062cf95, before this task touched
    # fenced-code recognition at all -- this must still be what
    # "```{.python #myid}" produces.
    html = convert("```{.python #myid}\nx=1\n```\n")
    assert '<pre id="myid"><code class="language-python">x=1' in html


def test_curly_attrs_with_only_a_class_set_no_id(convert):
    html = convert("```{.python}\nx=1\n```\n")
    assert '<code class="language-python">x=1' in html
    assert " id=" not in html


def test_an_unclosed_curly_brace_falls_back_to_plain_info_text(convert):
    # No closing "}" on the line, so the {attrs} branch never matches and
    # this falls through to the plain info-string branch instead. Its first
    # token, "{.python", is not a plausible language identifier, so no
    # class is emitted -- not a crash, and not a malformed one either.
    html = convert("```{.python\nx=1\n```\n")
    assert "<pre><code>x=1" in html
    assert "language-" not in html


@pytest.mark.parametrize("spaces", [1, 2, 3])
def test_a_fence_indented_one_to_three_spaces_is_recognised(convert, spaces):
    html = convert(f"{' ' * spaces}```sh\necho hi\n```\n")
    assert '<pre><code class="language-sh">echo hi' in html
    # The indentation shared with the fence marker does not leak into the
    # code content.
    assert "  echo hi" not in html


def test_a_fence_indented_two_spaces_inside_a_list_item_is_recognised(convert):
    # Whether this nests inside the <li> is F5's concern (a separate,
    # later task on list-continuation indentation) -- this only pins that
    # the fence itself is no longer degraded to inline `<code>` with its
    # language marker left as visible text, which is what F3 is about.
    html = convert("- item\n\n  ```sh\n  echo hi\n  ```\n")
    assert '<pre><code class="language-sh">echo hi' in html
    assert "<li>item</li>" in html


def test_a_fence_indented_four_spaces_stays_indented_code(convert):
    # Four spaces is indented code, not a fence -- CommonMark's own cutoff,
    # and the one the vendored list processors already use. The fence
    # markers must stay literal text, not become `<pre><code
    # class="language-sh">`.
    html = convert("    ```sh\n    echo hi\n    ```\n")
    assert 'class="language-sh"' not in html
    assert "```sh" in html


def test_the_desynchronisation_regression_from_f2(convert):
    # The exact input from the findings report's F2. Before this fix, the
    # unmatched closing fence acted as an *opening* fence for the rest of
    # the document -- in tokio.md this put 6224 of 9950 rendered body
    # characters inside <pre>, against cmark's 1252. This is the test that
    # would catch that 62% catastrophe returning.
    html = convert("```rust,no_run\nfn main() {}\n```\n\nAfter.\n")
    assert "<p>After.</p>" in html
    pre_end = html.index("</pre>")
    after_index = html.index("After.")
    assert (
        after_index > pre_end
    ), "the paragraph after the fence must not be inside <pre>"


# --- Fenced code: language token validation (task 13 review, fix round 1) ---
#
# `class="language-..."` reaches the rendered page unexamined --
# `sanitizer._ALLOWED_CLASS_PREFIXES` is a prefix check for blocking style
# injection, not a semantic validator -- so a first token that is not
# itself a plausible language identifier must emit no class at all, not an
# escaped-but-nonsensical one.


@pytest.mark.parametrize("lang", ["c++", "shell-session", "Rust", "objective-c"])
def test_a_plausible_identifier_still_gets_a_class(convert, lang):
    html = convert(f"```{lang}\ncode\n```\n")
    assert f'class="language-{lang}"' in html


def test_a_brace_led_token_with_no_closing_brace_gets_no_class(convert):
    html = convert("```{oops\ncode\n```\n")
    assert "<pre><code>code" in html
    assert "language-" not in html


def test_a_quoted_token_gets_no_class(convert):
    html = convert('```"weird\ncode\n```\n')
    assert "<pre><code>code" in html
    assert "language-" not in html


def test_an_empty_info_string_gets_no_class_and_does_not_crash(convert):
    html = convert("```\ncode\n```\n")
    assert "<pre><code>code" in html
    assert "language-" not in html


# --- `fence_lang` itself (task 13 / F2) ---


def test_fence_lang_takes_the_first_comma_delimited_token():
    assert fence_lang("rust,no_run") == "rust"


def test_fence_lang_takes_the_first_space_delimited_token():
    assert fence_lang('js title="x"') == "js"


def test_fence_lang_returns_the_whole_bare_word():
    assert fence_lang("shell-session") == "shell-session"


def test_fence_lang_returns_none_for_an_empty_info_string():
    assert fence_lang("") is None
    assert fence_lang(None) is None
    assert fence_lang("   ") is None


def test_fence_lang_rejects_a_token_that_is_not_a_plausible_identifier():
    assert fence_lang("{.python") is None
    assert fence_lang('"weird') is None


# --- Heading hash edge cases (task 12 / F9, F10) ---
#
# The vendored `HashHeaderProcessor.RE` has no space requirement after the
# hashes: `#NoSpace` became an `<h1>` and `####### Seven hashes` became an
# `<h6>` with a literal `#` left in its text. CommonMark makes both of these
# paragraphs. `[ ]+` (or end of line) is now required after the hashes.


def test_a_hash_with_no_following_space_is_not_a_heading(convert):
    html = convert("#NoSpace")
    assert "<h1" not in html
    assert "<p>#NoSpace</p>" in html


def test_seven_hashes_is_not_a_heading_and_leaves_no_stray_hash(convert):
    html = convert("####### Seven hashes")
    assert "<h6" not in html
    assert "<p>####### Seven hashes</p>" in html


def test_a_normal_heading_still_works(convert):
    assert "<h1" in convert("# Normal")


def test_a_six_hash_heading_still_works(convert):
    assert "<h6" in convert("###### Six")


def test_a_lone_hash_is_still_an_empty_heading(convert):
    # A bare "#" runs straight into end of line, which CommonMark treats
    # the same as a following space: a valid, empty ATX heading.
    html = convert("#")
    assert "<h1" in html


def test_a_heading_with_trailing_hashes_still_works(convert):
    html = convert("## Trailing ##")
    assert '<h2 id="trailing">Trailing</h2>' in html


# --- Paren-delimited ordered lists (task 14 / F20) ---
#
# The vendored `OListProcessor` only accepts `.` after the number.
# `1) one\n2) two` fell all the way through to a single paragraph -- a
# destroyed list, not merely renumbered.


def test_a_paren_ordered_list_becomes_an_ol(convert):
    html = convert("1) one\n2) two")
    assert "<ol>" in html
    assert html.count("<li>") == 2
    assert "<p>1) one" not in html


def test_a_period_ordered_list_still_works(convert):
    # Regression: the override must not lose the spelling it already had.
    html = convert("1. one\n2. two")
    assert "<ol>" in html
    assert html.count("<li>") == 2


def test_an_unordered_list_still_works(convert):
    html = convert("- a\n- b")
    assert "<ul>" in html
    assert html.count("<li>") == 2


def test_a_paren_list_interrupts_a_paragraph(convert):
    # Same terms as `1.`: interruption is allowed, following the same
    # restriction (find_list_interrupt only recognises `1)`, not `2)`).
    html = convert("Text.\n1) one\n2) two")
    assert "<p>Text.</p>" in html
    assert "<ol>" in html
    assert html.count("<li>") == 2


def test_wrapped_prose_starting_with_a_year_and_a_paren_stays_prose(convert):
    # The `)` counterpart of the existing `1985. What a year.` regression:
    # prose wrapping onto a line that merely looks like a paren list marker
    # must not become one.
    html = convert("The winning year was\n1985) what a year.")
    assert "<ol" not in html
    assert "1985)" in html


def test_a_paren_marker_starting_above_one_does_not_interrupt(convert):
    assert "<ol" not in convert("Text.\n3) one\n4) two")


def test_a_ul_then_ol_across_a_blank_line_stays_two_lists(convert):
    # sane_lists sets SIBLING_TAGS = ['ol'] on its OListProcessor precisely
    # so that a `ul` immediately above (separated only by a blank line)
    # does not get treated as the same list. A `ParenOListProcessor` built
    # by subclassing the plain vendored `OListProcessor` instead of
    # `SaneOListProcessor` would inherit `SIBLING_TAGS = ['ol', 'ul']` and
    # silently merge these into one `<ul>` with three `<li>` -- exactly
    # what `test_fragment_renders_core_markdown` in test_renderer.py caught
    # once, with no local test in this file to explain why.
    html = convert("- one\n- two\n\n1. first")
    assert html.count("<ul>") == 1
    assert html.count("<ol>") == 1
    assert "<ul>\n<li>one</li>\n<li>two</li>\n</ul>" in html
    assert "<ol>\n<li>first</li>\n</ol>" in html


# --- Backslash line breaks (task 14 / F21) ---
#
# CommonMark makes a backslash at the end of a line a hard break, the same
# as two trailing spaces. The vendored parser left the backslash as visible
# text with no break at all.


def test_a_trailing_backslash_becomes_a_hard_break(convert):
    html = convert("line one\\\nline two")
    assert "<br />" in html
    assert "\\" not in html


def test_two_trailing_spaces_still_make_a_hard_break(convert):
    # The spelling the brief says already worked -- pinned so the new
    # inline pattern cannot be the thing that breaks it.
    html = convert("line one  \nline two")
    assert "<br />" in html


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
    # Not just "no list": if the indent bound were widened to four spaces,
    # `code` (priority 80) would claim the second line and render a <pre>
    # instead -- a changed rendering "<ul> not in html" alone would miss.
    html = convert("Some text\n    - deep")
    assert "<ul>" not in html
    assert "<pre>" not in html
    assert "Some text\n    - deep" in html


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


# --- List indentation: the rule itself (task 15 / F5, F6) ---


def _normalized(text):
    return "\n".join(normalize_list_indentation(text.split("\n")))


def test_a_document_already_indented_four_spaces_is_untouched():
    # The invariant the whole pass rests on: it translates CommonMark's
    # continuation column onto the vendored parser's fixed four, and a
    # document that already speaks four says the same thing afterwards.
    for text in (
        "- a\n    - b\n        - c",
        "1. one\n    1. inner",
        "- a\n\n    para two\n\n- b",
        "Just a paragraph.\n\nAnd another.",
    ):
        assert _normalized(text) == text, text


def test_a_two_space_sublist_moves_to_four():
    assert _normalized("- Flask\n  - apiflask") == "- Flask\n    - apiflask"


def test_each_level_gets_one_tab_length_whatever_the_source_used():
    assert _normalized("* a\n  * b\n    * c") == "* a\n    * b\n        * c"


def test_an_ordered_marker_sets_a_three_column_continuation():
    # `1. ` is three columns wide, so a sublist indented three belongs to it.
    assert _normalized("1. one\n   1. inner") == "1. one\n    1. inner"


def test_a_sibling_dedents_back_to_its_own_level():
    assert _normalized("- a\n  - b\n- c") == "- a\n    - b\n- c"


def test_indented_code_at_the_top_level_is_left_alone():
    assert _normalized("text\n\n    - not a list") == "text\n\n    - not a list"


def test_a_marker_four_past_the_continuation_column_is_not_an_item():
    # Four spaces past the column is indented code, and code cannot
    # interrupt a paragraph, so this is prose. Pulling it down into
    # `OListProcessor.INDENT_RE`'s four-to-seven window would invent a
    # sublist that neither CommonMark nor the parser before this change saw.
    assert _normalized("- a\n        - b") == "- a\n        - b"


def test_prose_that_looks_like_an_ordered_marker_stays_prose():
    # GFM's rule, and the reason it exists: only `1.` may interrupt. Were
    # `1985.` taken for a marker it would open a level and become
    # `<ol start="1985">`, since `sane_lists` sets `LAZY_OL = False`.
    text = "- a\n  Text was\n  1985. What a year."
    assert _normalized(text) == text


def test_a_non_interrupting_marker_after_a_marker_line_still_opens_an_item():
    # `2.` cannot interrupt a *paragraph*, but the line above it is a marker,
    # not prose, so the sublist's second item is an item.
    assert _normalized("1. a\n   1. b\n   2. c") == "1. a\n    1. b\n    2. c"


def test_a_lazy_continuation_keeps_its_own_indentation():
    assert _normalized("- a\ncontinued") == "- a\ncontinued"


def test_a_content_less_marker_does_not_open_a_level():
    # The vendored `RE` needs a space and content, so a bare `-` is not an
    # item to the parser downstream. Opening a level here would indent the
    # sub-item into a level nothing can enter, and lose it in a paragraph:
    # `  - b` stays an outermost item, and an outermost item is never moved.
    assert _normalized("-\n  - b") == "-\n  - b"


def test_an_outermost_marker_keeps_its_own_indentation():
    # Nought to three columns is what every vendored list processor
    # tolerates on an outermost marker, so moving one buys nothing -- and
    # moving it left can walk it out from under an indented code block that
    # was holding it.
    assert _normalized("  - a\n    - b") == "  - a\n    - b"
    assert _normalized("   - a\n     - b") == "   - a\n    - b"


def test_a_blockquote_marker_past_the_column_is_pulled_back_within_three():
    # F6. `BlockQuoteProcessor.RE` tolerates three spaces and no more, and a
    # tight item's continuation lines reach it undedented.
    assert _normalized("- item\n    > quote") == "- item\n  > quote"


def test_a_rule_or_heading_line_inside_a_tight_item_is_never_moved():
    # The trap. Dedenting `  ---` would make `- a` a setext heading's text
    # and destroy the list; dedenting `  # x` would lift the heading out of
    # the item. Only `>` is safe to move, so only `>` moves.
    for line in ("  ---", "  ===", "  # heading", "  | a | b |"):
        assert _normalized(f"- a\n{line}") == f"- a\n{line}", line


def test_a_thematic_break_is_never_read_as_a_list_item():
    # `- - -` is a marker, a space and content to the item regex, and a rule
    # to CommonMark and to `HRProcessor` alike. Indenting it as an item would
    # put a literal `- -` where the rule was.
    for line in ("  - - -", "  * * *", "  -  -  -  -"):
        assert _normalized(f"- a\n{line}") == f"- a\n{line}", line


# --- List indentation: block splitters end the tracking (task 15, review) ---
#
# Declining to *move* a rule is not enough. `hr` (50), `setextheader` (60)
# and `hashheader` (70) split the block they are in and re-queue the halves,
# so whatever follows re-enters the chain with no list context -- where
# `tab_length` spaces mean indented code, not a sub-item. The whole block
# goes back the way it was written.

RULES = ("---", "***", "___", "- - -", "* * *")


def test_a_rule_tight_inside_an_item_puts_the_whole_block_back():
    for rule in RULES:
        assert _normalized(f"- a\n  {rule}\n  - b") == f"- a\n  {rule}\n  - b", rule


def test_a_rule_deeper_in_puts_the_whole_block_back_including_the_move():
    # The form the guard exists for. Rewinding matters here and not in the
    # shallow form: `  - b` has already been moved to four columns by the
    # time the rule is reached, and leaving it there is what makes
    # `setextheader` read `- b` as an `<h2>`'s text.
    for rule in RULES + ("===", "# x", "### x"):
        source = f"- a\n  - b\n    {rule}\n    - c"
        assert _normalized(source) == source, rule


def test_a_rule_in_a_block_of_its_own_leaves_the_list_alone(convert):
    # With a blank line either side the rule is its own block,
    # `ListIndentProcessor` carries the item across it, and the list
    # survives -- so the guard must not fire and the fix stays.
    assert _normalized("- a\n\n  ---\n\n  - b") == "- a\n\n    ---\n\n    - b"
    html = convert("- a\n\n  ---\n\n  - b")
    assert html.count("<ul>") == 2
    assert "<hr />" in html


def test_a_heading_at_the_margin_under_a_list_is_not_this_hazard():
    # An ATX heading cuts the block at its own line, so the half above it is
    # a whole list and keeps its nesting. This shape is in awesome-python;
    # treating it as the hazard would cost real sublists.
    assert _normalized("- a\n  - b\n### Geolocation") == (
        "- a\n    - b\n### Geolocation"
    )


def test_a_splitter_at_the_margin_still_ends_the_tracking():
    # Nothing above it is undone, but the list is over for the parser, so a
    # later line must not be measured against an item that no longer exists.
    # Left tracking, `   1. one` here would be read as a sub-item of `* b`
    # and moved to four columns, which is where the indented code block
    # above it would swallow it.
    source = "* b\n# head\n    <div>x</div>\n   1. one\n - a"
    assert _normalized(source) == source


def test_a_deeply_indented_splitter_is_claimed_by_nothing_and_is_left_alone():
    # Four or more columns past the nesting, a rule is not a rule to any
    # processor, so there is no hazard and the fix stays.
    assert _normalized("- a\n      ---\n  - b") == "- a\n      ---\n    - b"


def test_a_setext_underline_fires_wherever_it_is():
    # Unlike a rule or an ATX heading, a setext underline absorbs the line
    # *above* it, so a marker line this pass has moved becomes the heading's
    # text however far left the underline sits.
    for underline in ("===", "-", "--"):
        source = f"- a\n  - b\n{underline}"
        assert _normalized(source) == source, underline


def test_a_rule_tight_inside_an_item_renders_as_it_did_before(convert):
    # The reader-facing half of the same claim, and the outcome the guard
    # exists to prevent: `- b` in a code box.
    html = convert("- a\n  ---\n  - b")
    assert "<hr />" in html
    assert "<pre>" not in html
    assert html.count("<li>") == 2


def test_a_nested_ordered_paren_item_under_a_bullet_still_nests(convert):
    # `ulist` carries its own `INDENT_RE` for spotting a nested item of
    # either type, and `sane_lists` leaves the ordered half of it at
    # `\\d+\\.`. Widening `olist` alone (task 14 / F20) missed it, and this
    # pass moving the line to four columns is what made it visible.
    html = convert("- a\n  1) b")
    assert "<ol>" in html
    assert "1)" not in html


def test_a_blank_line_does_not_close_an_open_item():
    assert _normalized("- a\n\n  - b") == "- a\n\n    - b"


def test_a_block_of_its_own_inside_an_item_lands_where_indent_can_dedent_it():
    # A separate block goes to `ListIndentProcessor`, which dedents by
    # `tab_length * depth`, so the offset past the column survives as the
    # code indentation it is.
    assert _normalized("- a\n\n  para") == "- a\n\n    para"
    assert _normalized("- a\n\n      code") == "- a\n\n        code"


def test_the_tab_length_is_a_parameter_not_a_constant():
    assert normalize_list_indentation(["- a", "  - b"], tab_length=6) == [
        "- a",
        "      - b",
    ]


# --- List indentation: the fix (task 15 / F5, F6) ---


def test_a_two_space_sublist_nests_instead_of_flattening(convert):
    # F5, the minimal input from the audit.
    html = convert("- Flask\n  - apiflask")
    assert html.count("<ul>") == 2
    assert html.count("<li>") == 2
    assert "<li>Flask<ul>" in html


def test_three_two_space_levels_nest_three_deep(convert):
    html = convert("* a\n  * b\n    * c")
    assert html.count("<ul>") == 3
    assert html.count("<li>") == 3


def test_a_two_space_sublist_after_a_blank_line_nests(convert):
    html = convert("- item\n\n  - nested")
    assert html.count("<ul>") == 2


def test_an_ordered_sublist_keeps_both_of_its_items(convert):
    html = convert("1. a\n   1. b\n   2. c")
    assert html.count("<ol>") == 2
    assert html.count("<li>") == 3


def test_a_sibling_after_a_sublist_returns_to_the_outer_list(convert):
    html = convert("* [A](#a)\n  * [B](#b)\n* [C](#c)")
    assert html.count("<ul>") == 2
    assert html.count("<li>") == 3


def test_four_space_nesting_still_nests_exactly_one_level(convert):
    # The failure mode `tab_length=2` would have introduced, pinned from the
    # other side: four spaces is one level, not two, and not literal text.
    html = convert("- a\n    - b")
    assert html.count("<ul>") == 2
    assert html.count("<li>") == 2


def test_an_over_indented_blockquote_is_a_blockquote(convert):
    # F6, the minimal input from the audit. The damage it repairs is an
    # escaped `>` shown to the reader in place of the quotation.
    html = convert("- item\n    > quote")
    assert "<blockquote>" in html
    assert "&gt;" not in html


def test_a_blockquote_inside_a_two_space_sublist_survives_the_move(convert):
    html = convert("- a\n  - b\n    > q")
    assert html.count("<ul>") == 2
    assert "<blockquote>" in html


def test_a_two_space_task_sublist_nests_and_keeps_its_checkboxes(convert):
    html = convert("- [ ] a\n  - [x] b")
    # `<ul` rather than `<ul>`: both lists carry the task-list class.
    assert html.count("<ul") == 2
    assert html.count("<input") == 2
    assert "checked" in html


def test_a_list_interrupting_a_paragraph_still_nests_below_it(convert):
    # The two passes meet: this one re-indents, `xedown_list_interrupt`
    # splits the paragraph off the block that results.
    html = convert("Text.\n- a\n  - b")
    assert "<p>Text.</p>" in html
    assert html.count("<ul>") == 2


def test_a_rule_under_a_two_space_item_is_still_a_list_and_a_rule(convert):
    # The trap, end to end. If the `---` were dedented this would collapse
    # into a single `<h2>` whose text is `- a`.
    html = convert("- a\n  ---")
    assert "<ul>" in html
    assert "<hr />" in html
    assert "<h2" not in html


def test_a_fenced_body_inside_a_list_keeps_its_own_indentation(convert):
    # The reason priority 18 is the design and not a free choice: by the
    # time this pass runs, `fenced_code_block` (25) has already lifted the
    # fence into the HTML stash, so indentation that is code is not text
    # this pass declines to move -- it is not text.
    html = convert("- a\n\n  ```sh\n  one\n      two\n  ```")
    assert "<code" in html
    assert "one\n    two" in html


def test_a_nested_list_inside_a_blockquote_is_still_flattened(convert):
    # Recorded, not endorsed. This pass reads absolute indentation, and a
    # `>` prefix moves the continuation column somewhere it does not look.
    # Nothing regresses -- this rendered flat before the change too -- and
    # teaching it to strip quote prefixes is a second parser's worth of
    # state for a shape the corpus does not show.
    html = convert("> - a\n>   - b")
    assert html.count("<ul>") == 1
    assert html.count("<li>") == 2


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
    # The `↩` back-reference moves into its own paragraph, because the note
    # now holds more than one block -- true of any multi-block footnote, not
    # specific to this fix, but real enough to pin (design section 6).
    assert '<p><a class="footnote-backref"' in html


def test_an_unclosed_fence_does_not_protect_a_marker_line(convert):
    # Recorded, not endorsed -- see section 8 of the design. An unclosed
    # fence is not matched by fenced_code's preprocessor, so its lines reach
    # block parsing. Nothing regresses: these lines were not code before this
    # brief either, they were one paragraph. Teaching this processor about
    # fences is exactly the coupling priority 12 exists to avoid.
    assert "<ul>" in convert("Text.\n```\n- item")


def test_a_setext_underline_reclaims_the_lower_half_of_a_split_marker_line(convert):
    # Recorded, not endorsed -- see section 8 of the design. Registering at
    # 12 only guarantees what the undivided block cannot be claimed as; the
    # lower half `run` pushes back onto the queue re-enters the chain at
    # priority 100 and can be claimed by `setextheader` (60) before it ever
    # reaches 12 again, so the marker becomes literal heading text and the
    # list never forms. Nothing regresses: this document already renders
    # identically to "Text.\n\n- item\n===" -- the same document with a
    # blank line inserted, which is what a preprocessor-shaped fix would have
    # put there -- both before and after this brief.
    html = convert("Text.\n- item\n===")
    assert "<p>Text.</p>" in html
    assert '<h1 id="-item">- item</h1>' in html
    assert "<ul>" not in html


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


def _convert_without_list_indentation(markdown_module, text):
    """Convert with every xedown extension except task 15's."""
    extensions = make_extensions(markdown_module)
    kept = [e for e in extensions if type(e).__name__ != "ListIndentationExtension"]
    assert len(kept) == len(extensions) - 1, "ListIndentationExtension was not found"
    md = markdown_module.Markdown(extensions=list(vendoring.MARKDOWN_EXTENSIONS) + kept)
    return md.convert(text)


def test_every_fixture_renders_identically_without_the_indentation_pass(convert):
    # Every shipped fixture, `edge-cases.md` included: all of them already
    # indent four spaces per level, and on such a document this pass is a
    # no-op by construction. Stated as a test rather than assumed, because
    # "a four-space document comes through unchanged" is the property the
    # whole translation rests on, and a fixture is a real document rather
    # than a hand-built line.
    markdown_module = vendoring.import_markdown()
    for name in CLEAN_FIXTURES + ("edge-cases.md",):
        text = (FIXTURES_DIR / name).read_text(encoding="utf-8")
        assert convert(text) == _convert_without_list_indentation(
            markdown_module, text
        ), name
