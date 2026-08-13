"""What an image reference means, and what is shown when it cannot be shown."""

import base64
import os
import struct
import zlib

import pytest
from xedown import imagelimits, images, remoteimages
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


def data_uri(width, height, subtype="png"):
    """A `data:` image that is tiny on the wire whatever it declares."""

    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    )
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/{subtype};base64,{encoded}"


def test_a_data_uri_is_shown_without_touching_the_filesystem():
    # A real 1x1 PNG, not just the bare signature: the size check now reads
    # the IHDR, and a signature with no header is corrupt, not tiny.
    reference = data_uri(1, 1)
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


@pytest.mark.parametrize(
    "reference",
    ["https:///a.png", "https://", "https:/a.png", "https://[oops/a.png"],
)
def test_a_malformed_remote_reference_is_unresolved_not_remote(reference):
    decision = images.classify_image(reference, None, fetch_remote=True)
    assert decision.status == images.UNRESOLVED


def test_mailto_and_credentials_stay_remote_not_unresolved():
    assert (
        images.classify_image("mailto:a@b.c", None, fetch_remote=True).status
        == images.REMOTE
    )
    assert (
        images.classify_image(
            "https://u:p@example.com/a.png", None, fetch_remote=True
        ).status
        == images.REMOTE
    )


def test_reason_text_refuses_to_call_a_usable_image_missing():
    fetch_decision = images.classify_image(
        "https://e.com/a.png", None, fetch_remote=True
    )
    ok_decision = images.classify_image(data_uri(1, 1), None)
    for decision in (fetch_decision, ok_decision):
        text = images.reason_text(decision)
        assert "not found" not in text
        assert "has not been saved" not in text


def test_a_data_image_declaring_too_many_pixels_is_refused():
    decision = images.classify_image(data_uri(10000, 10000), None)
    assert decision.status == images.TOO_LARGE_TO_DECODE
    assert "10000" in images.reason_text(decision)


def test_the_data_limit_matches_the_remote_one_exactly():
    # One shared set of limits, not two that can drift apart.
    #
    # 5000x5001 is chosen so it trips the PIXEL cap and nothing else: both
    # sides are far below MAX_SIDE, so this fails if and only if MAX_PIXELS
    # is what it should be. A shape like (MAX_PIXELS + 1) x 1 would look
    # equivalent and is not -- its width also exceeds MAX_SIDE, so it would
    # keep passing even if the pixel cap were wrong.
    assert 5000 * 5001 > imagelimits.MAX_PIXELS
    assert max(5000, 5001) < imagelimits.MAX_SIDE
    assert images.classify_image(data_uri(5000, 5001), None).status == (
        images.TOO_LARGE_TO_DECODE
    )


@pytest.mark.parametrize(
    ("name", "width", "height"),
    [
        ("4K screenshot", 3840, 2160),
        ("24 MP DSLR photo", 6000, 4000),
        ("tall full-page screenshot", 1200, 20000),
        ("small inline badge", 88, 31),
    ],
)
def test_ordinary_inline_images_still_render(name, width, height):
    decision = images.classify_image(data_uri(width, height), None)
    assert decision.status == images.OK, f"{name} must still render"


def test_exactly_the_pixel_cap_still_renders():
    assert images.classify_image(data_uri(5000, 5000), None).status == images.OK


def test_an_unmeasurable_data_image_is_left_exactly_as_it_was():
    # AVIF cannot be measured. Refusing what has always worked would be a
    # worse regression than the bug being fixed.
    decision = images.classify_image("data:image/avif;base64,AAAA", None)
    assert decision.status == images.OK


def test_a_non_base64_data_uri_is_left_alone():
    decision = images.classify_image("data:image/gif,%89PNG", None)
    assert decision.status == images.OK


def test_a_malformed_payload_does_not_raise():
    decision = images.classify_image("data:image/png;base64,!!!not base64!!!", None)
    assert decision.status == images.OK


def test_the_refusal_honours_the_fallback_setting():
    decision = images.classify_image(data_uri(10000, 10000), None)
    assert images.placeholder_for(decision, "alt", images.DISPLAY_HIDDEN) is None


def test_a_data_image_with_only_a_signature_is_damaged_not_too_large():
    # No IHDR at all -- this is not "declares 0x0 pixels", it is unreadable.
    # Reusing TOO_LARGE_TO_DECODE's wording here would tell the reader a
    # corrupt image is an oversized one, which is neither true nor useful.
    signature_only = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    decision = images.classify_image(f"data:image/png;base64,{signature_only}", None)
    assert decision.status == images.DAMAGED
    text = images.reason_text(decision)
    assert "too large" not in text
    assert "0×0" not in text


def test_a_data_image_truncated_mid_ihdr_is_also_damaged():
    # Enough of a chunk header to claim PNG, not enough of it to read.
    partial = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + b"\x00\x00"
    encoded = base64.b64encode(partial).decode("ascii")
    decision = images.classify_image(f"data:image/png;base64,{encoded}", None)
    assert decision.status == images.DAMAGED
    text = images.reason_text(decision)
    assert "too large" not in text
    assert "0×0" not in text


def test_a_genuine_bomb_is_still_too_large_not_damaged():
    decision = images.classify_image(data_uri(20000, 20000), None)
    assert decision.status == images.TOO_LARGE_TO_DECODE
    assert "20000" in images.reason_text(decision)


def test_the_damaged_outcome_honours_the_fallback_setting():
    signature_only = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    decision = images.classify_image(f"data:image/png;base64,{signature_only}", None)
    assert images.placeholder_for(decision, "alt", images.DISPLAY_HIDDEN) is None


def _jpeg_with_exif(width, height, exif_size):
    """A JPEG whose SOF sits after an APP1/EXIF segment `exif_size` bytes
    long -- the way a real phone or camera photo is laid out, and unlike
    `data_uri`'s PNGs, where the header is always the first few bytes.
    """

    def segment(marker, payload):
        return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload

    app1 = segment(0xE1, b"Exif\x00\x00" + b"\x00" * exif_size)
    sof = segment(0xC0, struct.pack(">BHHB", 8, height, width, 3))
    return b"\xff\xd8" + app1 + sof + b"\xff\xd9"


def jpeg_data_uri(width, height, exif_size=0):
    encoded = base64.b64encode(_jpeg_with_exif(width, height, exif_size)).decode(
        "ascii"
    )
    return f"data:image/jpeg;base64,{encoded}"


@pytest.mark.parametrize("exif_size", [0, 3000, 10000, 40000])
def test_a_jpeg_with_a_large_exif_header_still_renders(exif_size):
    # A real photo's frame header can sit tens of kilobytes into the file,
    # behind an embedded EXIF thumbnail. There is no fixed prefix budget any
    # more -- see _data_uri_verdict -- so this must still measure correctly
    # rather than being refused as unmeasurable.
    decision = images.classify_image(jpeg_data_uri(6000, 4000, exif_size), None)
    assert decision.status == images.OK, f"exif_size={exif_size} must still render"


def test_a_jpeg_bomb_behind_a_large_exif_header_is_still_refused():
    # Proves removing the prefix budget did not reopen the hole it closed:
    # an oversized SOF pushed far into the payload by a padded EXIF segment
    # must still be found and refused, not waved through as unmeasurable.
    decision = images.classify_image(jpeg_data_uri(20000, 20000, 40000), None)
    assert decision.status == images.TOO_LARGE_TO_DECODE
    assert "20000" in images.reason_text(decision)
