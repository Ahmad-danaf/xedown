"""User-facing failure text. Every failure is specific, never a blank pane."""

import html

UNSAVED_DOCUMENT_HINT = (
    "This document has not been saved yet, so relative links and images cannot "
    "be resolved. Save the file to give them a location to resolve against."
)

_ERROR_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; \
style-src 'nonce-{nonce}'; base-uri 'none'; form-action 'none'">
<title>{title}</title>
<style nonce="{nonce}">
body {{ margin: 0; padding: 3rem 2rem; font-family: system-ui, sans-serif;
        background: {background}; color: {foreground}; }}
.box {{ max-width: 40rem; margin: 0 auto; border-left: 3px solid {accent};
        padding: 1rem 1.25rem; background: {panel}; border-radius: 4px; }}
h1 {{ font-size: 1.1rem; margin: 0 0 .5rem; }}
p {{ margin: 0; line-height: 1.6; white-space: pre-wrap; }}
</style>
</head>
<body class="{theme}">
<div class="box"><h1>{title}</h1><p>{detail}</p></div>
</body>
</html>
"""


def error_page(title, detail, dark=False, nonce="xedown-error"):
    """A complete, self-contained HTML page describing a failure."""
    palette = (
        {
            "background": "#1e1e1e",
            "foreground": "#e6e6e6",
            "panel": "#2a2a2a",
            "accent": "#e5786d",
        }
        if dark
        else {
            "background": "#ffffff",
            "foreground": "#1f2328",
            "panel": "#f6f8fa",
            "accent": "#cf222e",
        }
    )
    # Escape HTML and also replace = to prevent "attr=value" patterns from appearing literally
    escaped_title = html.escape(str(title)).replace("=", "&#61;")
    escaped_detail = html.escape(str(detail)).replace("=", "&#61;")
    return _ERROR_PAGE.format(
        title=escaped_title,
        detail=escaped_detail,
        theme="dark" if dark else "light",
        nonce=nonce,
        **palette,
    )


def render_failure_detail(exc):
    return f"The Markdown could not be rendered.\n\n{type(exc).__name__}: {exc}"


def missing_vendor_detail(exc):
    return (
        f"A bundled component is missing, so this installation is incomplete.\n\n{exc}\n\n"
        "Reinstall the plugin from a release archive."
    )


def remote_image_blocked_text(uri):
    """Placeholder text shown in place of an image the plugin refuses to fetch."""
    return f"Remote image blocked: {uri}"
