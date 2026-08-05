#!/usr/bin/env bash
# Re-vendor third-party dependencies. Run from the repository root.
# Requires network, python3 -m pip, and npm. Output is committed to git.
set -euo pipefail

MARKDOWN_VERSION="3.7"
HLJS_VERSION="11.11.1"
ESBUILD_VERSION="0.24.0"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/plugin/xedown/vendor"
RESOURCES="$ROOT/plugin/xedown/resources"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

rm -rf "$VENDOR/markdown" "$VENDOR/licenses" "$VENDOR/highlight.min.js"
mkdir -p "$VENDOR/licenses" "$RESOURCES"

echo "==> Vendoring Python-Markdown $MARKDOWN_VERSION"
python3 -m pip download "Markdown==$MARKDOWN_VERSION" --no-deps -d "$WORK/pip" >/dev/null
unzip -q "$WORK/pip/Markdown-$MARKDOWN_VERSION-py3-none-any.whl" -d "$WORK/md"
cp -r "$WORK/md/markdown" "$VENDOR/markdown"
cp "$WORK/md/Markdown-$MARKDOWN_VERSION.dist-info/LICENSE.md" "$VENDOR/licenses/python-markdown-LICENSE.md"
find "$VENDOR/markdown" -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "==> Building custom highlight.js $HLJS_VERSION"
cd "$WORK"
npm init -y >/dev/null 2>&1
npm install --silent "highlight.js@$HLJS_VERSION" "esbuild@$ESBUILD_VERSION" >/dev/null 2>&1

# Pinned language set. Changing this list is a deliberate release decision.
LANGUAGES="bash c cpp csharp css diff dockerfile go ini java javascript json \
kotlin lua makefile markdown objectivec perl php plaintext python r ruby rust \
scss shell sql swift typescript xml yaml"

{
  echo "import hljs from 'highlight.js/lib/core';"
  i=0
  for lang in $LANGUAGES; do
    echo "import lang$i from 'highlight.js/lib/languages/$lang';"
    i=$((i + 1))
  done
  i=0
  for lang in $LANGUAGES; do
    echo "hljs.registerLanguage('$lang', lang$i);"
    i=$((i + 1))
  done
  echo "export default hljs;"
} > entry.mjs

npx --no-install esbuild entry.mjs --bundle --minify --format=iife \
  --global-name=hljs --outfile="$VENDOR/highlight.min.js" --log-level=warning

cp node_modules/highlight.js/LICENSE "$VENDOR/licenses/highlight.js-LICENSE"
cp node_modules/highlight.js/styles/github.min.css "$RESOURCES/highlight-light.css"
cp node_modules/highlight.js/styles/github-dark.min.css "$RESOURCES/highlight-dark.css"

echo "==> Verifying the bundle registers exactly the pinned languages"
EXPECTED="$(echo $LANGUAGES | tr ' ' '\n' | sort | tr '\n' ' ')"
ACTUAL="$(node -e "
const fs = require('fs');
const g = {};
new Function('globalThis', fs.readFileSync('$VENDOR/highlight.min.js', 'utf8') +
  '; globalThis.__h = hljs;')(g);
const h = g.__h.default || g.__h;
process.stdout.write(h.listLanguages().sort().join(' ') + ' ');
")"
if [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "FAIL: bundled languages do not match the pinned list" >&2
  echo "  expected: $EXPECTED" >&2
  echo "  actual:   $ACTUAL" >&2
  exit 1
fi

echo "==> Done. Update plugin/xedown/vendor/MANIFEST.md and commit the result."
