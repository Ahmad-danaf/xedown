import re

from xedown import errors


def test_error_page_is_a_complete_html_document():
    page = errors.error_page("Cannot render", "something broke")
    assert page.startswith("<!DOCTYPE html>")
    assert "</html>" in page
    assert "Cannot render" in page
    assert "something broke" in page


def test_error_page_escapes_its_inputs():
    page = errors.error_page("<script>alert(1)</script>", "<img onerror=x>")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    # Markup is inert when tag delimiters are escaped
    assert "<img" not in page
    assert "&lt;img onerror=x&gt;" in page


def test_error_page_has_no_external_references():
    page = errors.error_page("t", "d")
    assert "http://" not in page
    assert "https://" not in page


def test_error_page_honours_dark_mode():
    light = errors.error_page("t", "d", dark=False)
    dark = errors.error_page("t", "d", dark=True)
    assert "dark" in dark
    # Verify styling actually differs between modes
    assert "#ffffff" in light  # Light mode background
    assert "#1e1e1e" in dark  # Dark mode background
    assert light != dark


def test_render_failure_detail_names_the_exception_type():
    detail = errors.render_failure_detail(ValueError("bad token"))
    assert "ValueError" in detail
    assert "bad token" in detail


def test_missing_vendor_detail_says_the_release_is_incomplete():
    detail = errors.missing_vendor_detail(RuntimeError("markdown missing"))
    assert "incomplete" in detail.lower()
    assert "markdown missing" in detail


def test_unsaved_hint_explains_relative_paths():
    assert "save" in errors.UNSAVED_DOCUMENT_HINT.lower()


def test_remote_image_text_names_the_uri_and_states_a_fact():
    uri = "https://example.com/a.png"
    text = errors.remote_image_text(uri)
    assert uri in text
    assert "not fetched" in text


def test_local_image_missing_text_names_the_path():
    assert "/tmp/gone.png" in errors.local_image_missing_text("/tmp/gone.png")
    assert "not found" in errors.local_image_missing_text("/tmp/gone.png")


def test_local_image_unreadable_text_carries_the_reason_when_there_is_one():
    with_detail = errors.local_image_unreadable_text("/tmp/a.png", "Permission denied")
    assert "Permission denied" in with_detail
    assert "could not be read" in with_detail
    # A missing reason must not leave an empty bracket dangling.
    assert errors.local_image_unreadable_text("/tmp/a.png") == (
        "Image could not be read: /tmp/a.png"
    )


def test_with_alt_appends_the_authors_words_only_when_there_are_any():
    result = errors.with_alt("Image not found: a.png", "Company logo")
    # em dash (U+2014) and curly quotes (U+201C, U+201D)
    expected = f"Image not found: a.png — {chr(0x201c)}Company logo{chr(0x201d)}"
    assert result == expected
    assert errors.with_alt("x", "") == "x"
    assert errors.with_alt("x", None) == "x"
    assert errors.with_alt("x", "   ") == "x"


# xedown never fetches remote images and no setting changes that, so no
# placeholder may hint at one. This is a rule from the brief, enforced here
# rather than left to review.
_IMPLIES_A_TOGGLE = re.compile(r"enable|allow|turn on|unblock|permit", re.IGNORECASE)


def test_no_image_wording_implies_remote_images_can_be_switched_on():
    for text in (
        errors.remote_image_text("https://example.com/a.png"),
        errors.local_image_missing_text("/tmp/a.png"),
        errors.local_image_unreadable_text("/tmp/a.png", "Permission denied"),
        errors.local_image_unresolved_text("a.png"),
    ):
        assert not _IMPLIES_A_TOGGLE.search(text), text


def test_local_image_unresolved_text_contains_uri_and_the_unsaved_hint():
    uri = "pic.png"
    text = errors.local_image_unresolved_text(uri)
    assert uri in text
    assert "save" in text.lower()
    assert "<" not in text
    assert ">" not in text


def test_the_stylesheet_notice_names_the_file_and_the_fallback():
    html_text = errors.user_stylesheet_notice(
        errors.STYLESHEET_EMPTY, "/home/you/mine.css", theme_label="Repository"
    )
    assert 'class="xedown-notice"' in html_text
    assert "/home/you/mine.css" in html_text
    assert "is empty" in html_text
    assert "Repository" in html_text


def test_the_stylesheet_notice_escapes_the_path():
    # The path comes out of a file the user hand-edits. It is data, not markup.
    html_text = errors.user_stylesheet_notice(
        errors.STYLESHEET_NOT_FOUND, "/tmp/<script>alert(1)</script>.css"
    )
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text


def test_the_stylesheet_notice_includes_the_reason_detail():
    html_text = errors.user_stylesheet_notice(
        errors.STYLESHEET_UNREADABLE, "/x.css", detail="Permission denied"
    )
    assert "Permission denied" in html_text


def test_the_stylesheet_notice_escapes_the_theme_label():
    html_text = errors.user_stylesheet_notice(
        errors.STYLESHEET_EMPTY, "/x.css", theme_label="<b>Nope</b>"
    )
    assert "<b>" not in html_text


def test_the_stylesheet_notice_escapes_a_phrase_containing_markup():
    # STYLESHEET_UNSAFE's own phrase contains a literal "</style", which the
    # HTML tokenizer reads as an end tag and follows to the next ">" -- the
    # notice's own closing </div>. Unescaped, that swallows half the message
    # and leaves the document nested inside the error bar.
    html_text = errors.user_stylesheet_notice(
        errors.STYLESHEET_UNSAFE, "/home/you/mine.css", theme_label="Repository"
    )
    assert "</style" not in html_text
    assert "&lt;/style" in html_text
    assert html_text.endswith("</div>")
    assert "cannot be embedded safely" in html_text
    assert "Showing the Repository theme." in html_text
