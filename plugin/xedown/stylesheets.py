"""Assembles the stylesheet a preview receives. Pure — no GTK imports here.

Emission order is this module's whole reason to exist, and it lives in one
place because two of the layers only work because of where they sit: the base
sheet's `pre code.hljs` override beats the vendored highlight sheet by source
order rather than by specificity, and the user's own stylesheet comes last
precisely so it can override everything above it.

`themes.py` is the registry of which built-in designs exist. This module is
what the page actually gets.
"""

import os
import pathlib
import stat
import sys

from . import errors, settings, themes, vendoring

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


# Larger than a full uncompiled Bootstrap, so every realistic stylesheet fits
# and only a mis-selected file is refused. It is also a page-weight guard:
# whatever is here is inlined into every full page load.
MAX_STYLESHEET_BYTES = 512 * 1024


class UserStylesheet:
    """The user's own stylesheet, or the reason there isn't one.

    `problem` is `None` both when a stylesheet loaded and when the setting is
    unset — `path` is what tells those apart. Nothing here raises; a
    stylesheet that cannot be used must leave the preview working on its
    built-in theme.
    """

    def __init__(self, css="", path=None, problem=None, detail=""):
        self.css = css
        self.path = path
        self.problem = problem
        self.detail = detail


def load_user_stylesheet(value, config_dir=None):
    """Read `value` as a stylesheet path. Never raises."""
    if not value or not str(value).strip():
        return UserStylesheet()

    path = _resolve(str(value).strip(), config_dir)
    display = str(path)

    try:
        info = os.stat(path)
    except FileNotFoundError:
        return UserStylesheet(path=display, problem=errors.STYLESHEET_NOT_FOUND)
    except OSError as exc:
        return UserStylesheet(
            path=display,
            problem=errors.STYLESHEET_UNREADABLE,
            detail=exc.strerror or str(exc),
        )

    # Checked before opening, and not with a size check. A FIFO blocks read()
    # until something writes to the other end -- which hangs the GTK main
    # thread, not merely the preview -- and /dev/zero reports st_size == 0 and
    # then reads without end. Both lie about their size; neither is a regular
    # file. This also disposes of directories and sockets.
    if not stat.S_ISREG(info.st_mode):
        return UserStylesheet(path=display, problem=errors.STYLESHEET_NOT_A_FILE)

    try:
        with open(path, "rb") as handle:
            # One byte past the cap, so oversize is decided by what was
            # actually read. Trusting the st_size above races a file being
            # appended to between the stat and the open.
            raw = handle.read(MAX_STYLESHEET_BYTES + 1)
    except OSError as exc:
        return UserStylesheet(
            path=display,
            problem=errors.STYLESHEET_UNREADABLE,
            detail=exc.strerror or str(exc),
        )

    if len(raw) > MAX_STYLESHEET_BYTES:
        return UserStylesheet(path=display, problem=errors.STYLESHEET_TOO_LARGE)

    # Decoding is its own guarded step because it fails differently: a
    # UnicodeDecodeError is a ValueError, not an OSError, and would escape the
    # handler above entirely. That exact escape broke settings.py twice; see
    # the comment in its `_load`.
    try:
        # utf-8-sig, not utf-8: a leading byte-order mark decodes as U+FEFF,
        # which is not whitespace to the CSS tokenizer and would sit in the
        # assembled sheet right after the theme layer, invalidating the
        # user's first rule with no message at all (xedown deliberately does
        # not validate CSS). utf-8-sig strips a leading BOM if present and is
        # otherwise identical to utf-8 -- this is about that silent papercut,
        # not about encoding detection.
        css = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return UserStylesheet(path=display, problem=errors.STYLESHEET_NOT_UTF8)

    if not css.strip():
        return UserStylesheet(path=display, problem=errors.STYLESHEET_EMPTY)

    # This CSS is interpolated raw between <style> and </style>, so the one
    # sequence that can escape the element is refused outright. Rewriting it
    # was considered: no single substitution is correct inside a comment,
    # inside a string and in ordinary CSS at once, and refusing is provably
    # safe where rewriting is only probably safe. Case-insensitive, because
    # the HTML tokenizer is.
    if "</style" in css.lower():
        return UserStylesheet(path=display, problem=errors.STYLESHEET_UNSAFE)

    return UserStylesheet(css=css, path=display)


def _resolve(value, config_dir):
    """The path `value` names, expanded but never guessed at.

    `~` is expanded because `settings.PathSetting` deliberately does not, and
    said so. Environment variables are *not*: `$HOME/x.css` is a path
    containing a dollar sign, and expanding it would make one stored setting
    mean different things depending on how xed was launched. A relative path
    resolves against the directory holding `settings.json` — "next to my
    settings" — rather than against a working directory that, for an
    application launched from a menu, is arbitrary and unstateable in the
    documentation.
    """
    path = pathlib.Path(os.path.expanduser(value))
    if path.is_absolute():
        return path
    base = pathlib.Path(config_dir) if config_dir else settings.default_config_dir()
    return base / path


class PreviewStyle:
    """Everything the settings say about how one preview should look.

    A plain mutable holder, not a frozen value: the controller replaces or
    updates fields as settings change, and rebuilds through `from_settings`
    when it wants the numbers re-coerced.
    """

    def __init__(
        self, theme=None, content_width_rem=None, text_size_px=None, user=None
    ):
        self.theme = theme
        self.content_width_rem = _in_range(
            settings.CONTENT_WIDTH_REM, content_width_rem
        )
        self.text_size_px = _in_range(settings.TEXT_SIZE_PX, text_size_px)
        self.user = user if user is not None else UserStylesheet()

    @classmethod
    def from_settings(cls, store, user=None):
        """Read all three appearance settings out of `store`."""
        return cls(
            theme=store.get(settings.PREVIEW_THEME),
            content_width_rem=store.get(settings.CONTENT_WIDTH_REM),
            text_size_px=store.get(settings.TEXT_SIZE_PX),
            user=user,
        )


def _in_range(name, value):
    """`value` clamped into `name`'s range, or that setting's default.

    The settings store already clamps, but `render_document` is also called
    directly by the two scripts and by the tests. `themes.resolve` set the
    precedent: a bad argument produces a sane page, not a broken one.
    """
    setting = settings.by_name(name)
    if value is None:
        return setting.default
    coerced, _ = setting.coerce(value)
    return coerced


def _number(value):
    """`46.0` as `46`, so the emitted CSS reads like something a person wrote."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def metrics_css(style):
    """The user's width and text size, as the two inputs the base sheet reads.

    Declared on `:root` because `rem` resolves against the root element:
    sizing text anywhere else while sizing the measure in `rem` lets the two
    drift apart. Each theme's own `--xedown-measure-scale` and
    `--xedown-text-scale` multiply these, so a theme stays proportionally
    itself at any width or size the user picks.
    """
    return (
        ":root {\n"
        f"  --xedown-content-width: {_number(style.content_width_rem)}rem;\n"
        f"  --xedown-text-size: {_number(style.text_size_px)}px;\n"
        "}"
    )


def assemble(style=None, dark=False):
    """`(css, effective_identifier)` — the complete stylesheet a page receives.

    Five layers: syntax, base, theme, metrics, user. Metrics sit after the
    theme so the user's explicit width and size beat anything a theme
    declares; the user's own stylesheet is last so it can override every one
    of them.
    """
    style = style if style is not None else PreviewStyle()
    theme_css, effective = assemble_css(style.theme, dark=dark)
    layers = [theme_css, metrics_css(style)]
    if style.user.css:
        layers.append(style.user.css)
    return "\n".join(layers), effective
