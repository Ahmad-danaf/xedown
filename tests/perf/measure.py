"""Time each layer of the render pipeline separately.

Parse, sanitize, fragment and whole document are four different numbers
and the difference between them is where a finding actually lives. The
compatibility audit is the evidence: three of its twenty-one findings had
their mechanism in a different layer from the symptom.

`repeat` takes the *best* of n rather than the mean. A benchmark on a
desktop competes with whatever else is running; the minimum is the run
least disturbed by something that is not the code under test.
"""

import time
from typing import NamedTuple

from xedown import renderer
from xedown.sanitizer import sanitize


class Timing(NamedTuple):
    chars: int
    parse_ms: float
    sanitize_ms: float
    fragment_ms: float
    document_ms: float


def _best_ms(fn, repeat):
    best = float("inf")
    for _ in range(max(1, repeat)):
        started = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - started) * 1000.0)
    return best


def time_layers(text, base_dir=None, repeat=3):
    """Time the four layers over `text`.

    The parse layer builds a fresh converter each time deliberately:
    `renderer._build_converter()` costs 0.5 ms, measured, and that is what
    the real render path pays. Reusing one here would measure something
    xedown never does.
    """
    raw_holder = {}

    def parse():
        converter = renderer._build_converter()
        raw_holder["raw"] = converter.convert(text or "")

    parse_ms = _best_ms(parse, repeat)
    raw = raw_holder["raw"]

    return Timing(
        chars=len(text),
        parse_ms=parse_ms,
        sanitize_ms=_best_ms(lambda: sanitize(raw), repeat),
        fragment_ms=_best_ms(
            lambda: renderer.render_fragment(text, base_dir=base_dir), repeat
        ),
        document_ms=_best_ms(
            lambda: renderer.render_document(text, base_dir=base_dir), repeat
        ),
    )
