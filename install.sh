#!/usr/bin/env bash
# Installs xedown into your xed plugins directory.
#
#   ./install.sh                       # from this checkout, or a sibling archive
#   ./install.sh --from xedown-0.3.0.tar.gz
#   ./install.sh --enable              # also switch the plugin on
#   ./install.sh --no-enable           # never ask about switching it on
#   ./install.sh --force               # install despite a failed requirement
#
# This script is deliberately self-contained: it sources nothing and
# hardcodes no path inside the repository, so it can be published next to a
# release archive and work when copied anywhere beside one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/xed/plugins"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xedown"

FROM=""
ENABLE="ask"
FORCE=0
STAGE=""

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from) FROM="${2-}"; [ -n "$FROM" ] || die "--from needs a path"; shift 2 ;;
    --enable) ENABLE="yes"; shift ;;
    --no-enable) ENABLE="no"; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

cleanup() {
  # `if`, not `[ -n "$STAGE" ] && rm -rf "$STAGE"`: this runs as the EXIT
  # trap, and under `set -e` a failing AND-list is itself the trap's exit
  # status, which silently overrides an otherwise-successful script exit.
  if [ -n "$STAGE" ]; then
    rm -rf "$STAGE"
  fi
}
trap cleanup EXIT

# --- where the plugin is coming from -------------------------------------

resolve_source() {
  if [ -n "$FROM" ]; then
    [ -e "$FROM" ] || die "no such file or directory: $FROM"
    printf '%s\n' "$FROM"
    return
  fi
  # A checkout.
  if [ -d "$HERE/plugin/xedown" ] && [ -f "$HERE/plugin/xedown.plugin" ]; then
    printf '%s\n' "$HERE/plugin"
    return
  fi
  # An already-extracted archive sitting beside this script.
  if [ -d "$HERE/xedown" ] && [ -f "$HERE/xedown.plugin" ]; then
    printf '%s\n' "$HERE"
    return
  fi
  # The newest release archive beside this script.
  local newest
  newest="$(ls -1t "$HERE"/xedown-*.tar.gz 2>/dev/null | head -1 || true)"
  if [ -n "$newest" ]; then
    printf '%s\n' "$newest"
    return
  fi
  die "nothing to install. Run this from a xedown checkout, or beside a
       release archive, or pass --from <archive-or-directory>."
}

# --- staging -------------------------------------------------------------
#
# Staged inside the plugins directory, not /tmp, so the final move is a
# rename on the same filesystem rather than a recursive copy that can fail
# halfway. The dot prefix keeps libpeas from reading a half-written tree as
# a plugin: it scans this directory's top level for `.plugin` files, and
# during the move ours is one level down inside a hidden directory.

stage_source() {
  local source="$1"
  mkdir -p "$PLUGIN_DIR"
  STAGE="$(mktemp -d "$PLUGIN_DIR/.xedown-stage-XXXXXX")"
  if [ -d "$source" ]; then
    cp -r "$source/xedown" "$STAGE/" 2>/dev/null \
      || die "$source does not contain a xedown/ directory"
    cp "$source/xedown.plugin" "$STAGE/" 2>/dev/null \
      || die "$source does not contain xedown.plugin"
  else
    tar -xzf "$source" -C "$STAGE" || die "could not extract $source"
  fi
  find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$STAGE" -name '*.py[co]' -delete
}

check_staged() {
  local unexpected
  unexpected="$(find "$STAGE" -mindepth 1 -maxdepth 1 \
                     -not -name 'xedown' -not -name 'xedown.plugin')"
  [ -z "$unexpected" ] || die "unexpected entries alongside the plugin:
$unexpected"
  [ -f "$STAGE/xedown/__init__.py" ] || die "no xedown/__init__.py to install"
  [ -f "$STAGE/xedown.plugin" ] || die "no xedown.plugin to install"

  VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$STAGE/xedown/__init__.py")"
  local descriptor
  descriptor="$(sed -n 's/^Version=\(.*\)$/\1/p' "$STAGE/xedown.plugin")"
  [ -n "$VERSION" ] || die "could not read __version__ from xedown/__init__.py"
  # The same disagreement build-release.sh refuses to build through,
  # refused again here: a hand-assembled directory must not be installed
  # under a version it does not carry.
  [ "$VERSION" = "$descriptor" ] || die "version mismatch — refusing to install:
  xedown/__init__.py: $VERSION
  xedown.plugin:      $descriptor"
}

installed_version() {
  [ -f "$PLUGIN_DIR/xedown/__init__.py" ] || return 0
  sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$PLUGIN_DIR/xedown/__init__.py"
}

# --- installing by replacement, never by merge ---------------------------
#
# Copying over an existing install merges: a module deleted in the new
# version survives as an orphan, and stale bytecode sits beside new source.
# The old tree is moved aside rather than deleted first, so a failure
# halfway leaves a working plugin behind rather than nothing.

install_plugin() {
  local aside="$PLUGIN_DIR/.xedown-previous-$$"
  local restore=0
  if [ -e "$PLUGIN_DIR/xedown" ] || [ -e "$PLUGIN_DIR/xedown.plugin" ]; then
    mkdir -p "$aside"
    # `if` blocks, not `[ -e X ] && mv ...`: under `set -e` an AND-list
    # whose test fails is itself the last command in the list, so a merely
    # absent file would abort the install.
    if [ -e "$PLUGIN_DIR/xedown" ]; then
      mv "$PLUGIN_DIR/xedown" "$aside/"
    fi
    if [ -e "$PLUGIN_DIR/xedown.plugin" ]; then
      mv "$PLUGIN_DIR/xedown.plugin" "$aside/"
    fi
    restore=1
  fi
  if mv "$STAGE/xedown" "$PLUGIN_DIR/" && mv "$STAGE/xedown.plugin" "$PLUGIN_DIR/"; then
    if [ "$restore" = 1 ]; then
      rm -rf "$aside"
    fi
    return 0
  fi
  if [ "$restore" = 1 ]; then
    rm -rf "$PLUGIN_DIR/xedown" "$PLUGIN_DIR/xedown.plugin"
    # Checked, not swallowed: a move-back failure must not be reported to
    # the user as a successful restore, and must not leave the aside copy
    # orphaned with no pointer to where it is.
    local restored=1
    if [ -e "$aside/xedown" ]; then
      mv "$aside/xedown" "$PLUGIN_DIR/" || restored=0
    fi
    if [ -e "$aside/xedown.plugin" ]; then
      mv "$aside/xedown.plugin" "$PLUGIN_DIR/" || restored=0
    fi
    if [ "$restored" = 1 ]; then
      rmdir "$aside" 2>/dev/null || true
      die "install failed; your previous install has been put back"
    fi
    die "install failed, and restoring your previous install also failed.
Your previous install is still sitting in $aside -- move it back by hand:
  mv $aside/xedown $PLUGIN_DIR/xedown
  mv $aside/xedown.plugin $PLUGIN_DIR/xedown.plugin"
  fi
  die "install failed"
}

# --- main ----------------------------------------------------------------

SOURCE="$(resolve_source)"
stage_source "$SOURCE"
check_staged

PREVIOUS="$(installed_version)"
install_plugin

if [ -n "$PREVIOUS" ]; then
  say "Upgraded xedown $PREVIOUS -> $VERSION in $PLUGIN_DIR"
else
  say "Installed xedown $VERSION in $PLUGIN_DIR"
fi
if [ -d "$CONFIG_DIR" ]; then
  say "Your settings in $CONFIG_DIR were not touched."
fi
say "Enable it in xed under Preferences -> Plugins, then tick Xedown."
