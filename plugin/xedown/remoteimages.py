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

# The timeout handed to the opener, which becomes a *socket* timeout: it
# bounds one `recv`, not the transfer. A server sending a few bytes at a time
# satisfies it forever, which is why the deadline below exists as well.
TIMEOUT_S = 5

# Wall-clock seconds for one whole fetch, redirects included. This is what
# actually bounds how long closing xed can be delayed: the fetch runs on a
# non-daemon worker thread that the interpreter joins at exit, so a fetch that
# will not end is a shutdown that will not finish. Generous for any image
# inside an 8 MB cap on an ordinary link, and short enough to be an honest
# worst case to write down.
MAX_TOTAL_S = 15

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
    """Whether a host may be contacted, and why not when it may not.

    `unresolved` separates the two refusals, which are not the same statement:
    a host that resolves to a private address was caught pointing somewhere it
    may not go, while a host that does not resolve at all has been accused of
    nothing. The caller needs the difference to say the right sentence.
    """

    def __init__(self, ok, detail="", unresolved=False):
        self.ok = ok
        self.detail = detail
        self.unresolved = unresolved


def _default_resolver(host):
    """Every address `host` resolves to, as strings."""
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def _is_public(address):
    """True only for an address on the public internet.

    `is_global` alone is not enough: the IPv4-compatible IPv6 form `::a.b.c.d`
    (the `::/96` family) reports `is_global=True` regardless of what its low 32
    bits hold — an attacker-controlled AAAA record could return `::127.0.0.1`.
    `is_reserved` is checked after `is_global` to exclude it and other reserved
    ranges.

    Carrier-grade NAT space (100.64.0.0/10) is rejected by `is_global`. A
    v4-mapped v6 address is unwrapped first, so `::ffff:127.0.0.1` is judged
    as the loopback it is, and the check reads the unwrapped address so
    legitimate v4-mapped public hosts are not refused by the outer address
    being reserved.

    Multicast is excluded by name rather than left to the two predicates
    above: `224.0.0.1` and `ff02::1` are neither reserved nor private, and
    `is_global` says True for them. Nothing can be reached over TCP that way,
    so this closes no hole -- but a predicate called "is this on the public
    internet" should not answer yes about the all-hosts group.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.version == 6 and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global and not parsed.is_reserved and not parsed.is_multicast


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
        return DestinationVerdict(
            False, "that address could not be found", unresolved=True
        )
    if not addresses:
        return DestinationVerdict(
            False, "that address could not be found", unresolved=True
        )
    for address in addresses:
        if not _is_public(address):
            return DestinationVerdict(
                False, "that address is not on the public internet"
            )
    return DestinationVerdict(True)
