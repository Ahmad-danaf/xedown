"""xedown — Markdown preview for xed, rendered and source modes in one tab.

The peas loader imports this module by name, which forces GTK/Xed imports here.
Those types ship with xed itself and are unavailable in CI, so the import is
guarded and the activatable classes are defined only when the host is present.
"""

import sys

__version__ = "0.1.0"

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("Xed", "1.0")
    _HOST_AVAILABLE = True
except (ImportError, ValueError) as exc:  # pragma: no cover - host-only path
    _HOST_AVAILABLE = False
    sys.stderr.write(
        f"xedown: xed/GTK typelibs unavailable ({exc}); plugin hooks not registered\n"
    )
