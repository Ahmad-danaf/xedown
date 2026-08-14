"""What xedown acquired, what it gave back, and what that leaves behind.

Pure by construction: no `gi`, nothing of xedown's, no globals. Liveness is
an injected callable, the same way `imagefetch` takes an injectable opener,
so the rule below can be tested without a display.

THE RULE. A resource is a leak only when it was never released AND the
thing holding it is still alive. Both halves matter. The plugin makes 45
signal connections outside its tracked `_connect` helper and nearly all are
on widgets it destroys itself -- destroying a widget invalidates its
connections, so those are self-cleaning. A checker without the liveness
half reports all of them, and a checker that cries wolf is deleted.
"""

from typing import NamedTuple

HANDLER = "handler"
SOURCE = "source"
OBJECT = "object"


class Record(NamedTuple):
    kind: str
    key: object
    label: str
    origin: str


class Finding(NamedTuple):
    kind: str
    label: str
    origin: str
    detail: str


class Ledger:
    """Bookkeeping for one process. Not thread-safe; nothing here is."""

    def __init__(self):
        self._records = {}
        self._live = {}

    def record(self, kind, key, label, origin, is_live):
        """Note an acquisition. `is_live()` answers whether its owner still exists."""
        index = (kind, key)
        self._records[index] = Record(kind=kind, key=key, label=label, origin=origin)
        self._live[index] = is_live

    def release(self, kind, key):
        """Note a hand-back. Tolerant of keys never recorded.

        `GLib.source_remove` is routinely called on ids this ledger never
        saw -- sources created before `install()`, or by GTK itself -- and
        a bookkeeping helper that raised on those would take the probe down
        with it.
        """
        index = (kind, key)
        self._records.pop(index, None)
        self._live.pop(index, None)

    def outstanding(self):
        """Every unreleased record, whether or not its owner still lives.

        The raw view, for diagnosing a confusing audit. `findings` is the
        one that applies the rule.
        """
        return tuple(self._records.values())

    def findings(self):
        """Unreleased records whose owner is still alive. The rule.

        A liveness probe that raises counts as dead. A weakref into a
        half-finalised GObject can raise rather than answer, and an audit
        must never crash the thing it is auditing -- a false negative here
        costs one missed finding, a crash costs the whole run.
        """
        out = []
        for index, record in self._records.items():
            try:
                alive = bool(self._live[index]())
            except Exception:  # noqa: BLE001 - an audit must not crash the probe
                alive = False
            if alive:
                out.append(
                    Finding(
                        kind=record.kind,
                        label=record.label,
                        origin=record.origin,
                        detail=f"{record.kind} {record.key!r} still held",
                    )
                )
        return tuple(out)

    def clear(self):
        self._records.clear()
        self._live.clear()
