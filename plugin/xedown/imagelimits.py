"""How big an image claims to be, and whether that is safe to decode.

Pure, and deliberately dependency-free: it imports nothing of xedown's own, so
both the remote fetch path and the inline `data:` path can share it without a
cycle -- `images.py` already imports `remoteimages`, which rules out putting
these limits there.

The byte cap in `remoteimages.py` is a *download* limit and is a different
protection from this one, not a weaker version of it. Measured, with the
preview's real CSS applied so the image is displayed at 640x640:

    2000x2000     4 MP    17 KiB on the wire     212 MiB of WebProcess RSS
    10000x10000 100 MP   426 KiB on the wire     578 MiB
    20000x20000 400 MP   1.7 MiB on the wire    1727 MiB

Roughly four bytes per *declared* pixel: the decode happens at native
resolution and only then is the result scaled down, so `max-width` saves
nothing. WebKit refuses to decode at all somewhere past 400 megapixels, which
is far too late to be a protection.
"""

import struct

# 5000x5000 exactly, which covers a 24 MP DSLR photo and a 4K screenshot.
MAX_PIXELS = 25_000_000

# Not 16384. That is a common GPU texture limit and was the first value here,
# and it rejected a 1200x20000 full-page screenshot -- 24 MP, well under the
# pixel cap, and an ordinary thing to put in a README -- while allowing a
# 10000x10000 image costing four times as much to decode. At 32768 the side
# cap only bites on extreme geometry that is already under the pixel cap.
MAX_SIDE = 32_768


class PixelVerdict:
    """Whether an image may be decoded, and what it said its size was.

    `known` is False when the format could not be measured. The verdict does
    not decide what that should mean: the fetch path refuses an unmeasurable
    image, and the `data:` path allows it, because refusing what already works
    would be a worse regression than the bug being fixed.
    """

    def __init__(self, ok, width=0, height=0, known=True):
        self.ok = ok
        self.width = width
        self.height = height
        self.known = known

    def describe(self):
        """The size, for a placeholder the reader will actually read."""
        return f"{self.width}×{self.height} pixels"


def pixel_verdict(data):
    """Whether `data`'s declared size is safe to hand to a decoder."""
    size = image_dimensions(data)
    if size is None:
        return PixelVerdict(True, known=False)
    width, height = size
    ok = width * height <= MAX_PIXELS and width <= MAX_SIDE and height <= MAX_SIDE
    return PixelVerdict(ok, width=width, height=height, known=True)


def _png_dimensions(data):
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _gif_dimensions(data):
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return None
    return struct.unpack("<HH", data[6:10])


def _bmp_dimensions(data):
    if len(data) < 18 or data[:2] != b"BM":
        return None
    # Read DIB header size at bytes 14-18
    dib_size = struct.unpack("<I", data[14:18])[0]

    if dib_size == 12:
        # BITMAPCOREHEADER (OS/2): two unsigned 16-bit fields
        if len(data) < 22:
            return None
        width, height = struct.unpack("<HH", data[18:22])
        return width, abs(height)

    if dib_size >= 40:
        # BITMAPINFOHEADER or later: two signed 32-bit fields
        if len(data) < 26:
            return None
        width, height = struct.unpack("<ii", data[18:26])
        return abs(width), abs(height)

    # Unknown DIB header size
    return None


def _webp_dimensions(data):
    # Check RIFF/WEBP header
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    if len(data) < 20:
        return None
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    if kind == b"VP8 " and len(data) >= 30:
        return (
            int.from_bytes(data[26:28], "little") & 0x3FFF,
            int.from_bytes(data[28:30], "little") & 0x3FFF,
        )
    if kind == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


# Start-of-frame markers. SOF4/SOF8/SOF12 are not frame headers.
_JPEG_SOF = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


def _jpeg_dimensions(data):
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    limit = len(data)
    loop_limit = 4096  # Prevent DoS on highly fragmented files

    while index < limit:
        # Use find() for speed: C time instead of Python loop over non-marker bytes
        ff_pos = data.find(b"\xff", index)
        if ff_pos == -1:
            return None
        index = ff_pos

        # Skip consecutive 0xFF bytes (fill bytes per ITU-T.81)
        fill_start = index
        while index + 1 < limit and data[index + 1] == 0xFF:
            index += 1
            # Cap the fill-byte scan to prevent DoS
            if index - fill_start > 16:
                break

        if index + 1 >= limit:
            return None

        marker = data[index + 1]

        # Markers with no segment length
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            loop_limit -= 1
            if loop_limit < 0:
                return None
            continue

        # Byte stuffing: 0xFF 0x00 is escaped and not a marker
        if marker == 0x00:
            index += 2
            loop_limit -= 1
            if loop_limit < 0:
                return None
            continue

        # All other markers carry a segment with length field
        if index + 4 > limit:
            return None

        length = struct.unpack(">H", data[index + 2 : index + 4])[0]
        if length < 2:
            return None

        # Check for start-of-frame marker
        if marker in _JPEG_SOF:
            if index + 9 > limit:
                return None
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return width, height

        # Skip this segment (index points to FF, so add 2 for marker + length bytes)
        index += 2 + length
        loop_limit -= 1
        if loop_limit < 0:
            return None

    return None


_READERS = (
    _png_dimensions,
    _gif_dimensions,
    _bmp_dimensions,
    _webp_dimensions,
    _jpeg_dimensions,
)


def image_dimensions(data):
    """`(width, height)` read from `data`'s header, or None.

    None means "cannot be measured". What that should cause is the caller's
    decision, not this function's -- see `PixelVerdict.known`.

    Formats with large headers (JPEG with EXIF) are read in full. Format-
    specific readers enforce their own bounds; this module's DoS protection
    lives in _jpeg_dimensions' loop limit.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None
    for reader in _READERS:
        try:
            result = reader(data)
        except (struct.error, IndexError, ValueError):
            continue
        if result is not None and result[0] > 0 and result[1] > 0:
            return result
    return None
