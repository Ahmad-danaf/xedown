"""Which mode each file was last left in. Pure logic — no GTK imports here.

Shaped like `settings.py` on purpose: a process-wide singleton, an atomic
write, and a broad handler wherever untrusted data flows. It diverges in one
respect, deliberately. `settings.json` is the user's own file, so a store that
cannot be used is quarantined and reported; this file is state xedown derived
and can regenerate, and the brief requires that a mode which cannot be
determined falls back to the default *without interrupting the user*. So a
store that cannot be used loads empty, keeps no copy, and says nothing.

Bounded on purpose too: remembering must not grow without end as a user opens
more files over months. The newest `MAX_ENTRIES` survive a write and the rest
are dropped.
"""

import json
import os
import pathlib

from . import settings
from .document_state import mode_from_setting, setting_name

STORE_NAME = "modes.json"
VERSION = 1
MAX_ENTRIES = 200


class ModeStore:
    """Every file's last mode, newest first, bounded.

    Everything here runs on the GTK main thread, so there is no locking.
    """

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._entries = []  # [(path, Mode)], newest first
        self._load()

    # --- reading -----------------------------------------------------------

    def get(self, path):
        """The mode remembered for `path`, or None when there is none."""
        if not path:
            return None
        for stored, mode in self._entries:
            if stored == path:
                return mode
        return None

    def _load(self):
        # One broad handler per stdlib call that touches untrusted data, for
        # the reasons settings.py records at length: `read_text` raises
        # UnicodeDecodeError (a ValueError) and `json.loads` raises
        # RecursionError (a RuntimeError), neither of which an enumerated
        # handler catches.
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except Exception:  # noqa: BLE001 - see the module docstring
            return
        try:
            stored = json.loads(text)
        except Exception:  # noqa: BLE001 - as above
            return
        self._entries = self._parse(stored)

    @staticmethod
    def _parse(stored):
        """The usable entries in a decoded store. Never raises."""
        if not isinstance(stored, dict) or stored.get("version") != VERSION:
            return []
        rows = stored.get("modes")
        if not isinstance(rows, list):
            return []
        entries = []
        seen = set()
        for row in rows:
            if len(entries) >= MAX_ENTRIES:
                break
            if not isinstance(row, list) or len(row) != 2:
                continue
            path, name = row
            if not isinstance(path, str) or not path or path in seen:
                continue
            mode = mode_from_setting(name)
            if mode is None:
                continue
            seen.add(path)
            entries.append((path, mode))
        return entries

    # --- writing -----------------------------------------------------------

    def remember(self, path, mode):
        """Record `mode` for `path` as the newest entry."""
        if not path:
            return
        self._promote(path, mode)
        self._write()

    def forget(self, path):
        """Drop `path`, if it is remembered at all."""
        if not path:
            return
        remaining = [row for row in self._entries if row[0] != path]
        if len(remaining) == len(self._entries):
            return
        self._entries = remaining
        self._write(removed={path})

    def rename(self, old_path, new_path):
        """Follow a file that moved, so the old path stops answering.

        This is the whole of what xedown can observe: a file renamed while
        xed is not looking leaves an entry keyed to a path that no longer
        exists, which the cap eventually eats.
        """
        mode = self.get(old_path)
        if mode is None:
            return
        self._entries = [row for row in self._entries if row[0] != old_path]
        if new_path:
            self._promote(new_path, mode)
        self._write(removed={old_path})

    def _promote(self, path, mode):
        self._entries = [(path, mode)] + [
            row for row in self._entries if row[0] != path
        ]
        del self._entries[MAX_ENTRIES:]

    def _write(self, removed=None):
        """Merge this process's entries over whatever is on disk.

        Another xed process (`xed --standalone`) has its own store object
        over the same file, and must not have its memory erased by ours. Ours
        win a conflicting path: the last mode set is the one the user chose
        most recently in the process doing the writing.

        A failure is swallowed. The mode stays live for this session and is
        simply not there next time; there is no surface in this brief on
        which to report it, and a dialog about a view mode would be worse
        than the loss.
        """
        if removed is None:
            removed = set()
        merged = list(self._entries)
        held = {path for path, _ in merged}
        for path, mode in self._parse(self._stored_on_disk()):
            if path in held or path in removed:
                continue
            merged.append((path, mode))
            held.add(path)
        del merged[MAX_ENTRIES:]

        payload = (
            json.dumps(
                {
                    "version": VERSION,
                    "modes": [[path, setting_name(mode)] for path, mode in merged],
                },
                indent=2,
            )
            + "\n"
        )
        temp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(payload, encoding="utf-8")
            # Atomic within one filesystem, so a crash mid-write cannot
            # leave a half-written store behind.
            os.replace(temp, self.path)
        except OSError:
            try:
                temp.unlink()
            except OSError:
                pass

    def _stored_on_disk(self):
        """The file's current contents, or None when it cannot be used."""
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - untrusted content, as in _load
            return None


def default_path():
    """Beside `settings.json`, so `XEDOWN_CONFIG_DIR` isolates it too."""
    return settings.default_config_dir() / STORE_NAME


_INSTANCE = None


def get_store():
    """The one store this process shares between every window and every tab."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ModeStore(default_path())
    return _INSTANCE
