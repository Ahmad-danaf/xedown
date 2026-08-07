"""Markdown source to a sanitized, self-contained HTML document."""

import secrets
import urllib.parse

from . import errors, stylesheets, themes, vendoring
from .links import REMOTE_SCHEMES, resolve_to_uri
from .mdext import make_extensions
from .sanitizer import ImagePlaceholder, sanitize

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

# The stylesheet is assembled by `stylesheets.assemble_css`: the syntax sheet
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
{notice}<article class="xedown-document" id="{content_id}">
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


def _on_blocked_image(uri, _alt):
    """Placeholder for an <img> src that could not be resolved locally.

    `uri` is the original reference (a `#`-free, already-safety-checked
    value) that either resolved to a remote scheme or failed to resolve to a
    local file at all. Which wording applies is decided here, from the
    reference itself, so the sanitizer stays free of user-facing copy.

    This is a temporary shim: it does not distinguish a missing local image
    from an unreadable one — both currently read as "unresolved". Task 5
    replaces it with a callback that stats the file to tell them apart.
    """
    try:
        scheme = urllib.parse.urlparse(uri).scheme.lower()
    except ValueError:
        # e.g. an unbalanced IPv6-literal bracket. Unparseable is certainly
        # not a remote reference we could have fetched, so it gets the
        # "unresolved local" wording rather than crashing the render.
        scheme = ""
    if scheme in REMOTE_SCHEMES:
        return ImagePlaceholder("error", errors.remote_image_text(uri))
    return ImagePlaceholder("error", errors.local_image_unresolved_text(uri))


def render_fragment(text, base_dir=None):
    """Convert Markdown to sanitized body HTML with absolute URIs.

    URI resolution happens inside the sanitizer's single structural pass:
    `resolve_uri` turns a relative href into an absolute `file://` URI (or
    leaves a remote/anchor target alone), and `on_image` — the controller's
    amendment for images specifically — decides each `<img>` for itself:
    a reference that resolves to a local `file:`/`data:` URI is rendered,
    and anything remote or unresolvable becomes a visible placeholder
    instead of a tag that would never load.
    """
    converter = _build_converter()
    raw = converter.convert(text or "")

    def resolve(_attribute_name, value):
        if value.startswith("#"):
            return value
        return resolve_to_uri(value, base_dir)

    def on_image(reference, alt):
        # Temporary shim standing in for Task 5: try the same local
        # resolution `resolve_uri` performs for other attributes, and fall
        # back to a placeholder — with no missing/unreadable distinction
        # yet — when that fails.
        resolved = resolve_to_uri(reference, base_dir)
        if resolved is not None and resolved.lower().startswith(("file:", "data:")):
            return resolved
        return _on_blocked_image(reference, alt)

    return sanitize(raw, resolve_uri=resolve, on_image=on_image)


def render_document(text, base_dir=None, dark=False, nonce=None, style=None):
    """Build the complete preview page. Never raises — failures become a page.

    `style` is a `stylesheets.PreviewStyle`: which theme, how wide, how large,
    and the user's own stylesheet. `None` means every default, which is the
    xedown 0.1.0 appearance exactly. A theme identifier the registry does not
    know resolves to the default rather than producing an unstyled page, and a
    theme whose own stylesheet cannot be read falls back the same way; only a
    broken *default* reaches the "Installation incomplete" page below.

    A user stylesheet that could not be loaded produces a notice bar above the
    document rather than a blank or unstyled preview. Error pages get neither
    the user's CSS nor the notice: an error page is not the document, and a
    stylesheet that failed to load is the last thing that should style the
    message saying so.
    """
    token = nonce or secrets.token_urlsafe(16)
    style = style if style is not None else stylesheets.PreviewStyle()
    try:
        body = render_fragment(text, base_dir=base_dir)
        stylesheet, theme_identifier = stylesheets.assemble(style, dark=dark)
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

    notice = ""
    if style.user.problem is not None:
        notice = (
            errors.user_stylesheet_notice(
                style.user.problem,
                style.user.path,
                detail=style.user.detail,
                theme_label=themes.resolve(theme_identifier).label,
            )
            + "\n"
        )

    return _DOCUMENT.format(
        csp=_CSP.format(nonce=token),
        nonce=token,
        appearance="dark" if dark else "light",
        theme=theme_identifier,
        content_id=CONTENT_ELEMENT_ID,
        notice=notice,
        body=body,
        stylesheet=stylesheet,
        preview_js=preview_js,
        highlight_js=highlight_js,
    )
