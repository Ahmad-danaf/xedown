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
    escaped_title = html.escape(str(title))
    escaped_detail = html.escape(str(detail))
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


def remote_image_text(uri):
    """Placeholder text for an image xedown does not fetch.

    Not "blocked": that invites "how do I unblock it?", and nothing can.
    This is a statement about what xedown does, which is nothing.
    """
    return f"Remote image, not fetched: {uri}"


def local_image_missing_text(path):
    """Placeholder text for a reference that resolved to nothing on disk."""
    return f"Image not found: {path}"


def local_image_unreadable_text(path, detail=""):
    """Placeholder text for a file that is there and cannot be opened."""
    if detail:
        return f"Image could not be read: {path} ({detail})"
    return f"Image could not be read: {path}"


def local_image_unresolved_text(uri):
    """Placeholder text for a local image reference that could not be
    resolved to a file, in the spirit of UNSAVED_DOCUMENT_HINT: this is
    normally an unsaved document, so a relative path has nothing to resolve
    against.
    """
    return f"Image not found: {uri}. {UNSAVED_DOCUMENT_HINT}"


def with_alt(text, alt):
    """`text`, followed by the author's alt text when there is any.

    Appended rather than substituted: a reader needs both what the image was
    meant to say and why it is not there.
    """
    words = (alt or "").strip()
    # Use Unicode code points for curly quotes: U+201C (left) and U+201D (right)
    if words:
        return f"{text} — {chr(0x201c)}{words}{chr(0x201d)}"
    return text


# The ways a user's own stylesheet can fail to be usable. Named here, beside
# every other piece of user-facing failure text, so `stylesheets.py` stays
# free of copy and this module stays a leaf that imports nothing of ours.
STYLESHEET_NOT_FOUND = "not-found"
STYLESHEET_NOT_A_FILE = "not-a-file"
STYLESHEET_UNREADABLE = "unreadable"
STYLESHEET_NOT_UTF8 = "not-utf8"
STYLESHEET_EMPTY = "empty"
STYLESHEET_TOO_LARGE = "too-large"
STYLESHEET_UNSAFE = "unsafe"

_STYLESHEET_PHRASES = {
    STYLESHEET_NOT_FOUND: "was not found",
    STYLESHEET_NOT_A_FILE: "is not a file",
    STYLESHEET_UNREADABLE: "could not be read",
    STYLESHEET_NOT_UTF8: "is not valid UTF-8 text",
    STYLESHEET_EMPTY: "is empty",
    STYLESHEET_TOO_LARGE: "is larger than the 512 KiB limit",
    STYLESHEET_UNSAFE: 'contains "</style", which cannot be embedded safely',
}


def stylesheet_problem_phrase(problem, detail=""):
    """Why a custom stylesheet could not be used, as a sentence fragment.

    Reads after the file's path: "<path> is empty." The fallback exists so a
    problem this version does not know still produces a sentence rather than
    a blank one.
    """
    phrase = _STYLESHEET_PHRASES.get(problem, "could not be used")
    return f"{phrase} ({detail})" if detail else phrase


def user_stylesheet_notice(problem, path, detail="", theme_label=""):
    """The in-page bar shown when a custom stylesheet could not be used.

    A sibling of the document article rather than a child: `update_body`
    replaces the article's contents with a fragment that knows nothing about
    this, so a notice inside it would vanish on the first keystroke.

    Both the path and the theme label are escaped. The path comes out of a
    file the user hand-edits, which makes it data rather than markup. So can
    the phrase itself: STYLESHEET_UNSAFE's own wording contains a literal
    "</style", which an unescaped interpolation would hand the HTML
    tokenizer as an end-tag-open, consuming everything up to this notice's
    own closing </div>.
    """
    sentence = (
        f"{html.escape(str(path))} "
        f"{html.escape(stylesheet_problem_phrase(problem, detail))}."
    )
    trailer = (
        f" Showing the {html.escape(str(theme_label))} theme." if theme_label else ""
    )
    return (
        '<div class="xedown-notice">'
        "<strong>Custom stylesheet not applied</strong> "
        f"{sentence}{trailer}"
        "</div>"
    )
