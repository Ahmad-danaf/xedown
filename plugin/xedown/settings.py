"""Persistent user settings. Pure logic — no GTK imports belong in this module.

The store is a JSON object in a file the user is allowed to hand-edit, so every
value is validated on the way in: a value that is missing, misspelled, of the
wrong type or out of range falls back to its default, or is clamped into range,
rather than failing the load. That file belongs to the user, and a broken one
must never stop the plugin from working.
"""

import json
import math
import os
import pathlib
import sys

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
        # Guarded to floats on purpose: JSON integers are unbounded, and
        # `math.isnan`/`isinf` raise OverflowError on an int too large to
        # convert to a C double -- which would turn a hand-edited setting
        # into a crash. An int can never be NaN or infinite anyway.
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
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


class Settings:
    """The user's settings: loaded once, written through on change.

    Everything here runs on the GTK main thread, so there is no locking.
    """

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.write_error = None
        self._values = defaults()
        # The names this instance has itself set. See `_write`.
        self._dirty = set()
        self._listeners = {}  # token -> callback
        self._next_token = 0
        self._load()

    # --- loading -----------------------------------------------------------

    def get(self, name):
        """The current value of `name`. An unknown name is a programming error."""
        by_name(name)
        return self._values[name]

    def _load(self):
        # Both handlers below name `Exception` rather than an enumerated list
        # of types, and each wraps exactly one stdlib call so it cannot hide
        # anything else. Enumerating is what went wrong twice here already:
        # `read_text` raises UnicodeDecodeError (a ValueError, not an OSError)
        # on invalid UTF-8, and `json.loads` raises RecursionError (a
        # RuntimeError, not a ValueError) on deeply nested input. Each escaped
        # its handler and stopped the plugin from loading at all -- and since
        # the escape happened before the quarantine, the same file broke every
        # subsequent launch too. The guarantee this module owes is absolute,
        # so it must not depend on having named every exception correctly.
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001 - see above
            self._quarantine(f"could not be read ({exc})")
            return

        if not text.strip():
            # A blank file is what a truncated write leaves behind. There is
            # nothing in it worth preserving, so it means "no settings yet"
            # rather than corruption, and produces no quarantine noise.
            return

        try:
            stored = json.loads(text)
        except Exception as exc:  # noqa: BLE001 - see above
            self._quarantine(f"could not be parsed ({exc})")
            return

        if not isinstance(stored, dict):
            self._quarantine("does not contain a JSON object")
            return

        for name, value in stored.items():
            setting = _BY_NAME.get(name)
            if setting is not None:
                # A misspelled key is simply not one of ours, and is left
                # alone rather than treated as a failure.
                self._values[name], _ = setting.coerce(value)

    def _quarantine(self, reason):
        """Move a store we cannot use aside, keeping the user's copy.

        The name is fixed rather than timestamped, so a second corruption
        overwrites the first preserved copy. That keeps the config directory
        from growing without bound and gives the preferences window a path it
        can always quote. Failing to move it is survivable — the defaults are
        already in memory either way.
        """
        target = self.path.with_name(self.path.name + ".corrupt")
        try:
            os.replace(self.path, target)
        except OSError as exc:
            sys.stderr.write(
                f"xedown: {self.path} {reason}; using defaults "
                f"(it could not be moved aside: {exc})\n"
            )
            return
        sys.stderr.write(
            f"xedown: {self.path} {reason}; using defaults. "
            f"Your copy was kept at {target}\n"
        )

    # --- writing -----------------------------------------------------------

    def set(self, name, value):
        """Store `value` under `name`. True when it changed anything."""
        return bool(self.set_many({name: value}))

    def set_many(self, values):
        """Apply several settings at once. Returns the names that moved.

        Everything is validated before anything is applied, so a bad value
        cannot leave a half-applied change behind.
        """
        coerced = {}
        for name, value in values.items():
            new_value, ok = by_name(name).coerce(value)
            if not ok:
                raise ValueError(f"{value!r} is not a usable value for {name!r}")
            coerced[name] = new_value

        changed = frozenset(
            name for name, value in coerced.items() if value != self._values[name]
        )
        if not changed:
            return changed

        self._values.update(coerced)
        self._dirty.update(changed)
        self._write()
        self._notify(changed)
        return changed

    def reset(self):
        """Restore every default. Keys this version does not know are left alone."""
        return self.set_many(defaults())

    def _write(self):
        """Merge this instance's own changes over whatever is on disk.

        Only the keys this instance has actually set are written. Writing the
        whole in-memory dict would look equivalent and is not: an untouched
        key's in-memory value is only ever its default, so a second xed
        process saving one setting would silently reset every other setting
        the first process had changed. Re-reading also preserves keys this
        version does not know.

        A failure here is never fatal. The new value stays live for the
        session, `write_error` records why it did not persist, and the
        preferences window can tell the user rather than leaving a mystery.
        """
        merged = self._stored_on_disk()
        merged.update({name: self._values[name] for name in self._dirty})
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(
                json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            # Atomic within one filesystem, so a crash mid-write cannot
            # leave a half-written store behind.
            os.replace(temp, self.path)
        except OSError as exc:
            self.write_error = str(exc)
            sys.stderr.write(f"xedown: cannot save settings to {self.path}: {exc}\n")
            try:
                temp.unlink()
            except OSError:
                pass
            return
        self.write_error = None

    def _stored_on_disk(self):
        """The file's current contents, or `{}` when it cannot be used.

        A store that could not be parsed was already quarantined at load
        time, and another process may have replaced the file with anything at
        all since. A write must not become the thing that fails because of
        it, so this reads untrusted content behind a broad handler for the
        same reason `_load` does.
        """
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - untrusted content, as in _load
            return {}
        return stored if isinstance(stored, dict) else {}

    # --- notification ------------------------------------------------------

    def connect(self, callback):
        """Call `callback(changed)` whenever values change. Returns a token.

        Mirrors `ThemeWatcher`'s shape deliberately, so the two long-lived
        subscriptions a controller holds are managed the same way. The token
        must be handed back to `disconnect`: this store outlives every
        controller, and a missed disconnect keeps a torn-down one — and the
        WebView, document and tab it references — alive for the life of the
        process.
        """
        self._next_token += 1
        self._listeners[self._next_token] = callback
        return self._next_token

    def disconnect(self, token):
        """Stop delivering to the listener `token` identifies. Idempotent."""
        self._listeners.pop(token, None)

    def _notify(self, changed):
        # Iterate a snapshot, because a listener may disconnect itself or
        # another listener from inside its own callback -- but re-check
        # membership before each call, so one disconnected earlier in this
        # same broadcast is not called after the fact.
        for token, callback in list(self._listeners.items()):
            if token not in self._listeners:
                continue
            try:
                callback(changed)
            except Exception as exc:  # noqa: BLE001 - one must not stop the rest
                sys.stderr.write(f"xedown: a settings listener failed: {exc}\n")
