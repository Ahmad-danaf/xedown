#!/usr/bin/env bash
# Drives a real xed instance through the scenarios CI cannot reach.
# Requires xed and an X display. Restores your plugin settings on exit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_DIR="$HOME/.local/share/xed/plugins"
WORKDIR="$(mktemp -d)"
REPORT="$WORKDIR/report.txt"
SAMPLE="$WORKDIR/sample.md"
XED_LOG="$WORKDIR/xed.log"
SAVED_PLUGINS=""
XED_PID=""

# How long to wait for the scripted sequence to reach "PASS done" or a FAIL
# line before giving up on it. It normally finishes in well under a minute:
# async WebView loads, gsettings round trips, a second window for the
# move-tab check, tab creation/teardown. How long to then wait for a
# *graceful* shutdown, once requested, before escalating to SIGTERM/SIGKILL.
SEQUENCE_TIMEOUT_SECONDS=90
SHUTDOWN_GRACE_SECONDS=10

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "No display available. These tests need a running desktop session." >&2
  exit 1
fi

if pgrep -x xed >/dev/null 2>&1; then
  echo "xed is already running. Close it first — the harness drives its own instance." >&2
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
  rm -rf "$PLUGIN_DIR/xedown_probe" "$PLUGIN_DIR/xedown_probe.plugin"
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
cp -r "$ROOT/plugin/xedown" "$ROOT/plugin/xedown.plugin" "$PLUGIN_DIR/"
cp -r "$ROOT/tests/integration/xedown_probe" \
      "$ROOT/tests/integration/xedown_probe.plugin" "$PLUGIN_DIR/"

printf '# Sample\n\nText with **bold**.\n\n- [ ] task\n' > "$SAMPLE"

SAVED_PLUGINS="$(gsettings get org.x.editor.plugins active-plugins)"
gsettings set org.x.editor.plugins active-plugins "['xedown', 'xedown_probe']"

echo "==> Launching xed under the probe"
# XEDOWN_PROBE_TMPDIR nests the probe's own fixture files under $WORKDIR, so
# the single rm -rf at the bottom of a clean run cleans those up too instead
# of leaving an "xedown-probe-*" directory behind under /tmp every time.
XEDOWN_PROBE_REPORT="$REPORT" XEDOWN_PROBE_TMPDIR="$WORKDIR" \
  xed --new-window "$SAMPLE" > "$XED_LOG" 2>&1 &
XED_PID=$!

echo "==> Waiting for the scripted sequence to finish (pid $XED_PID)"
SEQUENCE_DONE=0
for ((i = 0; i < SEQUENCE_TIMEOUT_SECONDS * 2; i++)); do
  if [ -f "$REPORT" ] && grep -qE '^(PASS done|FAIL)' "$REPORT"; then
    SEQUENCE_DONE=1
    break
  fi
  if ! kill -0 "$XED_PID" 2>/dev/null; then
    echo "xed exited on its own before the sequence finished." >&2
    break
  fi
  sleep 0.5
done

if [ "$SEQUENCE_DONE" -eq 0 ]; then
  echo "The scripted sequence did not reach a conclusion within ${SEQUENCE_TIMEOUT_SECONDS}s." >&2
fi

# Close gracefully from here, not from inside a plugin callback (that
# segfaults xed): ask the window manager to close every window belonging to
# this xed process, the same request a user's click on the window's close
# button sends, so xed goes through its normal shutdown and plugin-unload
# path. A hard timeout-driven SIGKILL can never observe that path -- it was
# why every earlier version of this script ended with the log stopping dead
# at the last "PROBE:" line and burning the full timeout regardless of how
# long the scripted sequence actually took.
SHUTDOWN_CAPTURED=0
if kill -0 "$XED_PID" 2>/dev/null; then
  if command -v wmctrl >/dev/null 2>&1; then
    echo "==> Closing xed's window(s) gracefully (pid $XED_PID)"
    # One at a time, waiting for each to actually go away before asking for
    # the next -- the way a real user closes windows. This does NOT avoid
    # the gtk_action_group_get_action Gtk-CRITICAL handled by the allowlist
    # below (confirmed: it still occurs closing one window at a time, and
    # even with only one window open) -- that turned out to be a xed-core
    # bug triggered by the move-tab-then-switch-tabs sequence itself, not a
    # simultaneous-close race. Sequential closing is kept anyway because
    # it is the more realistic thing to test and the safer default.
    while :; do
      WINDOW_IDS="$(wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" '$3 == pid {print $1}')"
      [ -n "$WINDOW_IDS" ] || break
      WIN="$(echo "$WINDOW_IDS" | head -n1)"
      wmctrl -ic "$WIN" || true
      CLOSED=0
      for ((i = 0; i < SHUTDOWN_GRACE_SECONDS * 2; i++)); do
        REMAINING="$(wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" -v win="$WIN" '$1 == win && $3 == pid')"
        if [ -z "$REMAINING" ]; then
          CLOSED=1
          break
        fi
        if ! kill -0 "$XED_PID" 2>/dev/null; then
          CLOSED=1
          break
        fi
        sleep 0.5
      done
      if [ "$CLOSED" -eq 0 ]; then
        echo "Window $WIN did not close within ${SHUTDOWN_GRACE_SECONDS}s." >&2
        break
      fi
    done
    if ! kill -0 "$XED_PID" 2>/dev/null; then
      SHUTDOWN_CAPTURED=1
    elif [ -z "$(wmctrl -lp 2>/dev/null | awk -v pid="$XED_PID" '$3 == pid')" ]; then
      # All windows gone but the process (WebKit helper teardown, etc.) may
      # still be exiting -- give it the same grace period once more.
      for ((i = 0; i < SHUTDOWN_GRACE_SECONDS * 2; i++)); do
        if ! kill -0 "$XED_PID" 2>/dev/null; then
          SHUTDOWN_CAPTURED=1
          break
        fi
        sleep 0.5
      done
    else
      echo "wmctrl found no window for pid $XED_PID; cannot request a graceful close." >&2
    fi
  else
    echo "wmctrl is not installed; cannot request a graceful window close." >&2
  fi

  if [ "$SHUTDOWN_CAPTURED" -eq 0 ] && kill -0 "$XED_PID" 2>/dev/null; then
    echo "Falling back to SIGTERM (xed may not capture its own shutdown log this way)." >&2
    kill -TERM "$XED_PID" 2>/dev/null || true
    for ((i = 0; i < SHUTDOWN_GRACE_SECONDS * 2; i++)); do
      if ! kill -0 "$XED_PID" 2>/dev/null; then
        break
      fi
      sleep 0.5
    done
  fi
else
  # xed already exited by itself (e.g. crashed, or the sequence killed it
  # some other way). Nothing to close.
  SHUTDOWN_CAPTURED=1
fi

if kill -0 "$XED_PID" 2>/dev/null; then
  echo "xed did not exit after a graceful close request; killing it." >&2
  kill -KILL "$XED_PID" 2>/dev/null || true
fi
wait "$XED_PID" 2>/dev/null || true

if [ "$SHUTDOWN_CAPTURED" -eq 0 ]; then
  echo "NOTE: shutdown output was not reliably captured this run (see the warning(s) above)." >&2
  echo "      xed.log covers the scripted sequence but may be missing window-close /" >&2
  echo "      plugin-unload output. Re-run with wmctrl installed for full coverage, or" >&2
  echo "      check docs/manual-smoke-test.md row 24 (terminal review) by hand." >&2
fi

if [ ! -f "$REPORT" ]; then
  echo "FAIL: the probe produced no report. xed log:" >&2
  cat "$XED_LOG" >&2
  exit 1
fi

echo
cat "$REPORT"
echo

STATUS=0

if grep -q '^FAIL' "$REPORT"; then
  echo "Integration tests FAILED" >&2
  STATUS=1
fi
if ! grep -q '^PASS done' "$REPORT"; then
  echo "Integration tests did not run to completion" >&2
  STATUS=1
fi

# Structural assertions live in the probe report above. Two checks can only
# be observed from outside the plugin process: that nothing warns and that
# no traceback reaches stderr (a regressed set_info_bar(None) call, a
# teardown exception on a quickly-closed or quickly-moved tab, and so on).
# xed's own stderr is captured whole in $XED_LOG, so check it here instead
# of trying to hook GLib's structured logging from inside the embedded
# interpreter. Since the window is now closed gracefully above rather than
# hard-killed, this also covers window-close and plugin-unload output when
# SHUTDOWN_CAPTURED=1, not just the scripted sequence itself.
#
# One single, precisely-named exception: a confirmed xed 3.8.9 core bug
# (not xedown's) that fires after this exact sequence -- a tab moved to
# another window, then an active-tab switch away from and back to a
# different tab in the original window, then window close. Reproduced with
# xedown completely uninstalled (not just disabled): the identical
# assertion appears from a plugin that only calls Xed/Gtk/Gio APIs
# directly and never references xedown. That is reproducible on demand,
# rather than being a claim you have to take on trust:
#   XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab
# runs the same scenario with xedown absent from the plugin directory
# entirely, and still prints this assertion. The window
# still closes cleanly either way -- this is a loud assertion, not a hang
# or a crash. This allowlist is intentionally ONE exact string: it must
# never grow into a general relaxation, and any other CRITICAL, WARNING,
# Traceback or segfault -- including a *different* assertion inside the
# same gtk_action_group_get_action call -- still fails the run below.
#
# Anchored end to end (^...$) so it matches a whole log line and nothing
# else: an unanchored substring would also have swallowed a second warning
# printed on the same line, or the same assertion raised at a different log
# level. scripts/run-shutdown-tests.sh carries this pattern verbatim, and
# tests/unit/test_shutdown_allowlist.py fails if the two ever drift apart
# or if the pattern starts admitting anything beyond this one line.
KNOWN_XED_CORE_ASSERTION="^\(xed:[0-9]+\): Gtk-CRITICAL \*\*: [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP \(action_group\)' failed$"

BAD_PATTERN='(CRITICAL \*\*|WARNING \*\*|ERROR \*\*|Traceback \(most recent|Segmentation fault|\*\*\* stack smashing|core dumped)'

ALL_MATCHES="$(grep -E "$BAD_PATTERN" "$XED_LOG" || true)"
UNEXPECTED="$(printf '%s\n' "$ALL_MATCHES" | grep -Ev "$KNOWN_XED_CORE_ASSERTION" | grep -Ev '^$' || true)"

if [ -n "$UNEXPECTED" ]; then
  echo "Integration tests FAILED: xed's log contains a warning, critical or traceback:" >&2
  printf '%s\n' "$UNEXPECTED" >&2
  STATUS=1
elif printf '%s\n' "$ALL_MATCHES" | grep -qE "$KNOWN_XED_CORE_ASSERTION"; then
  echo "NOTE: xed's log contains the known xed-core gtk_action_group_get_action" >&2
  echo "      assertion at shutdown, confirmed unrelated to xedown (reproduced with" >&2
  echo "      xedown completely uninstalled -- see docs/known-issues.md, and" >&2
  echo "      XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab to see it" >&2
  echo "      section). Not treated as a failure." >&2
fi

if [ "$STATUS" -ne 0 ]; then
  echo "Full xed log: $XED_LOG (kept for inspection)" >&2
  exit 1
fi

# Only clean up the workdir (report/log/probe fixtures) on a clean pass --
# a failure keeps it around for inspection, per the message above.
rm -rf "$WORKDIR"

echo "Integration tests passed"
