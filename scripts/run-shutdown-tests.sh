#!/usr/bin/env bash
# Verifies that xed shuts down cleanly after each of six scenarios.
#
# scripts/run-integration-tests.sh runs one long sequence, so it can only
# ever observe one shutdown -- and since that sequence disables the plugin
# near the end, the shutdown it observes is one where xedown is no longer
# active. This script covers the shutdown paths that leaves out: each
# scenario gets its own xed launch, is left in its own end state, and is
# then closed the way a user closes a window (a real window-manager close
# request, never a signal, so xed runs its normal shutdown and plugin-unload
# path). Every scenario's stderr is checked independently.
#
# Usage:
#   scripts/run-shutdown-tests.sh                 # all scenarios
#   scripts/run-shutdown-tests.sh close-tab       # one or more by name
#   XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab
#       ^ runs WITHOUT xedown installed at all, to establish whether a given
#         message comes from xed itself. This is the evidence the single
#         allowlisted assertion below depends on; re-run it whenever that
#         allowlist is questioned. xedown is reinstalled from the working
#         tree on the way out either way, so this never leaves the editor
#         configured to load a plugin that is no longer on disk.
#
#   XEDOWN_INSTALL_FROM_ARCHIVE=dist/xedown-0.1.0.tar.gz scripts/run-shutdown-tests.sh
#       ^ installs the release archive instead of the working tree, so the
#         thing being tested is the artifact users download. Build it with
#         scripts/build-release.sh first.
#
# Other knobs, all for investigating a failure rather than everyday use:
#   XEDOWN_KEEP_LOGS=1              keep each scenario's xed.log on success
#   XEDOWN_SHUTDOWN_GRACE_SECONDS=N how long a window may take to close (15)
#   XEDOWN_CLOSE_RESEND_SECONDS=N   how often to re-send the close request
#                                   (3; 0 sends it exactly once)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$HOME/.local/share/xed/plugins"
WORKDIR="$(mktemp -d)"
SAVED_PLUGINS=""
XED_PID=""
CONTROL="${XEDOWN_CONTROL:-0}"

READY_TIMEOUT_SECONDS=90
SHUTDOWN_GRACE_SECONDS="${XEDOWN_SHUTDOWN_GRACE_SECONDS:-15}"
# How often to re-send the window-close request while waiting; 0 sends it
# exactly once (see the comment at the send site).
RESEND_TICKS=$(( ${XEDOWN_CLOSE_RESEND_SECONDS:-3} * 2 ))

ALL_SCENARIOS=(
  close-tab
  close-many-tabs
  multi-window
  move-tab
  disable-plugin
  preview-active
)

if [ "$#" -gt 0 ]; then
  SCENARIOS=("$@")
else
  SCENARIOS=("${ALL_SCENARIOS[@]}")
fi

# The one and only allowlisted message. Anchored end to end on purpose: it
# matches a whole log line and nothing else, so it cannot swallow a second
# warning printed on the same line, a different assertion inside the same
# gtk_action_group_get_action call, or the same assertion raised at a
# different log level. A confirmed xed 3.8.9 core bug -- reproduced with
# xedown not installed at all, which is what XEDOWN_CONTROL=1 above exists
# to re-demonstrate on demand. Do not widen this pattern. If a new message
# appears, it is a release blocker until proven otherwise by a control run.
KNOWN_XED_CORE_ASSERTION="^\(xed:[0-9]+\): Gtk-CRITICAL \*\*: [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP \(action_group\)' failed$"

# Anything matching this is a release blocker unless it is the line above.
BAD_PATTERN='(CRITICAL \*\*|WARNING \*\*|ERROR \*\*|Traceback \(most recent|Segmentation fault|\*\*\* stack smashing|core dumped)'

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "No display available. These tests need a running desktop session." >&2
  exit 1
fi

if pgrep -x xed >/dev/null 2>&1; then
  echo "xed is already running. Close it first — the harness drives its own instance." >&2
  exit 1
fi

if ! command -v wmctrl >/dev/null 2>&1; then
  echo "wmctrl is required: it is how this harness asks xed to close the way a" >&2
  echo "user does. Without it no shutdown output can be captured at all." >&2
  exit 1
fi

cleanup() {
  local restore_failed=0
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
  rm -rf "$PLUGIN_DIR/xedown_shutdown_probe" \
         "$PLUGIN_DIR/xedown_shutdown_probe.plugin"
  # A control run deliberately uninstalls xedown. Put it back unconditionally:
  # active-plugins still lists xedown (it is restored just above), so leaving
  # the directory missing would hand back an editor configured to load a
  # plugin that is no longer on disk.
  rm -rf "$PLUGIN_DIR/xedown" "$PLUGIN_DIR/xedown.plugin"
  cp -r "$ROOT/plugin/xedown" "$ROOT/plugin/xedown.plugin" "$PLUGIN_DIR/"
  if [ -n "$XED_PID" ] && kill -0 "$XED_PID" 2>/dev/null; then
    echo "xed (pid $XED_PID) is still running at exit; killing it." >&2
    kill -KILL "$XED_PID" 2>/dev/null || true
  fi
  if [ "$restore_failed" -ne 0 ]; then
    exit 1
  fi
}
trap cleanup EXIT

mkdir -p "$PLUGIN_DIR"
rm -rf "$PLUGIN_DIR/xedown" "$PLUGIN_DIR/xedown.plugin"
# Always re-copy: an edited working tree with a stale installed copy silently
# tests the wrong code, which has bitten this project before.
if [ "$CONTROL" = "1" ]; then
  echo "### CONTROL RUN: xedown is NOT installed for these scenarios ###"
elif [ -n "${XEDOWN_INSTALL_FROM_ARCHIVE:-}" ]; then
  # Test the artifact users actually download, not the working tree it was
  # built from. The two are supposed to be identical; this is how you find
  # out when they are not.
  if [ ! -f "$XEDOWN_INSTALL_FROM_ARCHIVE" ]; then
    echo "No such archive: $XEDOWN_INSTALL_FROM_ARCHIVE" >&2
    exit 1
  fi
  echo "### Installing from release archive: $XEDOWN_INSTALL_FROM_ARCHIVE ###"
  tar -xzf "$XEDOWN_INSTALL_FROM_ARCHIVE" -C "$PLUGIN_DIR"
  if [ ! -f "$PLUGIN_DIR/xedown.plugin" ] || [ ! -d "$PLUGIN_DIR/xedown" ]; then
    echo "That archive did not unpack into a usable plugin." >&2
    exit 1
  fi
else
  cp -r "$ROOT/plugin/xedown" "$ROOT/plugin/xedown.plugin" "$PLUGIN_DIR/"
fi
rm -rf "$PLUGIN_DIR/xedown_shutdown_probe" "$PLUGIN_DIR/xedown_shutdown_probe.plugin"
cp -r "$ROOT/tests/integration/xedown_shutdown_probe" \
      "$ROOT/tests/integration/xedown_shutdown_probe.plugin" "$PLUGIN_DIR/"

SAVED_PLUGINS="$(gsettings get org.x.editor.plugins active-plugins)"

STATUS=0
declare -a SUMMARY=()

run_scenario() {
  local scenario="$1"
  local dir="$WORKDIR/$scenario"
  local report="$dir/report.txt"
  local log="$dir/xed.log"
  local sample="$dir/main.md"

  mkdir -p "$dir"
  printf '# %s\n\nOpening document for the %s scenario.\n' "$scenario" "$scenario" > "$sample"

  if [ "$CONTROL" = "1" ]; then
    gsettings set org.x.editor.plugins active-plugins "['xedown_shutdown_probe']"
  else
    gsettings set org.x.editor.plugins active-plugins "['xedown', 'xedown_shutdown_probe']"
  fi

  echo
  echo "=============================================================="
  echo "SCENARIO: $scenario"
  echo "=============================================================="

  XEDOWN_SHUTDOWN_SCENARIO="$scenario" \
  XEDOWN_SHUTDOWN_REPORT="$report" \
  XEDOWN_SHUTDOWN_TMPDIR="$dir" \
  XEDOWN_SHUTDOWN_CONTROL="$([ "$CONTROL" = "1" ] && echo 1 || echo 0)" \
    xed --new-window "$sample" > "$log" 2>&1 &
  XED_PID=$!

  local ready=0
  for ((i = 0; i < READY_TIMEOUT_SECONDS * 2; i++)); do
    if [ -f "$report" ] && grep -qE '^(READY|FAILED)' "$report"; then
      ready=1
      break
    fi
    if ! kill -0 "$XED_PID" 2>/dev/null; then
      echo "xed exited on its own before the scenario was set up." >&2
      break
    fi
    sleep 0.5
  done

  if [ "$ready" -eq 0 ]; then
    echo "FAIL [$scenario]: setup did not complete within ${READY_TIMEOUT_SECONDS}s." >&2
    STATUS=1
  fi

  if [ -f "$report" ]; then
    cat "$report"
  fi

  # Close every window this process owns, one at a time, waiting for each --
  # the way a user closes windows, and the only way xed's own shutdown and
  # plugin-unload output gets produced at all.
  local shutdown_captured=0
  if kill -0 "$XED_PID" 2>/dev/null; then
    echo "--> closing window(s) gracefully"
    while :; do
      local ids win remaining closed
      ids="$(wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" '$3 == pid {print $1}')"
      [ -n "$ids" ] || break
      win="$(echo "$ids" | head -n1)"
      closed=0
      for ((i = 0; i < SHUTDOWN_GRACE_SECONDS * 2; i++)); do
        # Re-send periodically rather than once. A single _NET_CLOSE_WINDOW
        # that lands while the window is still settling is simply dropped,
        # and waiting on a request nobody is going to answer looks exactly
        # like a hang in the application. A user clicks the close button
        # again; this is the same thing. A window that keeps ignoring
        # repeated requests really is stuck, which is what the failure
        # below means.
        #
        # XEDOWN_CLOSE_RESEND_SECONDS=0 restores the old send-once
        # behaviour. That exists so this can be A/B tested against a
        # control run: masking a genuine shutdown hang behind a retry would
        # be far worse than the flake it was introduced to remove.
        if ((i == 0 || (RESEND_TICKS > 0 && i % RESEND_TICKS == 0))); then
          wmctrl -ic "$win" || true
        fi
        remaining="$(wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" -v w="$win" '$1 == w && $3 == pid')"
        if [ -z "$remaining" ] || ! kill -0 "$XED_PID" 2>/dev/null; then
          closed=1
          break
        fi
        sleep 0.5
      done
      if [ "$closed" -eq 0 ]; then
        echo "FAIL [$scenario]: window $win did not close within ${SHUTDOWN_GRACE_SECONDS}s." >&2
        echo "    windows still owned by pid $XED_PID:" >&2
        wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" '$3 == pid' | sed 's/^/      /' >&2
        echo "    process state:" >&2
        ps -o pid,stat,wchan:20,etime,comm -p "$XED_PID" 2>/dev/null | sed 's/^/      /' >&2
        STATUS=1
        break
      fi
    done
    for ((i = 0; i < SHUTDOWN_GRACE_SECONDS * 2; i++)); do
      if ! kill -0 "$XED_PID" 2>/dev/null; then
        shutdown_captured=1
        break
      fi
      sleep 0.5
    done
  else
    shutdown_captured=1
  fi

  if kill -0 "$XED_PID" 2>/dev/null; then
    echo "FAIL [$scenario]: xed did not exit after every window was closed; killing." >&2
    kill -KILL "$XED_PID" 2>/dev/null || true
    STATUS=1
  fi
  wait "$XED_PID" 2>/dev/null || true
  XED_PID=""

  # --- the actual check -------------------------------------------------
  local scenario_status="clean"

  # Order matters: a scenario whose shutdown was never observed has NOT been
  # shown to shut down cleanly, and must not be summarised as if it had. An
  # empty log is the expected reading of a killed process, so "no warnings
  # found" here means nothing at all.
  if [ "$shutdown_captured" -eq 0 ]; then
    echo "FAIL [$scenario]: shutdown output was not captured; nothing below is trustworthy." >&2
    STATUS=1
    scenario_status="NOT OBSERVED"
  fi

  if [ ! -f "$report" ] || ! grep -q '^READY' "$report"; then
    echo "FAIL [$scenario]: the probe did not report READY." >&2
    STATUS=1
    scenario_status="setup-failed"
  fi

  local matches unexpected
  matches="$(grep -E "$BAD_PATTERN" "$log" || true)"
  unexpected="$(printf '%s\n' "$matches" | grep -Ev "$KNOWN_XED_CORE_ASSERTION" | grep -Ev '^$' || true)"

  if [ -n "$unexpected" ]; then
    echo "FAIL [$scenario]: xed's log contains output that blocks the release:" >&2
    printf '%s\n' "$unexpected" | sed 's/^/    /' >&2
    echo "    (full log: $log)" >&2
    STATUS=1
    scenario_status="BLOCKER"
  elif [ -n "$matches" ]; then
    echo "NOTE [$scenario]: only the known xed-core assertion appeared:" >&2
    printf '%s\n' "$matches" | sed 's/^/    /' >&2
    if [ "$scenario_status" = "clean" ]; then
      scenario_status="clean (known xed assertion)"
    fi
  elif [ "$scenario_status" = "clean" ]; then
    echo "OK [$scenario]: no warnings, criticals, tracebacks or crashes."
  fi

  SUMMARY+=("$(printf '%-18s %s' "$scenario" "$scenario_status")")
}

for scenario in "${SCENARIOS[@]}"; do
  run_scenario "$scenario"
done

echo
echo "=============================================================="
echo "SUMMARY$([ "$CONTROL" = "1" ] && echo "  (CONTROL RUN — xedown not installed)")"
echo "=============================================================="
for line in "${SUMMARY[@]}"; do
  echo "  $line"
done
echo

if [ "$STATUS" -ne 0 ]; then
  echo "Shutdown tests FAILED. Logs kept under: $WORKDIR" >&2
  exit 1
fi

if [ "${XEDOWN_KEEP_LOGS:-0}" = "1" ]; then
  echo "Logs kept under: $WORKDIR"
  exit 0
fi

rm -rf "$WORKDIR"
echo "Shutdown tests passed."
