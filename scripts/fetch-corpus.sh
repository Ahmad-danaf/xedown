#!/usr/bin/env bash
# Fetch the compatibility-audit corpus. Dev-only: needs the network. The
# fetched .md files are not committed (see .gitignore); MANIFEST.json is.
#
# ENTRIES below names each project by a branch ref, which is not by itself
# reproducible -- a branch moves. What actually pins the corpus is that an
# entry already recorded in the committed MANIFEST.json has its SHA reused
# outright rather than the ref being re-resolved, so re-running this months
# later fetches the exact same bytes for every entry that has run before.
# Only a name with no manifest record yet resolves its ref fresh.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORPUS="$HERE/tests/compat/corpus"
MANIFEST="$CORPUS/MANIFEST.json"

# name|stratum|owner/repo|ref|path
ENTRIES=(
  "react|mainstream|facebook/react|main|README.md"
  "vue|mainstream|vuejs/core|main|README.md"
  "django|mainstream|django/django|main|README.rst"
  "requests|mainstream|psf/requests|main|README.md"
  "flask|mainstream|pallets/flask|main|README.md"
  "ripgrep|mainstream|BurntSushi/ripgrep|master|README.md"
  "serde|mainstream|serde-rs/serde|master|README.md"
  "tokio|mainstream|tokio-rs/tokio|master|README.md"
  "cobra|mainstream|spf13/cobra|main|README.md"
  "gin|mainstream|gin-gonic/gin|master|README.md"
  "curl|mainstream|curl/curl|master|README.md"
  "redis|mainstream|redis/redis|unstable|README.md"
  "sqlite-wasm|mainstream|sqlite/sqlite-wasm|main|README.md"
  "esbuild|mainstream|evanw/esbuild|main|README.md"
  "ruff|mainstream|astral-sh/ruff|main|README.md"
  "mkdocs|docs|mkdocs/mkdocs|master|README.md"
  "sphinx|docs|sphinx-doc/sphinx|master|README.rst"
  "docusaurus|docs|facebook/docusaurus|main|README.md"
  "mdbook|docs|rust-lang/mdBook|master|README.md"
  "hugo|docs|gohugoio/hugo|master|README.md"
  "awesome-python|awesome|vinta/awesome-python|master|README.md"
  "awesome-go|awesome|avelino/awesome-go|main|README.md"
  "awesome-selfhosted|awesome|awesome-selfhosted/awesome-selfhosted|master|README.md"
  "public-apis|awesome|public-apis/public-apis|master|README.md"
  "hello-algo-zh|nonlatin|krahets/hello-algo|main|README.md"
  "javascript-questions-ar|nonlatin|lydiahallie/javascript-questions|master|ar-AR/README_AR.md"
  "javascript-algorithms-he|nonlatin|trekhleb/javascript-algorithms|master|README.he-IL.md"
  "programming-jp|nonlatin|jwasham/coding-interview-university|main|translations/README-ja.md"
  "free-programming-books|enormous|EbookFoundation/free-programming-books|main|books/free-programming-books-langs.md"
  "build-your-own-x|enormous|codecrafters-io/build-your-own-x|master|README.md"
  "system-design-primer|enormous|donnemartin/system-design-primer|master|README.md"
)

mkdir -p "$CORPUS"

# Resolving each entry's commit SHA costs one GitHub API call. Unauthenticated
# calls to api.github.com are capped at 60/hour, which a 31-entry corpus can
# exhaust in a single run and never survive a re-run. Prefer `gh api`, which
# rides the caller's authenticated 5000/hour quota, and fall back to the
# unauthenticated `curl` form only when `gh` isn't available or isn't logged
# in. The choice is made once, up front, not per entry.
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  SHA_METHOD="gh"
else
  SHA_METHOD="curl"
fi
echo "Resolving commit SHAs via: $SHA_METHOD"
if [ "$SHA_METHOD" = "curl" ]; then
  echo "  (unauthenticated api.github.com is capped at 60 requests/hour;" >&2
  echo "   install and log in to 'gh' to avoid rate-limit failures)" >&2
fi

# MANIFEST.json itself is committed (see .gitignore) precisely so this
# lookup has something to consult: an entry already recorded there pins a
# SHA that re-resolving the ref would not reproduce once a branch has
# moved on, so it is preferred outright and never re-resolved. Only an
# entry with no recorded SHA -- new to ENTRIES -- falls back to asking
# GitHub what the ref currently points at.
declare -A KNOWN_SHA
if [ -f "$MANIFEST" ]; then
  while IFS=$'\t' read -r known_name known_sha; do
    KNOWN_SHA["$known_name"]="$known_sha"
  done < <(python3 -c '
import json, sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        entries = json.load(handle)
except (OSError, json.JSONDecodeError):
    entries = []

for entry in entries:
    print(entry["name"] + "\t" + entry["sha"])
' "$MANIFEST")
fi

resolve_sha() {
  local name="$1" repo="$2" ref="$3"
  if [ -n "${KNOWN_SHA[$name]:-}" ]; then
    echo "${KNOWN_SHA[$name]}"
    return
  fi
  if [ "$SHA_METHOD" = "gh" ]; then
    gh api "repos/$repo/commits/$ref" --jq '.sha' 2>/dev/null || true
  else
    curl -fsSL \
      "https://api.github.com/repos/$repo/commits/$ref" \
      -H "Accept: application/vnd.github.sha" || true
  fi
}

# Written to a temp file and moved into place only once the whole loop has
# finished, so a run interrupted partway (network drop, Ctrl-C) never
# leaves the committed manifest truncated or missing entries the working
# tree's .md files still match.
TMP_MANIFEST="$(mktemp "$CORPUS/manifest.XXXXXX.tmp")"
trap 'rm -f "$TMP_MANIFEST"' EXIT

printf '[\n' > "$TMP_MANIFEST"
first=1

for entry in "${ENTRIES[@]}"; do
  IFS='|' read -r name stratum repo ref path <<< "$entry"

  # Resolve the ref to an immutable SHA so the manifest pins bytes, not a
  # moving branch.
  sha="$(resolve_sha "$name" "$repo" "$ref")"
  if [ -z "$sha" ]; then
    echo "SKIP $name: could not resolve $repo@$ref" >&2
    continue
  fi

  url="https://raw.githubusercontent.com/$repo/$sha/$path"
  if ! curl -fsSL "$url" -o "$CORPUS/$name.md"; then
    echo "SKIP $name: could not fetch $url" >&2
    continue
  fi

  bytes="$(wc -c < "$CORPUS/$name.md" | tr -d ' ')"
  [ "$first" -eq 1 ] || printf ',\n' >> "$TMP_MANIFEST"
  first=0
  printf '  {"name": "%s", "stratum": "%s", "url": "%s", "sha": "%s", "bytes": %s}' \
    "$name" "$stratum" "$url" "$sha" "$bytes" >> "$TMP_MANIFEST"
  echo "OK   $name  ($bytes bytes)"
done

printf '\n]\n' >> "$TMP_MANIFEST"
mv "$TMP_MANIFEST" "$MANIFEST"
trap - EXIT
echo
echo "Corpus written to $CORPUS"
echo "Manifest: $MANIFEST"
