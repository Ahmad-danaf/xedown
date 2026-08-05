"""Pins the one allowlisted xed-core message to exactly one log line.

Both shell harnesses treat any warning, critical, traceback or crash in
xed's stderr as a release blocker, with a single exception: a confirmed xed
3.8.9 core assertion that reproduces with xedown not installed at all (run
`XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab` to see it again).

An exception like that is only safe while it stays narrow, and "narrow" is
not something a comment can enforce. The patterns are therefore read out of
the shell scripts themselves rather than restated here -- a copy would
happily keep passing while the real harness drifted -- and applied to
crafted log lines that a too-loose pattern would wrongly swallow.

The cases below are the ways this allowlist could plausibly rot: matching a
different assertion in the same function, a different log level, the same
text from another process, or a line carrying a second message alongside
the known one.
"""

import pathlib
import re

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "scripts"
SHUTDOWN_SCRIPT = SCRIPTS_DIR / "run-shutdown-tests.sh"
INTEGRATION_SCRIPT = SCRIPTS_DIR / "run-integration-tests.sh"

# The real thing, copied verbatim from a captured run (see
# docs/known-issues.md, which also carries the stack it shares with the
# segfault the same xed bug produces).
KNOWN_LINE = (
    "(xed:76920): Gtk-CRITICAL **: 18:38:01.931: gtk_action_group_get_action: "
    "assertion 'GTK_IS_ACTION_GROUP (action_group)' failed"
)


def _extract(script, name, quote):
    text = script.read_text(encoding="utf-8")
    match = re.search(rf"^{name}={quote}(.*){quote}$", text, re.MULTILINE)
    assert match is not None, f"{name} not found in {script.name}"
    return match.group(1)


def _known(script):
    return _extract(script, "KNOWN_XED_CORE_ASSERTION", '"')


def _bad(script):
    return _extract(script, "BAD_PATTERN", "'")


def _blocks(line, script=SHUTDOWN_SCRIPT):
    """Mirror the shell check: flagged by BAD_PATTERN, not excused by the allowlist.

    `grep -Ev` drops a line when the pattern matches anywhere in it, which
    `re.search` reproduces; the anchors live in the pattern itself.
    """
    line = line.rstrip("\n")
    if not re.search(_bad(script), line):
        return False
    return not re.search(_known(script), line)


def test_both_harnesses_use_the_same_patterns():
    # Two scripts, one rule. If they drift, the weaker one silently becomes
    # the project's real standard.
    assert _known(SHUTDOWN_SCRIPT) == _known(INTEGRATION_SCRIPT)
    assert _bad(SHUTDOWN_SCRIPT) == _bad(INTEGRATION_SCRIPT)


def test_the_known_assertion_is_allowed():
    assert re.search(_bad(SHUTDOWN_SCRIPT), KNOWN_LINE), (
        "the known line must still be recognised as noteworthy output; "
        "otherwise this allowlist is being tested against nothing"
    )
    assert not _blocks(KNOWN_LINE)


def test_allowlist_is_anchored_to_a_whole_line():
    # Without ^...$ every case in this test would pass by accident.
    pattern = _known(SHUTDOWN_SCRIPT)
    assert pattern.startswith("^")
    assert pattern.endswith("$")


@pytest.mark.parametrize(
    "line",
    [
        # A different assertion inside the very same function.
        (
            "(xed:76920): Gtk-CRITICAL **: 18:38:01.931: gtk_action_group_get_action: "
            "assertion 'GTK_IS_SOMETHING_ELSE (action_group)' failed"
        ),
        # The same assertion text, different function.
        (
            "(xed:76920): Gtk-CRITICAL **: 18:38:01.931: gtk_action_group_add_action: "
            "assertion 'GTK_IS_ACTION_GROUP (action_group)' failed"
        ),
        # The same assertion, raised at a different log level.
        (
            "(xed:76920): Gtk-WARNING **: 18:38:01.931: gtk_action_group_get_action: "
            "assertion 'GTK_IS_ACTION_GROUP (action_group)' failed"
        ),
        # The same text from another process entirely.
        (
            "(gedit:76920): Gtk-CRITICAL **: 18:38:01.931: gtk_action_group_get_action: "
            "assertion 'GTK_IS_ACTION_GROUP (action_group)' failed"
        ),
        # A second message riding along on the same line -- the exact thing
        # an unanchored substring match would have hidden.
        KNOWN_LINE + " AND ALSO: Gtk-CRITICAL **: something else broke",
        "prefixed junk " + KNOWN_LINE,
        # Ordinary blockers, none of which are near the allowlist.
        "(xed:76920): Gtk-CRITICAL **: 18:38:01.931: gtk_widget_show: assertion failed",
        "(xed:76920): GLib-GObject-WARNING **: 18:38:01.931: instance has no handler",
        "Traceback (most recent call last):",
        "Segmentation fault (core dumped)",
        "*** stack smashing detected ***",
    ],
)
def test_these_all_block_the_release(line):
    assert _blocks(line), f"should have blocked the release: {line!r}"


@pytest.mark.parametrize(
    "line",
    [
        "",
        "SHUTDOWN-PROBE: PASS preview-active-previews-live",
        "READY preview-active",
        # xedown's own guarded stderr note is informational, not a fault.
        (
            "xedown: xed/GTK typelibs unavailable (No module named gi); "
            "plugin hooks not registered"
        ),
    ],
)
def test_ordinary_output_does_not_block(line):
    assert not _blocks(line)
