import pathlib

import pytest
from xedown import vendoring
from xedown.mdext import fence_lang, find_list_interrupt, make_extensions


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
