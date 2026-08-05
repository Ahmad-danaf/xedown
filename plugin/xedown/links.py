"""Decides what a link or image reference means. Pure — no GTK calls here."""

import dataclasses
import enum
import os
import urllib.parse

from .document_state import is_markdown_path

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico")

DANGEROUS_SUFFIXES = (
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".desktop",
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".ps1",
    ".py",
    ".pl",
    ".rb",
    ".jar",
    ".appimage",
    ".run",
    ".bin",
    ".deb",
    ".rpm",
    ".so",
    ".dll",
)

REMOTE_SCHEMES = frozenset({"http", "https", "mailto"})


class LinkAction(enum.Enum):
    EXTERNAL_BROWSER = "external_browser"
    OPEN_IN_XED = "open_in_xed"
    DESKTOP_HANDLER = "desktop_handler"
    CONFIRM_THEN_DESKTOP = "confirm_then_desktop"
    IN_PAGE_ANCHOR = "in_page_anchor"
    REFUSE = "refuse"


@dataclasses.dataclass(frozen=True)
class LinkDecision:
    action: LinkAction
    target: str = ""
    reason: str = ""


def is_supported_image(path):
    return os.path.splitext(path or "")[1].lower() in IMAGE_SUFFIXES


def is_dangerous_path(path):
    return os.path.splitext(path or "")[1].lower() in DANGEROUS_SUFFIXES


def _normalized_local_path(reference, base_dir):
    """Resolve `reference` against `base_dir` into a normalized absolute path.

    Returns None when `reference` is relative and there is no base directory
    to resolve it against (e.g. an unsaved document). An already-absolute
    reference — including one carried inside a `file://` URI — does not need
    a base directory and resolves regardless of whether one was given.

    Malformed input (for example a percent-escape that decodes to an
    embedded NUL byte) must not raise out of here; it is treated the same as
    "cannot resolve".
    """
    try:
        candidate = urllib.parse.unquote(reference)
        if candidate[:7].lower() == "file://":
            candidate = urllib.parse.unquote(urllib.parse.urlparse(candidate).path)
        if not os.path.isabs(candidate):
            if base_dir is None:
                return None
            candidate = os.path.join(base_dir, candidate)
        return os.path.normpath(os.path.realpath(candidate))
    except (OSError, ValueError):
        return None


def resolve_to_uri(reference, base_dir):
    """Return an absolute URI for `reference`, or None when it cannot resolve.

    `file:` references are resolved through the same local-path machinery
    as bare paths (rather than being handed back verbatim), so the result
    is always a properly percent-encoded `file://` URI — consistent with
    what `classify_link` returns for the same reference.
    """
    if not reference:
        return None
    try:
        scheme = urllib.parse.urlparse(reference).scheme.lower()
    except ValueError:
        # e.g. an unbalanced IPv6-literal bracket in the authority.
        # Malformed input fails closed instead of propagating, the same way
        # `_normalized_local_path` already does for other malformed input
        # (bad percent escapes, embedded NUL bytes) below.
        return None
    if scheme in REMOTE_SCHEMES or scheme == "data":
        return reference
    path = _normalized_local_path(reference, base_dir)
    if path is None:
        return None
    return "file://" + urllib.parse.quote(path)


def classify_link(uri, base_dir):
    """Map a link target to exactly one action."""
    if not uri:
        return LinkDecision(LinkAction.REFUSE, reason="empty link target")

    if uri.startswith("#"):
        return LinkDecision(LinkAction.IN_PAGE_ANCHOR, target=uri[1:])

    try:
        scheme = urllib.parse.urlparse(uri).scheme.lower()
    except ValueError:
        return LinkDecision(
            LinkAction.REFUSE, reason=f"cannot resolve “{uri}”: malformed link"
        )
    if scheme in REMOTE_SCHEMES:
        return LinkDecision(LinkAction.EXTERNAL_BROWSER, target=uri)
    if scheme and scheme != "file":
        return LinkDecision(
            LinkAction.REFUSE, reason=f"unsupported link type: {scheme}:"
        )

    path = _normalized_local_path(uri, base_dir)
    if path is None:
        return LinkDecision(
            LinkAction.REFUSE,
            reason=(
                f"cannot resolve “{uri}” because this document has not been "
                "saved yet"
            ),
        )
    if not os.path.exists(path):
        return LinkDecision(
            LinkAction.REFUSE, reason=f"cannot open “{uri}”: the file does not exist"
        )

    target = "file://" + urllib.parse.quote(path)
    if is_markdown_path(path):
        return LinkDecision(LinkAction.OPEN_IN_XED, target=target)
    if is_dangerous_path(path) or (os.path.isfile(path) and os.access(path, os.X_OK)):
        return LinkDecision(
            LinkAction.CONFIRM_THEN_DESKTOP,
            target=target,
            reason=f"“{os.path.basename(path)}” can run code on your computer",
        )
    return LinkDecision(LinkAction.DESKTOP_HANDLER, target=target)
