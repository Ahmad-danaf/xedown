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
    assert "onerror=x" not in page
    assert "&lt;script&gt;" in page


def test_error_page_has_no_external_references():
    page = errors.error_page("t", "d")
    assert "http://" not in page
    assert "https://" not in page


def test_error_page_honours_dark_mode():
    assert "dark" in errors.error_page("t", "d", dark=True)


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


def test_remote_image_blocked_text_contains_uri_and_blocked():
    uri = "https://example.com/image.png"
    text = errors.remote_image_blocked_text(uri)
    assert uri in text
    assert "blocked" in text.lower()
    assert "<" not in text
    assert ">" not in text
