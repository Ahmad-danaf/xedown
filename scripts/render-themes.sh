#!/usr/bin/env bash
# Renders every fixture in every theme, light and dark, through the real
# render_document -- the same function the preview uses -- so a theme can be
# reviewed in a browser without installing the plugin and launching xed.
#
# What it writes is what xed shows, because it is the same code path. It is
# not a substitute for the manual smoke test: GTK, WebKit and the desktop's
# appearance signal are all absent here.
#
# Usage:
#   scripts/render-themes.sh              # writes to a fresh temp directory
#   scripts/render-themes.sh /some/dir    # writes there instead
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$(mktemp -d)}"
mkdir -p "$OUT"

PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

"$PYTHON" - "$ROOT" "$OUT" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(root / "plugin"))

from xedown import renderer, stylesheets, themes  # noqa: E402

rows = []
for fixture in sorted((root / "tests" / "fixtures").glob("*.md")):
    for theme in themes.THEMES:
        for dark in (False, True):
            appearance = "dark" if dark else "light"
            name = f"{fixture.stem}-{theme.identifier}-{appearance}.html"
            (out / name).write_text(
                renderer.render_document(
                    fixture.read_text(encoding="utf-8"),
                    base_dir=str(fixture.parent),
                    dark=dark,
                    style=stylesheets.PreviewStyle(theme=theme.identifier),
                ),
                encoding="utf-8",
            )
            rows.append(f'<li><a href="{name}">{name}</a></li>')

(out / "index.html").write_text(
    "<!DOCTYPE html><meta charset=utf-8><title>xedown themes</title>"
    "<ul>" + "".join(rows) + "</ul>",
    encoding="utf-8",
)
print(out / "index.html")
PY
