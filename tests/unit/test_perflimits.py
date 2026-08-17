"""Which documents are too big to render on every keystroke."""

import pytest
from xedown import perflimits


def test_a_small_document_is_unconstrained():
    decision = perflimits.classify(5_000)
    assert decision.live_refresh is True
    assert decision.defer_initial is False


def test_live_refresh_stops_above_its_threshold():
    below = perflimits.classify(perflimits.LIVE_REFRESH_MAX_CHARS - 1)
    above = perflimits.classify(perflimits.LIVE_REFRESH_MAX_CHARS + 1)
    assert below.live_refresh is True
    assert above.live_refresh is False


def test_a_document_exactly_at_the_live_refresh_threshold_still_refreshes():
    # The threshold is a maximum, so the boundary value itself is inside
    # it. Tested separately from the +-1 pair above because that pair
    # cannot see the boundary: `<=` and `<` agree everywhere except here,
    # and the constants are retuned from measurement, so which comparison
    # is written must not be free to drift. Symbolic, never a literal --
    # the next retune moves the number and this test must move with it.
    decision = perflimits.classify(perflimits.LIVE_REFRESH_MAX_CHARS)
    assert decision.live_refresh is True


def test_the_initial_render_defers_above_its_threshold():
    below = perflimits.classify(perflimits.DEFER_INITIAL_MIN_CHARS - 1)
    above = perflimits.classify(perflimits.DEFER_INITIAL_MIN_CHARS + 1)
    assert below.defer_initial is False
    assert above.defer_initial is True


def test_a_document_exactly_at_the_defer_threshold_does_not_defer():
    # The mirror of the live-refresh boundary above, and the opposite
    # sense: this threshold is a minimum a document must *exceed*, so the
    # boundary value itself does not defer. `>` and `>=` differ only here.
    decision = perflimits.classify(perflimits.DEFER_INITIAL_MIN_CHARS)
    assert decision.defer_initial is False


def test_a_deferred_document_never_live_refreshes():
    # The thresholds are ordered, so the states are nested rather than
    # independent. A document big enough to defer is certainly big enough
    # to stop live refresh, and a combination that said otherwise would be
    # a bug in the constants.
    assert perflimits.DEFER_INITIAL_MIN_CHARS > perflimits.LIVE_REFRESH_MAX_CHARS
    decision = perflimits.classify(perflimits.DEFER_INITIAL_MIN_CHARS + 1)
    assert decision.defer_initial is True
    assert decision.live_refresh is False


@pytest.mark.parametrize("value", [0, -1, -100_000])
def test_a_nonpositive_count_is_unconstrained(value):
    # An empty or not-yet-loaded buffer must not trip a guard.
    decision = perflimits.classify(value)
    assert decision.live_refresh is True
    assert decision.defer_initial is False


@pytest.mark.parametrize("value", [None, "big", 1.5, object()])
def test_a_bad_count_is_unconstrained_rather_than_raising(value):
    # Same reasoning as `settings.BoolSetting.coerce` and
    # `direction.coerce_ui`: this is consulted from a path that must not
    # raise, so a value of the wrong type degrades to "no limit" rather
    # than propagating out of a render.
    decision = perflimits.classify(value)
    assert decision.live_refresh is True
    assert decision.defer_initial is False


@pytest.mark.parametrize(
    "byte_count,expected",
    [
        (0, "0 KB"),
        (999, "1 KB"),
        (150_000, "146 KB"),
        (405_180, "396 KB"),
        (1_048_576, "1.0 MB"),
        (5_242_880, "5.0 MB"),
    ],
)
def test_describe_bytes(byte_count, expected):
    assert perflimits.describe_bytes(byte_count) == expected


def test_describe_bytes_never_raises_on_a_bad_value():
    assert perflimits.describe_bytes(None) == ""
    assert perflimits.describe_bytes("huge") == ""


@pytest.mark.parametrize("value", [True, False])
def test_describe_bytes_refuses_a_bool(value):
    # `bool` subclasses `int`, so without the explicit guard both of these
    # would format as "0 KB" -- a chip confidently labelling a document
    # zero kilobytes because a caller passed a flag where a size belongs.
    # Unlike `classify`'s own bool guard, whose output for `True` happens
    # to coincide with the unconstrained answer, this one is observable,
    # so it is pinned.
    assert perflimits.describe_bytes(value) == ""
