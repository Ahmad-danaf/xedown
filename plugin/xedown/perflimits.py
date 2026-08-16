"""How large a document may be before xedown stops rendering it eagerly.

xedown renders synchronously on the GTK main thread, so freeze time equals
render time and a large document without a guard is an editor that stops
responding. Both thresholds are constants rather than settings: they are a
floor under a failure mode, not a preference.

    COUNTED IN CHARACTERS, NOT BYTES.

Python-Markdown works on `str`, so cost tracks characters; counting bytes
would overstate a CJK or Arabic document by up to 3x and fire the guard
early on exactly the documents the compatibility pass worked to support.
`describe_bytes` is the one place bytes appear.

Size cannot see shape, and shape matters more -- at 100k characters the
spread from prose to tables is 8x. It is used anyway because it is the only
thing knowable *before* paying the render. Measurements behind both numbers
are in `docs/performance.md`.
"""

from typing import NamedTuple

# Where a typical render exceeds the 250 ms debounce, so that typing leaves
# the editor busy more often than idle. Sits 16% under the measured crossing
# deliberately: being early costs only a visible Refresh button.
LIVE_REFRESH_MAX_CHARS = 128 * 1024

# Where an *unrequested* render costs about a second, so a tab whose saved
# mode is Preview shows its source and offers the preview instead. Calibrated
# against dense tables, the most expensive shape real documents were measured
# to have. Knowingly does not cover the repeated-headings shape, which crosses
# a second nearer 155,000 characters: that residual is accepted because a
# threshold there would sit almost on top of LIVE_REFRESH_MAX_CHARS and defer
# four corpus documents that render in 317-636 ms.
DEFER_INITIAL_MIN_CHARS = 256 * 1024


class Decision(NamedTuple):
    live_refresh: bool
    defer_initial: bool


_UNCONSTRAINED = Decision(live_refresh=True, defer_initial=False)


def classify(char_count):
    """What to do with a document of `char_count` characters.

    A bad value degrades to "no limit" rather than raising: the callers
    (`_on_buffer_changed` and the build path) may not raise. `bool` is
    excluded explicitly because it is a subclass of `int`, so
    `classify(True)` is a caller error, not a one-character document.
    """
    if isinstance(char_count, bool) or not isinstance(char_count, int):
        return _UNCONSTRAINED
    if char_count <= 0:
        return _UNCONSTRAINED
    return Decision(
        live_refresh=char_count <= LIVE_REFRESH_MAX_CHARS,
        defer_initial=char_count > DEFER_INITIAL_MIN_CHARS,
    )


def describe_bytes(byte_count):
    """A short human size for the mode bar's chip, or "" if unknowable.

    Bytes, not characters, because that is the number a reader recognises
    from their file manager. Built once when the chip appears, never on the
    per-keystroke path.
    """
    if isinstance(byte_count, bool) or not isinstance(byte_count, int):
        return ""
    if byte_count < 0:
        return ""
    if byte_count >= 1024 * 1024:
        return f"{byte_count / (1024 * 1024):.1f} MB"
    return f"{round(byte_count / 1024)} KB"
