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

from . import remoteimages

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
