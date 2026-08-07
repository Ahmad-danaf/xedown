"""What an image reference means: shown, or replaced, and why.

Pure logic — no GTK imports belong here. Modelled on `links.classify_link`:
one reference in, exactly one outcome out.

The decision lives here rather than in the page because a browser cannot
tell "no such file" from "permission denied". It reports one load error for
both, and the reader needs to know which.
"""

import os
import stat
import urllib.parse

from . import errors, links, settings
from .sanitizer import ImagePlaceholder

OK = "ok"
REMOTE = "remote"
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


def classify_image(reference, base_dir):
    """What can be done with `reference`. Never raises, never fetches."""
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


def reason_text(decision):
    """Why this image is not being shown, as one sentence."""
    if decision.status == REMOTE:
        return errors.remote_image_text(decision.reference)
    if decision.status == MISSING:
        return errors.local_image_missing_text(decision.path or decision.reference)
    if decision.status == UNREADABLE:
        return errors.local_image_unreadable_text(
            decision.path or decision.reference, decision.detail
        )
    return errors.local_image_unresolved_text(decision.reference)


def placeholder_for(decision, alt, display):
    """What to emit in place of an image. `None` means emit nothing.

    Every failing status is treated alike. The setting is named
    `remote_images`, but a reader who asked for no broken-image noise did
    not mean only the remote kind — and none of the three values touches
    what is fetched, which is nothing.
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
    coerced, _ = settings.by_name(settings.REMOTE_IMAGES).coerce(value)
    return coerced
