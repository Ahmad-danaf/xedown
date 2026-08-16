"""What the preflight module makes of the strings a real machine produces.

The parsers are separated from the verdict because the strings are the part
that varies by machine and the part a unit test can pin exactly. The live
development machine reports `xed - Version 3.8.9+zena`: a prose prefix from
xed and a distro suffix from Mint, neither of which a naive split survives.

Every parser returns None rather than raising, and None means "could not be
determined" -- a distinction `evaluate` depends on, because a probe that
merely failed must never refuse an install.
"""

import pytest
from xedown import preflight


@pytest.mark.parametrize(
    "text,expected",
    [
        # The real string, from the live machine.
        ("xed - Version 3.8.9+zena", (3, 8, 9)),
        ("xed - Version 3.8.9", (3, 8, 9)),
        # A two-component version fills the patch slot with zero, so callers
        # can compare tuples without special-casing length.
        ("xed - Version 3.8", (3, 8, 0)),
        ("xed - Version 3.0.0", (3, 0, 0)),
        ("xed - Version 4.10.2", (4, 10, 2)),
    ],
)
def test_reads_a_real_xed_version(text, expected):
    assert preflight.parse_xed_version(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "xed: command not found",
        "xed - Version unknown",
        None,
        3.8,
    ],
)
def test_unreadable_xed_version_is_none(text):
    assert preflight.parse_xed_version(text) is None


def test_xed_version_rejects_non_ascii_digits():
    # `\d` would match these and `int()` would convert them, inventing a
    # version nobody reported. The same trap CLAUDE.md records for the
    # sanitizer's `start` attribute.
    assert preflight.parse_xed_version("xed - Version ٣.٨.٩") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3.12.3", (3, 12, 3)),
        ("3.10", (3, 10, 0)),
        ("3.13.0rc1", (3, 13, 0)),
    ],
)
def test_reads_a_python_version(text, expected):
    assert preflight.parse_python_version(text) == expected


@pytest.mark.parametrize("text", ["", "python3", None, "٣.١٢"])
def test_unreadable_python_version_is_none(text):
    assert preflight.parse_python_version(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [("22.3", 22), ("22", 22), ("24.04", 24), ("41", 41)],
)
def test_reads_a_distro_major(text, expected):
    assert preflight.parse_distro_major(text) == expected


@pytest.mark.parametrize("text", ["", "rolling", None, "٢٢"])
def test_unreadable_distro_major_is_none(text):
    assert preflight.parse_distro_major(text) is None
