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


def test_an_unrecognized_format_is_reported_as_unknown_not_as_refused():
    # A format we don't parse (AVIF) is unknown, not refused. The fetch path
    # refuses unmeasurable images, but only those claiming a format we parse.
    # Unknown formats get the benefit of the doubt: known=False, ok=True.
    verdict = imagelimits.pixel_verdict(b"\x00\x00\x00\x20ftypavif")
    assert verdict.known is False
    assert verdict.ok is True


def test_a_verdict_describes_itself_for_the_placeholder():
    verdict = imagelimits.pixel_verdict(png_bytes(10000, 12000))
    assert verdict.describe() == "10000×12000 pixels"


# --- Fix: Critical 1+2 - JPEG with large EXIF headers and 0xFF fill bytes -----


def test_jpeg_with_large_exif_header_finds_the_sof():
    # A JPEG with a large APP1 (EXIF) segment before the SOF. This used to
    # fail when the SOF pushed past 4096 bytes. Now it should measure correctly.
    # Build: SOI, APP1 with 3000+ bytes, then the real SOF.
    app1_payload = b"\x00" * 3000
    app1_length = struct.pack(">H", len(app1_payload) + 2)  # Length includes itself
    sof_frame = (
        b"\xff\xc0"  # SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 4000, 6000)  # height=4000, width=6000
        + b"\x03"
    )
    data = b"\xff\xd8" + b"\xff\xe1" + app1_length + app1_payload + sof_frame
    assert imagelimits.image_dimensions(data) == (6000, 4000)


def test_jpeg_with_0xff_fill_bytes_before_marker():
    # ITU-T.81 permits any number of 0xFF bytes before a marker.
    # A bomb without fill bytes: measured correctly
    bomb_no_fill = png_bytes(20000, 20000)
    assert imagelimits.image_dimensions(bomb_no_fill) == (20000, 20000)
    assert imagelimits.pixel_verdict(bomb_no_fill).ok is False

    # The same bomb with a 0xFF fill byte before the SOF0 marker.
    # The old code treated the fill byte as if it were the marker code,
    # reading bogus data and eventually giving up. Should now be measured.
    data = (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 4)
        + b"\x00\x00"
        + b"\xff\xff"  # 0xFF fill byte before the real SOF0 marker
        + b"\xc0"  # SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 20000, 20000)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (20000, 20000)
    # The bomb should now be correctly identified and refused
    assert imagelimits.pixel_verdict(data).ok is False


def test_jpeg_dht_segment_before_sof_does_not_confuse_walk():
    # DHT (0xC4) is a valid segment marker but not a start-of-frame.
    # The old code would skip reading its length in some cases.
    data = (
        b"\xff\xd8"
        + b"\xff\xc4"  # DHT
        + struct.pack(">H", 19)  # Length
        + b"X" * 17  # 19 - 2 bytes of payload
        + b"\xff\xc0"  # Real SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 480, 640)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (640, 480)


def test_jpeg_with_standalone_markers_before_sof():
    # Markers 0xD0-0xD7, 0xD8, 0xD9, 0x01 have no segment.
    # They should be skipped correctly.
    data = (
        b"\xff\xd8"  # SOI
        + b"\xff\xd0"  # RSTm
        + b"\xff\xd1"  # RSTm
        + b"\xff\xc0"  # SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 600, 800)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (800, 600)


def test_jpeg_byte_stuffed_0xff00_in_payload():
    # A 0xFF 0x00 sequence inside a segment payload should not be treated
    # as a marker. The segment length must carry the walk over it.
    payload_with_stuffing = b"\xff\x00" * 5  # Stuffed bytes
    segment_length = struct.pack(">H", len(payload_with_stuffing) + 2)
    data = (
        b"\xff\xd8"
        + b"\xff\xe0"  # APP0
        + segment_length
        + payload_with_stuffing
        + b"\xff\xc0"  # Real SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 1080, 1920)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (1920, 1080)


def test_jpeg_fake_sof_in_app1_payload_is_ignored():
    # If an APP1 payload happens to contain bytes that look like a SOF
    # marker, the segment length must carry the walk over them.
    fake_sof_in_app1 = (
        b"\xff\xc0" + b"\x00" * 10  # Looks like SOF0 but is inside APP1 payload
    )
    segment_length = struct.pack(">H", len(fake_sof_in_app1) + 2)
    data = (
        b"\xff\xd8"
        + b"\xff\xe1"  # APP1
        + segment_length
        + fake_sof_in_app1
        + b"\xff\xc0"  # Real SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 720, 1280)
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (1280, 720)


def test_jpeg_progressive_sof2_is_measured():
    # SOF2 (0xC2) is a progressive JPEG start-of-frame and must be recognized.
    data = (
        b"\xff\xd8"
        + b"\xff\xe0"  # APP0
        + struct.pack(">H", 4)
        + b"\x00\x00"
        + b"\xff\xc2"  # SOF2 (progressive)
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 2160, 3840)  # 4K resolution
        + b"\x03"
    )
    assert imagelimits.image_dimensions(data) == (3840, 2160)


# --- Fix: Important 3 - WebP VP8L at 25 bytes ----------------------------------


def test_webp_vp8l_25_bytes_is_measured():
    # A minimal valid VP8L is 25 bytes. The old 30-byte gate rejected it.
    # VP8L chunk: RIFF(4) + size(4) + WEBP(4) + VP8L(4) + chunk_size(4) +
    #            signature(1) + dimensions(4) = 25 bytes minimum
    # VP8L dimensions: width-1 in bits 0-13, height-1 in bits 14-27
    # For 16384×16384: (16383 & 0x3FFF) | ((16383 & 0x3FFF) << 14)
    dimensions_value = (16383 & 0x3FFF) | ((16383 & 0x3FFF) << 14)
    vp8l_chunk_size = 5  # 1 byte signature + 4 bytes dimensions
    vp8l_payload = b"\x00" + struct.pack("<I", dimensions_value)
    body = b"VP8L" + struct.pack("<I", vp8l_chunk_size) + vp8l_payload
    data = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body
    # Should measure as 16384×16384 (over the cap, so verdict.ok=False)
    dims = imagelimits.image_dimensions(data)
    assert dims == (16384, 16384)
    verdict = imagelimits.pixel_verdict(data)
    assert verdict.ok is False


# --- Fix: Important 4 - BMP BITMAPCOREHEADER vs BITMAPINFOHEADER ---------------


def test_bmp_bitmapcoreheader_os2_format():
    # OS/2 BITMAPCOREHEADER has DIB size = 12 and uses unsigned 16-bit fields.
    # The old code read signed 32-bit fields, mangling the dimensions.
    # BM + 12 bytes + DIB size 12 + width (uint16) + height (uint16)
    data = (
        b"BM"
        + b"\x00" * 12  # Filler
        + struct.pack("<I", 12)  # DIB header size = 12
        + struct.pack("<HH", 640, 480)  # width, height as unsigned 16-bit
    )
    assert imagelimits.image_dimensions(data) == (640, 480)


def test_bmp_top_down_bitmap_still_positive():
    # BITMAPINFOHEADER with negative height means top-down; abs() must apply.
    data = (
        b"BM"
        + b"\x00" * 12
        + struct.pack("<I", 40)  # BITMAPINFOHEADER
        + struct.pack("<i", 320)  # width (positive)
        + struct.pack("<i", -240)  # height (negative = top-down)
    )
    dims = imagelimits.image_dimensions(data)
    assert dims == (320, 240)  # Should be positive


def test_bmp_with_unknown_dib_size_returns_none():
    # If DIB header size is not 12 or >= 40, we cannot read dimensions safely.
    data = (
        b"BM"
        + b"\x00" * 12
        + struct.pack("<I", 32)  # DIB size 32: not recognized
        + b"\x00" * 10
    )
    assert imagelimits.image_dimensions(data) is None


# --- Fix Round 2: Structural safety - distinguish "not our format" from "corrupt" ---


@pytest.mark.parametrize("fill_count", [0, 1, 17, 18, 100, 10000])
def test_bomb_refused_at_any_fill_run_length(fill_count):
    # A 20000×20000 bomb with any number of 0xFF fill bytes before SOF.
    # With the new rule, it's always measured and refused, never allowed.
    fill_bytes = b"\xff" * fill_count
    sof_frame = (
        b"\xff\xc0"  # SOF0
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", 20000, 20000)
        + b"\x03"
    )
    data = (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 4)
        + b"\x00\x00"
        + fill_bytes
        + sof_frame
    )
    verdict = imagelimits.pixel_verdict(data)
    # Either measured and refused, or unmeasurable but claimed (refused on corruption).
    # With many fill bytes (~10000+), the walk exceeds _MAX_STEPS, returns None,
    # and refusal comes from "format claimed but unmeasurable" rule.
    assert verdict.ok is False, f"bomb with {fill_count} fill bytes must be refused"


def test_format_claimed_but_unmeasurable_is_refused():
    # A PNG with the magic bytes but truncated before IHDR: claims PNG but has
    # no dimensions. This is corruption or evasion, not a new format.
    truncated_png = png_bytes(100, 100)[:12]  # Just the magic and part of IHDR
    assert imagelimits.image_dimensions(truncated_png) is None
    verdict = imagelimits.pixel_verdict(truncated_png)
    # Should recognize PNG magic and refuse
    assert verdict.known is True
    assert verdict.ok is False


def test_not_our_format_still_allowed_as_unknown():
    # AVIF and other formats we don't parse: still ok=True, known=False.
    # The new rule only affects formats we claim to parse.
    verdict = imagelimits.pixel_verdict(b"\x00\x00\x00\x20ftypavif")
    assert verdict.known is False
    assert verdict.ok is True
