"""The Orca transcript parser.

These are the CI-reachable half of the Orca pass: the harness itself needs a
desktop, a nested X server and a screen reader, but slicing a speech log by
marker is ordinary text processing and belongs on the pure side of the `gi`
boundary.
"""

import pytest

from . import orca_transcript as ot

# Two real lines, copied verbatim from an Orca 46.1 debug log, trailing voice
# dict included -- the parser has to survive the shape Orca actually writes,
# not a tidied-up version of it.
REAL_LOG = (
    "21:34:30.493443 - SPEECH OUTPUT: 'Scroll Test' {'established': False}\n"
    "21:34:30.496163 - SPEECH OUTPUT: 'selected' {'established': False}\n"
)


def test_an_utterance_is_read_with_its_time_and_text():
    assert ot.parse_utterances(REAL_LOG) == [
        (77670.493443, "Scroll Test"),
        (77670.496163, "selected"),
    ]


def test_lines_that_are_not_speech_are_ignored():
    text = (
        "21:34:30.000000 - FOCUS MANAGER: Locus of focus is [heading: 'Scroll Test']\n"
        + REAL_LOG
    )
    assert [t for _, t in ot.parse_utterances(text)] == ["Scroll Test", "selected"]


def test_an_utterance_with_no_trailing_voice_dict_still_parses():
    text = "21:34:30.493443 - SPEECH OUTPUT: 'Screen reader on.'\n"
    assert ot.parse_utterances(text) == [(77670.493443, "Screen reader on.")]


def test_an_utterance_containing_a_quote_keeps_it():
    text = "01:00:00.000000 - SPEECH OUTPUT: 'it's here' {'established': False}\n"
    assert ot.parse_utterances(text) == [(3600.0, "it's here")]


def test_markers_are_read_with_their_time():
    text = "21:34:29.000000 mode-switch\n21:34:31.000000 mode-bar-tab\n"
    assert ot.parse_markers(text) == [
        (77669.0, "mode-switch"),
        (77671.0, "mode-bar-tab"),
    ]


def test_each_utterance_lands_in_the_marker_that_preceded_it():
    utterances = [(10.0, "before"), (20.5, "during"), (30.0, "after")]
    markers = [(15.0, "first"), (25.0, "second")]
    assert ot.slice_by_marker(utterances, markers) == {
        "first": ["during"],
        "second": ["after"],
    }


def test_an_utterance_before_the_first_marker_belongs_to_no_marker():
    utterances = [(1.0, "startup chatter"), (20.0, "real")]
    markers = [(10.0, "only")]
    assert ot.slice_by_marker(utterances, markers) == {"only": ["real"]}


def test_a_marker_with_nothing_spoken_in_it_slices_to_an_empty_list():
    """The silence itself is the finding -- it must be reported, not dropped."""
    utterances = [(20.0, "spoken")]
    markers = [(10.0, "loud"), (30.0, "silent")]
    assert ot.slice_by_marker(utterances, markers) == {"loud": ["spoken"], "silent": []}


def test_marker_times_stepping_backwards_raises():
    """Midnight crossing in markers is detected and refused."""
    utterances = [(1.0, "u")]
    markers = [(86398.0, "late"), (100.0, "early")]
    with pytest.raises(ot.AmbiguousTimeline):
        ot.slice_by_marker(utterances, markers)


def test_utterance_times_stepping_backwards_raises():
    """Midnight crossing in utterances is detected and refused."""
    markers = [(10.0, "M")]
    utterances = [(86398.0, "u_late"), (100.0, "u_early")]
    with pytest.raises(ot.AmbiguousTimeline):
        ot.slice_by_marker(utterances, markers)


def test_same_day_operation_is_untouched():
    """Ordinary same-day operation works without detecting crossing."""
    markers = [(1.0, "A"), (10.0, "B"), (20.0, "C")]
    utterances = [(2.0, "u1"), (15.0, "u2"), (25.0, "u3")]
    assert ot.slice_by_marker(utterances, markers) == {
        "A": ["u1"],
        "B": ["u2"],
        "C": ["u3"],
    }


def test_an_empty_transcript_is_an_error_not_an_empty_result():
    """An audit that found nothing is not a pass -- a11y.check_tree's rule."""
    with pytest.raises(ot.EmptyTranscript):
        ot.slice_by_marker([], [(10.0, "anything")])


def test_missing_reports_what_was_not_said():
    assert ot.missing(["Preview", "Markdown source"], ["Preview", "Refresh"]) == [
        "Refresh"
    ]


def test_missing_matches_inside_a_longer_utterance_and_ignores_case():
    spoken = ["Preview toggle button pressed"]
    assert ot.missing(spoken, ["preview"]) == []


def test_missing_returns_nothing_when_everything_was_said():
    assert ot.missing(["Match case", "Close search"], ["Match case"]) == []


# --- evaluate_rows: the decision scripts/run-orca-tests.sh's exit code turns
# on, moved here so it has coverage independent of a live Orca session. ---


def test_evaluate_rows_a_rows_entry_that_said_the_expected_substring_passes():
    sliced = {"row-97-mode-bar-tab": ["Markdown source toggle button not pressed."]}
    lines = ot.evaluate_rows(sliced, {"row-97-mode-bar-tab": ["Markdown source"]}, [])
    assert lines == ["PASS row-97-mode-bar-tab - ['Markdown source']"]


def test_evaluate_rows_a_rows_entry_that_never_said_the_expected_substring_fails():
    sliced = {"row-97-mode-bar-tab": ["something unrelated"]}
    lines = ot.evaluate_rows(sliced, {"row-97-mode-bar-tab": ["Markdown source"]}, [])
    assert lines == [
        (
            "FAIL row-97-mode-bar-tab - never said: ['Markdown source'] "
            "(said: ['something unrelated'])"
        )
    ]


def test_evaluate_rows_a_rows_entry_with_an_empty_slice_fails():
    """Silence is a finding, not a pass -- a11y.check_tree's rule."""
    sliced = {"row-98-preview-scroll": []}
    lines = ot.evaluate_rows(sliced, {"row-98-preview-scroll": ["anything"]}, [])
    assert lines == ["FAIL row-98-preview-scroll - Orca said nothing at all"]


def test_evaluate_rows_a_silent_rows_entry_with_an_empty_slice_passes():
    sliced = {"row-96-switch-to-source": []}
    lines = ot.evaluate_rows(sliced, {}, ["row-96-switch-to-source"])
    assert lines == ["PASS row-96-switch-to-source - silent, as measured"]


def test_evaluate_rows_a_silent_rows_entry_that_spoke_fails():
    """The asymmetry with ROWS: here an empty slice is the pass, and any
    speech at all is the failure -- the opposite polarity, on purpose."""
    sliced = {"row-96-switch-to-source": ["unexpected speech"]}
    lines = ot.evaluate_rows(sliced, {}, ["row-96-switch-to-source"])
    assert lines == [
        (
            "FAIL row-96-switch-to-source - Orca spoke, expected silence: "
            "['unexpected speech']"
        )
    ]


def test_evaluate_rows_a_missing_marker_fails_in_the_rows_table():
    """A missing marker means the probe never reached the action -- an
    assertion that found nothing is not a pass, in either table."""
    lines = ot.evaluate_rows({}, {"row-101-external-change": ["x"]}, [])
    assert lines == ["FAIL row-101-external-change - no such marker in the transcript"]


def test_evaluate_rows_a_missing_marker_fails_in_the_silent_rows_table():
    lines = ot.evaluate_rows({}, {}, ["row-98-preview-scroll"])
    assert lines == ["FAIL row-98-preview-scroll - no such marker in the transcript"]


def test_evaluate_rows_preserves_table_order_rows_then_silent_rows():
    sliced = {"a": ["x"], "b": []}
    lines = ot.evaluate_rows(sliced, {"a": ["x"]}, ["b"])
    assert lines == ["PASS a - ['x']", "PASS b - silent, as measured"]
