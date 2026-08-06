"""Persistent user settings. Pure logic — no GTK imports belong in this module.

The store is a JSON object in a file the user is allowed to hand-edit, so every
value is validated on the way in: a value that is missing, misspelled, of the
wrong type or out of range falls back to its default, or is clamped into range,
rather than failing the load. That file belongs to the user, and a broken one
must never stop the plugin from working.
"""

import math

DEFAULT_MODE = "default_mode"
REMEMBER_MODE_PER_FILE = "remember_mode_per_file"
PREVIEW_THEME = "preview_theme"
CUSTOM_STYLESHEET = "custom_stylesheet"
CONTENT_WIDTH_REM = "content_width_rem"
TEXT_SIZE_PX = "text_size_px"
AUTO_REFRESH = "auto_refresh"
REFRESH_DELAY_MS = "refresh_delay_ms"
REMOTE_IMAGES = "remote_images"
CODE_COPY_BUTTONS = "code_copy_buttons"
TEXT_DIRECTION = "text_direction"
WATCH_EXTERNAL_CHANGES = "watch_external_changes"


class _Setting:
    """One named choice: its default, and how to make sense of a stored value."""

    def __init__(self, name, default):
        self.name = name
        self.default = default

    def coerce(self, value):
        """Return `(usable_value, ok)`. On `ok=False` the value is the default."""
        raise NotImplementedError


class ChoiceSetting(_Setting):
    """One of a fixed set of lowercase names."""

    def __init__(self, name, choices, default):
        super().__init__(name, default)
        self.choices = tuple(choices)

    def coerce(self, value):
        if not isinstance(value, str):
            return self.default, False
        # Forgiving about case and surrounding space, so a hand-typed
        # "GitHub" is honoured rather than silently reverting to a default
        # the user cannot tell apart from their own choice.
        normalized = value.strip().lower()
        if normalized in self.choices:
            return normalized, True
        return self.default, False


class BoolSetting(_Setting):
    """A real JSON boolean, and nothing else."""

    def coerce(self, value):
        # "true", "on" and 1 are mistakes, not synonyms: JSON has a boolean
        # type, so accepting substitutes would hide a typo instead of
        # surfacing it as a value the user can see reverting.
        if isinstance(value, bool):
            return value, True
        return self.default, False


class NumberSetting(_Setting):
    """A number, clamped into range rather than rejected for being outside it."""

    def __init__(self, name, default, minimum, maximum, integer=False):
        super().__init__(name, default)
        self.minimum = minimum
        self.maximum = maximum
        self.integer = integer

    def coerce(self, value):
        # `isinstance(True, int)` is true in Python, so without the explicit
        # bool check a stored `true` would become the number 1 and then be
        # clamped to the minimum -- a wrong value that looks deliberate.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self.default, False
        # json.loads accepts the literals NaN, Infinity and -Infinity by
        # default. None of the three can be clamped into a usable range.
        if math.isnan(value) or math.isinf(value):
            return self.default, False
        clamped = min(max(value, self.minimum), self.maximum)
        # `round` with one argument already returns an int. Do not wrap it in
        # `int(...)`: ruff's RUF046 is on by default and rejects that.
        return (round(clamped) if self.integer else float(clamped)), True


class PathSetting(_Setting):
    """A file path as the user wrote it, or nothing at all."""

    def __init__(self, name):
        super().__init__(name, None)

    def coerce(self, value):
        if value is None:
            return None, True
        if not isinstance(value, str):
            return None, False
        # Deliberately not resolved, and `~` deliberately not expanded:
        # brief 3 owns turning this into a file, and storing a resolved value
        # would make the setting misreport what the user actually chose.
        return (value.strip() or None), True


SETTINGS = (
    ChoiceSetting(DEFAULT_MODE, ("preview", "markdown"), "preview"),
    BoolSetting(REMEMBER_MODE_PER_FILE, True),
    ChoiceSetting(
        PREVIEW_THEME,
        ("cursor", "github", "minimal", "document"),
        "github",
    ),
    PathSetting(CUSTOM_STYLESHEET),
    NumberSetting(CONTENT_WIDTH_REM, 46.0, 30.0, 100.0),
    NumberSetting(TEXT_SIZE_PX, 16.0, 11.0, 28.0),
    BoolSetting(AUTO_REFRESH, True),
    NumberSetting(REFRESH_DELAY_MS, 250, 50, 2000, integer=True),
    ChoiceSetting(REMOTE_IMAGES, ("placeholder", "alt", "hidden"), "placeholder"),
    BoolSetting(CODE_COPY_BUTTONS, True),
    ChoiceSetting(TEXT_DIRECTION, ("auto", "ltr", "rtl"), "auto"),
    BoolSetting(WATCH_EXTERNAL_CHANGES, True),
)

_BY_NAME = {setting.name: setting for setting in SETTINGS}


def by_name(name):
    """The descriptor for `name`. An unknown name is a programming error."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"no such setting: {name!r}") from None


def defaults():
    """A fresh dict of every setting's default value."""
    return {setting.name: setting.default for setting in SETTINGS}
