"""When a freshly loaded page is ready for its once-per-load work.

Pure logic -- no GTK imports belong here, by the same rule `document_state.py`
follows: this is exactly the kind of small state machine the `gi` boundary
would otherwise put out of the unit tests' reach.

`PreviewView` owns one `PageReadyGate` per WebView and feeds it two
independent, asynchronous main-loop dispatches: the page's own `"ready"`
script message (posted on `DOMContentLoaded`, which does not wait for a
subresource still in flight -- see preview.js) and WebKit's own
`LoadEvent.COMMITTED` / `LoadEvent.FINISHED`. Whichever of "ready" and
FINISHED arrives first should do the once-per-load work (restoring scroll,
re-issuing a live search); the other is then a no-op.

Requiring `commit()` before a `ready()` call is accepted narrows, but does
not eliminate, a race: a "ready" queued by the OUTGOING page can still be
sitting in the main loop when the next load starts. Without this gate it
would satisfy the NEW load's `ready()` check, running the new load's restore
work against whatever page is actually current and silently discarding the
real signal when it eventually arrives -- a lost scroll position with no
error anywhere. Requiring `commit()` first closes the common case -- a stale
message dispatched before the new page's own commit -- but both signals are
still separate main-loop dispatches from different sources, so a "ready"
delivered late enough to land AFTER the next commit could still slip through
undetected. This is a narrowing, not an airtight fix; a genuinely airtight
version would need the page to echo a per-load token, which is renderer
plumbing out of proportion to a race this narrow. `FINISHED` always arrives
after `COMMITTED` for the same load (WebKit orders load events STARTED,
COMMITTED, FINISHED), so `ready()` never holds back the FINISHED path -- only
a same-load "ready" arriving early, before its own page has committed.
"""


class PageReadyGate:
    """Tracks one load's progress toward becoming ready, exactly once."""

    def __init__(self):
        self.reset()

    def reset(self):
        """Call at the start of every new load."""
        self.committed = False
        self.settled = False

    def commit(self):
        """Call on `LoadEvent.COMMITTED` for the load this gate belongs to."""
        self.committed = True

    def ready(self):
        """True the first time this is called after `commit()`.

        False on every other call -- including every call made before
        `commit()`, which is what keeps a stale "ready" from an outgoing page
        from settling a load it was never sent for -- and every call after
        the first `True`, which is what keeps the once-per-load work from
        running twice.
        """
        if self.settled or not self.committed:
            return False
        self.settled = True
        return True
