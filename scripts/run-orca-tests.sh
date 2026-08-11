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
  set +e
  pkill -x orca 2>/dev/null
  [ -n "$XEPHYR_PID" ] && kill "$XEPHYR_PID" 2>/dev/null
  # Remove the probe -- it is only ever meant to be installed for the
  # duration of this run, the same reasoning run-integration-tests.sh
  # applies to xedown_probe.
  rm -rf "$PLUGIN_DIR/xedown_orca_probe" "$PLUGIN_DIR/xedown_orca_probe.plugin"
  if [ -n "$SAVED_PLUGINS" ]; then
    gsettings set org.x.editor.plugins active-plugins "$SAVED_PLUGINS"
    current="$(gsettings get org.x.editor.plugins active-plugins)"
    if [ "$current" != "$SAVED_PLUGINS" ]; then
      echo "FAILED TO RESTORE org.x.editor.plugins active-plugins:" >&2
      echo "  wanted: $SAVED_PLUGINS" >&2
      echo "  got:    $current" >&2
    fi
  fi
  echo "Transcript kept at: $WORKDIR"
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
# row-96 (the mode switch) is deliberately absent -- it is measured to be
# silent, and Task 4 decides whether that becomes an expectation or a fix.
PYTHONPATH="$ROOT/tests/unit" python3 - "$WORKDIR/transcript.json" <<'PY'
import json
import sys

from orca_transcript import missing

ROWS = {
    "row-98-preview-scroll": ["Scroll Test"],
    "row-101-external-change": ["changed on disk"],
}

with open(sys.argv[1], encoding="utf-8") as handle:
    sliced = json.load(handle)

failed = False
for row, expected in ROWS.items():
    spoken = sliced.get(row)
    if spoken is None:
        print(f"FAIL {row} - no such marker in the transcript")
        failed = True
        continue
    if not spoken:
        # Silence is a finding, not a pass: a11y.check_tree's rule.
        print(f"FAIL {row} - Orca said nothing at all")
        failed = True
        continue
    absent = missing(spoken, expected)
    if absent:
        print(f"FAIL {row} - never said: {absent} (said: {spoken})")
        failed = True
    else:
        print(f"PASS {row} - {expected}")

sys.exit(1 if failed else 0)
PY
ASSERT_RC=$?

if [ "$ASSERT_RC" -ne 0 ]; then
  echo "Orca tests FAILED" >&2
  exit 1
fi
echo "Orca tests passed"
