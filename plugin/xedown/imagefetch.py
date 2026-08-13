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

# Sent on every request, and nothing else is. No Cookie, no Referer, no
# Authorization: the reader's IP is disclosure enough, and this feature exists
# because that disclosure is the thing being controlled.
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
    destination-checked, so the guarantees hold for the last hop exactly as
    they do for the first.

    Credentials in the *original* reference get their own, specific error --
    it names what is wrong with the address the document actually pointed to.
    Credentials appearing only after a redirect are reported as a refused
    redirect instead: the document did not name that address, the server's
    Location header did, and "redirected somewhere xedown will not follow" is
    the truer description of what the reader hit.
    """
    current = url
    for hop in range(remoteimages.MAX_REDIRECTS + 1):
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
            return _refuse(BLOCKED_DESTINATION, verdict.detail)

        try:
            response = opener(current, dict(_HEADERS), remoteimages.TIMEOUT_S, proxies)
        except urllib.error.HTTPError as exc:
            # Ahead of `URLError`, which is its base class -- and taken as
            # the *response* it also is (`.status`, `.headers`, `.read()`,
            # `.close()` are all there) rather than as a transport failure,
            # so the status handling below is reached with exactly the
            # object it would have got from an opener that returned instead
            # of raising.
            #
            # urllib raises whatever its own handlers did not settle, which
            # here is every non-2xx: `_urllib_opener` removes the redirect
            # handler on purpose, so a 3xx reaches `HTTPDefaultErrorHandler`
            # and is raised too. Reading this as an error would therefore
            # have made the `status != 200` branch below unreachable with a
            # real opener *and* killed the hop-by-hop redirect following
            # this loop exists for. Both were confirmed against real
            # servers: a 404 came back as `network`/"Not Found", and a 302
            # as `network`/"Found" instead of being followed. Only the stub
            # opener in the tests returns a non-200 rather than raising,
            # which is why neither was caught.
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
            return _read_body(response)
        except Exception as exc:  # noqa: BLE001 - a malformed response must not raise
            return _refuse(NETWORK, str(exc))
        finally:
            # A `finally` that raises replaces whatever the `try`/`except` was
            # about to return -- so closing must never be allowed to override
            # the outcome, on a success path or a failure path alike.
            closer = getattr(response, "close", None)
            if closer is not None:
                try:
                    closer()
                except Exception:  # noqa: BLE001, S110 - must not override the outcome
                    pass

    return _refuse(REDIRECT_REFUSED, "it redirected too many times")


def _read_body(response):
    """Read, cap, and measure. Nothing reaches WebKit that is not measured."""
    subtype = _subtype(response.headers.get("Content-Type"))
    if subtype not in remoteimages.FETCHABLE_SUBTYPES:
        return _refuse(NOT_AN_IMAGE, "that address is not an image xedown can measure")

    # One byte past the cap: enough to know it was exceeded, and the
    # Content-Length header is never trusted to say so.
    try:
        body = response.read(remoteimages.MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001
        return _refuse(NETWORK, str(exc))
    if body is None:
        return _refuse(NETWORK, "the server sent nothing")
    if len(body) > remoteimages.MAX_BYTES:
        return _refuse(TOO_LARGE, "it is larger than 8 MB")

    # The same verdict the `data:` path uses, from the same module, so the two
    # cannot drift. They differ only in what an unmeasurable payload means:
    # here it is a refusal, because refusing a fetch takes nothing away from
    # the reader that already worked.
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

    return FetchResult(data=body, mime=f"image/{subtype}")


class Fetcher:
    """One fetch per URL at a time, however many times it is asked for.

    Everything here runs on the GTK main thread except the work handed to the
    executor, so the registry needs no locking: `request` and the delivery
    that follows it are both main-thread, and the worker's only outside call
    besides the fetch itself is the host-supplied `proxies_for` hook, which
    deliberately also runs off the main thread -- Task 12 backs it with
    `Gio.ProxyResolver.lookup()`, which blocks and can consult a PAC script,
    and the whole point of doing the fetch off the main thread is to keep
    exactly that kind of call from stalling the editor. The worker still
    writes to nothing shared: it hands its `result` back through
    `_schedule`/`dispatch` rather than mutating any registry itself.
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
            self._deliver_one(
                on_done,
                _refuse(OFFLINE, "you appear to be offline"),
            )
            return

        if len(self._waiting) >= remoteimages.MAX_PENDING_URLS:
            self._deliver_one(
                on_done,
                _refuse(TOO_MANY, "too many images are already loading"),
            )
            return

        self._waiting[url] = [on_done]
        self._start(url)

    def shutdown(self):
        """Stop taking new work. Running fetches are not interrupted.

        `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)` cancels
        only work still *queued*; anything already *running* runs to
        completion regardless, and the interpreter's own `atexit` hook joins
        the worker threads either way, so this method does not bound how long
        the process can take to exit -- `TIMEOUT_S` does, by bounding how long
        a single running fetch can take.
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
                # Nothing here may leave the URL in flight: the waiters would
                # never hear back and the pending slot would never come back.
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
    """The real opener. Redirects are handled by `fetch_once`, not here."""
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
