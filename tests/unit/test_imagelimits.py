"""Reading an image's declared size, and refusing what would exhaust memory."""

import struct
import zlib

import pytest
from xedown import imagelimits


def png_bytes(width, height):
    """A real, valid PNG header -- tiny on the wire whatever it declares."""

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)


def test_png_dimensions_come_from_the_header_alone():
    assert imagelimits.image_dimensions(png_bytes(1920, 1080)) == (1920, 1080)


def test_gif_dimensions():
    data = b"GIF89a" + struct.pack("<HH", 800, 600) + b"\x00\x00\x00"
    assert imagelimits.image_dimensions(data) == (800, 600)


def test_bmp_dimensions():
    data = b"BM" + b"\x00" * 12 + struct.pack("<Ii", 40, 640) + struct.pack("<i", 480)
    assert imagelimits.image_dimensions(data) == (640, 480)


def test_webp_vp8x_dimensions():
    body = b"VP8X" + struct.pack("<I", 10) + b"\x00" * 4
    body += bytes([0x3F, 0x00, 0x00]) + bytes([0x2B, 0x01, 0x00])  # 64x300
    data = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body
    assert imagelimits.image_dimensions(data) == (64, 300)


def test_jpeg_dimensions_come_from_the_frame_header():
    data = (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 4)
        + b"\x00\x00"
        + b"\xff\xc0"
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 1200, 1600)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (1600, 1200)


def test_an_unreadable_format_returns_none_rather_than_a_guess():
    # AVIF: dimensions live in an ISOBMFF `ispe` box. Guessing is not an
    # option when the guess is the protection.
    assert imagelimits.image_dimensions(b"\x00\x00\x00\x20ftypavif") is None
    assert imagelimits.image_dimensions(b"<svg xmlns=") is None
    assert imagelimits.image_dimensions(b"") is None


def test_truncated_input_returns_none_rather_than_raising():
    assert imagelimits.image_dimensions(png_bytes(100, 100)[:12]) is None


# --- bombs: a tiny payload declaring an enormous size ---------------------


@pytest.mark.parametrize("side", [10000, 20000, 30000])
def test_a_tiny_payload_declaring_an_enormous_size_is_refused(side):
    data = png_bytes(side, side)
    assert len(data) < 100, "the payload really is tiny; the declaration is not"
    verdict = imagelimits.pixel_verdict(data)
    assert verdict.ok is False
    assert verdict.known is True
    assert verdict.width == side


# --- not too restrictive: shapes that must keep working -------------------


@pytest.mark.parametrize(
    ("name", "width", "height"),
    [
        ("4K screenshot", 3840, 2160),
        ("24 MP DSLR photo", 6000, 4000),
        # A full-page screenshot of a long web page. MAX_SIDE = 16384 rejected
        # this while allowing a 10000x10000 image with four times the decode
        # cost, which is why the cap is 32768. Regression test for that.
        ("tall full-page screenshot", 1200, 20000),
        ("wide panorama", 12000, 2000),
        ("small inline badge", 88, 31),
    ],
)
def test_ordinary_large_images_are_allowed(name, width, height):
    verdict = imagelimits.pixel_verdict(png_bytes(width, height))
    assert verdict.ok is True, f"{name} ({width}x{height}) must still render"


# --- exact boundaries -----------------------------------------------------


def test_exactly_the_pixel_cap_is_allowed():
    # 5000 * 5000 == MAX_PIXELS exactly. The rule is "greater than", so this
    # is the largest square that renders.
    assert 5000 * 5000 == imagelimits.MAX_PIXELS
    assert imagelimits.pixel_verdict(png_bytes(5000, 5000)).ok is True


def test_one_pixel_over_the_cap_is_refused():
    assert imagelimits.pixel_verdict(png_bytes(5000, 5001)).ok is False


def test_exactly_the_side_cap_is_allowed():
    assert imagelimits.pixel_verdict(png_bytes(imagelimits.MAX_SIDE, 100)).ok is True


def test_one_pixel_over_the_side_cap_is_refused():
    verdict = imagelimits.pixel_verdict(png_bytes(imagelimits.MAX_SIDE + 1, 100))
    assert verdict.ok is False


def test_an_unmeasurable_payload_is_reported_as_unknown_not_as_refused():
    # Each caller decides what to do with "cannot measure": the fetch path
    # refuses, the data: path allows. The verdict must not decide for them.
    verdict = imagelimits.pixel_verdict(b"\x00\x00\x00\x20ftypavif")
    assert verdict.known is False
    assert verdict.ok is True


def test_a_verdict_describes_itself_for_the_placeholder():
    verdict = imagelimits.pixel_verdict(png_bytes(10000, 12000))
    assert verdict.describe() == "10000×12000 pixels"
