"""What an image reference means: shown, or replaced, and why.

Pure logic — no GTK imports belong here. Modelled on `links.classify_link`:
one reference in, exactly one outcome out.

The decision lives here rather than in the page because a browser cannot
tell "no such file" from "permission denied". It reports one load error for
both, and the reader needs to know which.
"""

import os
import stat
import sys
import urllib.parse

from . import errors, links, remoteimages, settings
from .sanitizer import ImagePlaceholder

OK = "ok"
REMOTE = "remote"
FETCH = "fetch"
REMOTE_BLOCKED = "remote_blocked"
REMOTE_INSECURE = "remote_insecure"
UNRESOLVED = "unresolved"
MISSING = "missing"
UNREADABLE = "unreadable"

DISPLAY_PLACEHOLDER = "placeholder"
DISPLAY_ALT = "alt"
DISPLAY_HIDDEN = "hidden"


class ImageDecision:
    """One reference's outcome. `uri` is set only when the status is OK."""

    def __init__(self, status, uri=None, reference="", path=None, detail=""):
        self.status = status
        self.uri = uri
        self.reference = reference
        self.path = path
        self.detail = detail


def classify_image(reference, base_dir, fetch_remote=False):
    """What can be done with `reference`. Never raises, never fetches itself.

    `fetch_remote` is the *document's* permission -- already resolved by the
    caller from the global setting and any per-document override -- not a
    policy this function consults on its own.
    """
    # No caller in this codebase can reach this today: the sanitizer never
    # hands `on_image` a reference at all unless `_is_safe_uri` already
    # accepted it, which requires a non-empty string. But the guarantee is
    # this module's own, not its callers' -- `images.py` exists to be
    # called and tested directly, so `None`/`""` must resolve to a status
    # rather than raise or read a bogus path (an empty reference would
    # otherwise resolve to `base_dir` itself and be reported "unreadable").
    if not isinstance(reference, str) or not reference:
        return ImageDecision(
            UNRESOLVED, reference=reference if isinstance(reference, str) else ""
        )

    try:
        scheme = urllib.parse.urlparse(reference).scheme.lower()
    except ValueError:
        # e.g. an unbalanced IPv6-literal bracket. Something unparseable is
        # certainly not a reference we could have fetched, so it gets the
        # unresolved wording -- which is what this has always done.
        return ImageDecision(UNRESOLVED, reference=reference)

    if scheme == "data":
        return ImageDecision(OK, uri=reference, reference=reference)
    if scheme in links.REMOTE_SCHEMES:
        remote = remoteimages.classify_remote(reference)
        if remote.status == remoteimages.INSECURE:
            return ImageDecision(REMOTE_INSECURE, reference=reference)
        if remote.status == remoteimages.FETCHABLE:
            if not fetch_remote:
                return ImageDecision(REMOTE_BLOCKED, reference=reference)
            return ImageDecision(
                FETCH, uri=remoteimages.scheme_uri(remote.url), reference=reference
            )
        if remote.status == remoteimages.MALFORMED:
            # Not a well-formed reference at all (empty authority, missing
            # host) -- the same "unresolved" wording an unparseable local
            # path gets, not the remote wording, because there is no address
            # here for a remote sentence to name.
            return ImageDecision(UNRESOLVED, reference=reference)
        # mailto:, or credentials. Neither is a thing the reader can choose
        # to load, so they keep the older, deliberately vaguer wording
        # rather than gaining a control they cannot act on.
        return ImageDecision(REMOTE, reference=reference)

    path = links.resolve_to_path(reference, base_dir)
    if path is None:
        return ImageDecision(UNRESOLVED, reference=reference)

    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return ImageDecision(MISSING, reference=reference, path=path)
    except OSError as exc:
        return ImageDecision(
            UNREADABLE,
            reference=reference,
            path=path,
            detail=exc.strerror or str(exc),
        )
    except ValueError as exc:
        # `os.stat` raises ValueError, not OSError, on an embedded NUL
        # byte. `resolve_to_path` normally catches that first, but its
        # guard depends on `os.path.realpath`'s own handling, which has
        # changed between Python versions. A render must not depend on that.
        return ImageDecision(
            UNREADABLE, reference=reference, path=path, detail=str(exc)
        )

    # Not a size check: a FIFO blocks a read until something writes to the
    # other end, and the GTK main thread is what would block. The same
    # reasoning as `stylesheets.load_user_stylesheet`. This also disposes of
    # directories, sockets and device nodes.
    if not stat.S_ISREG(info.st_mode):
        return ImageDecision(
            UNREADABLE, reference=reference, path=path, detail="not a regular file"
        )
    if not os.access(path, os.R_OK):
        return ImageDecision(
            UNREADABLE, reference=reference, path=path, detail="permission denied"
        )
    return ImageDecision(
        OK, uri=links.uri_for_path(path), reference=reference, path=path
    )


_NOT_A_REFUSAL = frozenset({OK, FETCH})


def reason_text(decision):
    """Why this image is not being shown, as one sentence.

    `OK` and `FETCH` are not refusals -- each carries a URI the caller is
    meant to use -- so reaching here with one means a caller skipped that
    branch. Say something neutral and complain to stderr rather than tell
    the reader a working image is missing, which is what the fall-through
    below would otherwise do.
    """
    if decision.status in _NOT_A_REFUSAL:
        sys.stderr.write(
            f"xedown: reason_text called for a usable image ({decision.status})\n"
        )
        return "This image could not be displayed."
    if decision.status == REMOTE:
        return errors.remote_image_text(decision.reference)
    if decision.status == REMOTE_BLOCKED:
        return errors.remote_image_blocked_text(decision.reference)
    if decision.status == REMOTE_INSECURE:
        return errors.insecure_image_text(decision.reference)
    if decision.status == MISSING:
        return errors.local_image_missing_text(decision.path or decision.reference)
    if decision.status == UNREADABLE:
        return errors.local_image_unreadable_text(
            decision.path or decision.reference, decision.detail
        )
    return errors.local_image_unresolved_text(decision.reference)


def placeholder_for(decision, alt, display):
    """What to emit in place of an image. `None` means emit nothing.

    Every failing status is treated alike: a reader who asked for no
    broken-image noise did not mean only the remote kind. `display` is
    `image_fallback`, not the `remote_images` fetch policy — none of its
    three values touches whether anything is fetched.
    """
    if display == DISPLAY_HIDDEN:
        return None
    if display == DISPLAY_ALT:
        words = (alt or "").strip()
        return ImagePlaceholder("alt", words) if words else None
    return ImagePlaceholder("error", errors.with_alt(reason_text(decision), alt))


def coerce_display(value):
    """`value` as one of the three display modes, or the default.

    `render_document` is called directly by the render script and by the
    tests, not only through the settings store. `themes.resolve` set the
    precedent: a bad argument produces a sane page, not a broken one.
    """
    coerced, _ = settings.by_name(settings.IMAGE_FALLBACK).coerce(value)
    return coerced


class RenderStats:
    """What one render did about the images in it.

    Filled in by the renderer and read by the controller, which needs
    `blocked_remote` to decide whether the mode bar offers to load them.

    `rendered` is the second half of that answer, and the counts are not
    usable without it: the body is built *before* the steps of a full-page
    render that can still fail, so an error page can be returned with real
    counts already recorded against it. It says that the HTML this describes
    is the document -- that the images counted here are in the page the
    reader is about to see. Set by whichever entry point produced that HTML
    (`render_fragment` when it returns, `render_document` after its last
    step that can fail, which also puts it back to False when the fragment
    succeeded and a later step did not), so a caller can offer to load
    blocked images without first having to tell an error page from a
    document itself.
    """

    def __init__(self):
        self.blocked_remote = 0
        self.remote = 0
        self.insecure = 0
        self.rendered = False

    def record(self, decision):
        if decision.status == REMOTE_BLOCKED:
            self.blocked_remote += 1
        elif decision.status == FETCH:
            self.remote += 1
        elif decision.status == REMOTE_INSECURE:
            self.insecure += 1
