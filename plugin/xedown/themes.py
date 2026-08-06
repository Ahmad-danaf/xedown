"""The built-in preview themes. Pure logic — no GTK imports belong here.

A theme is a complete design, not a palette: each one owns its typography,
spacing and structure on top of an invariant base stylesheet. This module is
the single source of truth for which themes exist, and it is what brief 14's
preferences window iterates instead of hardcoding a second list — the same
role `SETTINGS` plays in `settings.py`.

The desktop's light/dark setting is a separate axis entirely and belongs to
`appearance.py`. Every theme works in both.
"""

import sys

from . import vendoring

DEFAULT_THEME = "repository"
BASE_STYLESHEET = "preview.css"
SHARED_SYNTAX_STYLESHEET = "syntax.css"


class Theme:
    """One built-in theme: its identity and the stylesheets it is made of."""

    def __init__(self, identifier, label, summary, syntax_light, syntax_dark):
        self.identifier = identifier
        self.label = label
        self.summary = summary
        self.stylesheet = f"themes/{identifier}.css"
        self.syntax_light = syntax_light
        self.syntax_dark = syntax_dark

    def syntax_stylesheet(self, dark):
        return self.syntax_dark if dark else self.syntax_light


THEMES = (
    Theme(
        "repository",
        "Repository",
        "Clean and familiar, for README files and technical documentation.",
        # The vendored highlight.js stylesheets, under their own licence and
        # attribution. This theme reproduces xedown 0.1.0 exactly, and
        # 0.1.0's code colours are these files -- transcribing them into a
        # hand-written xedown sheet would strip the attribution the licence
        # requires.
        "highlight-light.css",
        "highlight-dark.css",
    ),
)

_BY_IDENTIFIER = {theme.identifier: theme for theme in THEMES}


def resolve(identifier):
    """The theme `identifier` names, falling back to the default.

    Unknown, blank, mis-typed and non-string values all resolve to the
    default rather than raising. `settings.py` already guarantees a stored
    value is one of the registered names, so anything else arriving here is
    a caller's mistake — and the preview must never be unstyled over one.
    """
    if isinstance(identifier, str):
        theme = _BY_IDENTIFIER.get(identifier.strip().lower())
        if theme is not None:
            return theme
    return _BY_IDENTIFIER[DEFAULT_THEME]


def assemble_css(identifier, dark=False):
    """`(css, effective_identifier)` for one theme, in emission order.

    Syntax sheet, then base, then theme. Syntax comes first because
    `preview.css`'s `pre code.hljs` override beats the highlight stylesheet
    by source order rather than by specificity — see the comment above that
    rule.

    Raises `VendorError` only when the *default* theme cannot be read, which
    means the installation itself is incomplete; `render_document` turns that
    into a readable page.
    """
    theme = resolve(identifier)
    try:
        return _read(theme, dark), theme.identifier
    except vendoring.VendorError as exc:
        if theme.identifier == DEFAULT_THEME:
            raise
        sys.stderr.write(
            f"xedown: the {theme.identifier} theme could not be read ({exc}); "
            f"using {DEFAULT_THEME} instead\n"
        )
        default = _BY_IDENTIFIER[DEFAULT_THEME]
        return _read(default, dark), default.identifier


def _read(theme, dark):
    return "\n".join(
        (
            vendoring.read_resource(theme.syntax_stylesheet(dark)),
            vendoring.read_resource(BASE_STYLESHEET),
            vendoring.read_resource(theme.stylesheet),
        )
    )
