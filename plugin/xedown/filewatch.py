"""Watches one document's file for writes from outside xed. Needs the host — uses Gio.

`gi` is imported lazily inside the methods that need it, exactly as
`stylewatcher.StylesheetWatcher` does, so importing this module outside xed
still works and CI can reach the lifecycle promises below.

One watch per tab, unlike the stylesheet's single process-wide watcher: the
thing being watched here is this document's own file, it moves when the
document is saved under a new name, and it dies with the tab.

This module knows about events and timing and nothing about meaning.
`diskstate.evaluate` decides what a settled change is; `controller.py` acts on
it. Nothing here reads the file.
"""

import sys

# A single save by another program is several file events: a temporary file
# created, written, then renamed over the target. One settled update is what
# the user should see, not a flicker of three. Deliberately not
# `Gio.FileMonitor.set_rate_limit`, which coalesces per event kind and so
# still delivers a truncate-then-write as several callbacks.
SETTLE_DELAY_MS = 300


class FileWatch:
    """One file, watched. Calls `on_settled()` once its events stop."""

    def __init__(self, path, on_settled):
        # No `gi` here on purpose: constructing a watch must not require the
        # host, so the controller can build one and decide later whether to
        # start it, and so CI can reach the lifecycle at all.
        self.path = path
        self._on_settled = on_settled
        self._monitor = None
        self._monitor_handler = 0
        self._settle_source = 0

    def start(self):
        """Begin watching `self.path`. Idempotent — it re-arms.

        A failure to watch is reported once and is never fatal: a preview that
        does not follow external edits is a great deal better than a tab that
        will not open.
        """
        self._unwatch()
        if not self.path:
            return

        from gi.repository import Gio

        try:
            self._monitor = Gio.File.new_for_path(self.path).monitor_file(
                Gio.FileMonitorFlags.WATCH_MOVES, None
            )
        except Exception as exc:  # noqa: BLE001 - never stop the preview working
            sys.stderr.write(
                f"xedown: cannot watch {self.path} for changes ({exc}); "
                f"the preview will not follow edits made outside xed\n"
            )
            self._monitor = None
            return
        self._monitor_handler = self._monitor.connect("changed", self._on_changed)

    def repoint(self, path):
        """Follow the document to `path` — a Save As.

        Guarded on the path actually moving: re-arming tears down a live
        monitor to build another, and an ordinary save must not cost the watch
        its monitor for the window in between.
        """
        if path == self.path:
            return
        self.path = path
        self._cancel_settle()
        self.start()

    def stop(self):
        """Leave nothing behind: no monitor, no timer. Idempotent.

        Safe before `start()` and safe twice. Called from the controller's
        `deactivate()`, which runs both when a tab closes and when the plugin
        is disabled, so the shutdown scenarios stay silent.
        """
        self._cancel_settle()
        self._unwatch()

    # --- machinery ---------------------------------------------------------

    def _unwatch(self):
        if self._monitor is not None:
            if self._monitor_handler:
                self._monitor.disconnect(self._monitor_handler)
            self._monitor.cancel()
        self._monitor = None
        self._monitor_handler = 0

    def _on_changed(self, *_args):
        """Every event kind does the same thing: restart the settle timer.

        `CHANGED`, `CHANGES_DONE_HINT`, `CREATED`, `DELETED`, `RENAMED`,
        `MOVED_IN`, `MOVED_OUT` and `ATTRIBUTE_CHANGED` are not told apart on
        purpose. The comparison in `diskstate` is what distinguishes a real
        change from a false alarm, and it does so from the file's own content
        rather than from a guess about which event kind implies what.
        """
        from gi.repository import GLib

        self._cancel_settle()
        self._settle_source = GLib.timeout_add(SETTLE_DELAY_MS, self._on_settle_elapsed)

    def _on_settle_elapsed(self):
        self._settle_source = 0
        # Re-armed rather than merely left running: most programs save by
        # writing a temporary file and renaming it over the target, which
        # replaces the inode, and a monitor still attached to the old one sees
        # the FIRST such save and never another. This is the same fix, for the
        # same reason, as stylewatcher._on_debounce_elapsed -- behaviour this
        # repository has already measured once. It is also what makes
        # deletion, replacement and move-away-and-back work without a separate
        # code path for each.
        self.start()
        self._on_settled()
        return False

    def _cancel_settle(self):
        if self._settle_source:
            from gi.repository import GLib

            GLib.source_remove(self._settle_source)
            self._settle_source = 0
