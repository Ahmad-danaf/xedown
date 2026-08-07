"""Assembles the stylesheet a preview receives. Pure — no GTK imports here.

Emission order is this module's whole reason to exist, and it lives in one
place because two of the layers only work because of where they sit: the base
sheet's `pre code.hljs` override beats the vendored highlight sheet by source
order rather than by specificity, and the user's own stylesheet comes last
precisely so it can override everything above it.

`themes.py` is the registry of which built-in designs exist. This module is
what the page actually gets.
"""

import sys

from . import themes, vendoring

BASE_STYLESHEET = "preview.css"


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
    theme = themes.resolve(identifier)
    try:
        return _read(theme, dark), theme.identifier
    except vendoring.VendorError as exc:
        if theme.identifier == themes.DEFAULT_THEME:
            raise
        sys.stderr.write(
            f"xedown: the {theme.identifier} theme could not be read ({exc}); "
            f"using {themes.DEFAULT_THEME} instead\n"
        )
        default = themes.resolve(themes.DEFAULT_THEME)
        return _read(default, dark), default.identifier


def _read(theme, dark):
    return "\n".join(
        (
            vendoring.read_resource(theme.syntax_stylesheet(dark)),
            vendoring.read_resource(BASE_STYLESHEET),
            vendoring.read_resource(theme.stylesheet),
        )
    )
