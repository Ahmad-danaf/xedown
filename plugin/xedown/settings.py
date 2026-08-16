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

CONFIG_DIR_ENV = "XEDOWN_CONFIG_DIR"
STORE_NAME = "settings.json"

DEFAULT_MODE = "default_mode"
REMEMBER_MODE_PER_FILE = "remember_mode_per_file"
PREVIEW_THEME = "preview_theme"
CUSTOM_STYLESHEET = "custom_stylesheet"
CONTENT_WIDTH_REM = "content_width_rem"
TEXT_SIZE_PX = "text_size_px"
AUTO_REFRESH = "auto_refresh"
REFRESH_DELAY_MS = "refresh_delay_ms"
REMOTE_IMAGES = "remote_images"
IMAGE_FALLBACK = "image_fallback"
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
        # Forgiving about case and space, so a hand-typed "Repository" is
        # honoured rather than silently reverting to a default.
        normalized = value.strip().lower()
        if normalized in self.choices:
            return normalized, True
        return self.default, False


class BoolSetting(_Setting):
    """A real JSON boolean, and nothing else."""

    def coerce(self, value):
        # "true", "on" and 1 are mistakes, not synonyms: JSON has a boolean
        # type, so accepting substitutes would hide a typo.
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
        # `isinstance(True, int)` is true, so without this a stored `true`
        # becomes 1 and clamps to the minimum -- a wrong value looking
        # deliberate.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self.default, False
        # json.loads accepts NaN, Infinity and -Infinity, none of which can
        # be clamped into a range. Guarded to floats because JSON integers
        # are unbounded and `math.isnan` raises OverflowError on an int too
        # large for a C double -- an int is never NaN or infinite anyway.
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return self.default, False
        clamped = min(max(value, self.minimum), self.maximum)
        # One-argument `round` already returns an int; wrapping it in
        # `int(...)` is what ruff's RUF046 rejects.
        return (round(clamped) if self.integer else float(clamped)), True


class PathSetting(_Setting):
    """A file path as the user wrote it, or nothing at all."""

    def __init__(self, name):
        super().__init__(name, None)

    def coerce(self, value):
        if value is None:
            return None, True
        if not isinstance(value, str):
            return self.default, False
        # Deliberately unresolved, `~` deliberately unexpanded: storing a
        # resolved value would misreport what the user chose.
        return (value.strip() or None), True


SETTINGS = (
    ChoiceSetting(DEFAULT_MODE, ("preview", "markdown"), "preview"),
    BoolSetting(REMEMBER_MODE_PER_FILE, True),
    ChoiceSetting(
        PREVIEW_THEME,
        ("focused", "repository", "minimal", "document"),
        "repository",
    ),
    PathSetting(CUSTOM_STYLESHEET),
    NumberSetting(CONTENT_WIDTH_REM, 46.0, 30.0, 100.0),
    NumberSetting(TEXT_SIZE_PX, 16.0, 11.0, 28.0),
    BoolSetting(AUTO_REFRESH, True),
    NumberSetting(REFRESH_DELAY_MS, 250, 50, 2000, integer=True),
    ChoiceSetting(REMOTE_IMAGES, ("never", "https"), "never"),
    ChoiceSetting(IMAGE_FALLBACK, ("placeholder", "alt", "hidden"), "placeholder"),
    BoolSetting(CODE_COPY_BUTTONS, True),
    ChoiceSetting(TEXT_DIRECTION, ("auto", "ltr", "rtl"), "auto"),
    BoolSetting(WATCH_EXTERNAL_CHANGES, True),
)

# The values `remote_images` held before it became a fetch policy. Disjoint
# from ("never", "https"), so a stored "alt" can only be the old meaning --
# which makes the migration unambiguous and self-terminating, with no version
# stamp needed in the file.
_LEGACY_REMOTE_IMAGES = frozenset({"placeholder", "alt", "hidden"})


def _migrate_legacy_remote_images(stored):
    """`stored` with a pre-1.0 `remote_images` re-read as `image_fallback`.

    In memory only. The file is not rewritten: it belongs to the user, a
    second xed process may be reading it, and nothing here is worth a write
    the user did not ask for. Running again on the same file is harmless.
    """
    legacy = stored.get(REMOTE_IMAGES)
    if not isinstance(legacy, str):
        return stored
    if legacy.strip().lower() not in _LEGACY_REMOTE_IMAGES:
        return stored
    migrated = dict(stored)
    # An explicit new-style value always wins: the user set it deliberately.
    migrated.setdefault(IMAGE_FALLBACK, legacy)
    migrated.pop(REMOTE_IMAGES, None)
    return migrated


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
        # None, or (reason, preserved_path_or_None). Set by `_quarantine`.
        # `write_error` is about this session's writes; this is about what was
        # found at startup, and the preferences window reports both.
        self.quarantine = None
        self._values = defaults()
        # The names this instance has itself set. See `_write`.
        self._dirty = set()
        self._listeners = {}  # token -> callback
        self._next_token = 0
        self._load()

    def get(self, name):
        """The current value of `name`. An unknown name is a programming error."""
        by_name(name)
        return self._values[name]

    def _load(self):
        # Both handlers name `Exception` rather than an enumerated list, and
        # each wraps exactly one stdlib call so it cannot hide anything else.
        # Enumerating went wrong twice: `read_text` raises UnicodeDecodeError
        # (a ValueError) on bad UTF-8 and `json.loads` raises RecursionError
        # (a RuntimeError) on deep nesting. Each escaped before the quarantine
        # ran, so the same file broke every subsequent launch. The rule: a
        # broad handler wherever untrusted DATA flows, not merely wherever
        # untrusted I/O happens.
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001 - see above
            self._quarantine(f"could not be read ({exc})")
            return

        if not text.strip():
            # What a truncated write leaves behind, with nothing worth
            # preserving: "no settings yet" rather than corruption.
            return

        try:
            stored = json.loads(text)
        except Exception as exc:  # noqa: BLE001 - see above
            self._quarantine(f"could not be parsed ({exc})")
            return

        if not isinstance(stored, dict):
            self._quarantine("does not contain a JSON object")
            return

        migrated = _migrate_legacy_remote_images(stored)
        if IMAGE_FALLBACK in migrated and IMAGE_FALLBACK not in stored:
            # Nothing is written here, but `_write` merges only keys this
            # instance has set, so an unmarked migrated value would never
            # reach the file -- and the first write an upgrading reader makes
            # (setting `remote_images` to the new fetch policy) is exactly the
            # one that overwrites the legacy value it was read from. Marking
            # it dirty carries the display choice forward.
            self._dirty.add(IMAGE_FALLBACK)
        stored = migrated

        for name, value in stored.items():
            setting = _BY_NAME.get(name)
            if setting is not None:
                # A misspelled key is not ours, and is left alone.
                self._values[name], _ = setting.coerce(value)

    def _quarantine(self, reason):
        """Move a store we cannot use aside, keeping the user's copy.

        The name is fixed rather than timestamped, so a second corruption
        overwrites the first preserved copy. That keeps the config directory
        from growing without bound and gives the preferences window a path it
        can always quote. Failing to move it is survivable — the defaults are
        already in memory either way, and `quarantine` then carries None for
        the path so the window says the file was left where it is.
        """
        target = self.path.with_name(self.path.name + ".corrupt")
        try:
            os.replace(self.path, target)
        except OSError as exc:
            self.quarantine = (reason, None)
            sys.stderr.write(
                f"xedown: {self.path} {reason}; using defaults "
                f"(it could not be moved aside: {exc})\n"
            )
            return
        self.quarantine = (reason, str(target))
        sys.stderr.write(
            f"xedown: {self.path} {reason}; using defaults. "
            f"Your copy was kept at {target}\n"
        )

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
        own = self._own_settings()
        for name in self._dirty:
            if name in own:
                merged[name] = own[name]
            else:
                # A key at its default is written as absent, so a user who
                # resets receives a changed default in a later release
                # instead of being pinned to today's.
                merged.pop(name, None)
        try:
            payload = json.dumps(merged, indent=2, sort_keys=True) + "\n"
        except Exception:  # noqa: BLE001 - merged carries untrusted content
            # `json.dumps(indent=...)` uses the pure-Python encoder, which
            # recurses far more per nesting level than `json.loads`' C
            # scanner -- so a store can load, escape quarantine, and still
            # blow the stack here. Keep our own keys rather than let the
            # user's file block every save from now on.
            payload = json.dumps(own, indent=2, sort_keys=True) + "\n"
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
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

    def _own_settings(self):
        """This instance's own settings that differ from their default.

        Every value here came from `coerce`, so it is a scalar: a str, bool,
        int, float or None. That is what makes it a safe fallback payload
        when the merged content cannot be serialised.
        """
        return {
            name: self._values[name]
            for name in self._dirty
            if self._values[name] != by_name(name).default
        }

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

    def connect(self, callback):
        """Call `callback(changed)` whenever values change. Returns a token.

        Mirrors `AppearanceWatcher`'s shape deliberately, so the two long-lived
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
        # A snapshot, because a listener may disconnect itself or another
        # from inside its callback -- but membership is re-checked per call,
        # so one disconnected earlier in this broadcast is not called.
        for token, callback in list(self._listeners.items()):
            if token not in self._listeners:
                continue
            try:
                callback(changed)
            except Exception as exc:  # noqa: BLE001 - one must not stop the rest
                sys.stderr.write(f"xedown: a settings listener failed: {exc}\n")


def _from_environment(name):
    """`name`'s value, or None when it is unset or blank."""
    value = (os.environ.get(name) or "").strip()
    return value or None


def default_config_dir():
    """Where the settings file lives, honouring the usual overrides.

    `XEDOWN_CONFIG_DIR` comes first so the live test harnesses can point a
    real xed at a scratch directory instead of rewriting — or quarantining —
    the developer's own settings. Read from `os.environ` rather than
    `GLib.get_user_config_dir()`, because a `gi` import here would put this
    whole module out of reach of the unit tests.
    """
    override = _from_environment(CONFIG_DIR_ENV)
    if override is not None:
        return pathlib.Path(override)
    xdg = _from_environment("XDG_CONFIG_HOME")
    if xdg is not None:
        return pathlib.Path(xdg) / "xedown"
    return pathlib.Path(os.path.expanduser("~")) / ".config" / "xedown"


def default_path():
    """The settings file this user's xedown reads and writes."""
    return default_config_dir() / STORE_NAME


_INSTANCE = None


def get_settings():
    """The one store this process shares between every window and every tab.

    All of xed's windows normally live in one process, so this singleton is
    what makes a change apply everywhere at once. `xed --standalone` starts a
    second process, which will not see another's change until it restarts —
    a documented limitation, not an oversight.
    """
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = Settings(default_path())
    return _INSTANCE
