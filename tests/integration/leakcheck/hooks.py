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
import traceback
import weakref

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import GLib, GObject

from .ledger import HANDLER, OBJECT, SOURCE, Ledger

_LEDGER = Ledger()
_ORIGINALS = {}
_WATCHED = []


def _origin():
    """The xedown frame that acquired this, not our own wrapper frames.

    Full stacks are unreadable in a probe report, and the frames inside
    this file are never the answer. The first frame from the plugin is.
    """
    for frame in reversed(traceback.extract_stack()[:-2]):
        if "xedown" in frame.filename and "leakcheck" not in frame.filename:
            return f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno} in {frame.name}"
    frame = traceback.extract_stack()[-3]
    return f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}"


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
            return handler_id
        _LEDGER.record(
            HANDLER,
            handler_id,
            f"{detailed_signal} on {type(self).__name__}",
            _origin(),
            _handler_liveness(reference, handler_id),
        )
        return handler_id

    return original, wrapper


def _wrap_disconnect(name):
    original = getattr(GObject.Object, name)

    def wrapper(self, handler_id, *args, **kwargs):
        _LEDGER.release(HANDLER, handler_id)
        return original(self, handler_id, *args, **kwargs)

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
        holder = {}

        def wrapped(*cb_args, **cb_kwargs):
            keep = callback(*cb_args, **cb_kwargs)
            if not keep:
                # Returned False: GLib retires the source itself, so it is
                # not outstanding and must not be reported. Without this
                # every legitimate one-shot idle_add reads as a leak.
                _LEDGER.release(SOURCE, holder.get("id"))
            return keep

        patched = list(args)
        patched[index] = wrapped
        source_id = original(*patched, **kwargs)
        holder["id"] = source_id
        _LEDGER.record(SOURCE, source_id, f"{name} source", _origin(), lambda: True)
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
    _WATCHED.append((label, reference))
    _LEDGER.record(OBJECT, label, label, _origin(), lambda: reference() is not None)


def release_object(label):
    _LEDGER.release(OBJECT, label)


def audit():
    """Findings as of now. Collects first, so Python-side cycles do not count."""
    gc.collect()
    return _LEDGER.findings()


def format_findings(findings):
    if not findings:
        return "none"
    return "; ".join(f"{f.label} @ {f.origin}" for f in findings)
