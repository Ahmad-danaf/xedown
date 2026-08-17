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


SUPPORTED = {
    "python_version": "3.12.3",
    "has_gi": True,
    "gtk3_typelib": True,
    "webkit41_typelib": True,
    "has_xed": True,
    "xed_version": "xed - Version 3.8.9+zena",
    "distro_id": "linuxmint",
    "distro_version_id": "22.3",
    "session_type": "x11",
}


def _codes(**overrides):
    facts = dict(SUPPORTED, **overrides)
    return {f.code: f.severity for f in preflight.evaluate(facts)}


def test_the_live_machine_produces_no_findings():
    # The exact configuration the matrix claims. If this ever reports
    # something, the matrix and the machine have drifted apart.
    assert preflight.evaluate(SUPPORTED) == []


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"has_gi": False}, "gi-missing"),
        ({"gtk3_typelib": False}, "gtk3-missing"),
        ({"webkit41_typelib": False}, "webkit41-missing"),
        ({"python_version": "3.9.18"}, "python-too-old"),
        ({"has_xed": False}, "xed-missing"),
    ],
)
def test_these_refuse_the_install(overrides, code):
    assert _codes(**overrides).get(code) == preflight.HARD


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"xed_version": "xed - Version 3.9.0"}, "xed-untested"),
        ({"xed_version": "xed - Version 3.0.0"}, "xed-untested"),
        ({"xed_version": "xed - Version 4.0.0"}, "xed-untested"),
        ({"xed_version": "nonsense"}, "xed-version-unknown"),
        ({"distro_id": "fedora", "distro_version_id": "41"}, "distro-untested"),
        ({"distro_id": "linuxmint", "distro_version_id": "21.3"}, "distro-untested"),
        ({"python_version": "3.13.0"}, "python-untested"),
        ({"session_type": "wayland"}, "wayland-untested"),
    ],
)
def test_these_only_warn(overrides, code):
    assert _codes(**overrides).get(code) == preflight.SOFT


@pytest.mark.parametrize(
    "key",
    [
        "python_version",
        "has_gi",
        "gtk3_typelib",
        "webkit41_typelib",
        "has_xed",
        "xed_version",
        "distro_id",
        "distro_version_id",
        "session_type",
    ],
)
def test_an_undetermined_fact_never_refuses(key):
    # A probe that failed is not evidence of absence. Refusing to install
    # over a question the script could not answer is worse than installing
    # with a warning.
    severities = set(_codes(**{key: None}).values())
    assert preflight.HARD not in severities


def test_a_missing_gi_does_not_also_report_two_missing_typelibs():
    # Both typelib probes need `gi` to run at all, so `install.sh` reports
    # them as undetermined when `gi` is absent. One cause, one message.
    codes = _codes(has_gi=False, gtk3_typelib=None, webkit41_typelib=None)
    assert codes == {"gi-missing": preflight.HARD}


def test_boundaries_of_the_python_floor():
    assert "python-too-old" in _codes(python_version="3.9.99")
    assert _codes(python_version="3.10.0") == {}
    assert _codes(python_version="3.12.99") == {}
    assert "python-untested" in _codes(python_version="3.13.0")


def test_every_hard_finding_that_apt_can_fix_names_a_package():
    for overrides in (
        {"has_gi": False},
        {"gtk3_typelib": False},
        {"webkit41_typelib": False},
        {"has_xed": False},
    ):
        facts = dict(SUPPORTED, **overrides)
        hard = [f for f in preflight.evaluate(facts) if f.severity == preflight.HARD]
        assert hard, overrides
        assert all("apt install" in f.remedy for f in hard), overrides


def test_the_required_webkit_version_appears_in_its_message():
    # The one row that is a requirement rather than a measurement. A reader
    # on WebKit2GTK 4.0 must be told the number, not just "unsupported".
    facts = dict(SUPPORTED, webkit41_typelib=False)
    (finding,) = [f for f in preflight.evaluate(facts) if f.code == "webkit41-missing"]
    assert preflight.REQUIRED_WEBKIT_GI in finding.message


SUPPORTED_STRINGS = {
    "python_version": "3.12.3",
    "has_gi": "1",
    "gtk3_typelib": "1",
    "webkit41_typelib": "1",
    "has_xed": "1",
    "xed_version": "xed - Version 3.8.9+zena",
    "distro_id": "linuxmint",
    "distro_version_id": "22.3",
    "session_type": "x11",
}


def _argv(**overrides):
    """A full argument list with some facts replaced.

    Built from a dict rather than by slicing a list: `parse_facts` reads
    arguments in order and a later one wins, so a test that appended an
    override would have it silently overwritten by the value it meant to
    replace.
    """
    facts = dict(SUPPORTED_STRINGS, **overrides)
    return [f"{key}={value}" for key, value in facts.items()]


def test_facts_decode_from_key_value_arguments():
    facts = preflight.parse_facts(_argv())
    assert facts["has_gi"] is True
    assert facts["python_version"] == "3.12.3"
    # The value may contain spaces and its own separators; only the first
    # `=` splits.
    assert facts["xed_version"] == "xed - Version 3.8.9+zena"


def test_an_empty_value_means_undetermined():
    facts = preflight.parse_facts(["has_gi=", "xed_version="])
    assert facts["has_gi"] is None
    assert facts["xed_version"] is None


def test_boolean_facts_decode_from_one_and_zero():
    facts = preflight.parse_facts(["has_gi=0", "has_xed=1"])
    assert facts["has_gi"] is False
    assert facts["has_xed"] is True


def test_an_unknown_key_is_ignored_rather_than_fatal():
    # The installer and this module are versioned together but installed
    # separately; a stale caller must not crash the check it is running.
    assert "nonsense" not in preflight.parse_facts(["nonsense=1", "has_gi=1"])


@pytest.mark.parametrize(
    "argv,expected",
    [
        (_argv(), 0),
        (_argv(xed_version="xed - Version 3.9.0"), 1),
        (_argv(has_gi="0"), 2),
    ],
)
def test_exit_code_says_clear_warned_or_refused(argv, expected):
    assert preflight.main(argv) == expected


def test_a_hard_finding_wins_over_soft_ones(capsys):
    argv = _argv(has_gi="0", session_type="wayland")
    assert preflight.main(argv) == 2
    printed = capsys.readouterr().out
    # Every finding is printed, not only the first: a reader fixing one
    # missing package should learn about the second in the same run.
    assert "python3-gi" in printed
    assert "Wayland" in printed


def test_a_remedy_is_printed_where_there_is_one(capsys):
    preflight.main(_argv(webkit41_typelib="0"))
    assert "sudo apt install gir1.2-webkit2-4.1" in capsys.readouterr().out


def test_a_clear_machine_prints_nothing(capsys):
    assert preflight.main(_argv()) == 0
    assert capsys.readouterr().out == ""
