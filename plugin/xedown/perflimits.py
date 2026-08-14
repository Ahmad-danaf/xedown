"""How large a document may be before xedown stops rendering it eagerly.

Pure, and modelled on `imagelimits.py`: the numbers and the decision live
here so they can be tested without a display, and `controller.py` holds
only the wiring. Both thresholds are constants rather than settings, for
the same reason `imagelimits.MAX_PIXELS` is -- they are a floor under a
failure mode, not a preference.

Why this exists at all: xedown renders synchronously on the GTK main
thread, so freeze time equals render time. Measured on the pipeline as
shipped, prose costs 174 ms at 100k characters, 903 ms at 500k and
1,817 ms at 1M. Nothing yields during that, so a large document without a
guard is an editor that stops responding.

    COUNTED IN CHARACTERS, NOT BYTES.

Python-Markdown works on `str`, so cost tracks characters. Counting bytes
would overstate a CJK or Arabic document's work by up to 3x and fire the
guard early on exactly the documents the compatibility pass worked to
support -- and `len(text)` is free where an encode is not, on a path that
runs per keystroke. `describe_bytes` below is the one place bytes appear:
the human-readable label on the chip, built once when the chip appears.

Shape matters more than size and this cannot see shape -- at 100k
characters the spread from prose to tables is 5x. A byte or character
count is used anyway because it is the only thing knowable *before*
paying the render, which is the cost being avoided. The consequence is
published rather than hidden: see `docs/performance.md`.
"""

from typing import NamedTuple

# The point at which a typical document's render exceeds the debounce
# interval. `settings.REFRESH_DELAY_MS` defaults to 250 ms; past this size
# a reader typing continuously leaves the editor busy more often than
# idle, and the debounce stops being a debounce. Corpus documents measure
# 245 ms at 110k characters and 293 ms at 152k, which brackets the
# crossing here.
LIVE_REFRESH_MAX_CHARS = 128 * 1024

# The point at which an *unrequested* render costs about a second. The
# slowest real corpus document measures 874 ms at 233k characters. Above
# this, a tab whose saved mode is Preview shows its source and offers the
# preview instead of building one nobody asked for.
DEFER_INITIAL_MIN_CHARS = 256 * 1024


class Decision(NamedTuple):
    live_refresh: bool
    defer_initial: bool


_UNCONSTRAINED = Decision(live_refresh=True, defer_initial=False)


def classify(char_count):
    """What to do with a document of `char_count` characters.

    Anything that is not a positive integer is unconstrained rather than
    an error. This is consulted from `_on_buffer_changed` and from the
    build path, neither of which may raise, so a bad value degrades to
    "no limit" -- the same reasoning as `settings.BoolSetting.coerce` and
    `direction.coerce_ui`. `bool` is excluded explicitly because it is a
    subclass of `int` and `classify(True)` is a caller error, not a
    one-character document.
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

    Bytes, not characters, because this is the number a reader recognises
    from their file manager. Built once, when the chip appears -- never on
    the per-keystroke path.
    """
    if isinstance(byte_count, bool) or not isinstance(byte_count, int):
        return ""
    if byte_count < 0:
        return ""
    if byte_count >= 1024 * 1024:
        return f"{byte_count / (1024 * 1024):.1f} MB"
    return f"{round(byte_count / 1024)} KB"
