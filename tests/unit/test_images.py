"""What an image reference means, and what is shown when it cannot be shown."""

import os

import pytest
from xedown import images, remoteimages
from xedown.sanitizer import ImagePlaceholder

# Root bypasses the read permission bit, so an unreadable-file assertion
# would pass for the wrong reason there.
not_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root can read a file with mode 000",
)


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "pics" / "a.png"
    path.parent.mkdir()
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def test_a_readable_local_file_is_shown(tmp_path, image):
    decision = images.classify_image("pics/a.png", str(tmp_path))
    assert decision.status == images.OK
    assert decision.uri.startswith("file://")
    assert decision.uri.endswith("/pics/a.png")


def test_a_data_uri_is_shown_without_touching_the_filesystem():
    reference = "data:image/png;base64,iVBORw0KGgo="
    decision = images.classify_image(reference, None)
    assert decision.status == images.OK
    assert decision.uri == reference


def test_a_remote_https_reference_is_blocked_unless_permitted(tmp_path):
    decision = images.classify_image("https://example.com/a.png", str(tmp_path))
    assert decision.status == images.REMOTE_BLOCKED


def test_a_relative_reference_with_no_base_directory_is_unresolved():
    assert images.classify_image("pics/a.png", None).status == images.UNRESOLVED


def test_a_path_that_is_not_there_is_missing(tmp_path):
    decision = images.classify_image("pics/gone.png", str(tmp_path))
    assert decision.status == images.MISSING
    assert decision.path.endswith("/pics/gone.png")


def test_a_broken_symlink_is_missing(tmp_path):
    link = tmp_path / "broken.png"
    link.symlink_to(tmp_path / "nothing.png")
    assert images.classify_image("broken.png", str(tmp_path)).status == images.MISSING


def test_a_directory_is_unreadable_rather_than_missing(tmp_path):
    (tmp_path / "folder.png").mkdir()
    decision = images.classify_image("folder.png", str(tmp_path))
    assert decision.status == images.UNREADABLE
    assert "regular file" in decision.detail


@not_root
def test_a_file_that_cannot_be_opened_is_unreadable(tmp_path, image):
    image.chmod(0o000)
    try:
        decision = images.classify_image("pics/a.png", str(tmp_path))
    finally:
        image.chmod(0o644)
    assert decision.status == images.UNREADABLE
    assert decision.detail


def test_malformed_input_never_raises_and_is_never_shown(tmp_path):
    for reference in ("a\x00b.png", "http://[unclosed/a.png", "%%%.png", None, ""):
        assert images.classify_image(reference, str(tmp_path)).status != images.OK


def test_the_reason_names_the_resolved_path_not_the_reference(tmp_path):
    decision = images.classify_image("pics/gone.png", str(tmp_path))
    text = images.reason_text(decision)
    assert str(tmp_path) in text
    assert "not found" in text


def test_placeholder_mode_gives_the_reason_and_the_alt_text(tmp_path):
    decision = images.classify_image("pics/gone.png", str(tmp_path))
    placeholder = images.placeholder_for(decision, "A logo", images.DISPLAY_PLACEHOLDER)
    assert isinstance(placeholder, ImagePlaceholder)
    assert placeholder.kind == "error"
    assert "not found" in placeholder.text
    assert "A logo" in placeholder.text


def test_alt_mode_gives_only_the_alt_text(tmp_path):
    decision = images.classify_image("pics/gone.png", str(tmp_path))
    placeholder = images.placeholder_for(decision, "A logo", images.DISPLAY_ALT)
    assert placeholder.kind == "alt"
    assert placeholder.text == "A logo"


def test_alt_mode_with_no_alt_text_shows_nothing(tmp_path):
    decision = images.classify_image("pics/gone.png", str(tmp_path))
    assert images.placeholder_for(decision, "   ", images.DISPLAY_ALT) is None


def test_hidden_mode_shows_nothing_whatever_the_reason(tmp_path):
    for reference in ("pics/gone.png", "https://example.com/a.png"):
        decision = images.classify_image(reference, str(tmp_path))
        assert images.placeholder_for(decision, "A logo", images.DISPLAY_HIDDEN) is None


@pytest.mark.parametrize(
    "status_reference",
    ["pics/gone.png", "https://example.com/a.png", "folder.png"],
)
def test_every_failure_obeys_the_display_setting(tmp_path, status_reference):
    # The setting is named remote_images, but a reader who asked for no
    # broken-image noise did not mean only the remote kind.
    (tmp_path / "folder.png").mkdir()
    decision = images.classify_image(status_reference, str(tmp_path))
    assert decision.status != images.OK
    assert images.placeholder_for(decision, "", images.DISPLAY_HIDDEN) is None
    assert images.placeholder_for(decision, "x", images.DISPLAY_ALT).kind == "alt"
    assert (
        images.placeholder_for(decision, "", images.DISPLAY_PLACEHOLDER).kind == "error"
    )


@pytest.mark.parametrize(
    "given,expected",
    [
        ("hidden", "hidden"),
        ("  ALT  ", "alt"),
        ("nonsense", "placeholder"),
        (None, "placeholder"),
        (7, "placeholder"),
    ],
)
def test_an_unusable_display_value_falls_back_to_the_default(given, expected):
    assert images.coerce_display(given) == expected


def test_an_https_image_is_fetchable_when_permitted():
    decision = images.classify_image(
        "https://example.com/a.png", None, fetch_remote=True
    )
    assert decision.status == images.FETCH
    assert decision.uri == remoteimages.scheme_uri("https://example.com/a.png")


def test_an_https_image_is_blocked_by_default():
    decision = images.classify_image("https://example.com/a.png", None)
    assert decision.status == images.REMOTE_BLOCKED
    assert decision.uri is None


def test_an_http_image_is_refused_even_when_fetching_is_permitted():
    decision = images.classify_image(
        "http://example.com/a.png", None, fetch_remote=True
    )
    assert decision.status == images.REMOTE_INSECURE


def test_a_credential_bearing_url_is_never_fetchable():
    decision = images.classify_image(
        "https://u:p@example.com/a.png", None, fetch_remote=True
    )
    assert decision.status != images.FETCH


def test_a_mailto_image_keeps_the_old_remote_wording():
    decision = images.classify_image("mailto:a@b.c", None, fetch_remote=True)
    assert decision.status == images.REMOTE


def test_each_refusal_says_something_different():
    texts = {
        images.reason_text(images.classify_image("https://e.com/a.png", None)),
        images.reason_text(
            images.classify_image("http://e.com/a.png", None, fetch_remote=True)
        ),
    }
    assert len(texts) == 2
    assert any("not encrypted" in text for text in texts)


def test_the_insecure_placeholder_still_honours_the_fallback_setting():
    decision = images.classify_image("http://e.com/a.png", None)
    assert images.placeholder_for(decision, "alt words", images.DISPLAY_HIDDEN) is None


def test_render_stats_count_each_kind():
    stats = images.RenderStats()
    stats.record(images.classify_image("https://e.com/a.png", None))
    stats.record(images.classify_image("https://e.com/b.png", None))
    stats.record(images.classify_image("http://e.com/c.png", None))
    assert stats.blocked_remote == 2
    assert stats.insecure == 1
    assert stats.remote == 0


def test_a_failure_kind_becomes_a_sentence():
    from xedown import errors, imagefetch

    text = errors.remote_image_failure_text(imagefetch.TOO_MANY_PIXELS, "10000×10000")
    assert "10000×10000" in text
    assert errors.remote_image_failure_text(imagefetch.OFFLINE, "").strip()
