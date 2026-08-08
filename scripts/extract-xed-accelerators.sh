#!/usr/bin/env bash
# Re-extract xed's own keyboard accelerators from the INSTALLED application.
#
# Brief 8 requires xedown's four shortcuts to be checked against xed's real
# list rather than an assumed one. This reads that list out of the binaries on
# this machine and writes tests/fixtures/xed-accelerators.json, which
# tests/unit/test_shortcuts.py holds xedown to in CI, where no xed exists.
# Run it again after upgrading xed.
#
# Two sources, because xed uses both: the accelerator strings its GtkActionEntry
# tables carry, and the GtkShortcutsWindow definition embedded beside them.
set -euo pipefail

cd "$(dirname "$0")/.."

OUT="tests/fixtures/xed-accelerators.json"

command -v strings >/dev/null || {
  echo "extract-xed-accelerators: 'strings' is missing (install binutils)" >&2
  exit 1
}

LIB=""
for candidate in /usr/lib/*/xed/libxed.so /usr/lib/xed/libxed.so; do
  if [ -f "$candidate" ]; then
    LIB="$candidate"
    break
  fi
done
if [ -z "$LIB" ]; then
  echo "extract-xed-accelerators: no installed libxed.so found" >&2
  exit 1
fi

PLUGIN_DIR="$(dirname "$LIB")/plugins"
VERSION="$(xed --version | head -n 1)"

# The filter script lives in its own temp file rather than a heredoc on the
# same command as the pipe below: `producer | python3 - <<PY ... PY` lets the
# heredoc redirect win over the piped stdin, so the script would run with an
# already-exhausted stdin and silently extract nothing.
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat >"$WORK/extract.py" <<'PY'
import html
import json
import re
import sys

version, out = sys.argv[1], sys.argv[2]

# A whole line that is nothing but an accelerator: how a GtkActionEntry's
# accel reaches the binary's string table.
BARE = re.compile(r"^<[A-Za-z]+>(?:<[A-Za-z]+>)*[A-Za-z0-9_]+$")
# The embedded GtkShortcutsWindow arrives as one enormous line of XML.
IN_XML = re.compile(r'name="accelerator">(.*?)<')

found = set()
for line in sys.stdin:
    line = line.strip()
    if BARE.match(line):
        found.add(line)
    for candidate in IN_XML.findall(line):
        candidate = html.unescape(candidate).strip()
        if candidate:
            found.add(candidate)

# `<alt>%d` is the runtime template xed binds Alt+1..Alt+9 from, and
# `<Alt>1...9` is how its shortcuts window writes the same thing for a human
# reader. Both are expanded rather than stored, so what the test compares
# against is a list of accelerators that actually exist. This is the only
# transformation this script makes.
accelerators = set()
for accel in found:
    if accel in ("<alt>%d", "<Alt>1...9"):
        accelerators.update(f"<alt>{digit}" for digit in range(1, 10))
    elif "%" in accel:
        continue
    else:
        accelerators.add(accel)

payload = {
    "xed_version": version,
    "extracted_from": ["libxed.so", "xed/plugins"],
    "accelerators": sorted(accelerators),
}
with open(out, "w", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, indent=2) + "\n")
print(f"{out}: {len(payload['accelerators'])} accelerators from {version}")
PY

{
  strings -a "$LIB"
  if [ -d "$PLUGIN_DIR" ]; then
    strings -a "$PLUGIN_DIR"/*.so 2>/dev/null || true
    grep -rhoiE \
      '<(ctrl|control|primary|shift|alt|super|mod1)>(<(ctrl|control|primary|shift|alt|super|mod1)>)*[A-Za-z0-9_]+' \
      "$PLUGIN_DIR" 2>/dev/null || true
  fi
} | python3 "$WORK/extract.py" "$VERSION" "$OUT"
