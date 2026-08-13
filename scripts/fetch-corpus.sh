#!/usr/bin/env bash
# Fetch the compatibility-audit corpus. Dev-only: needs the network, and
# nothing it writes is committed (see .gitignore).
#
# Each entry is pinned to a commit SHA rather than a branch, and the SHA is
# recorded in MANIFEST.json, so re-running this months later produces the
# same bytes and the audit stays reproducible.
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

resolve_sha() {
  local repo="$1" ref="$2"
  if [ "$SHA_METHOD" = "gh" ]; then
    gh api "repos/$repo/commits/$ref" --jq '.sha' 2>/dev/null || true
  else
    curl -fsSL \
      "https://api.github.com/repos/$repo/commits/$ref" \
      -H "Accept: application/vnd.github.sha" || true
  fi
}

printf '[\n' > "$MANIFEST"
first=1

for entry in "${ENTRIES[@]}"; do
  IFS='|' read -r name stratum repo ref path <<< "$entry"

  # Resolve the ref to an immutable SHA so the manifest pins bytes, not a
  # moving branch.
  sha="$(resolve_sha "$repo" "$ref")"
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
  [ "$first" -eq 1 ] || printf ',\n' >> "$MANIFEST"
  first=0
  printf '  {"name": "%s", "stratum": "%s", "url": "%s", "sha": "%s", "bytes": %s}' \
    "$name" "$stratum" "$url" "$sha" "$bytes" >> "$MANIFEST"
  echo "OK   $name  ($bytes bytes)"
done

printf '\n]\n' >> "$MANIFEST"
echo
echo "Corpus written to $CORPUS"
echo "Manifest: $MANIFEST"
