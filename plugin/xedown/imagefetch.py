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
            closer = getattr(response, "close", None)
            if closer is not None:
                closer()

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
