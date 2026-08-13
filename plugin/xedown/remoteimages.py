"""Whether a remote image reference may be fetched, and how it is addressed.

Pure policy — no I/O, no `gi`, no network. This module decides; it never acts.
Modelled on `links.classify_link` and `images.classify_image`: one reference
in, exactly one outcome out.

The private URI scheme exists so the preview page is never granted `https:`.
Every network byte goes through xedown's own fetch code, and the page can
address it only through a scheme that document content cannot mint --
`sanitizer.ALLOWED_URI_SCHEMES` does not contain it, and must never gain it.
"""

import ipaddress
import socket
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


class DestinationVerdict:
    """Whether a host may be contacted, and why not when it may not."""

    def __init__(self, ok, detail=""):
        self.ok = ok
        self.detail = detail


def _default_resolver(host):
    """Every address `host` resolves to, as strings."""
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _is_public(address):
    """True only for an address on the public internet.

    `is_global` rather than `not is_private`: carrier-grade NAT space
    (100.64.0.0/10) is neither global nor private, and only `is_global`
    rejects it. A v4-mapped v6 address is unwrapped first, so
    `::ffff:127.0.0.1` is judged as the loopback it is.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global


def check_destination(host, resolver=None):
    """Whether `host` resolves only to public addresses.

    Checked after resolution, never on the hostname string: `2130706433`,
    `0x7f000001` and `0177.0.0.1` all resolve to 127.0.0.1, so a string check
    would be no check at all.

    Every returned address must be public. One private answer is enough to
    refuse -- a round-robin that sometimes answers privately must not be
    allowed through on a lucky ordering.
    """
    resolve = resolver if resolver is not None else _default_resolver
    try:
        addresses = list(resolve(host))
    except Exception:  # noqa: BLE001 - a resolver failure is a refusal
        return DestinationVerdict(False, "the address could not be resolved")
    if not addresses:
        return DestinationVerdict(False, "the address could not be resolved")
    for address in addresses:
        if not _is_public(address):
            return DestinationVerdict(
                False, "that address is not on the public internet"
            )
    return DestinationVerdict(True)
