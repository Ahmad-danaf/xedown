"""Whether a remote image reference may be fetched, and how it is addressed.

Pure policy — no I/O, no `gi`, no network. This module decides; it never acts.
Modelled on `links.classify_link` and `images.classify_image`: one reference
in, exactly one outcome out.

The private URI scheme exists so the preview page is never granted `https:`.
Every network byte goes through xedown's own fetch code, and the page can
address it only through a scheme that document content cannot mint --
`sanitizer.ALLOWED_URI_SCHEMES` does not contain it, and must never gain it.
"""

import urllib.parse

SCHEME = "xedown-image"

FETCHABLE = "fetchable"
INSECURE = "insecure"
CREDENTIALS = "credentials"
UNSUPPORTED = "unsupported"
MALFORMED = "malformed"

# A download limit. The decode limits are a separate protection and live in
# `imagelimits.py`, because they also govern inline `data:` images, which have
# nothing to download.
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 5
MAX_REDIRECTS = 3
MAX_CONCURRENT = 4
MAX_PENDING_URLS = 64
CACHE_BYTES = 64 * 1024 * 1024

FETCHABLE_SUBTYPES = frozenset({"png", "jpeg", "jpg", "gif", "webp", "bmp"})


class RemoteDecision:
    """One reference's outcome. `url` is set only when the status is FETCHABLE."""

    def __init__(self, status, url=None):
        self.status = status
        self.url = url


def classify_remote(reference):
    """What may be done with `reference`. Never raises, never resolves DNS."""
    if not isinstance(reference, str) or not reference:
        return RemoteDecision(MALFORMED)
    try:
        parts = urllib.parse.urlsplit(reference)
        scheme = (parts.scheme or "").lower()
        # `.username`/`.password`/`.hostname` each re-parse the authority and
        # can raise on a malformed one, so they are read inside the guard.
        has_credentials = bool(parts.username or parts.password)
        host = parts.hostname
    except ValueError:
        # e.g. an unbalanced IPv6-literal bracket.
        return RemoteDecision(MALFORMED)

    if scheme == "http":
        return RemoteDecision(INSECURE)
    if scheme != "https":
        return RemoteDecision(UNSUPPORTED)
    if has_credentials:
        return RemoteDecision(CREDENTIALS)
    if not host:
        return RemoteDecision(MALFORMED)
    return RemoteDecision(FETCHABLE, url=reference)


def scheme_uri(url):
    """Address `url` through the private scheme.

    `safe=""` leaves no unescaped `/` in the payload, which is what lets
    `parse_scheme_uri` split on the scheme separator without ambiguity.
    """
    return f"{SCHEME}:{urllib.parse.quote(url, safe='')}"


def parse_scheme_uri(uri):
    """The https URL inside `uri`, or None if it is not one we would fetch.

    Re-runs `classify_remote` on the decoded payload rather than trusting it.
    The scheme handler is an entry point: it is reached with whatever is in
    the page's DOM, not only with what the renderer put there.
    """
    if not isinstance(uri, str):
        return None
    prefix = SCHEME + ":"
    if not uri.startswith(prefix):
        return None
    payload = uri[len(prefix) :]
    if not payload:
        return None
    try:
        url = urllib.parse.unquote(payload)
    except (UnicodeDecodeError, ValueError):
        return None
    decision = classify_remote(url)
    return decision.url if decision.status == FETCHABLE else None
