"""Serving `xedown-image:` from xedown's own fetch path.

Glue, and no policy: `remoteimages` decides what may be fetched,
`imagefetch` does the fetching, and this module only moves bytes between
them and WebKit.

Everything here was established by probe rather than assumed:

- the handler is called on the **main thread**, so it must never fetch
  inline;
- `finish()` may be deferred to a later main-loop turn from a worker thread;
- `get_web_view()` returns the originating view, and `None` once that view
  is destroyed;
- `finish()` and `finish_error()` on a destroyed view's request are safe --
  they return normally rather than crashing, which is why the per-view
  check in `_on_remote_image_failed` (controller.py) is an optimisation and
  not a safety measure;
- `LoadEvent.FINISHED` does not arrive while scheme requests are
  outstanding (a later task's problem, not this module's);
- `Gio.ProxyResolver.get_default().lookup(uri, None)` answers
  `['direct://']` when no proxy is configured, and the proxy URI when one
  is -- `_proxies_for` reads exactly that.

`imagefetch.Fetcher` takes `proxies_for` as a callable consulted per URL on
its own worker thread, not a per-request attribute assignment: mutating a
shared `Fetcher`'s internals on every request would race the very worker
that reads them. `_proxies_for` is instead handed to the `Fetcher`
constructor once, in `get_fetcher()`.

`Fetcher.shutdown()` stops the executor from taking new work but does not
itself refuse a later `.request()` call -- that invariant belongs to
whoever owns the `Fetcher`'s lifecycle, which is this module. `get_fetcher()`
never hands back an instance that has already been shut down: see its
docstring for how, and why the alternative (going permanently inert) was
not chosen.
"""

import concurrent.futures
import contextlib
import sys

import gi

gi.require_version("WebKit2", "4.1")

from gi.repository import Gio, GLib, WebKit2

from . import imagefetch, remoteimages

_registered = False
_fetcher = None
_executor = None
_failure_listeners = []
# Whether the process-wide network-change subscription has ever been made.
# Kept separate from `_fetcher` itself: `get_fetcher()` can build a second
# (third, ...) `Fetcher` across a shutdown()/get_fetcher() cycle, and
# `Gio.NetworkMonitor.get_default()` is a singleton with no "disconnect on
# rebuild" moment, so reconnecting on every rebuild would pile up handlers
# for the life of the process instead of holding the one the brief promises.
_monitor_connected = False


def _proxies_for(url):
    """What the desktop says to use for `url`, as urllib wants it.

    Asked of `GProxyResolver` rather than read from the environment, because
    `urllib.request.getproxies()` on Linux is environment-only and would
    silently bypass a proxy the rest of the desktop is using. Runs on the
    worker thread `imagefetch.Fetcher` calls it from (see the module
    docstring); `lookup()` blocks and can consult a PAC script, which is
    exactly the kind of call the fetch is already off the main thread to
    keep away from the editor.
    """
    try:
        answers = Gio.ProxyResolver.get_default().lookup(url, None)
    except Exception:  # noqa: BLE001 - no proxy is a usable answer
        return {}
    for answer in answers or []:
        if answer and not answer.startswith("direct://"):
            return {"http": answer, "https": answer}
    return {}


def _network_available():
    try:
        return Gio.NetworkMonitor.get_default().get_network_available()
    except Exception:  # noqa: BLE001 - assume reachable rather than block
        return True


def _on_network_changed(_monitor, available):
    """Forget failures on reconnect, against whichever fetcher is live.

    Reads the module-level `_fetcher` at call time rather than closing over
    the instance that was live when `connect()` ran, because this handler
    outlives any single `Fetcher`: it is connected once per process (see
    `_monitor_connected`), and `get_fetcher()` can replace `_fetcher` many
    times across that same process's life. The None-guard covers the gap
    between a `shutdown()` and the next `get_fetcher()` call, when there is
    momentarily no fetcher to invalidate.
    """
    if available and _fetcher is not None:
        _fetcher.invalidate_failures()


def get_fetcher():
    """The one fetcher this process shares, built on first use.

    Also rebuilt, fresh, the first time this is called *after*
    `shutdown()`: `shutdown()` resets `_fetcher` (and `_executor`) to
    `None` rather than leaving a torn-down instance in place, so this
    function only ever does one of two things -- return the single live
    fetcher, or build an entirely new one. It never hands back the instance
    `shutdown()` just tore down. Combined with `_on_request` asking this
    function fresh on every request rather than caching the result across
    calls, that is what keeps a `.request()` call from ever landing on a
    `Fetcher` whose executor has already been shut down.

    Rebuilding was chosen over the alternative -- latching permanently
    inert once `shutdown()` has ever run. `register_once()` installs the
    scheme handler once for the life of the process, so WebKit can hand
    this module a request at any later point, including after every tab
    has closed and a new one has been opened. A fetcher that never came
    back would mean every image in that next document hangs forever, with
    no recovery short of restarting xed -- worse than the resource cost of
    rebuilding a thread pool that only happens on the cold path anyway.
    """
    global _fetcher, _executor, _monitor_connected
    if _fetcher is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=remoteimages.MAX_CONCURRENT,
            thread_name_prefix="xedown-image",
        )
        _fetcher = imagefetch.Fetcher(
            network_available=_network_available,
            proxies_for=_proxies_for,
            executor=_executor,
            dispatch=lambda thunk: GLib.idle_add(lambda: (thunk(), False)[1]),
        )
        if not _monitor_connected:
            try:
                Gio.NetworkMonitor.get_default().connect(
                    "network-changed", _on_network_changed
                )
                _monitor_connected = True
            except Exception as exc:  # noqa: BLE001 - retry on refresh is enough
                sys.stderr.write(f"xedown: cannot watch the network: {exc}\n")
    return _fetcher


def note_failure_listener(callback):
    """Be told `(webview, url, result)` whenever a fetch fails."""
    _failure_listeners.append(callback)


def forget_failure_listener(callback):
    """Stop telling `callback` about failures. Safe if it never listened.

    The list is process-wide and its entries are ordinarily bound methods of
    a per-tab controller, so without this a closed tab's controller -- and
    the WebView, buffer and document it references -- would be held here for
    the life of the process, one entry per tab ever opened. Bound methods
    compare equal by `(instance, function)`, which is what makes `remove`
    find the entry `note_failure_listener` was handed even though the caller
    passes a freshly-created bound-method object.
    """
    with contextlib.suppress(ValueError):
        _failure_listeners.remove(callback)


def register_once():
    """Install the scheme handler. Safe to call from every activation.

    Never unregistered: a disable/re-enable must not try to register
    twice, and an installed handler nothing is asking about is inert.
    """
    global _registered
    if _registered:
        return
    WebKit2.WebContext.get_default().register_uri_scheme(
        remoteimages.SCHEME, _on_request, None
    )
    _registered = True


def _on_request(request, _user_data=None):
    """WebKit's entry point for every `xedown-image:` request.

    Runs on the main thread (probed), and must never let an exception
    escape: nothing upstream of a scheme-request callback is positioned to
    catch one. Every path funnels through `settle()`, which guarantees
    `request.finish()` or `request.finish_error()` runs exactly once --
    not zero times, which would hang the image forever, and not twice,
    which is unverified territory no probe covers.
    """
    settled = False

    def settle(finisher):
        """Run `finisher()` exactly once, however many callers try to.

        `finisher` is a zero-argument callable that ends in either
        `request.finish()` or `_fail(request, ...)`. If it raises before
        getting there, the request has still not been answered, so this
        falls back to `_fail()` directly rather than trusting whichever
        branch called `settle()` to also handle that -- otherwise a raise
        from deep inside a "finish" attempt would leave the image loading
        forever with only a stderr line to show for it. The
        `contextlib.suppress` is the true last resort: `finish_error()` is
        probed safe even against a destroyed view, so reaching it is not
        expected, but there is no third channel back to WebKit if it ever
        is reached and still raises.
        """
        nonlocal settled
        if settled:
            return
        settled = True
        try:
            finisher()
        except Exception as exc:  # noqa: BLE001 - still must answer the request
            sys.stderr.write(f"xedown: could not answer an image request: {exc}\n")
            with contextlib.suppress(Exception):
                _fail(request, "an internal error prevented this image from loading")

    def done(result):
        if result.ok:

            def finish_ok():
                stream = Gio.MemoryInputStream.new_from_data(result.data, None)
                request.finish(stream, len(result.data), result.mime)

            settle(finish_ok)
            return
        for listener in _failure_listeners[:]:
            try:
                listener(view, url, result)
            except Exception as exc:  # noqa: BLE001 - one must not stop the rest
                sys.stderr.write(f"xedown: an image failure listener failed: {exc}\n")
        settle(lambda: _fail(request, result.detail or "it could not be loaded"))

    try:
        url = remoteimages.parse_scheme_uri(request.get_uri())
        if url is None:
            settle(lambda: _fail(request, "not a fetchable address"))
            return

        view = request.get_web_view()
        fetcher = get_fetcher()
        fetcher.request(url, done)
    except Exception as exc:  # noqa: BLE001 - the request must still be answered
        sys.stderr.write(f"xedown: an image request failed: {exc}\n")
        settle(
            lambda: _fail(
                request, "an internal error prevented this image from loading"
            )
        )


def _fail(request, message):
    request.finish_error(
        GLib.Error.new_literal(Gio.io_error_quark(), message, Gio.IOErrorEnum.FAILED)
    )


def shutdown():
    """Stop taking new fetches, and release this fetcher's resources.

    Queued work is cancelled; work already running is not -- the
    interpreter joins those threads at exit either way, and `MAX_TOTAL_S`
    (the wall-clock deadline on one fetch, not the socket timeout) is what
    bounds how long that can delay closing xed. Callers whose fetch
    was already queued when this runs and whose callback never fires as a
    result are a pre-existing, documented residual of `Fetcher.shutdown()`
    itself (it clears its waiters without answering them); this module
    does not paper over that from the outside, since retrying here could
    just as easily double-answer a request `Fetcher` is about to settle on
    its own.

    Setting `_fetcher` back to `None` is what lets `get_fetcher()` build a
    fresh instance next time rather than resurrecting this one -- see its
    docstring. `_monitor_connected` is deliberately left set: the
    network-change subscription is process-wide and outlives any single
    `Fetcher`.
    """
    global _fetcher, _executor
    if _fetcher is not None:
        _fetcher.shutdown()
    _fetcher = None
    _executor = None
    _failure_listeners.clear()
