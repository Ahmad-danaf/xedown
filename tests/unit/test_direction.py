"""The document's reading direction, decided from content or from the setting."""

from xedown import direction

ARABIC = "هذه فقرة باللغة العربية تُقرأ من اليمين إلى اليسار."
HEBREW = "זהו משפט בעברית שנקרא מימין לשמאל."
ENGLISH = "This is an ordinary English paragraph that reads left to right."


def test_an_arabic_document_detects_right_to_left():
    assert direction.detect(ARABIC) == direction.RTL


def test_a_hebrew_document_detects_right_to_left():
    assert direction.detect(HEBREW) == direction.RTL


def test_an_english_document_detects_left_to_right():
    assert direction.detect(ENGLISH) == direction.LTR


def test_a_document_with_no_strong_characters_is_left_to_right():
    # Neither direction is claimed, so nothing is mirrored.
    for text in ("", "   \n\n\t", "12345 67.89", "!?.,;:()[]{}", "€ £ ¥ ½ ×"):
        assert direction.detect(text) == direction.LTR, repr(text)


def test_nothing_that_is_not_a_string_reaches_the_counter():
    # render_document is called directly by scripts and tests, so a bad
    # argument must answer rather than raise.
    for value in (None, 0, [], {}, object()):
        assert direction.detect(value) == direction.LTR


def test_an_english_first_paragraph_does_not_decide_an_arabic_document():
    # The brief's own example, and the whole reason this counts rather than
    # taking the first strong character the way HTML's dir="auto" does.
    text = (
        "# Getting started\n\nThis project is documented in Arabic.\n\n"
        + (ARABIC + "\n\n") * 8
    )
    assert direction.detect(text) == direction.RTL


def test_a_few_arabic_quotations_do_not_flip_an_english_document():
    text = (ENGLISH + "\n\n") * 8 + "> " + ARABIC + "\n"
    assert direction.detect(text) == direction.LTR


def test_a_fenced_block_does_not_decide_the_direction():
    # A short Arabic note with a long Latin code sample is still an Arabic
    # document. Both fence markers are stripped.
    for fence in ("```", "~~~"):
        text = (
            ARABIC
            + f"\n\n{fence}python\n"
            + "def compute_the_running_total(collection_of_values):\n" * 6
            + f"{fence}\n"
        )
        assert direction.detect(text) == direction.RTL, fence


def test_an_unterminated_fence_is_left_alone():
    # Python-Markdown does not treat it as code either, so neither does this.
    text = "```\n" + "x = 1\n" * 40
    assert direction.detect(text) == direction.LTR


def test_inline_code_does_not_decide_the_direction():
    text = ARABIC + " `git status --short --branch --porcelain=v2` " + ARABIC
    assert direction.detect(text) == direction.RTL


def test_a_link_destination_does_not_decide_the_direction_but_its_text_does():
    stripped = "[نص](https://example.com/a/very/long/path/to/somewhere/deep)"
    assert direction.detect(stripped) == direction.RTL
    # The link *text* is prose and is counted.
    assert direction.detect("[English link](https://example.com)") == direction.LTR


def test_a_reference_definition_does_not_decide_the_direction():
    text = ARABIC + "\n\n[ref]: https://example.com/a/long/path/to/a/document\n"
    assert direction.detect(text) == direction.RTL


def test_a_raw_html_tag_does_not_decide_the_direction():
    text = ARABIC + '\n\n<span class="a-very-long-class-name-indeed">x</span>\n'
    assert direction.detect(text) == direction.RTL


def test_indented_content_is_counted_rather_than_guessed_at():
    # A four-space indent is a nested list item as often as it is a code
    # block, and only Markdown's block context can tell them apart. Dropping
    # it would delete real Arabic prose from the count.
    text = "- عنصر\n\n    " + ARABIC + "\n"
    assert direction.detect(text) == direction.RTL


def test_resolve_honours_a_forced_direction_over_the_content():
    assert direction.resolve(direction.LTR, ARABIC) == direction.LTR
    assert direction.resolve(direction.RTL, ENGLISH) == direction.RTL


def test_resolve_falls_through_to_detection_on_auto():
    assert direction.resolve(direction.AUTO, ARABIC) == direction.RTL
    assert direction.resolve(direction.AUTO, ENGLISH) == direction.LTR


def test_resolve_is_forgiving_about_case_and_space_like_the_setting_is():
    assert direction.resolve("  RTL  ", ENGLISH) == direction.RTL


def test_resolve_treats_an_unusable_setting_value_as_auto():
    # The settings descriptor's default is "auto", so a junk value detects
    # rather than raising or pinning a direction the user did not choose.
    for value in ("nonsense", "", None, 7, True, [], {}):
        assert direction.resolve(value, ARABIC) == direction.RTL
        assert direction.resolve(value, ENGLISH) == direction.LTR


def test_coerce_ui_answers_one_of_exactly_two_strings():
    assert direction.coerce_ui(direction.RTL) == direction.RTL
    for value in (direction.LTR, direction.AUTO, "nonsense", None, 7, object()):
        assert direction.coerce_ui(value) == direction.LTR
