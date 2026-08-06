"""WCAG 2.1 relative luminance and contrast ratio.

Test-only: it exists to keep the themes honest, and shipping it inside the
plugin would be dead code at run time. Brief 13 extends the table in
test_contrast.py rather than writing a second checker.
"""


def relative_luminance(colour):
    """WCAG 2.1 relative luminance of a `#rgb` or `#rrggbb` colour."""
    digits = colour.strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) != 6:
        raise ValueError(f"not a hex colour: {colour!r}")
    channels = []
    for start in (0, 2, 4):
        value = int(digits[start : start + 2], 16) / 255
        channels.append(
            value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background):
    """The WCAG contrast ratio between two colours, lighter over darker."""
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)
