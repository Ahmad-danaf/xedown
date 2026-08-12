"""What the settings window contains. Pure logic — no GTK imports belong here.

`settings.py` owns which settings exist, their defaults and their validation.
`themes.py` owns which themes exist. This module owns only their
*presentation*: which group a setting sits in, what kind of control shows it,
what order its choices appear in, and what the explanation under it says.

Nothing here restates a bound or a choice list another module already knows —
`bounds()` reads the `NumberSetting`, and the theme row is built from
`themes.THEMES` — so a control cannot drift out of agreement with the
validator behind it.

Labels are not here either. They come from `a11y.NAMES`, because the label a
user reads, the name a screen reader speaks and the string the live audit
asserts against have to be one string rather than three copies of it.
"""

from . import a11y, settings, themes

SWITCH = "switch"
CHOICE = "choice"
NUMBER = "number"
PATH = "path"


class Row:
    """One setting, as the window shows it."""

    def __init__(
        self,
        setting,
        kind,
        key,
        help_text=None,
        choices=(),
        unit=None,
        step=1,
        page_step=10,
        enabled_by=None,
    ):
        self.setting = setting
        self.kind = kind
        self.key = key
        self.help_text = help_text
        self.choices = tuple(choices)
        self.unit = unit
        self.step = step
        self.page_step = page_step
        # The boolean setting whose truth makes this row sensitive, or None.
        self.enabled_by = enabled_by

    @property
    def label(self):
        """The visible label, which is also the accessible name."""
        return a11y.NAMES[self.key]


class Group:
    """A heading and the rows under it."""

    def __init__(self, title, rows):
        self.title = title
        self.rows = tuple(rows)


_THEME_CHOICES = tuple((theme.identifier, theme.label) for theme in themes.THEMES)

# Wording is carried over from docs/settings.md rather than newly invented,
# so the window and the documentation cannot drift into saying different
# things about the same setting.
GROUPS = (
    Group(
        "How files open",
        (
            Row(
                settings.DEFAULT_MODE,
                CHOICE,
                "prefs_default_mode",
                help_text=(
                    "Only affects files you open from now on. A tab already "
                    "open is never switched."
                ),
                choices=(("preview", "Preview"), ("markdown", "Markdown source")),
            ),
            Row(
                settings.REMEMBER_MODE_PER_FILE,
                SWITCH,
                "prefs_remember_mode",
                help_text=(
                    "Overrides the choice above for files you have opened "
                    "before. Switching it on records the mode of every tab "
                    "already open."
                ),
            ),
        ),
    ),
    Group(
        "How the preview looks",
        (
            # No static help: the theme's own summary is shown instead, and
            # follows the selection. See `choice_help`.
            Row(settings.PREVIEW_THEME, CHOICE, "prefs_theme", choices=_THEME_CHOICES),
            Row(
                settings.CUSTOM_STYLESHEET,
                PATH,
                "prefs_stylesheet",
                help_text=(
                    "Applied on top of the theme. Saving an edit to that file "
                    "updates every open preview straight away."
                ),
            ),
            Row(
                settings.CONTENT_WIDTH_REM,
                NUMBER,
                "prefs_content_width",
                unit="rem",
                step=1,
                page_step=10,
            ),
            Row(
                settings.TEXT_SIZE_PX,
                NUMBER,
                "prefs_text_size",
                help_text=(
                    "Base values. Every theme multiplies them by its own "
                    "scale, so the rendered result may differ."
                ),
                unit="px",
                step=1,
                page_step=4,
            ),
            Row(
                settings.TEXT_DIRECTION,
                CHOICE,
                "prefs_text_direction",
                help_text=(
                    "Sets the document's layout — bullets, quote bars, table "
                    "column order. Each paragraph still reads in its own "
                    "direction."
                ),
                choices=(
                    ("auto", "Automatic"),
                    ("ltr", "Left to right"),
                    ("rtl", "Right to left"),
                ),
            ),
            Row(settings.CODE_COPY_BUTTONS, SWITCH, "prefs_copy_buttons"),
        ),
    ),
    Group(
        "How it refreshes",
        (
            Row(
                settings.AUTO_REFRESH,
                SWITCH,
                "prefs_auto_refresh",
                help_text=(
                    "Covers changes arriving while the preview is showing. "
                    "Switching to Preview always renders, whatever this says. "
                    "Off adds a Refresh button to the mode bar."
                ),
            ),
            Row(
                settings.REFRESH_DELAY_MS,
                NUMBER,
                "prefs_refresh_delay",
                unit="ms",
                step=50,
                page_step=250,
                enabled_by=settings.AUTO_REFRESH,
            ),
        ),
    ),
    Group(
        "Images and changes made outside xed",
        (
            Row(
                settings.REMOTE_IMAGES,
                CHOICE,
                "prefs_remote_images",
                help_text=(
                    "xedown never fetches an image from the network. This "
                    "only decides what appears in its place."
                ),
                choices=(
                    ("placeholder", "Show a placeholder"),
                    ("alt", "Show the alt text only"),
                    ("hidden", "Show nothing"),
                ),
            ),
            Row(
                settings.WATCH_EXTERNAL_CHANGES,
                SWITCH,
                "prefs_watch_external",
                help_text=(
                    "With unsaved edits xedown shows a bar instead, and never "
                    "replaces your text."
                ),
            ),
        ),
    ),
)

# Controls the window has that are not rows: the stylesheet chooser's button,
# the restore button, and our own window's close. Declared so the unit test
# can insist that every `prefs_` name in `a11y.NAMES` is actually used.
EXTRA_KEYS = (
    "prefs_stylesheet_browse",
    "prefs_restore_defaults",
    "prefs_close",
)


def rows():
    """Every row, in the order the window shows them."""
    return tuple(row for group in GROUPS for row in group.rows)


def bounds(row):
    """`(minimum, maximum, integer)` for a number row, from the validator."""
    setting = settings.by_name(row.setting)
    return setting.minimum, setting.maximum, setting.integer


def choice_help(setting_name, value):
    """Help that depends on which value is selected, or None.

    Only the theme row has any: each theme carries its own one-line summary in
    `themes.py`, and showing the selected one is better than a static sentence
    that has to describe four designs at once.
    """
    if setting_name == settings.PREVIEW_THEME:
        return themes.resolve(value).summary
    return None
