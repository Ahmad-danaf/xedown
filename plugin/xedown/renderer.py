"""Markdown source to a sanitized, self-contained HTML document."""

import html
import json
import secrets

from . import direction, errors, images, settings, stylesheets, themes, vendoring
from .links import resolve_to_uri
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

# The stylesheet is assembled by `stylesheets.assemble_css`: the syntax sheet
# first, then preview.css, then the theme. preview.css carries an override
# of at least equal specificity to the highlight theme's — see the comment
# above `pre code.hljs` in preview.css for why that ordering, and not just
# the extra rule, is what makes the override actually win.
_DOCUMENT = """<!DOCTYPE html>
<html{lang} dir="{ui_direction}">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<style nonce="{nonce}">
{stylesheet}
</style>
</head>
<body class="{appearance} xedown-theme-{theme}">
{notice}<article class="xedown-document" role="document" id="{content_id}" dir="{doc_direction}">
{body}
</article>
<script nonce="{nonce}">
window.xedownConfig = {config};
</script>
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


def render_fragment(text, base_dir=None, image_display=images.DISPLAY_PLACEHOLDER):
    """Convert Markdown to sanitized body HTML with absolute URIs.

    URI resolution happens inside the sanitizer's single structural pass.
    `resolve_uri` turns a relative href into an absolute `file://` URI (or
    leaves a remote/anchor target alone). Images go through `on_image`
    instead, which classifies the reference once — including a `stat`, so a
    missing file and an unreadable one are told apart — and returns either a
    usable src or the placeholder `image_display` asks for.
    """
    converter = _build_converter()
    raw = converter.convert(text or "")
    display = images.coerce_display(image_display)

    def resolve(_attribute_name, value):
        if value.startswith("#"):
            return value
        return resolve_to_uri(value, base_dir)

    def on_image(reference, alt):
        decision = images.classify_image(reference, base_dir)
        if decision.status == images.OK:
            return decision.uri
        return images.placeholder_for(decision, alt, display)

    return sanitize(raw, resolve_uri=resolve, on_image=on_image)


def render_document(
    text,
    base_dir=None,
    dark=False,
    nonce=None,
    style=None,
    image_display=images.DISPLAY_PLACEHOLDER,
    code_copy_buttons=True,
    text_direction=direction.AUTO,
    ui_direction=direction.LTR,
    lang=None,
):
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

    `image_display` and `code_copy_buttons` are what the settings say about
    the *content* rather than the appearance, which is why they are plain
    arguments and not fields of `PreviewStyle`. Both are also emitted as a
    `window.xedownConfig` object, so a loaded page can be told about a
    change without being reloaded and a fresh page needs no telling.

    `text_direction` and `ui_direction` are two different things and both are
    needed. The first is the *document's*, from the setting of the same name,
    and lands on the article; `auto` means it is detected from the text. The
    second is the *desktop's*, and lands on `<html>`, so xedown's own chrome —
    the stylesheet notice, and the error pages — follows GTK rather than
    whatever language the document happens to be in.
    """
    token = nonce or secrets.token_urlsafe(16)
    style = style if style is not None else stylesheets.PreviewStyle()
    display = images.coerce_display(image_display)
    # Coerced the same way `display` is, and for the same reason:
    # render_document is called directly by the render script and by the
    # tests, not only through the settings store, so a bad argument here
    # (not just a bad stored value) must still produce a page rather than
    # let `json.dumps`/`bool()` raise past the try below. Mirrors
    # `stylesheets._in_range`'s use of the descriptor for the same purpose.
    copy_buttons, _ = settings.by_name(settings.CODE_COPY_BUTTONS).coerce(
        code_copy_buttons
    )
    # Resolved before the try, because both except branches build an error
    # page and need it. The document's own direction is resolved inside the
    # try instead: it reads the text, so it belongs with the render.
    ui = direction.coerce_ui(ui_direction)
    try:
        doc_direction = direction.resolve(text_direction, text)
        body = render_fragment(text, base_dir=base_dir, image_display=display)
        stylesheet, theme_identifier = stylesheets.assemble(style, dark=dark)
        preview_js = vendoring.read_resource("preview.js")
        highlight_js = vendoring.read_vendor_file("highlight.min.js")
    except vendoring.VendorError as exc:
        return errors.error_page(
            "Installation incomplete",
            errors.missing_vendor_detail(exc),
            dark=dark,
            nonce=token,
            ui_direction=ui,
        )
    except Exception as exc:  # noqa: BLE001 - a blank pane is never acceptable
        return errors.error_page(
            "Cannot render this document",
            errors.render_failure_detail(exc),
            dark=dark,
            nonce=token,
            ui_direction=ui,
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

    lang_attribute = ""
    if lang:
        # Escaped like every other author-influenced value that reaches the
        # template: the locale comes from the environment, not from the
        # document, but the escaping costs nothing and the rule is that
        # nothing reaches an attribute unescaped.
        lang_attribute = f' lang="{html.escape(str(lang), quote=True)}"'

    return _DOCUMENT.format(
        csp=_CSP.format(nonce=token),
        nonce=token,
        appearance="dark" if dark else "light",
        theme=theme_identifier,
        content_id=CONTENT_ELEMENT_ID,
        notice=notice,
        body=body,
        stylesheet=stylesheet,
        config=json.dumps({"codeCopy": copy_buttons, "imageDisplay": display}),
        preview_js=preview_js,
        highlight_js=highlight_js,
        ui_direction=ui,
        doc_direction=doc_direction,
        lang=lang_attribute,
    )
