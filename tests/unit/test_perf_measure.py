"""The measurement helper reports per-layer times, not one number."""

from tests.perf import generate, measure


def test_reports_every_layer():
    timing = measure.time_layers(generate.build("prose", 2000), repeat=1)
    assert timing.chars > 0
    for field in ("parse_ms", "sanitize_ms", "fragment_ms", "document_ms"):
        assert getattr(timing, field) > 0.0, f"{field} was not measured"


def test_fragment_and_document_layers_are_both_measured():
    # This used to also assert `document_ms >= fragment_ms * 0.75` -- a
    # wall-clock ratio between two independently timed runs on a shared
    # runner, which is exactly the class of assertion clock-based guards
    # elsewhere in this codebase were rejected for. It flaked once during
    # review and was removed rather than loosened: a looser threshold
    # still flakes, just less often. `render_document` being `render_
    # fragment` plus a page around it is a real invariant, but a timing
    # comparison was never a sound way to check it; what is safe to keep
    # is that both layers ran and measured something, for a document
    # bigger than test_reports_every_layer's.
    timing = measure.time_layers(generate.build("prose", 20_000), repeat=2)
    assert timing.fragment_ms > 0.0
    assert timing.document_ms > 0.0


def test_an_empty_document_still_measures():
    timing = measure.time_layers("", repeat=1)
    assert timing.chars == 0
    assert timing.document_ms > 0.0
