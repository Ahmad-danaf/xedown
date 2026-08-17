"""Fetching a remote image, and remembering what happened.

Pure in the sense that matters here: no `gi`, and every network call goes
through an injectable opener, so CI drives every path without a network.

The cache holds failures as well as successes, and that is the half that
carries the weight. WebKit serves a previously *successful* image from its own
memory cache across a body swap, but it never caches a failure: a broken image
is re-requested on every re-render, which at `REFRESH_DELAY_MS = 250` is four
attempts a second for as long as the reader keeps typing.
"""

import collections
import ssl
import sys
import time
import urllib.error
import urllib.parse

from . import imagelimits, remoteimages

OFFLINE = "offline"
TIMEOUT = "timeout"
TOO_LARGE = "too_large"
TOO_MANY_PIXELS = "too_many_pixels"
NOT_AN_IMAGE = "not_an_image"
HTTP_ERROR = "http_error"
REDIRECT_REFUSED = "redirect_refused"
BLOCKED_DESTINATION = "blocked_destination"
CREDENTIALS = "credentials"
TOO_MANY = "too_many"
TLS_ERROR = "tls_error"
NETWORK = "network"

# What a negative entry is charged against the byte cap. Failures are small
# but not free: a document naming ten thousand broken URLs should still be
# bounded by the same number the successes are.
_FAILURE_WEIGHT = 256

# An upper bound rather than a target: `read1` hands back whatever one recv
# produced. This only caps how much a single read can be waiting for.
_CHUNK_BYTES = 64 * 1024


def _now():
    """Monotonic seconds, named so a test can drive the deadline."""
    return time.monotonic()


def _reader_for(response):
    """`response.read1` where there is one, `response.read` otherwise.

    This is what lets the deadline bite: `read(n)` blocks until it has all n
    bytes, and the socket timeout only bounds each `recv` underneath, so a
    server sending one byte every four seconds keeps one `read` going as long
    as it likes. `read1` returns after one `recv`, putting the deadline check
    between every piece of the response.
    """
    return getattr(response, "read1", None) or response.read


class FetchResult:
    """One fetch's outcome. Either `data`+`mime`, or `error`+`detail`."""

    def __init__(self, data=None, mime=None, error=None, detail=""):
        self.data = data
        self.mime = mime
        self.error = error
        self.detail = detail

    @property
    def ok(self):
        return self.error is None and self.data is not None

    @property
    def weight(self):
        return len(self.data) if self.ok else _FAILURE_WEIGHT


class ResultCache:
    """An LRU over total bytes, holding successes and failures alike."""

    def __init__(self, max_bytes=remoteimages.CACHE_BYTES):
        self.max_bytes = max_bytes
        self.bytes_held = 0
        self._entries = collections.OrderedDict()

    def get(self, url):
        result = self._entries.get(url)
        if result is not None:
            self._entries.move_to_end(url)
        return result

    def put(self, url, result):
        self._drop(url)
        weight = result.weight
        if weight > self.max_bytes:
            # Storing it would evict everything else and still not fit.
            return
        self._entries[url] = result
        self.bytes_held += weight
        while self.bytes_held > self.max_bytes and self._entries:
            oldest, _ = next(iter(self._entries.items()))
            self._drop(oldest)

    def invalidate_failures(self):
        """Forget every failure, keeping every success.

        Called on reconnect, on Refresh, and on the Load button -- the three
        moments a reader has said, one way or another, "try again".
        """
        for url in [u for u, r in self._entries.items() if not r.ok]:
            self._drop(url)

    def _drop(self, url):
        existing = self._entries.pop(url, None)
        if existing is not None:
            self.bytes_held -= existing.weight


USER_AGENT = "xedown (Markdown preview for xed; https://github.com/Ahmad-danaf/xedown)"

# Sent on every request, and no Cookie, Referer, or Authorization header is
# added. The reader's IP is disclosure enough, and this feature exists because
# that disclosure is the thing being controlled.
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/png, image/jpeg, image/gif, image/webp, image/bmp",
    "Accept-Encoding": "identity",
}

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _subtype(content_type):
    value = (content_type or "").split(";", 1)[0].strip().lower()
    prefix = "image/"
    return value[len(prefix) :] if value.startswith(prefix) else ""


def _refuse(kind, detail=""):
    return FetchResult(error=kind, detail=detail)


def fetch_once(url, opener, resolver=None, proxies=None):
    """Fetch `url` and return a `FetchResult`. Never raises.

    Redirects are followed by hand, one hop at a time, because urllib's own
    handler permits an https -> http downgrade. Every hop is re-classified and
    destination-checked, so the guarantees hold on the last hop as on the
    first.

    Credentials in the *original* reference get their own error naming what is
    wrong with the address the document pointed to; credentials appearing only
    after a redirect are reported as a refused redirect, since the document
    did not name that address.

    One deadline covers the whole call, redirects included, so a chain of slow
    hops cannot restart the clock.
    """
    deadline = _now() + remoteimages.MAX_TOTAL_S
    current = url
    for hop in range(remoteimages.MAX_REDIRECTS + 1):
        if _now() >= deadline:
            return _refuse(TIMEOUT, "the server did not respond")
        decision = remoteimages.classify_remote(current)
        if decision.status != remoteimages.FETCHABLE:
            if hop == 0 and decision.status == remoteimages.CREDENTIALS:
                return _refuse(
                    CREDENTIALS, "that address contains a username and password"
                )
            return _refuse(
                REDIRECT_REFUSED, "it redirected somewhere xedown will not follow"
            )

        host = urllib.parse.urlsplit(current).hostname
        verdict = remoteimages.check_destination(host, resolver=resolver)
        if not verdict.ok:
            if verdict.unresolved:
                # A name that does not resolve has not been caught doing
                # anything: calling it a blocked destination accuses an
                # ordinary typo or DNS outage of being a private-network probe.
                return _refuse(NETWORK, verdict.detail)
            return _refuse(BLOCKED_DESTINATION, verdict.detail)

        try:
            response = opener(current, dict(_HEADERS), remoteimages.TIMEOUT_S, proxies)
        except urllib.error.HTTPError as exc:
            # Ahead of its base `URLError`, and taken as the *response* it
            # also is rather than a transport failure. `_urllib_opener` drops
            # the redirect handler, so urllib raises every non-2xx including
            # 3xx: treating this as an error made the `status != 200` branch
            # unreachable and killed redirect following outright (confirmed
            # against real servers -- a 404 became `network`/"Not Found", a
            # 302 was never followed). Only the test stub returns rather than
            # raising, which is why neither was caught.
            response = exc
        except TimeoutError:
            return _refuse(TIMEOUT, "the server did not respond")
        except ssl.SSLError as exc:
            return _refuse(TLS_ERROR, str(exc))
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, TimeoutError):
                return _refuse(TIMEOUT, "the server did not respond")
            if isinstance(reason, ssl.SSLError):
                return _refuse(TLS_ERROR, str(reason))
            return _refuse(NETWORK, str(reason))
        except Exception as exc:  # noqa: BLE001 - a fetch never breaks a render
            return _refuse(NETWORK, str(exc))

        try:
            status = int(getattr(response, "status", 0) or 0)
            if status in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location:
                    return _refuse(
                        REDIRECT_REFUSED,
                        "it redirected somewhere xedown will not follow",
                    )
                current = urllib.parse.urljoin(current, location)
                continue
            if status != 200:
                return _refuse(HTTP_ERROR, f"the server said {status}")
            return _read_body(response, deadline)
        except Exception as exc:  # noqa: BLE001 - a malformed response must not raise
            return _refuse(NETWORK, str(exc))
        finally:
            # A raising `finally` would replace the outcome the `try` was
            # about to return, on success and failure paths alike.
            closer = getattr(response, "close", None)
            if closer is not None:
                try:
                    closer()
                except Exception:  # noqa: BLE001, S110 - must not override the outcome
                    pass

    return _refuse(REDIRECT_REFUSED, "it redirected too many times")


def _read_body(response, deadline=None):
    """Read, cap, and measure. Nothing reaches WebKit that is not measured.

    Chunked against a wall-clock `deadline`, because the opener's timeout is
    a *socket* timeout that a server dripping bytes satisfies indefinitely.
    The fetch runs on a non-daemon worker the interpreter joins at exit, so
    an unbounded read is an unbounded wait for anyone closing xed --
    `deadline` is what makes the documented 15 seconds true.
    """
    subtype = _subtype(response.headers.get("Content-Type"))
    if subtype not in remoteimages.FETCHABLE_SUBTYPES:
        return _refuse(NOT_AN_IMAGE, "that address is not an image xedown can measure")

    # One byte past the cap, enforced on what was actually read: the
    # Content-Length header is never trusted to report the size.
    cap = remoteimages.MAX_BYTES + 1
    read = _reader_for(response)
    chunks = []
    read_so_far = 0
    while read_so_far < cap:
        if deadline is not None and _now() >= deadline:
            return _refuse(TIMEOUT, "the server did not respond")
        try:
            chunk = read(min(_CHUNK_BYTES, cap - read_so_far))
        except TimeoutError:
            # Without this, a socket timeout mid-body fell through to the
            # broad handler and was reported as "it could not be reached" for
            # a server that answered fine and then stopped talking.
            # (`socket.timeout` is this class from 3.10 on; ruff UP041.)
            return _refuse(TIMEOUT, "the server did not respond")
        except Exception as exc:  # noqa: BLE001
            return _refuse(NETWORK, str(exc))
        if chunk is None:
            # On the first read this is a response that never produced a
            # body, not an empty image.
            if not chunks:
                return _refuse(NETWORK, "the server sent nothing")
            break
        if not chunk:
            break
        chunks.append(chunk)
        read_so_far += len(chunk)

    body = b"".join(chunks)
    if read_so_far > remoteimages.MAX_BYTES:
        return _refuse(TOO_LARGE, "it is larger than 8 MB")

    # The same verdict the `data:` path uses, so the two cannot drift. They
    # differ only in what an unmeasurable payload means: a refusal here,
    # because refusing a fetch takes away nothing that already worked.
    verdict = imagelimits.pixel_verdict(body)
    if not verdict.known:
        # Not a container we can measure at all (AVIF, SVG, anything else).
        return _refuse(NOT_AN_IMAGE, "that address is not an image xedown can measure")
    if not verdict.ok:
        if verdict.width:
            return _refuse(TOO_MANY_PIXELS, verdict.describe())
        # Claimed a format we parse, then would not yield dimensions: corrupt
        # or evasive, and either way not something to hand to a decoder.
        return _refuse(NOT_AN_IMAGE, "that image is damaged or could not be read")

    # `image/jpg` is a spelling servers use and no registry has: WebKit is
    # handed the canonical type rather than one it has to be forgiving about.
    mime = "image/jpeg" if subtype == "jpg" else f"image/{subtype}"
    return FetchResult(data=body, mime=mime)


class Fetcher:
    """One fetch per URL at a time, however many times it is asked for.

    Everything runs on the GTK main thread except the work handed to the
    executor, so the registry needs no locking. The worker's only outside call
    besides the fetch is `proxies_for`, which runs off the main thread on
    purpose: it is backed by `Gio.ProxyResolver.lookup()`, which blocks and
    can consult a PAC script. The worker mutates nothing shared, handing its
    result back through `_schedule`/`dispatch`.
    """

    def __init__(
        self,
        opener=None,
        resolver=None,
        network_available=None,
        proxies_for=None,
        executor=None,
        dispatch=None,
    ):
        self._opener = opener if opener is not None else _urllib_opener
        self._resolver = resolver
        self._network_available = network_available
        self._proxies_for = proxies_for
        self._executor = executor
        self._dispatch = dispatch
        self.cache = ResultCache()
        self._waiting = {}  # url -> [callbacks]

    def cached(self, url):
        return self.cache.get(url)

    def invalidate_failures(self):
        self.cache.invalidate_failures()

    def request(self, url, on_done):
        """Deliver `url`'s result to `on_done`, fetching at most once."""
        cached = self.cache.get(url)
        if cached is not None:
            self._deliver_one(on_done, cached)
            return

        waiters = self._waiting.get(url)
        if waiters is not None:
            # Already in flight. This is what stops a re-render every 250ms
            # from starting a second, third and twentieth fetch of one image.
            waiters.append(on_done)
            return

        if self._network_available is not None and not self._network_available():
            # Cached like any other failure, unlike TOO_MANY below. Without
            # this, `controller._on_image_error` looks the failure up by
            # `cached(url)`, misses, and the reader gets generic text instead
            # of "you appear to be offline" in the one situation that sentence
            # exists for. `invalidate_failures()` on reconnect, Refresh and
            # Load is exactly the lifetime the placeholder's wording promises.
            result = _refuse(OFFLINE, "you appear to be offline")
            self.cache.put(url, result)
            self._deliver_one(on_done, result)
            return

        if len(self._waiting) >= remoteimages.MAX_PENDING_URLS:
            # Deliberately NOT cached, unlike OFFLINE: this is a fact about
            # the queue right now, not about the URL, and caching it would
            # leave the URL stuck failed long after the queue drained.
            self._deliver_one(
                on_done,
                _refuse(TOO_MANY, "too many images are already loading"),
            )
            return

        self._waiting[url] = [on_done]
        self._start(url)

    def shutdown(self):
        """Stop taking new work. Running fetches are not interrupted.

        `cancel_futures=True` cancels only *queued* work; anything running
        finishes, and the interpreter joins the workers at exit anyway. So
        this does not bound exit time -- `MAX_TOTAL_S` does. `TIMEOUT_S`
        cannot: a server dribbling bytes never trips a socket timeout.
        """
        self._waiting.clear()
        executor = self._executor
        if executor is not None and hasattr(executor, "shutdown"):
            executor.shutdown(wait=False, cancel_futures=True)

    def _start(self, url):
        def work():
            try:
                proxies = (
                    self._proxies_for(url) if self._proxies_for is not None else None
                )
                result = fetch_once(
                    url,
                    opener=self._opener,
                    resolver=self._resolver,
                    proxies=proxies,
                )
            except Exception as exc:  # noqa: BLE001 - the slot must always be released
                # Leaving the URL in flight would strand its waiters and
                # never return the pending slot.
                result = _refuse(NETWORK, str(exc))
            self._schedule(lambda: self._settle(url, result))

        if self._executor is None:
            work()
        else:
            self._executor.submit(work)

    def _schedule(self, thunk):
        if self._dispatch is None:
            thunk()
        else:
            self._dispatch(thunk)

    def _settle(self, url, result):
        self.cache.put(url, result)
        for callback in self._waiting.pop(url, []):
            self._deliver_one(callback, result)

    @staticmethod
    def _deliver_one(callback, result):
        try:
            callback(result)
        except Exception as exc:  # noqa: BLE001 - one waiter must not stop the rest
            sys.stderr.write(f"xedown: an image callback failed: {exc}\n")


def _urllib_opener(url, headers, timeout, proxies):
    """The real opener. Redirects are handled by `fetch_once`, not here.

    `timeout` is only a socket timeout, bounding each network operation; the
    transfer as a whole is bounded by `fetch_once`'s deadline.
    """
    import urllib.request

    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            # urllib's own handler permits an https -> http downgrade, so it
            # is removed outright and `fetch_once` follows hops itself.
            return None

    opener = urllib.request.build_opener(
        _NoRedirects(), urllib.request.ProxyHandler(proxies or {})
    )
    request = urllib.request.Request(url, headers=headers)
    return opener.open(request, timeout=timeout)
