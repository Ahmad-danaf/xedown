from xedown.pageready import PageReadyGate


def test_a_ready_before_commit_is_ignored_but_finished_still_settles():
    # A "ready" script message can be dispatched before WebKit's own
    # LoadEvent.COMMITTED for the same load; the gate must not let it settle
    # the load. LoadEvent.FINISHED -- which always arrives after COMMITTED --
    # still has to settle it once the load actually commits.
    gate = PageReadyGate()
    assert gate.ready() is False  # "ready" arrives before commit()
    assert gate.settled is False

    gate.commit()
    assert gate.ready() is True  # FINISHED, after commit()
    assert gate.settled is True


def test_a_ready_after_commit_settles_the_load_exactly_once():
    gate = PageReadyGate()
    gate.commit()
    assert gate.ready() is True
    # Whichever of "ready" or FINISHED arrives second must be a no-op.
    assert gate.ready() is False
    assert gate.ready() is False


def test_reset_clears_both_flags_so_the_next_load_restores_its_own_scroll():
    gate = PageReadyGate()
    gate.commit()
    assert gate.ready() is True

    gate.reset()
    assert gate.committed is False
    assert gate.settled is False
    # A stale signal arriving for the OLD load after reset must not settle
    # the new one.
    assert gate.ready() is False

    gate.commit()
    assert gate.ready() is True


def test_a_fresh_gate_starts_unsettled_and_uncommitted():
    gate = PageReadyGate()
    assert gate.committed is False
    assert gate.settled is False
