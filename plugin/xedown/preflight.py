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


# --- the verdict ---------------------------------------------------------
#
# Three states per fact, and the difference between two of them is the whole
# point:
#
#   True  -- present.
#   False -- determined absent. Only this can be fatal.
#   None  -- could not be determined. Never fatal, at most a warning.
#
# A probe that failed is not evidence of absence, and an installer that
# refuses over a question it could not answer is worse than one that
# installs with a warning.


def _python(facts):
    version = parse_python_version(facts.get("python_version"))
    if version is None:
        return [
            Finding(
                SOFT,
                "python-unknown",
                "could not determine the Python version",
            )
        ]
    if version < MIN_PYTHON:
        return [
            Finding(
                HARD,
                "python-too-old",
                f"Python {_dotted(version)} is too old; "
                f"xedown needs {_dotted(MIN_PYTHON)} or newer",
            )
        ]
    if version[:2] > TESTED_PYTHON[-1]:
        return [
            Finding(
                SOFT,
                "python-untested",
                f"Python {_dotted(version)} is newer than any version "
                f"xedown is tested on ({_dotted(TESTED_PYTHON[-1])})",
            )
        ]
    return []


def _dependency(present, code, label, package):
    if present is False:
        return [
            Finding(
                HARD,
                code,
                f"{label} is missing",
                f"install it with: sudo apt install {package}",
            )
        ]
    if present is None:
        return [
            Finding(
                SOFT,
                code.replace("-missing", "-unknown"),
                f"could not determine whether {label} is present",
            )
        ]
    return []


def _typelibs(facts):
    findings = _dependency(
        facts.get("has_gi"), "gi-missing", "python3-gi", "python3-gi"
    )
    if facts.get("has_gi") is not True:
        # Both probes below need `gi` to run, so their result carries no
        # information here. One cause, one message.
        return findings
    findings += _dependency(
        facts.get("gtk3_typelib"),
        "gtk3-missing",
        f"the GTK {REQUIRED_GTK_GI} typelib",
        "gir1.2-gtk-3.0",
    )
    findings += _dependency(
        facts.get("webkit41_typelib"),
        "webkit41-missing",
        f"the WebKit2 {REQUIRED_WEBKIT_GI} typelib",
        "gir1.2-webkit2-4.1",
    )
    return findings


def _xed(facts):
    if facts.get("has_xed") is False:
        return [
            Finding(
                HARD,
                "xed-missing",
                "xed was not found on PATH",
                "install it with: sudo apt install xed",
            )
        ]
    if facts.get("has_xed") is None:
        return [
            Finding(SOFT, "xed-unknown", "could not determine whether xed is installed")
        ]
    version = parse_xed_version(facts.get("xed_version"))
    if version is None:
        return [
            Finding(
                SOFT,
                "xed-version-unknown",
                "xed is installed but its version could not be read",
            )
        ]
    if version[:2] != TESTED_XED:
        return [
            Finding(
                SOFT,
                "xed-untested",
                f"xed {_dotted(version)} is outside the tested "
                f"{TESTED_XED[0]}.{TESTED_XED[1]} series",
            )
        ]
    return []


def _distro(facts):
    distro_id = facts.get("distro_id")
    major = parse_distro_major(facts.get("distro_version_id"))
    if distro_id is None or major is None:
        return [Finding(SOFT, "distro-unknown", "could not determine the distribution")]
    if distro_id.strip().lower() != TESTED_DISTRO_ID or major != TESTED_DISTRO_MAJOR:
        return [
            Finding(
                SOFT,
                "distro-untested",
                f"{distro_id} {facts.get('distro_version_id')} is outside "
                f"the tested Linux Mint {TESTED_DISTRO_MAJOR}.x",
            )
        ]
    return []


def _session(facts):
    session = facts.get("session_type")
    # An absent XDG_SESSION_TYPE is ordinary -- over ssh, in a container --
    # and says nothing about what xedown will meet when it runs. Only a
    # session that positively reports Wayland is worth a warning.
    if isinstance(session, str) and session.strip().lower() == "wayland":
        return [
            Finding(
                SOFT,
                "wayland-untested",
                "this is a Wayland session; xedown is only tested on "
                f"{TESTED_SESSION_TYPE.upper()}",
            )
        ]
    return []


def _dotted(version):
    return ".".join(str(part) for part in version)


def evaluate(facts):
    """Everything worth saying about `facts`, worst first is not required.

    An empty list means this machine is exactly what the matrix claims.
    """
    findings = []
    for check in (_typelibs, _python, _xed, _distro, _session):
        findings.extend(check(facts))
    return findings
