"""The rule that decides what counts as a leak, tested without a display.

A resource is a leak only when it was never released AND the thing holding
it is still alive. That second half is what keeps the check honest: the
plugin makes 45 signal connections outside its tracked helper, and almost
all are on widgets it destroys itself. Reporting those would be 45 false
positives and the tool would be ignored within a week.
"""

from tests.integration.leakcheck import ledger as led


def _ledger():
    return led.Ledger()


def test_a_released_record_is_not_a_finding():
    lg = _ledger()
    lg.record(led.HANDLER, 7, "set-focus on XedWindow", "origin.py:1", lambda: True)
    lg.release(led.HANDLER, 7)
    assert lg.findings() == ()


def test_an_unreleased_record_whose_owner_died_is_not_a_finding():
    # The SearchBar case: the widget was destroyed, so its connections went
    # with it. Nothing leaked, and reporting it would be noise.
    lg = _ledger()
    lg.record(led.HANDLER, 7, "clicked on SearchBar", "origin.py:1", lambda: False)
    assert lg.findings() == ()


def test_an_unreleased_record_whose_owner_lives_is_a_finding():
    lg = _ledger()
    lg.record(
        led.HANDLER, 7, "set-focus on XedWindow", "controller.py:271", lambda: True
    )
    findings = lg.findings()
    assert len(findings) == 1
    assert findings[0].kind == led.HANDLER
    assert findings[0].label == "set-focus on XedWindow"
    assert findings[0].origin == "controller.py:271"


def test_the_origin_travels_with_the_finding():
    # A count is not actionable. The stack that created the resource is.
    lg = _ledger()
    lg.record(led.SOURCE, 3, "timeout 250ms", "controller.py:1163", lambda: True)
    assert "controller.py:1163" in lg.findings()[0].origin


def test_releasing_an_unknown_key_is_tolerated():
    # GLib.source_remove is called on ids this ledger never saw -- sources
    # created before install(), or by GTK itself. It must not raise.
    lg = _ledger()
    lg.release(led.SOURCE, 999)
    assert lg.findings() == ()


def test_releasing_twice_is_tolerated():
    lg = _ledger()
    lg.record(led.SOURCE, 3, "timeout", "o", lambda: True)
    lg.release(led.SOURCE, 3)
    lg.release(led.SOURCE, 3)
    assert lg.findings() == ()


def test_kinds_do_not_collide_on_equal_keys():
    # Handler ids and source ids are both small integers from separate
    # sequences, so key 1 routinely means two different things at once.
    lg = _ledger()
    lg.record(led.HANDLER, 1, "handler one", "o", lambda: True)
    lg.record(led.SOURCE, 1, "source one", "o", lambda: True)
    lg.release(led.SOURCE, 1)
    labels = [f.label for f in lg.findings()]
    assert labels == ["handler one"]


def test_outstanding_reports_unreleased_records_regardless_of_liveness():
    # `outstanding` is the raw bookkeeping view, for diagnosis; `findings`
    # applies the rule. They deliberately differ.
    lg = _ledger()
    lg.record(led.HANDLER, 1, "dead owner", "o", lambda: False)
    lg.record(led.HANDLER, 2, "live owner", "o", lambda: True)
    assert len(lg.outstanding()) == 2
    assert len(lg.findings()) == 1


def test_a_liveness_probe_that_raises_is_treated_as_dead():
    # A weakref into a half-finalised GObject can raise rather than answer.
    # An audit must never crash the probe it is auditing.
    def boom():
        raise RuntimeError("finalised")

    lg = _ledger()
    lg.record(led.HANDLER, 1, "exploding", "o", boom)
    assert lg.findings() == ()


def test_clear_empties_everything():
    lg = _ledger()
    lg.record(led.HANDLER, 1, "x", "o", lambda: True)
    lg.clear()
    assert lg.outstanding() == ()
    assert lg.findings() == ()


def test_mark_on_an_empty_ledger_works():
    lg = _ledger()
    assert lg.mark() == 0


def test_a_record_before_the_mark_is_excluded_from_findings_since():
    # A scenario's own long-lived setup, or something else entirely still
    # open in the process, must not be reported as a leak of the thing
    # torn down after the mark.
    lg = _ledger()
    lg.record(led.HANDLER, 1, "before", "o", lambda: True)
    mark = lg.mark()
    assert lg.findings(since=mark) == ()


def test_a_record_after_the_mark_is_included_in_findings_since():
    lg = _ledger()
    lg.record(led.HANDLER, 1, "before", "o", lambda: True)
    mark = lg.mark()
    lg.record(led.HANDLER, 2, "after", "o", lambda: True)
    findings = lg.findings(since=mark)
    assert [f.label for f in findings] == ["after"]


def test_findings_with_no_argument_still_reports_everything():
    lg = _ledger()
    lg.record(led.HANDLER, 1, "before", "o", lambda: True)
    _ = lg.mark()
    lg.record(led.HANDLER, 2, "after", "o", lambda: True)
    labels = sorted(f.label for f in lg.findings())
    assert labels == ["after", "before"]


def test_a_key_can_be_released_and_recorded_again():
    # The dispatch cycle of a repeating timer, in ledger terms. `hooks`
    # releases a source BEFORE running its callback -- a source being
    # dispatched is not a source still armed -- and records it again only
    # if the callback returned True. Both halves have to work on one key,
    # and the second record must replace the first rather than duplicate
    # it.
    lg = _ledger()
    lg.record(led.SOURCE, 3, "timeout_add source", "filewatch.py:110", lambda: True)
    lg.release(led.SOURCE, 3)
    assert lg.findings() == ()

    lg.record(led.SOURCE, 3, "timeout_add source", "filewatch.py:110", lambda: True)
    findings = lg.findings()
    assert [f.label for f in findings] == ["timeout_add source"]
    assert findings[0].origin == "filewatch.py:110"


def test_a_re_recorded_key_gets_a_fresh_sequence_number():
    # Checkpoint scoping is what makes an audit mean anything, and it runs
    # entirely on the sequence number `record()` assigns. A source armed
    # before a checkpoint, dispatched, and then re-armed after it is armed
    # NOW, and belongs in that checkpoint's scope -- which only happens if
    # the re-record takes a new number instead of keeping the old one.
    lg = _ledger()
    lg.record(led.SOURCE, 3, "repeating", "o", lambda: True)
    first = lg.outstanding()[0].seq
    lg.release(led.SOURCE, 3)
    mark = lg.mark()
    lg.record(led.SOURCE, 3, "repeating", "o", lambda: True)
    second = lg.outstanding()[0].seq
    assert second > first
    assert [f.label for f in lg.findings(since=mark)] == ["repeating"]


def test_a_key_released_and_not_re_recorded_leaves_the_scope_empty():
    # The other half of the same mechanism: a one-shot that retires itself
    # is released and never comes back, so an audit taken afterwards --
    # including one taken from inside another source's callback -- sees
    # nothing.
    lg = _ledger()
    mark = lg.mark()
    lg.record(led.SOURCE, 3, "one shot", "o", lambda: True)
    lg.release(led.SOURCE, 3)
    assert lg.findings(since=mark) == ()
    assert lg.outstanding(since=mark) == ()


def test_outstanding_since_filters_the_same_way_as_findings_since():
    lg = _ledger()
    lg.record(led.HANDLER, 1, "before", "o", lambda: False)
    mark = lg.mark()
    lg.record(led.HANDLER, 2, "after", "o", lambda: False)
    labels = [r.label for r in lg.outstanding(since=mark)]
    assert labels == ["after"]
