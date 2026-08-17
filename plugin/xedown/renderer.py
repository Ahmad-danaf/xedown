"""Markdown source to a sanitized, self-contained HTML document."""

import html
import json
import secrets

from . import (
    direction,
    errors,
    images,
    remoteimages,
    settings,
    stylesheets,
    themes,
    vendoring,
)
from .links import resolve_to_uri
from .mdext import make_extensions
from .sanitizer import RemoteImage, sanitize

CONTENT_ELEMENT_ID = "xedown-content"

# How the loaded extensions are configured, keyed by the same fully-qualified
# names as `vendoring.MARKDOWN_EXTENSIONS`, and here because it is a rendering
# decision rather than a vendoring one.
#
# `tables` emits `style="text-align: ..."` by default, which the sanitizer
# drops -- correctly, and that must not change. `use_align_attribute` makes it
# emit `align="..."` instead, which `ALLOWED_ATTRIBUTES` already permits on
# `td`/`th`: no sanitizer change and no vendored-code edit needed.
_EXTENSION_CONFIGS = {
    "markdown.extensions.tables": {"use_align_attribute": True},
}

_CSP_TEMPLATE = (
    "default-src 'none'; "
    "img-src {img_sources}; "
    "style-src 'nonce-{nonce}'; "
    "script-src 'nonce-{nonce}'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-src 'none'; "
    "object-src 'none'"
)


def _csp(nonce, fetch_remote):
    """The policy for one page.

    `img-src` never contains `http:` or `https:`, whatever the settings say:
    the page is not the thing that fetches. The private scheme is listed only
    for a permitted render, which puts a second, independent layer under the
    render-time gating -- a blocked document could not load such a URL even
    if one reached its DOM.
    """
    sources = "file: data:"
    if fetch_remote:
        sources += f" {remoteimages.SCHEME}:"
    return _CSP_TEMPLATE.format(img_sources=sources, nonce=nonce)


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
{notice}<article class="xedown-document" role="main" id="{content_id}" dir="{doc_direction}">
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


def _note_rendered(stats, rendered):
    """Say whether the HTML about to be returned is the document itself.

    A free function rather than a method on `RenderStats`, because `stats`
    is optional at every call site and this is the only place that knows it.
    """
    if stats is not None:
        stats.rendered = rendered


def _build_converter():
    markdown_module = vendoring.import_markdown()
    return markdown_module.Markdown(
        extensions=list(vendoring.MARKDOWN_EXTENSIONS)
        + make_extensions(markdown_module),
        extension_configs=_EXTENSION_CONFIGS,
        output_format="html",
    )


def render_fragment(
    text,
    base_dir=None,
    image_display=images.DISPLAY_PLACEHOLDER,
    fetch_remote=False,
    stats=None,
):
    """Convert Markdown to sanitized body HTML with absolute URIs.

    URI resolution happens inside the sanitizer's single structural pass.
    `resolve_uri` makes a relative href absolute; images go through
    `on_image`, which classifies the reference once -- including a `stat`, so
    a missing file and an unreadable one are told apart.

    `stats` is an out-parameter, since the return value is HTML and this must
    never raise. Its `rendered` flag is set only on the way out, so a
    fragment that raised leaves no counts a caller could mistake for what is
    on screen -- and `render_document` puts it back to False if one of *its*
    later steps fails after this one succeeded.
    """
    converter = _build_converter()
    raw = converter.convert(text or "")
    display = images.coerce_display(image_display)

    def resolve(_attribute_name, value):
        if value.startswith("#"):
            return value
        return resolve_to_uri(value, base_dir)

    def on_image(reference, alt):
        decision = images.classify_image(reference, base_dir, fetch_remote=fetch_remote)
        if stats is not None:
            stats.record(decision)
        if decision.status == images.OK:
            return decision.uri
        if decision.status == images.FETCH:
            return RemoteImage(decision.uri)
        return images.placeholder_for(decision, alt, display)

    body = sanitize(raw, resolve_uri=resolve, on_image=on_image)
    _note_rendered(stats, True)
    return body


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
    fetch_remote=False,
    stats=None,
):
    """Build the complete preview page. Never raises — failures become a page.

    `style` is a `stylesheets.PreviewStyle`; `None` means every default. An
    unknown theme identifier, or a theme whose stylesheet cannot be read,
    falls back to the default -- only a broken *default* reaches the
    "Installation incomplete" page below. A user stylesheet that failed to
    load produces a notice bar instead of an unstyled preview, and error
    pages get neither that CSS nor the notice: a stylesheet that failed is
    the last thing that should style the message saying so.

    `image_display` and `code_copy_buttons` describe the *content* rather
    than the appearance, which is why they are not fields of `PreviewStyle`.
    Both are also emitted as `window.xedownConfig`, so a loaded page can be
    told about a change without a reload.

    `text_direction` is the *document's* and lands on the article; `auto`
    detects it from the text. `ui_direction` is the *desktop's* and lands on
    `<html>`, so xedown's own chrome follows GTK rather than the document's
    language.

    `lang` is the *reader's* language, since xedown cannot detect a
    document's and a wrong guess would make a screen reader mispronounce the
    whole page. Anything but a non-empty string produces no attribute at all,
    rather than an empty one a screen reader treats as unrecognised.

    `fetch_remote` decides both what `render_fragment` does with a remote
    reference and whether the CSP names the private scheme, so a blocked
    document cannot load one even if a stray URL reached its DOM. `stats` is
    an out-parameter: this returns a page and never raises, so it is the only
    way a caller learns how many images were blocked.
    """
    token = nonce or secrets.token_urlsafe(16)
    style = style if style is not None else stylesheets.PreviewStyle()
    display = images.coerce_display(image_display)
    # Coerced like `display`: this is called directly by the render script
    # and the tests, not only through the settings store, so a bad argument
    # must still produce a page rather than raise past the try below.
    copy_buttons, _ = settings.by_name(settings.CODE_COPY_BUTTONS).coerce(
        code_copy_buttons
    )
    # Before the try, because both except branches need it. The document's
    # own direction is resolved inside, since it reads the text.
    ui = direction.coerce_ui(ui_direction)
    try:
        doc_direction = direction.resolve(text_direction, text)
        body = render_fragment(
            text,
            base_dir=base_dir,
            image_display=display,
            fetch_remote=fetch_remote,
            stats=stats,
        )
        stylesheet, theme_identifier = stylesheets.assemble(style, dark=dark)
        preview_js = vendoring.read_resource("preview.js")
        highlight_js = vendoring.read_vendor_file("highlight.min.js")
    except vendoring.VendorError as exc:
        # `render_fragment` may already have marked the stats rendered
        # before this failed, and the caller is getting an error page with no
        # images in it. Same in the branch below.
        _note_rendered(stats, False)
        return errors.error_page(
            "Installation incomplete",
            errors.missing_vendor_detail(exc),
            dark=dark,
            nonce=token,
            ui_direction=ui,
        )
    except Exception as exc:  # noqa: BLE001 - a blank pane is never acceptable
        _note_rendered(stats, False)
        return errors.error_page(
            "Cannot render this document",
            errors.render_failure_detail(exc),
            dark=dark,
            nonce=token,
            ui_direction=ui,
        )

    # Past both error-page routes: the body, the stylesheet and the vendored
    # resources are all in hand, so what this render did about the document's
    # images describes the page the caller is about to be given. Stated here
    # as well as in `render_fragment`, so this function's own promise does
    # not rest on a flag set inside a call it makes.
    _note_rendered(stats, True)

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
    # `isinstance` rather than a truth test: this runs outside the guarded
    # render above, and `render_document` promises never to raise. A bare
    # `if lang:` calls `__bool__` and `str(lang)` calls `__str__`, either of
    # which is arbitrary code on an object this function did not create.
    # Same reasoning as `settings.BoolSetting.coerce` and
    # `direction.coerce_ui`, which guard their template-bound values the
    # same way and for the same reason.
    if isinstance(lang, str) and lang.strip():
        lang_attribute = f' lang="{html.escape(lang.strip(), quote=True)}"'

    return _DOCUMENT.format(
        csp=_csp(token, fetch_remote),
        nonce=token,
        appearance="dark" if dark else "light",
        theme=theme_identifier,
        content_id=CONTENT_ELEMENT_ID,
        notice=notice,
        body=body,
        stylesheet=stylesheet,
        config=json.dumps({"codeCopy": copy_buttons, "imageFallback": display}),
        preview_js=preview_js,
        highlight_js=highlight_js,
        ui_direction=ui,
        doc_direction=doc_direction,
        lang=lang_attribute,
    )
