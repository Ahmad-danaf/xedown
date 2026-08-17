"""Watches the user's custom stylesheet file. Needs the host — uses Gio.

`gi` is imported lazily inside the methods that need it, exactly as
`appearance.AppearanceWatcher` imports Gtk, so importing this module outside
xed still works.

One monitor for the whole process, not one per tab. The stylesheet is a
global resource like the settings store; an editor saving it fires several
events that deserve one debounce rather than one per open tab; and
re-targeting when the path changes then lives in a single place.

The important property is that this is the *only* route by which a controller
learns the user's stylesheet is different. Both causes — the setting moved, or
the file changed — leave through the same callback, so nothing depends on the
order the settings store delivers to its listeners, which brief 1 recorded as
unasserted.
"""

import sys

from . import settings, stylesheets

# One save by an editor is several file events: a temporary file created,
# written, then renamed over the target. Coalesced into one reload rather
# than reloading every open preview three times.
DEBOUNCE_MS = 150


class StylesheetWatcher:
    """The current user stylesheet, and whoever wants to hear it change."""

    def __init__(self):
        self._listeners = {}  # token -> callback
        self._next_token = 0
        self._monitor = None
        self._monitor_handler = 0
        self._debounce_source = 0
        self._settings_token = None
        self._current = stylesheets.UserStylesheet()

    def current(self):
        """The stylesheet as of the last load. Never None.

        No load happens until the first `connect()` — that call is what
        performs it, via `_start()` -> `_retarget()`. Calling `current()`
        before any `connect()` returns the unset default, not the live
        setting.
        """
        return self._current

    def connect(self, callback):
        """Call `callback(user)` when the stylesheet changes. Returns a token.

        The first listener starts the machinery; the token must be handed
        back to `disconnect`, because this watcher outlives every controller
        and a missed disconnect keeps a torn-down one — and the WebView,
        document and tab it references — alive for the life of the process.
        """
        if not self._listeners:
            self._start()
        self._next_token += 1
        self._listeners[self._next_token] = callback
        return self._next_token

    def disconnect(self, token):
        """Stop delivering to `token`. Idempotent. The last one shuts down."""
        self._listeners.pop(token, None)
        if not self._listeners:
            self._stop()

    def _start(self):
        self._settings_token = settings.get_settings().connect(
            self._on_settings_changed
        )
        self._retarget()

    def _stop(self):
        """Leave nothing behind: no monitor, no timer, no subscription.

        Called when the last tab goes away and when the plugin is disabled,
        so the shutdown scenarios stay silent.
        """
        self._cancel_debounce()
        self._unwatch()
        if self._settings_token is not None:
            settings.get_settings().disconnect(self._settings_token)
            self._settings_token = None
        self._current = stylesheets.UserStylesheet()

    def _on_settings_changed(self, changed):
        if settings.CUSTOM_STYLESHEET not in changed:
            return
        self._retarget()
        self._notify()

    def _retarget(self):
        """Re-read the setting, re-read the file, and watch whatever is there."""
        self._unwatch()
        self._current = stylesheets.load_user_stylesheet(
            settings.get_settings().get(settings.CUSTOM_STYLESHEET)
        )
        path = self._current.path
        if path is None:
            return

        from gi.repository import Gio

        try:
            # Watched even when it does not exist yet, so creating the file
            # is itself a change worth hearing about.
            self._monitor = Gio.File.new_for_path(path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
        except Exception as exc:  # noqa: BLE001 - never stop the preview working
            sys.stderr.write(
                f"xedown: cannot watch {path} for changes ({exc}); "
                f"the stylesheet will still be read when a setting changes\n"
            )
            self._monitor = None
            return
        self._monitor_handler = self._monitor.connect("changed", self._on_file_changed)

    def _unwatch(self):
        if self._monitor is not None:
            if self._monitor_handler:
                self._monitor.disconnect(self._monitor_handler)
            self._monitor.cancel()
        self._monitor = None
        self._monitor_handler = 0

    def _on_file_changed(self, *_args):
        from gi.repository import GLib

        self._cancel_debounce()
        self._debounce_source = GLib.timeout_add(DEBOUNCE_MS, self._on_debounce_elapsed)

    def _on_debounce_elapsed(self):
        self._debounce_source = 0
        # Re-target rather than merely re-read: most editors save by writing a
        # temporary file and renaming it over the target, which replaces the
        # inode. Watching the path again after every settled change means the
        # *second* save is still noticed.
        self._retarget()
        self._notify()
        return False

    def _cancel_debounce(self):
        if self._debounce_source:
            from gi.repository import GLib

            GLib.source_remove(self._debounce_source)
            self._debounce_source = 0

    def _notify(self):
        # A snapshot, because a listener may disconnect itself or another
        # from inside its own callback -- but membership is re-checked before
        # each call, so one disconnected earlier in this broadcast is not
        # called after the fact. Same shape as Settings._notify.
        for token, callback in list(self._listeners.items()):
            if token not in self._listeners:
                continue
            try:
                callback(self._current)
            except Exception as exc:  # noqa: BLE001 - one must not stop the rest
                sys.stderr.write(f"xedown: a stylesheet listener failed: {exc}\n")


_INSTANCE = None


def get_watcher():
    """The one watcher this process shares between every window and every tab."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = StylesheetWatcher()
    return _INSTANCE
