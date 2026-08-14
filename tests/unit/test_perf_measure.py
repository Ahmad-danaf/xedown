"""The measurement helper reports per-layer times, not one number."""

from tests.perf import generate, measure


def test_reports_every_layer():
    timing = measure.time_layers(generate.build("prose", 2000), repeat=1)
    assert timing.chars > 0
    for field in ("parse_ms", "sanitize_ms", "fragment_ms", "document_ms"):
        assert getattr(timing, field) > 0.0, f"{field} was not measured"


def test_document_costs_at_least_as_much_as_a_fragment():
    # render_document is render_fragment plus a page around it. Any other
    # ordering means the harness is measuring the wrong thing.
    timing = measure.time_layers(generate.build("prose", 20_000), repeat=2)
    assert timing.document_ms >= timing.fragment_ms * 0.75


def test_an_empty_document_still_measures():
    timing = measure.time_layers("", repeat=1)
    assert timing.chars == 0
    assert timing.document_ms > 0.0
