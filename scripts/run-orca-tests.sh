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
# real Orca user has, and the log does not depend on audio either way.
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

cleanup() {
  # This trap must run to completion no matter what fails inside it, and a
  # failed gsettings restore must still fail the run: a caller checking only
  # the exit code must not see success while the developer's real
  # active-plugins setting was left wrong. Same restore_failed idiom as
  # run-integration-tests.sh's cleanup() -- see the reasoning there.
  set +e
  local restore_failed=0
  pkill -x orca 2>/dev/null
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

cp -r "$ROOT/plugin/xedown" "$ROOT/plugin/xedown.plugin" "$PLUGIN_DIR/"
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

from orca_transcript import evaluate_rows

ROWS = {
    # Tabbing through the mode bar announces each control by name and
    # pressed state. Task 4's cleanest, highest-confidence result: identical
    # across three independent live runs.
    "row-97-mode-bar-tab": ["Markdown source"],
    # The external-change warning bar. Unchanged since Task 3.
    "row-101-external-change": ["changed on disk"],
}

# Rows measured, on real hardware, to produce no speech at all -- not an
# unmeasured gap, a result. A row here FAILs if Orca *does* speak: that would
# be news (something changed) worth surfacing loudly, not something to
# silently absorb.
SILENT_ROWS = [
    # Ctrl+Shift+M to Source: at the moment of the press, Orca's tracked
    # locus of focus was already the source view -- xed's own tab-open
    # behaviour put it there before xedown's own mode switch ran -- so the
    # press is not a new transition from Orca's point of view. This window
    # is clean (no other probe action shares it) in all three live runs
    # behind Task 4's report.
    "row-96-switch-to-source",
    # Down/Page_Down with the preview showing: total AT-SPI silence between
    # mark and next mark, not merely unpresented speech. Reproduced three
    # times, including once with WebKit2's enable-caret-browsing forced on,
    # which changed nothing. Root cause is inside WebKit2GTK's own AT-SPI
    # bridge, outside xedown's Python and outside this project's reach.
    "row-98-preview-scroll",
    # Ctrl+Shift+M back to Preview: the WebView's own focus event does fire,
    # but Orca's toolkit layer deems the WebView's outer accessible object
    # "layout only" and never presents it. Task 4 could only measure this as
    # "unclear, leaning silent" -- its window was contaminated by
    # step_row_97_focus_mode_bar's grab_focus(), which had no marker of its
    # own and produced real speech that landed here instead. Task 5 gave
    # that grab_focus() its own marker (row-97-focus-mode-bar) and re-ran
    # live, twice, to confirm this row now measures clean-silent in
    # isolation.
    "row-96-switch-back-to-preview",
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
#   row-98-prepare-preview  -- a preparation step (focuses the WebView before
#                              row 98's own scroll keys). Measures silent
#                              today by luck, not by design; not a row this
#                              project has committed to a claim about.
#   row-100-prepare-stale   -- a preparation step (closes the search bar,
#                              resets AUTO_REFRESH before row 100's own
#                              edit). Same reasoning as row-98-prepare-preview.
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
