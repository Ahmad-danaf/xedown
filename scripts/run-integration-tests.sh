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

# Generous: the scripted sequence schedules roughly 25s of deliberate waits
# (async WebView loads, gsettings round trips, tab creation/teardown) on top
# of xed's own startup time. 90s leaves comfortable margin without letting a
# genuinely hung run block forever.
TIMEOUT_SECONDS=90

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "No display available. These tests need a running desktop session." >&2
  exit 1
fi

if pgrep -x xed >/dev/null 2>&1; then
  echo "xed is already running. Close it first — the harness drives its own instance." >&2
  exit 1
fi

cleanup() {
  if [ -n "$SAVED_PLUGINS" ]; then
    gsettings set org.x.editor.plugins active-plugins "$SAVED_PLUGINS"
  fi
  rm -rf "$PLUGIN_DIR/xedown_probe" "$PLUGIN_DIR/xedown_probe.plugin"
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

echo "==> Running xed under the probe (timeout ${TIMEOUT_SECONDS}s)"
XEDOWN_PROBE_REPORT="$REPORT" timeout "$TIMEOUT_SECONDS" xed --new-window "$SAMPLE" \
  > "$XED_LOG" 2>&1 || true

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

# Structural assertions live in the probe report above. Two checks from the
# brief can only be observed from outside the plugin process: that nothing
# warns and that no traceback reaches stderr (a regressed set_info_bar(None)
# call, a teardown exception on a quickly-closed tab, and so on). xed's own
# stderr is captured whole in $XED_LOG, so check it here instead of trying
# to hook GLib's structured logging from inside the embedded interpreter.
if grep -Eq '(CRITICAL \*\*|WARNING \*\*|Traceback \(most recent|Segmentation fault)' "$XED_LOG"; then
  echo "Integration tests FAILED: xed's log contains a warning, critical or traceback:" >&2
  grep -En '(CRITICAL \*\*|WARNING \*\*|Traceback \(most recent|Segmentation fault)' "$XED_LOG" >&2
  STATUS=1
fi

if [ "$STATUS" -ne 0 ]; then
  echo "Full xed log: $XED_LOG (kept for inspection)" >&2
  exit 1
fi

echo "Integration tests passed"
