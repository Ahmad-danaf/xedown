"""Markdown source to a sanitized, self-contained HTML document."""

import secrets
import urllib.parse

from . import errors, vendoring
from .links import REMOTE_SCHEMES, resolve_to_uri
from .mdext import make_extensions
from .sanitizer import sanitize

CONTENT_ELEMENT_ID = "xedown-content"

_CSP = (
    "default-src 'none'; "
    "img-src file: data:; "
    "style-src 'nonce-{nonce}'; "
    "script-src 'nonce-{nonce}'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "object-src 'none'"
)

# The highlight theme is emitted before preview.css, and preview.css carries
# an override of at least equal specificity — see the comment above
# `pre code.hljs` in preview.css for why this order (not just the extra
# rule) is what makes the override actually win.
_DOCUMENT = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<style nonce="{nonce}">
{highlight_css}
{preview_css}
</style>
</head>
<body class="{theme}">
<article class="xedown-document" id="{content_id}">
{body}
</article>
<script nonce="{nonce}">
{highlight_js}
</script>
<script nonce="{nonce}">
{preview_js}
</script>
</body>
</html>
"""


def _build_converter():
    markdown_module = vendoring.import_markdown()
    return markdown_module.Markdown(
        extensions=list(vendoring.MARKDOWN_EXTENSIONS)
        + make_extensions(markdown_module),
        output_format="html",
    )


def _on_blocked_image(uri):
    """Placeholder text for an <img> src the sanitizer refused to emit.

    `uri` is the original reference (a `#`-free, already-safety-checked
    value) that either resolved to a remote scheme or failed to resolve to a
    local file at all. Which wording applies is decided here, from the
    reference itself, so the sanitizer stays free of user-facing copy.
    """
    try:
        scheme = urllib.parse.urlparse(uri).scheme.lower()
    except ValueError:
        # e.g. an unbalanced IPv6-literal bracket. Unparseable is certainly
        # not a remote reference we could have fetched, so it gets the
        # "unresolved local" wording rather than crashing the render.
        scheme = ""
    if scheme in REMOTE_SCHEMES:
        return errors.remote_image_blocked_text(uri)
    return errors.local_image_unresolved_text(uri)


def render_fragment(text, base_dir=None):
    """Convert Markdown to sanitized body HTML with absolute URIs.

    URI resolution happens inside the sanitizer's single structural pass:
    `resolve_uri` turns a relative href/src into an absolute `file://` URI
    (or leaves a remote/anchor target alone), and `on_blocked_image` — the
    controller's amendment for images specifically — replaces an `<img>`
    whose src is remote or unresolvable with a visible placeholder instead
    of emitting a tag that would never load.
    """
    converter = _build_converter()
    raw = converter.convert(text or "")

    def resolve(_attribute_name, value):
        if value.startswith("#"):
            return value
        return resolve_to_uri(value, base_dir)

    return sanitize(raw, resolve_uri=resolve, on_blocked_image=_on_blocked_image)


def render_document(text, base_dir=None, dark=False, nonce=None):
    """Build the complete preview page. Never raises — failures become a page."""
    token = nonce or secrets.token_urlsafe(16)
    try:
        body = render_fragment(text, base_dir=base_dir)
        highlight_css = vendoring.read_resource(
            "highlight-dark.css" if dark else "highlight-light.css"
        )
        preview_css = vendoring.read_resource("preview.css")
        preview_js = vendoring.read_resource("preview.js")
        highlight_js = vendoring.read_vendor_file("highlight.min.js")
    except vendoring.VendorError as exc:
        return errors.error_page(
            "Installation incomplete",
            errors.missing_vendor_detail(exc),
            dark=dark,
            nonce=token,
        )
    except Exception as exc:  # noqa: BLE001 - a blank pane is never acceptable
        return errors.error_page(
            "Cannot render this document",
            errors.render_failure_detail(exc),
            dark=dark,
            nonce=token,
        )

    return _DOCUMENT.format(
        csp=_CSP.format(nonce=token),
        nonce=token,
        theme="dark" if dark else "light",
        content_id=CONTENT_ELEMENT_ID,
        body=body,
        preview_css=preview_css,
        highlight_css=highlight_css,
        preview_js=preview_js,
        highlight_js=highlight_js,
    )
