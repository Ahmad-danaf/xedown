"""WCAG 2.1 relative luminance and contrast ratio, plus CIE76 colour difference.

Test-only: it exists to keep the themes honest, and shipping it inside the
plugin would be dead code at run time. Brief 13 extends the table in
test_contrast.py rather than writing a second checker.

Two measures, each where it belongs: contrast ratio answers "can this be
read", ΔE answers "is this a different colour from that one". Brief 11 needs
both, because a search highlight has to be legible *and* not look like the
selection.
"""


def _srgb(colour):
    """The three 0..1 sRGB channels of a `#rgb` or `#rrggbb` colour."""
    digits = colour.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) != 6:
        raise ValueError(f"not a hex colour: {colour!r}")
    return [int(digits[start : start + 2], 16) / 255 for start in (0, 2, 4)]


def relative_luminance(colour):
    """WCAG 2.1 relative luminance of a `#rgb` or `#rrggbb` colour."""
    channels = [
        value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        for value in _srgb(colour)
    ]
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background):
    """The WCAG contrast ratio between two colours, lighter over darker."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


# D65, the illuminant sRGB is defined against.
_WHITE_POINT = (0.95047, 1.0, 1.08883)


def _lab(colour):
    """CIE L*a*b* for a hex colour.

    Note the transfer function here uses sRGB's own 0.04045 threshold rather
    than the 0.03928 WCAG writes above: the two differ in the sixth decimal of
    the result and each is correct for its own formula, so neither is made to
    borrow the other's constant.
    """
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in _srgb(colour)
    ]
    red, green, blue = linear
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / _WHITE_POINT[0]
    y = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / _WHITE_POINT[1]
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / _WHITE_POINT[2]

    def f(value):
        return value ** (1 / 3) if value > 216 / 24389 else (841 / 108) * value + 4 / 29

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(first, second):
    """CIE76 colour difference: how far apart two colours look.

    Contrast ratio compares luminance and nothing else, so it cannot tell an
    amber highlight from a tan selection of the same weight. This can. Used
    only for the "distinguishable from" rows in test_contrast.py; legibility
    is still a contrast question and still uses the ratio above.
    """
    first_l, first_a, first_b = _lab(first)
    second_l, second_a, second_b = _lab(second)
    return (
        (first_l - second_l) ** 2
        + (first_a - second_a) ** 2
        + (first_b - second_b) ** 2
    ) ** 0.5
