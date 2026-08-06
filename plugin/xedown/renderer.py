"""Markdown source to a sanitized, self-contained HTML document."""

import secrets
import urllib.parse

from . import errors, themes, vendoring
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

# The stylesheet is assembled by `themes.assemble_css`: the syntax sheet
# first, then preview.css, then the theme. preview.css carries an override
# of at least equal specificity to the highlight theme's — see the comment
# above `pre code.hljs` in preview.css for why that ordering, and not just
# the extra rule, is what makes the override actually win.
_DOCUMENT = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<style nonce="{nonce}">
{stylesheet}
</style>
</head>
<body class="{appearance} xedown-theme-{theme}">
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


def render_document(text, base_dir=None, dark=False, nonce=None, theme=None):
    """Build the complete preview page. Never raises — failures become a page.

    `theme` is a `themes` identifier. Anything unknown resolves to the
    default rather than producing an unstyled page, and a theme whose own
    stylesheet cannot be read falls back the same way; only a broken
    *default* reaches the "Installation incomplete" page below.
    """
    token = nonce or secrets.token_urlsafe(16)
    try:
        body = render_fragment(text, base_dir=base_dir)
        stylesheet, theme_identifier = themes.assemble_css(theme, dark=dark)
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
        appearance="dark" if dark else "light",
        theme=theme_identifier,
        content_id=CONTENT_ELEMENT_ID,
        body=body,
        stylesheet=stylesheet,
        preview_js=preview_js,
        highlight_js=highlight_js,
    )
