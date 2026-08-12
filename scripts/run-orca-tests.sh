#!/usr/bin/env bash
# Runs xedown past a real screen reader and asserts on what it said.
#
# Needs Orca, Xephyr, metacity and dbus-run-session. Restores your plugin
# settings on exit, like the other two harnesses.
#
# Why an isolated session rather than just running Orca on your desktop:
#   - Orca only attends to the ACTIVE window, and a terminal driving the run
#     keeps taking focus back. A first attempt captured almost nothing.
#   - AT-SPI is bus-scoped, not display-scoped, so a nested display alone
#     would still leave Orca watching the real desktop. dbus-run-session is
#     what actually isolates it.
# Orca speaks out loud during the run. That is deliberate: it is the setup a
# real Orca user has, and the log does not depend on audio either way. If
# Orca is already running on your own desktop this script refuses to start
# at all (see the pgrep check below, next to the one for xed) rather than
# risk it, and cleanup only ever touches the copy this run itself launched
# inside the isolated session -- never a screen reader it did not start.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$HOME/.local/share/xed/plugins"
WORKDIR="$(mktemp -d)"
NESTED_DISPLAY="${XEDOWN_ORCA_DISPLAY:-:9}"
ORCA_LOG="$WORKDIR/orca.log"
MARKERS="$WORKDIR/markers.txt"
REPORT="$WORKDIR/report.txt"
SAVED_PLUGINS=""
XEPHYR_PID=""

for tool in orca Xephyr metacity dbus-run-session xed; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is not installed." >&2; exit 1; }
done

if pgrep -x xed >/dev/null 2>&1; then
  echo "xed is already running. Close it first." >&2
  exit 1
fi

# A developer who actually uses Orca on this desktop must not have their
# real screen reader killed by this harness's own cleanup -- see cleanup()'s
# orca-pid handling below. Refusing to start over an existing Orca is the
# other half of that: cleanup only ever kills the one PID this run itself
# launches, but that guarantee is worth nothing if a real session was
# already running before this script's own copy started inside it.
if pgrep -x orca >/dev/null 2>&1; then
  echo "Orca is already running on your desktop. Close it first -- this harness starts its own copy inside an isolated session." >&2
  exit 1
fi

cleanup() {
  # This trap must run to completion no matter what fails inside it, and a
  # failed gsettings restore must still fail the run: a caller checking only
  # the exit code must not see success while the developer's real
  # active-plugins setting was left wrong. `set +e` below is defensive, not
  # load-bearing: unlike run-integration-tests.sh's cleanup(), this script
  # never sets `-e` in the first place (`set -uo pipefail` at the top), so a
  # failing command inside this trap was never going to abort it either way.
  # What actually keeps the exit code honest is the explicit
  # `restore_failed` check and `exit 1` at the bottom of this function, the
  # same idiom run-integration-tests.sh's cleanup() uses.
  set +e
  local restore_failed=0
  # Kill only the Orca process THIS run started, by the PID the nested
  # session itself recorded (see the `orca.pid` write inside the
  # dbus-run-session block below) -- never by name. `orca` inside the
  # session is left running as an orphan once `bash -c` returns (it is a
  # background job of a non-interactive shell, which does not get SIGHUP'd
  # on exit), so something here does have to reap it; a name-based `pkill -x
  # orca` did that but also matches a screen reader the developer is
  # actually using on their own desktop -- not this harness's process to
  # kill. The `pgrep -x orca` refusal above only stops this script from
  # STARTING over somebody else's session; it does nothing to protect a
  # session that starts fresh after this one launches, so cleanup still has
  # to be scoped by PID regardless.
  if [ -f "$WORKDIR/orca.pid" ]; then
    kill "$(cat "$WORKDIR/orca.pid")" 2>/dev/null
  fi
  [ -n "$XEPHYR_PID" ] && kill "$XEPHYR_PID" 2>/dev/null
  # Remove the probe -- it is only ever meant to be installed for the
  # duration of this run, the same reasoning run-integration-tests.sh
  # applies to xedown_probe.
  rm -rf "$PLUGIN_DIR/xedown_orca_probe" "$PLUGIN_DIR/xedown_orca_probe.plugin"
  if [ -n "$SAVED_PLUGINS" ]; then
    gsettings set org.x.editor.plugins active-plugins "$SAVED_PLUGINS"
    local current
    current="$(gsettings get org.x.editor.plugins active-plugins)"
    if [ "$current" != "$SAVED_PLUGINS" ]; then
      echo "FAILED TO RESTORE org.x.editor.plugins active-plugins:" >&2
      echo "  wanted: $SAVED_PLUGINS" >&2
      echo "  got:    $current" >&2
      restore_failed=1
    fi
  fi
  echo "Transcript kept at: $WORKDIR"
  if [ "$restore_failed" -ne 0 ]; then
    exit 1
  fi
}
trap cleanup EXIT

# Deleted before the copy, and the directory created if this is a fresh
# machine -- the same two steps run-integration-tests.sh:165-166 and
# run-shutdown-tests.sh:230-231 take before their own install. Without the
# delete, a stale previously-installed copy can survive alongside (or
# shadow parts of) the working tree this run means to measure, so a pass
# could be measuring a hybrid of the two rather than either one cleanly.
mkdir -p "$PLUGIN_DIR"
rm -rf "$PLUGIN_DIR/xedown" "$PLUGIN_DIR/xedown.plugin"
cp -r "$ROOT/plugin/xedown" "$ROOT/plugin/xedown.plugin" "$PLUGIN_DIR/"
rm -rf "$PLUGIN_DIR/xedown_orca_probe" "$PLUGIN_DIR/xedown_orca_probe.plugin"
cp -r "$ROOT/tests/integration/xedown_orca_probe" \
      "$ROOT/tests/integration/xedown_orca_probe.plugin" "$PLUGIN_DIR/"
SAVED_PLUGINS="$(gsettings get org.x.editor.plugins active-plugins)"
gsettings set org.x.editor.plugins active-plugins "['xedown', 'xedown_orca_probe']"

Xephyr "$NESTED_DISPLAY" -screen 1280x900 -resizeable -no-host-grab \
  >"$WORKDIR/xephyr.log" 2>&1 &
XEPHYR_PID=$!
sleep 2
kill -0 "$XEPHYR_PID" 2>/dev/null || { echo "Xephyr failed to start." >&2; exit 1; }

# XEDOWN_CONFIG_DIR keeps the settings xedown (and the probe, which flips
# AUTO_REFRESH off mid-run) writes inside $WORKDIR. This harness drives a
# REAL xed as the real user, so without it a run would rewrite -- and on a
# bad store, quarantine -- the developer's own
# ~/.config/xedown/settings.json. Same reasoning, same env var, as
# run-integration-tests.sh:179-184.
DISPLAY="$NESTED_DISPLAY" \
XEDOWN_ORCA_REPORT="$REPORT" \
XEDOWN_ORCA_MARKERS="$MARKERS" \
XEDOWN_ORCA_TMPDIR="$WORKDIR" \
XEDOWN_CONFIG_DIR="$WORKDIR/config" \
ORCA_LOG="$ORCA_LOG" \
dbus-run-session -- bash -c '
  set -uo pipefail
  export GTK_MODULES="gail:atk-bridge"
  metacity --replace >/dev/null 2>&1 &
  sleep 2
  orca --debug-file="$ORCA_LOG" >/dev/null 2>&1 &
  # Recorded here so the outer cleanup() function can kill exactly this
  # process by PID afterward, never by name -- see the comment on cleanup()
  # for the reasoning.
  echo $! > "$XEDOWN_ORCA_TMPDIR/orca.pid"
  for _ in $(seq 1 30); do
    grep -q "Screen reader on" "$ORCA_LOG"* 2>/dev/null && break
    sleep 1
  done
  timeout 90 xed >/dev/null 2>&1
' >"$WORKDIR/session.log" 2>&1

echo "=== what the probe did ==="
cat "$REPORT" 2>/dev/null || echo "(no probe report -- the probe never ran)"

# The ROWS assertion further down only ever sees Orca's transcript, not the
# probe's own report. A failed precondition -- e.g. focus never actually
# reaching the WebView before the scroll keys were pressed -- would
# otherwise surface only as silence in the transcript, which is
# indistinguishable from a genuine "Orca said nothing" finding. Gate on the
# probe's own PASS/FAIL lines too, same idiom as
# run-integration-tests.sh:309-316.
REPORT_FAILED=0
if grep -q '^FAIL' "$REPORT" 2>/dev/null; then
  echo "Orca probe reported a FAIL" >&2
  REPORT_FAILED=1
fi
if ! grep -q '^PASS done' "$REPORT" 2>/dev/null; then
  echo "Orca probe did not run to completion (no 'PASS done' in $REPORT)" >&2
  REPORT_FAILED=1
fi

if [ ! -s "$MARKERS" ]; then
  echo "No markers were written: the probe never ran. Nothing to assert on." >&2
  exit 1
fi

ORCA_LOG_FILE="$(ls "$ORCA_LOG"* 2>/dev/null | head -1)"
if [ -z "$ORCA_LOG_FILE" ]; then
  echo "No Orca debug log was found at $ORCA_LOG*. Nothing to assert on." >&2
  exit 1
fi

TRANSCRIPT_ERR="$WORKDIR/transcript.err"
PYTHONPATH="$ROOT/tests/unit" python3 -m orca_transcript \
  "$ORCA_LOG_FILE" "$MARKERS" >"$WORKDIR/transcript.json" 2>"$TRANSCRIPT_ERR"
TRANSCRIPT_RC=$?
if [ "$TRANSCRIPT_RC" -ne 0 ]; then
  # A run that cannot be attributed (EmptyTranscript, AmbiguousTimeline)
  # must not look like a run with no findings: surface the parser's own
  # ERROR line rather than letting an empty/partial transcript.json speak
  # for itself.
  echo "Transcript could not be sliced (exit $TRANSCRIPT_RC):" >&2
  cat "$TRANSCRIPT_ERR" >&2
  exit 1
fi

echo "=== what Orca said, per row ==="
cat "$WORKDIR/transcript.json"

# The rows this harness asserts on, and what Orca must be heard saying in
# each. Only rows already measured on real hardware appear here: adding a
# row on the strength of what it *ought* to say would be exactly the
# unmeasured claim this whole exercise exists to stop making.
#
# Two tables, with a deliberate asymmetry: in ROWS an empty slice is a
# FAIL (silence is a finding, not a pass -- a11y.check_tree's rule); in
# SILENT_ROWS an empty slice is the PASS, because that row was measured, on
# real hardware, to produce no speech at all, and that is the currently-true,
# currently-desired result. Both tables FAIL on a *missing* marker either
# way, because that means the probe never reached the action -- an assertion
# that found nothing is not a pass.
PYTHONPATH="$ROOT/tests/unit" python3 - "$WORKDIR/transcript.json" <<'PY'
import json
import sys

from orca_transcript import Exact, evaluate_rows

ROWS = {
    # Ctrl+Shift+M to Source: Task 4 measured this direction genuinely
    # silent (Orca's locus of focus was already the source view before the
    # press). Task 6 added an explicit `Atk.Object` "announcement" emission
    # in `TabController.set_mode` for exactly this gap -- see
    # `plugin/xedown/modebar.py:ModeBar.announce` and task-6-report.md.
    # a11y.NAMES["mode_source"]. Exact, not a substring check: measured to
    # be this one utterance and no other (transcript-task6-fixed.json), and
    # a plain substring match on "Markdown source" would also be satisfied
    # by e.g. a toggle's own "Markdown source toggle button pressed." --
    # the misattribution shape that fooled earlier review rounds in this
    # project. Exact equality closes that hole at the gate itself.
    "row-96-switch-to-source": Exact(["Markdown source"]),
    # Ctrl+Shift+M back to Preview: same mechanism, the other direction, and
    # the same reasoning for Exact -- "Preview" alone as a substring is also
    # satisfied by "Preview toggle button pressed.", exactly the utterance
    # that was once misread as this switch announcing itself (Task 4's
    # first, contaminated reading; see Task 5's re-measurement).
    # a11y.NAMES["mode_preview"].
    "row-96-switch-back-to-preview": Exact(["Preview"]),
    # Tabbing from the bar's first control (Preview, already focused by
    # `step_row_97_focus_mode_bar`) one press over lands on the
    # Markdown/Source toggle -- Task 4's cleanest, highest-confidence
    # result: identical across three independent live runs. This proves
    # that ONE control's name and pressed state, exactly, not that "every
    # control tabbed through" was individually announced: the row captures
    # one utterance, from the one Tab press this sequence actually makes
    # (see `_modebar_focusables` and `step_row_97_mode_bar_tab` in the
    # probe). Exact for the same reason as row 96: a substring check on
    # "Markdown source" would also pass on a bare toggled-on announcement
    # with no pressed-state text at all.
    "row-97-mode-bar-tab": Exact(["Markdown source toggle button not pressed."]),
    # Fix round 1 regression check: Ctrl+Shift+M with the *refresh* button
    # focused, not a mode toggle button. The first version of
    # `ModeBar.has_focus_inside()` suppressed the announcement for any
    # focused control in the bar, including this one -- but Orca has no
    # toggle-state speech of its own for a plain `Gtk.Button`, so that made
    # this exact switch silent, the defect this task exists to remove,
    # reintroduced in a corner. Presence, not absence, so a plain substring
    # check is the right tool here (contrast
    # `row-97-activate-focused-button`, deliberately unasserted below).
    "row-100-refresh-focused-switch": ["Markdown source"],
    # The external-change warning bar. Unchanged since Task 3.
    "row-101-external-change": ["changed on disk"],
}

# Rows measured, on real hardware, to produce no speech at all -- not an
# unmeasured gap, a result. A row here FAILs if Orca *does* speak: that would
# be news (something changed) worth surfacing loudly, not something to
# silently absorb.
SILENT_ROWS = [
    # Down/Page_Down with the preview showing: total AT-SPI silence between
    # mark and next mark, not merely unpresented speech. Reproduced three
    # times, including once with WebKit2's enable-caret-browsing forced on,
    # which changed nothing. Root cause is inside WebKit2GTK's own AT-SPI
    # bridge, outside xedown's Python and outside this project's reach.
    "row-98-preview-scroll",
]

# Markers that exist -- every action that can cause speech now owns one, so
# none can ever again contaminate a neighbouring row's window -- but are
# deliberately not asserted on here:
#   row-97-focus-mode-bar   -- a preparation step (grabs focus onto the mode
#                              bar before row 97's own Tab presses). It is
#                              the very grab_focus() described above; its own
#                              speech was never what this row set out to
#                              measure, and asserting on it would duplicate
#                              row-96-switch-back-to-preview's finding under
#                              a different name.
#   row-97-activate-focused-button -- Task 6: activates the button row 97
#                              just tabbed to (Space), switching mode from
#                              *inside* the mode bar -- the suppression half
#                              of the mode announcement (`ModeBar.has_focus_inside()`
#                              is True here, so `set_mode` must not call
#                              `ModeBar.announce`). Not asserted because
#                              `evaluate_rows` can only check substrings
#                              present or total silence, and the one thing
#                              this row needs to show -- exactly one
#                              utterance, not two -- can't be told apart that
#                              way: a real state-change announcement and a
#                              would-be duplicate mode announcement both
#                              contain "Markdown source" as a substring.
#                              Verified instead by reading the raw Orca log
#                              directly; see task-6-report.md.
#   row-98-prepare-preview  -- a preparation step (corrects mode back to
#                              Preview if row 97's new activation left it in
#                              Source, then focuses the WebView before row
#                              98's own scroll keys). Used to be silent by
#                              luck (mode was already Preview by
#                              construction); since Task 6 the correction
#                              genuinely runs and does speak -- a second,
#                              unsuppressed measurement of the same
#                              announcement row 96 already asserts. Still not
#                              asserted here, to keep one row's proof in one
#                              place.
#   row-100-prepare-stale   -- a preparation step (closes the search bar,
#                              resets AUTO_REFRESH before row 100's own
#                              edit). Same reasoning as row-98-prepare-preview.
#   row-100-focus-refresh   -- Task 6 fix round 1: a preparation step
#                              (grabs focus onto the refresh button before
#                              row-100-refresh-focused-switch). Same
#                              reasoning as row-97-focus-mode-bar -- not
#                              silent by construction, so it gets its own
#                              marker, but what it says isn't this row's
#                              own claim to make.
#   row-99-search-bar-tab   -- not one of the rows Task 5's brief required
#                              an expectation for. Task 4 found the old
#                              6-press burst coalesced in Orca's own event
#                              queue, a probe-timing artifact rather than a
#                              xedown defect; Task 5 spaced the presses out
#                              and the row now speaks (see task-5-report.md).
#                              But the fixed 6-press count sweeps focus past
#                              the search bar's own last control and into
#                              xed's surrounding chrome -- one of the 7
#                              utterances measured is "Show or hide the side
#                              pane in the current window.", not a search-bar
#                              control at all. Asserting a clean expectation
#                              now would encode that overshoot as if it were
#                              deliberate. Needs the press count re-scoped to
#                              the bar's own controls before it gets one.
#   row-100-stale           -- the only utterance present is the ordinary
#                              "document modified" title-change any edit
#                              produces, not anything about staleness;
#                              asserting on it would misrepresent that as the
#                              stale/refresh mechanism being announced, when
#                              measurement shows the opposite.
#   done                    -- the sequence's final marker. Measured silent
#                              today, but not on the strength of any
#                              guarantee: `step_done`'s own docstring
#                              explains its window can carry real speech --
#                              the `AUTO_REFRESH` write it marks reaches
#                              `_refresh_body_now()` when the preview is
#                              stale and Preview mode is showing, both true
#                              at this point in the sequence. Left off both
#                              tables so a future run where that render
#                              happens to speak is neither a surprise nor an
#                              unexplained gate failure.

with open(sys.argv[1], encoding="utf-8") as handle:
    sliced = json.load(handle)

# evaluate_rows is the tested half of this decision (tests/unit/
# test_orca_transcript.py) -- this script just prints its lines and turns
# any "FAIL" into a non-zero exit.
lines = evaluate_rows(sliced, ROWS, SILENT_ROWS)
failed = False
for line in lines:
    print(line)
    if line.startswith("FAIL"):
        failed = True

sys.exit(1 if failed else 0)
PY
ASSERT_RC=$?

if [ "$ASSERT_RC" -ne 0 ] || [ "$REPORT_FAILED" -ne 0 ]; then
  echo "Orca tests FAILED" >&2
  exit 1
fi
echo "Orca tests passed"
