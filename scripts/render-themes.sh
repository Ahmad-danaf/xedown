#!/usr/bin/env bash
# Renders every fixture in every theme, light and dark, plus the extremes of
# content width and text size, through the real render_document -- the same
# function the preview uses -- so appearance can be reviewed in a browser
# without installing the plugin and launching xed.
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

from xedown import renderer, settings as xedown_settings, stylesheets, themes  # noqa: E402

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

# The extremes, so "no combination scrolls the page sideways" and "the
# hierarchy survives at every size" get looked at rather than asserted.
width = xedown_settings.by_name(xedown_settings.CONTENT_WIDTH_REM)
size = xedown_settings.by_name(xedown_settings.TEXT_SIZE_PX)
fixture = root / "tests" / "fixtures" / "showcase.md"
for w in (width.minimum, width.default, width.maximum):
    for s in (size.minimum, size.default, size.maximum):
        name = f"metrics-{w:g}rem-{s:g}px.html"
        (out / name).write_text(
            renderer.render_document(
                fixture.read_text(encoding="utf-8"),
                base_dir=str(fixture.parent),
                style=stylesheets.PreviewStyle(content_width_rem=w, text_size_px=s),
            ),
            encoding="utf-8",
        )
        rows.append(f'<li><a href="{name}">{name}</a></li>')

# The three ways a blocked or missing image can be presented, so all three
# get looked at in every theme rather than asserted.
edge = root / "tests" / "fixtures" / "edge-cases.md"
for display in ("placeholder", "alt", "hidden"):
    for theme in themes.THEMES:
        name = f"images-{display}-{theme.identifier}.html"
        (out / name).write_text(
            renderer.render_document(
                edge.read_text(encoding="utf-8"),
                base_dir=str(edge.parent),
                dark=False,
                style=stylesheets.PreviewStyle(theme=theme.identifier),
                image_display=display,
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
