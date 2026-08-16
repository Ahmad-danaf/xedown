"""What this machine can and cannot run, decided away from the shell.

Pure, and on purpose: `install.sh` gathers facts about the machine, and this
module decides what they mean. The split is the same one the rest of the
codebase uses -- anything that imports `gi` is unreachable by the unit tests,
because GTK/Xed/WebKit typelibs do not exist in CI -- and it is what lets the
supported matrix be table-tested on all three Pythons instead of being
trusted.

It is run as a file, never imported as `xedown.preflight` by the installer:
importing the package executes `__init__.py`, whose `gi` guard prints a note
to stderr, which is correct behaviour and noise in the middle of an install.
That is why there are no relative imports here.

The matrix below is duplicated in `docs/compatibility.md`, which is the copy
a reader actually meets. `tests/unit/test_compatibility.py` pins the two
together, the same way `test_shutdown_allowlist.py` pins the allowlist line
that is duplicated across both harness scripts: the fact lives in two places
because both places need it readable, and a test makes that safe.
"""

import re
from typing import NamedTuple

# --- the supported matrix ------------------------------------------------

MIN_PYTHON = (3, 10)
TESTED_PYTHON = ((3, 10), (3, 11), (3, 12))
TESTED_XED = (3, 8)
REQUIRED_WEBKIT_GI = "4.1"
REQUIRED_GTK_GI = "3.0"
TESTED_DISTRO_ID = "linuxmint"
TESTED_DISTRO_MAJOR = 22
TESTED_SESSION_TYPE = "x11"

# --- severities ----------------------------------------------------------

HARD = "hard"
SOFT = "soft"


class Finding(NamedTuple):
    """One thing worth saying about this machine before installing.

    `remedy` is the empty string when there is nothing to install -- an
    unsupported Python is not fixed by apt, and inventing a command for it
    would be worse than saying nothing.
    """

    severity: str
    code: str
    message: str
    remedy: str = ""


# --- parsers -------------------------------------------------------------
#
# `[0-9]`, never `\d`: `\d` is Unicode-aware and matches Arabic-Indic
# digits, which `int()` then converts without complaint, inventing a version
# nobody reported. CLAUDE.md records the same trap in the sanitizer.

_XED_VERSION = re.compile(r"Version\s+([0-9]+)\.([0-9]+)(?:\.([0-9]+))?")
_DOTTED = re.compile(r"^\s*([0-9]+)\.([0-9]+)(?:\.([0-9]+))?")
_LEADING_INT = re.compile(r"^\s*([0-9]+)")


def _triple(match):
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def parse_xed_version(text):
    """`(major, minor, patch)` from `xed --version`, or None.

    The real output carries a prose prefix and, on Mint, a distro suffix:
    `xed - Version 3.8.9+zena`. Anchoring on the word `Version` rather than
    on "the first run of digits" keeps a future prefix from being read as
    the version.
    """
    if not isinstance(text, str):
        return None
    return _triple(_XED_VERSION.search(text))


def parse_python_version(text):
    """`(major, minor, patch)` from a dotted version string, or None."""
    if not isinstance(text, str):
        return None
    return _triple(_DOTTED.match(text))


def parse_distro_major(text):
    """The leading integer of an os-release VERSION_ID, or None.

    `22.3` and `22` both mean Mint 22; only the series is claimed.
    """
    if not isinstance(text, str):
        return None
    match = _LEADING_INT.match(text)
    return int(match.group(1)) if match else None
