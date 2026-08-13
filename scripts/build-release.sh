#!/usr/bin/env bash
# Builds the downloadable release archive and proves it actually works.
#
# The archive extracts straight into a xed plugins directory:
#
#   tar -xzf dist/xedown-<version>.tar.gz -C ~/.local/share/xed/plugins
#
# so it contains exactly two entries at its root -- `xedown/` and
# `xedown.plugin` -- and nothing else. No checkout, no apt, no pip: the
# vendored Markdown library, the highlight.js bundle, the themes and both
# third-party licenses all travel inside `xedown/`.
#
# Building is the easy half. The point of this script is the checks: a
# release that is missing a vendored dependency, or that silently renders
# by borrowing a system Markdown install, would look completely fine to
# whoever built it and fail on the first clean machine it reached. So the
# archive is unpacked into a scratch directory and asked to render a real
# document, with the source tree off sys.path entirely.
#
# Usage:
#   scripts/build-release.sh                # refuses to build a dirty tree
#   scripts/build-release.sh --allow-dirty  # for testing the script itself
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT/dist"
STAGING="$(mktemp -d)"
VERIFY_DIR="$(mktemp -d)"
ALLOW_DIRTY=0

for arg in "$@"; do
  case "$arg" in
    --allow-dirty) ALLOW_DIRTY=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

cleanup() {
  rm -rf "$STAGING" "$VERIFY_DIR"
}
trap cleanup EXIT

# --- version, from one source of truth ----------------------------------
#
# __version__ is the source of truth; the .plugin descriptor is what xed
# actually shows in Preferences. They drift silently and nobody notices
# until a user reports the wrong version, so disagreement is fatal here.

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$ROOT/plugin/xedown/__init__.py")"
PLUGIN_VERSION="$(sed -n 's/^Version=\(.*\)$/\1/p' "$ROOT/plugin/xedown.plugin")"

if [ -z "$VERSION" ]; then
  echo "Could not read __version__ from plugin/xedown/__init__.py" >&2
  exit 1
fi
if [ "$VERSION" != "$PLUGIN_VERSION" ]; then
  echo "Version mismatch — refusing to build:" >&2
  echo "  plugin/xedown/__init__.py: $VERSION" >&2
  echo "  plugin/xedown.plugin:      $PLUGIN_VERSION" >&2
  exit 1
fi

if [ "$ALLOW_DIRTY" -eq 0 ] && [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
  echo "The working tree has uncommitted changes. A release archive built from" >&2
  echo "one cannot be reproduced from any commit, so this is refused by default." >&2
  echo "Commit first, or pass --allow-dirty if you are testing this script." >&2
  exit 1
fi

ARCHIVE="$DIST_DIR/xedown-$VERSION.tar.gz"

echo "==> Building xedown $VERSION"

# --- stage ---------------------------------------------------------------

cp -r "$ROOT/plugin/xedown" "$STAGING/"
cp "$ROOT/plugin/xedown.plugin" "$STAGING/"
# Our own licence travels with the code. It lands inside xedown/ rather than
# at the archive root, because the root IS the user's plugins directory --
# anything left there would litter a directory xedown does not own.
cp "$ROOT/LICENSE" "$STAGING/xedown/LICENSE"

find "$STAGING" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGING" -name '*.py[cod]' -delete

# --- refuse to ship something incomplete ---------------------------------
#
# Each of these is a promise the release makes: no pip step, offline syntax
# highlighting, both third-party licences included. A missing one is a
# broken promise, not a missing nicety.

REQUIRED=(
  # Every module the package imports, gated by
  # tests/unit/test_release_manifest.py rather than by hand: the array had
  # drifted to five of twenty-seven before that test existed.
  "xedown/__init__.py"
  "xedown/a11y.py"
  "xedown/appearance.py"
  "xedown/controller.py"
  "xedown/direction.py"
  "xedown/diskstate.py"
  "xedown/document_state.py"
  "xedown/errors.py"
  "xedown/filewatch.py"
  "xedown/imagefetch.py"
  "xedown/imagelimits.py"
  "xedown/images.py"
  "xedown/imagescheme.py"
  "xedown/links.py"
  "xedown/mdext.py"
  "xedown/modebar.py"
  "xedown/modestore.py"
  "xedown/prefs.py"
  "xedown/prefswindow.py"
  "xedown/preview.py"
  "xedown/remoteimages.py"
  "xedown/renderer.py"
  "xedown/sanitizer.py"
  "xedown/search.py"
  "xedown/searchbar.py"
  "xedown/settings.py"
  "xedown/shortcuts.py"
  "xedown/stylesheets.py"
  "xedown/stylewatcher.py"
  "xedown/themes.py"
  "xedown/vendoring.py"
  "xedown/vendor/MANIFEST.md"
  "xedown/vendor/markdown/__init__.py"
  "xedown/vendor/highlight.min.js"
  "xedown/vendor/licenses/highlight.js-LICENSE"
  "xedown/vendor/licenses/python-markdown-LICENSE.md"
  "xedown/resources/preview.css"
  "xedown/resources/preview.js"
  "xedown/resources/highlight-light.css"
  "xedown/resources/highlight-dark.css"
  "xedown/resources/syntax.css"
  "xedown/resources/themes/repository.css"
  "xedown/resources/themes/focused.css"
  "xedown/resources/themes/minimal.css"
  "xedown/resources/themes/document.css"
  "xedown/LICENSE"
  "xedown.plugin"
)

missing=()
for path in "${REQUIRED[@]}"; do
  [ -e "$STAGING/$path" ] || missing+=("$path")
done
if [ "${#missing[@]}" -ne 0 ]; then
  echo "Refusing to build: the staged archive is missing:" >&2
  printf '  %s\n' "${missing[@]}" >&2
  exit 1
fi

# Nothing of ours that is not the plugin should end up in a user's plugins
# directory. Catches a stray test file or scratch directory added under
# plugin/ without anyone thinking about the release.
UNEXPECTED="$(find "$STAGING" -mindepth 1 -maxdepth 1 -not -name 'xedown' -not -name 'xedown.plugin')"
if [ -n "$UNEXPECTED" ]; then
  echo "Refusing to build: unexpected entries at the archive root:" >&2
  printf '%s\n' "$UNEXPECTED" | sed 's/^/  /' >&2
  exit 1
fi

# --- pack, reproducibly --------------------------------------------------
#
# Same commit in, byte-identical archive out: fixed timestamps taken from
# the commit itself, sorted entries, no owner names, and gzip -n so the
# compressor does not stamp its own mtime into the header.

mkdir -p "$DIST_DIR"
SOURCE_DATE="$(git -C "$ROOT" log -1 --format=%cI 2>/dev/null || echo '2026-01-01T00:00:00+00:00')"

tar --sort=name \
    --mtime="$SOURCE_DATE" \
    --owner=0 --group=0 --numeric-owner \
    --format=gnu \
    -C "$STAGING" -cf - xedown xedown.plugin \
  | gzip -n -9 > "$ARCHIVE"

# --- prove it works on its own -------------------------------------------

echo "==> Verifying the archive renders with nothing else on the path"
echo "    (a 'xed/GTK typelibs unavailable' note below is expected and correct:"
echo "     this check runs outside xed, and the plugin guards those imports)"
tar -xzf "$ARCHIVE" -C "$VERIFY_DIR"

# `-I` empties sys.path of the invoking script's directory and ignores
# PYTHON* environment variables, and the only path added back is the
# extracted archive: if this render succeeds, it succeeded using the
# bundled Markdown library and the bundled resources, because there is
# nothing else it could have used. import_markdown() itself raises if a
# non-bundled Markdown wins the import, so borrowing a system copy fails
# here rather than passing quietly.
python3 -I - "$VERIFY_DIR" <<'PYTHON'
import sys

sys.path.insert(0, sys.argv[1])

from xedown import renderer

page = renderer.render_document(
    "# Release check\n\n"
    "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
    "- [x] task\n- [ ] another\n\n"
    "~~struck~~ and `code`\n\n"
    "```python\nprint('hello')\n```\n",
    base_dir=None,
    nonce="release-verify",
)

from xedown import vendoring

markdown = vendoring.import_markdown()
assert sys.argv[1] in markdown.__file__, markdown.__file__

for needed in ("<table>", "<input", "<del>", 'class="language-python"'):
    assert needed in page, f"missing from rendered output: {needed}"
for broken in ("Cannot render this document", "Installation incomplete"):
    assert broken not in page, f"render fell back to an error page: {broken}"

print(f"    vendored Markdown {markdown.__version__} loaded from the archive")
print(f"    rendered {len(page)} bytes with tables, tasks, strikethrough and highlighting")
PYTHON

# --- report ---------------------------------------------------------------

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
SHA="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
FILES="$(tar -tzf "$ARCHIVE" | wc -l)"

echo
echo "  archive : $ARCHIVE"
echo "  size    : $SIZE ($FILES entries)"
echo "  sha256  : $SHA"
echo
echo "Install with:"
echo "  mkdir -p ~/.local/share/xed/plugins"
echo "  tar -xzf $(basename "$ARCHIVE") -C ~/.local/share/xed/plugins"
