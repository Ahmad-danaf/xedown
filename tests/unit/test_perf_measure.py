"""The measurement helper reports per-layer times, not one number."""

from tests.perf import corpus, generate, measure


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


def test_peak_memory_is_measured_and_grows_with_the_document():
    # Not a wall-clock assertion, which is why it is allowed here at all:
    # peak allocation is deterministic where a duration is not.
    #
    # The warm-up is load-bearing. The *first* render in a process also
    # pays Python-Markdown's lazy import of its extension modules and
    # every regex they compile -- around 4 MB nothing later pays again --
    # so without it whichever call ran first would dominate both figures
    # and the comparison would mean nothing. `run_bench --memory`
    # discards a render for exactly this reason.
    measure.peak_render_bytes("warm up, discard")
    floor = measure.peak_render_bytes("")
    loaded = measure.peak_render_bytes(generate.build("prose", 50_000))
    assert floor > 0
    assert loaded > floor


def test_a_named_corpus_document_that_is_not_there_is_none():
    # Not an error and not a download: the corpus is uncommitted, so
    # every entry point into it has to answer "absent" cleanly. CI never
    # has one at all.
    assert corpus.read("no-such-readme.md") is None
