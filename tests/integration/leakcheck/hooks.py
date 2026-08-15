"""Wrap the `gi` entry points xedown uses to acquire long-lived resources.

Only importable inside a real xed process. `install()` must run BEFORE
xedown is imported, or the wrap misses everything the plugin does at import
time. Both probes defer their xedown imports (the integration probe to
`_lazy_imports`, the shutdown probe to a function body), so installing at
probe-module import time is early enough -- verified, not assumed.

What is wrapped, and why each one:

  GObject.Object.connect / connect_after   the handlers of spec section 3
  GObject.Object.disconnect / handler_disconnect   their release
  GLib.timeout_add / timeout_add_seconds / idle_add   armed timers
  GLib.source_remove                        their release

Nothing else. Wrapping more would slow a live session and widen the blast
radius of a bug in this file, which runs inside the process it audits.
"""

import gc
import os
import sys
import traceback
import weakref

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, GObject

from .ledger import HANDLER, OBJECT, SOURCE, Ledger

_LEDGER = Ledger()
_ORIGINALS = {}


def _plugin_frame(filename):
    """Whether `filename` sits inside a directory literally named `xedown`.

    That path component names only the plugin: `plugin/xedown/...` in the
    repo, `~/.local/share/xed/plugins/xedown/...` once installed -- and both
    harness scripts only ever run copies from the latter (`cp -r` into
    `$HOME/.local/share/xed/plugins`, confirmed by reading both), never the
    checkout in place. A substring test on "xedown" also matches the probe
    packages (`xedown_probe/`, `xedown_shutdown_probe/`), which is exactly
    what made `_origin()` mis-attribute handlers non-xedown code connects
    during `create_tab_from_location` to the probe instead of recognising
    that no xedown frame is on the stack at all.

    This file's own directory, `leakcheck/`, does not contain the `xedown`
    component at the harnesses' real install path, so no separate exclusion
    should be needed there the way the old substring test carried one. It
    gets one anyway, explicitly: a checkout cloned into a directory that
    happens to be named `xedown` (true of this very repo's clone on this
    machine) would put that component on every path under it, including
    this file's own -- harmless today only because `_origin()` slices off
    this module's own frames before this function ever sees them, which is
    a fact about call depth, not about paths. Excluding this directory by
    name keeps that true even if a future call site changes the depth.
    """
    sep = os.sep
    if f"{sep}leakcheck{sep}" in filename:
        return False
    return f"{sep}xedown{sep}" in filename


def _origin():
    """The plugin frame that acquired this, or None if there is not one.

    Full stacks are unreadable in a probe report, and the frames inside
    this file are never the answer. The first frame that is actually
    inside the plugin package is -- and if no such frame is on the stack,
    the resource was not acquired by xedown at all, so there is no origin
    to name. Callers that wrap a `gi` entry point treat `None` as "skip
    recording this", not as license to guess at a fallback frame the way
    this used to.
    """
    stack = traceback.extract_stack()
    for frame in reversed(stack[:-2]):
        if _plugin_frame(frame.filename):
            return f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} in {frame.name}"
    return None


def _auditor_failed(what, exc):
    """Report a bug in this file on stderr, then carry on.

    Swallowed in silence, a bug here would present as an audit that quietly
    stopped finding things -- the worst possible failure for a tool whose
    whole job is noticing what is missing. The wording is deliberately
    plain: `run-shutdown-tests.sh` treats `Traceback (most recent`,
    `CRITICAL **` and friends in xed's log as release blockers, and an
    auditor hiccup is a harness bug to fix rather than a blocker to file
    against the plugin.
    """
    sys.stderr.write(f"LEAKCHECK: bookkeeping failed in {what}: {exc!r}\n")
    sys.stderr.flush()


def _guard(action, *args):
    """Run one piece of bookkeeping that must never escape into the host.

    Everything recorded here happens inside a wrapped `gi` entry point, on
    xedown's or GTK's own call stack -- or, for the source wrapper, inside
    a GLib dispatch. A bug in the auditor must cost one missing record, not
    an exception out of `GObject.connect` or out of a timer callback.
    `Ledger.findings` is deliberately defensive for the same reason; the
    recording side matches it.

    Never used to wrap the audited callback itself: a step that raises must
    still surface as the probe's own `crash-in-step-N`.
    """
    try:
        action(*args)
    except Exception as exc:  # noqa: BLE001 - an auditor must not break its host
        _auditor_failed(getattr(action, "__name__", "bookkeeping"), exc)


def _handler_liveness(emitter_ref, handler_id):
    """Alive only if the emitter still exists AND still holds the handler.

    This closure is the rule of spec section 5.1 made executable. A dead
    weakref means the emitter was finalised and took its connections with
    it -- the SearchBar case, and not a leak.
    """

    def is_live():
        emitter = emitter_ref()
        if emitter is None:
            return False
        return bool(GObject.signal_handler_is_connected(emitter, handler_id))

    return is_live


def _wrap_connect(name):
    original = getattr(GObject.Object, name)

    def wrapper(self, detailed_signal, *args, **kwargs):
        handler_id = original(self, detailed_signal, *args, **kwargs)
        try:
            reference = weakref.ref(self)
        except TypeError:
            # Not weak-referenceable. Recording it would mean holding a
            # strong reference from the auditor, which is itself a leak.
            # Silent, and kept as its own narrow branch rather than folded
            # into the guard below: this is an expected outcome, and
            # `_auditor_failed` is for things that should not happen.
            return handler_id
        # The record below runs INSIDE `GObject.connect`, on the plugin's
        # own call stack -- `_origin()` walks a traceback, `Ledger.record`
        # touches two dicts -- and an exception escaping it would come out
        # of a connect() call in xedown or GTK. A missed record is by far
        # the cheaper failure. `Ledger.findings` is deliberately defensive
        # about exactly this on the reading side; the wrappers match it.
        # The handler id is returned either way, so the caller never
        # notices.
        try:
            origin = _origin()
            if origin is None:
                # No xedown frame on the stack: something other than the
                # plugin made this connection (e.g. non-xedown code wiring
                # up a signal during `create_tab_from_location`). The tool
                # audits xedown, so a handler it never connected is not its
                # leak to report -- recording it here is what used to blame
                # the probe for connections it never made either.
                return handler_id
            _LEDGER.record(
                HANDLER,
                handler_id,
                f"{detailed_signal} on {type(self).__name__}",
                origin,
                _handler_liveness(reference, handler_id),
            )
        except Exception as exc:  # noqa: BLE001 - an auditor must not break its host
            _auditor_failed(f"{name}({detailed_signal})", exc)
        return handler_id

    return original, wrapper


def _wrap_disconnect(name):
    original = getattr(GObject.Object, name)

    def wrapper(self, handler_id, *args, **kwargs):
        # The original runs FIRST, and release() only on success. A
        # disconnect that raises (TypeError, RuntimeError -- the pair
        # `TabController.deactivate()` itself tolerates, against a window or
        # widget GTK has already disposed) must not be recorded as released:
        # doing so would stop tracking a handler that may still be
        # connected, silently hiding it from every later audit. The
        # liveness check (`signal_handler_is_connected`) is what actually
        # arbitrates whether a still-tracked handler is a leak; release()
        # must not pre-empt that by guessing.
        result = original(self, handler_id, *args, **kwargs)
        _LEDGER.release(HANDLER, handler_id)
        return result

    return original, wrapper


def _wrap_source(name):
    original = getattr(GLib, name)

    def wrapper(*args, **kwargs):
        # GLib's signatures differ: timeout_add(interval, callback, ...) and
        # idle_add(callback, ...). Find the first callable rather than
        # indexing by position.
        index = next(
            (i for i, value in enumerate(args) if callable(value)),
            None,
        )
        if index is None:
            return original(*args, **kwargs)

        callback = args[index]
        # Captured once, here, at the moment the source is ARMED -- and
        # reused verbatim if `wrapped` below re-records it. That stack is
        # the actionable one; re-deriving the origin from inside the
        # callback would name the main loop dispatching it instead, which
        # is never the answer to "who armed this timer".
        try:
            origin = _origin()
        except Exception as exc:  # noqa: BLE001 - an auditor must not break its host
            _auditor_failed(f"{name} origin", exc)
            origin = None

        if origin is None:
            # No xedown frame armed this timer, so it is not xedown's
            # resource to track -- run it unwrapped rather than recording a
            # leak that was never the plugin's to begin with. This is the
            # only place a source can skip the ledger entirely; once
            # `wrapped` below is installed, its release-before-invoke
            # ordering is unconditional, same as always.
            return original(*args, **kwargs)

        holder = {}
        label = f"{name} source"

        def wrapped(*cb_args, **cb_kwargs):
            # Released BEFORE the callback runs; re-recorded only if the
            # callback asks to stay armed.
            #
            # A source being DISPATCHED is not a source still armed. While
            # its own callback is on the stack, GLib has already taken it
            # off the ready list and is waiting on the return value to
            # learn whether to keep it -- so for the duration of the call
            # there is nothing outstanding to report.
            #
            # Releasing afterwards instead broke every audit in the suite.
            # Both probes chain their steps with `GLib.timeout_add` and
            # each step schedules the next from inside its own body, so the
            # source dispatching a step was armed after that scenario's
            # checkpoint and is still on the books while the step runs. An
            # audit taken from inside a step body -- which is the only kind
            # either probe takes -- saw the very source running it, whose
            # liveness closure is `lambda: True`, and failed on correct
            # code every time.
            sid = holder.get("id")
            _guard(_LEDGER.release, SOURCE, sid)
            keep = callback(*cb_args, **cb_kwargs)
            if keep:
                # Genuinely repeating: GLib keeps it armed, so it goes back
                # on the books under the same key, with the origin that
                # armed it. The re-record takes a fresh sequence number, so
                # a timer that re-arms after a checkpoint is in that
                # checkpoint's scope -- which is correct: it is armed now.
                _guard(_LEDGER.record, SOURCE, sid, label, origin, lambda: True)
            # Returning falsy retires the source, and the release above
            # already accounted for that -- without it every legitimate
            # one-shot `idle_add` in the plugin would read as a leak.
            return keep

        patched = list(args)
        patched[index] = wrapped
        source_id = original(*patched, **kwargs)
        holder["id"] = source_id
        _guard(_LEDGER.record, SOURCE, source_id, label, origin, lambda: True)
        return source_id

    return original, wrapper


def install():
    """Idempotent. Must run before xedown is imported."""
    if _ORIGINALS:
        return
    for name in ("connect", "connect_after"):
        original, wrapper = _wrap_connect(name)
        _ORIGINALS[("gobject", name)] = original
        setattr(GObject.Object, name, wrapper)
    for name in ("disconnect", "handler_disconnect"):
        original, wrapper = _wrap_disconnect(name)
        _ORIGINALS[("gobject", name)] = original
        setattr(GObject.Object, name, wrapper)
    for name in ("timeout_add", "timeout_add_seconds", "idle_add"):
        original, wrapper = _wrap_source(name)
        _ORIGINALS[("glib", name)] = original
        setattr(GLib, name, wrapper)

    original_remove = GLib.source_remove

    def source_remove(source_id, *args, **kwargs):
        _LEDGER.release(SOURCE, source_id)
        return original_remove(source_id, *args, **kwargs)

    _ORIGINALS[("glib", "source_remove")] = original_remove
    GLib.source_remove = source_remove


def uninstall():
    for (namespace, name), original in _ORIGINALS.items():
        target = GObject.Object if namespace == "gobject" else GLib
        setattr(target, name, original)
    _ORIGINALS.clear()


def watch_object(obj, label):
    """Track `obj` so a surviving reference after teardown is a finding.

    A weakref, never a strong one: an auditor that pins the object it is
    auditing guarantees the leak it is looking for.
    """
    try:
        reference = weakref.ref(obj)
    except TypeError:
        return
    _LEDGER.record(OBJECT, label, label, _origin(), lambda: reference() is not None)


def release_object(label):
    _LEDGER.release(OBJECT, label)


def checkpoint():
    """The ledger's "now", for scoping a later audit. See `Ledger.mark()`.

    A scenario calls this before creating the tab/window it means to tear
    down, then passes the result to `audit(since=...)` so a still-open tab
    or window elsewhere in the process -- entirely legitimate -- is not
    reported as a leak of the thing this scenario actually acquired.
    """
    return _LEDGER.mark()


def audit(since=None):
    """Findings as of now. Collects first, so Python-side cycles do not count.

    `since`, if given, restricts the audit to resources acquired at or
    after that checkpoint -- see `checkpoint()`.
    """
    gc.collect()
    return _LEDGER.findings(since=since)


def format_findings(findings):
    if not findings:
        return "none"
    return "; ".join(f"{f.label} @ {f.origin}" for f in findings)
