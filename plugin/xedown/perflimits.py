"""How large a document may be before xedown stops rendering it eagerly.

Pure, and modelled on `imagelimits.py`: the numbers and the decision live
here so they can be tested without a display, and `controller.py` holds
only the wiring. Both thresholds are constants rather than settings, for
the same reason `imagelimits.MAX_PIXELS` is -- they are a floor under a
failure mode, not a preference.

Why this exists at all: xedown renders synchronously on the GTK main
thread, so freeze time equals render time. Measured on the pipeline as
shipped, prose costs 43 ms at 100k characters, 227 ms at 500k and 469 ms
at 1M; the same sizes in tables cost 349 ms, 1,960 ms and 3,963 ms.
Nothing yields during that, so a large document without a guard is an
editor that stops responding.

    COUNTED IN CHARACTERS, NOT BYTES.

Python-Markdown works on `str`, so cost tracks characters. Counting bytes
would overstate a CJK or Arabic document's work by up to 3x and fire the
guard early on exactly the documents the compatibility pass worked to
support -- and `len(text)` is free where an encode is not, on a path that
runs per keystroke. `describe_bytes` below is the one place bytes appear:
the human-readable label on the chip, built once when the chip appears.

Shape matters more than size and this cannot see shape -- at 100k
characters the spread from prose to tables is 8x, and to the densest
shape measured 15x. A byte or character count is used anyway because it
is the only thing knowable *before* paying the render, which is the cost
being avoided. The consequence is published rather than hidden: see
`docs/performance.md`.
"""

from typing import NamedTuple

# The point at which a *typical* document's render exceeds the debounce
# interval. `settings.REFRESH_DELAY_MS` defaults to 250 ms; past this size
# a reader typing continuously leaves the editor busy more often than
# idle, and the debounce stops being a debounce.
#
# Re-derived from the 31-document corpus (`--corpus`, best of 17 across
# three passes). Nothing under this size crosses 250 ms: the largest
# document below it, system-design-primer at 109,682 characters, renders
# in 179 ms, and the slowest per character below it, programming-jp at
# 98,280, in 206 ms. Fitting the corpus's own rate -- 1.60 us/char, least
# squares through the origin over all 31 -- puts 250 ms at about 155,800
# characters, so this sits 16% under the crossing. Left on the low side
# deliberately: the cost of being early here is a visible Refresh button,
# and "typical" is a median over a population whose spread is 3x.
LIVE_REFRESH_MAX_CHARS = 128 * 1024

# The point at which an *unrequested* render costs about a second. Above
# this, a tab whose saved mode is Preview shows its source and offers the
# preview instead of building one nobody asked for.
#
# The corpus cannot supply this crossing, which is the honest state of it:
# no real README measured reaches a second. The slowest is public-apis at
# 636 ms for 232,413 characters, and the largest, awesome-go at 404,874
# characters, costs only 514 ms. Extrapolating the corpus's central rate
# would put a second near 623,000 characters.
#
# It is calibrated against the most expensive shape real documents were
# measured to have -- dense tables, which is what the corpus's worst
# document per character is made of. The tables shape crosses 1,000 ms at
# about 305,000 characters (measured directly across the crossing -- 889 ms
# at 276,843, 1,099 ms at 333,111), and this sits 14% under that. At the
# corpus's own worst rate, 2.74 us/char, this size costs 718 ms. Between
# 262,144 and 305,000 the choice is immaterial: the same two of 31 corpus
# documents defer at either end.
#
# What that knowingly does not cover: the repeated-headings shape costs
# 6.46 us/char, so a document of this size shaped like a very large
# changelog costs about 1.6 s rather than 1 s, and crosses a second near
# 155,000 characters. The residual is accepted rather than calibrated
# away. That shape is a stress fixture, not a population -- it repeats
# each of four headings 1,389 times in 100k characters, where the corpus's
# worst genuinely repeated heading text occurs 16 times -- and a threshold
# near 155,000 would sit almost on top of LIVE_REFRESH_MAX_CHARS and would
# defer four corpus documents that render in 317-636 ms. Interrupting a
# third-of-a-second render is the worse failure. See `docs/performance.md`.
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
