#!/usr/bin/env bash
# Installs xedown into your xed plugins directory.
#
#   ./install.sh                       # from this checkout, or a sibling archive
#   ./install.sh --from xedown-1.0.0.tar.gz
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
  sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
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

  STAGED_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$STAGE/xedown/__init__.py")"
  local descriptor
  descriptor="$(sed -n 's/^Version=\(.*\)$/\1/p' "$STAGE/xedown.plugin")"
  [ -n "$STAGED_VERSION" ] || die "could not read __version__ from xedown/__init__.py"
  # The same disagreement build-release.sh refuses to build through,
  # refused again here: a hand-assembled directory must not be installed
  # under a version it does not carry.
  [ "$STAGED_VERSION" = "$descriptor" ] || die "version mismatch — refusing to install:
  xedown/__init__.py: $STAGED_VERSION
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

# --- what this machine actually is ---------------------------------------
#
# Facts are gathered here and judged in `xedown/preflight.py`, which is pure
# Python and therefore reachable by the unit tests -- the same boundary that
# decides where the rest of this project's logic lives.
#
# preflight.py is run as a FILE, not imported as `xedown.preflight`:
# importing the package runs __init__.py, whose gi guard prints a note to
# stderr, and an install is the wrong place for that note.

FACT_NAMES=(python_version has_gi gtk3_typelib webkit41_typelib
            has_xed xed_version distro_id distro_version_id session_type)

probe_facts() {
  fact_python_version="$(python3 -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"

  if python3 -c 'import gi' >/dev/null 2>&1; then
    fact_has_gi=1
    if python3 -c 'import gi; gi.require_version("Gtk", "3.0")' >/dev/null 2>&1
    then fact_gtk3_typelib=1; else fact_gtk3_typelib=0; fi
    if python3 -c 'import gi; gi.require_version("WebKit2", "4.1")' >/dev/null 2>&1
    then fact_webkit41_typelib=1; else fact_webkit41_typelib=0; fi
  else
    fact_has_gi=0
    # Both probes need gi to run, so with gi gone their answer would be a
    # guess dressed as a measurement. Left undetermined on purpose.
    fact_gtk3_typelib=""
    fact_webkit41_typelib=""
  fi

  if command -v xed >/dev/null 2>&1; then
    fact_has_xed=1
    fact_xed_version="$(xed --version 2>/dev/null || true)"
  else
    fact_has_xed=0
    fact_xed_version=""
  fi

  fact_distro_id=""
  fact_distro_version_id=""
  if [ -r /etc/os-release ]; then
    fact_distro_id="$(. /etc/os-release 2>/dev/null && printf '%s' "${ID-}")"
    fact_distro_version_id="$(. /etc/os-release 2>/dev/null && printf '%s' "${VERSION_ID-}")"
  fi

  fact_session_type="${XDG_SESSION_TYPE-}"

  # TEST-ONLY SEAM. `scripts/run-install-tests.sh` sets this to override
  # probed facts, so "the WebKit 4.1 typelib is missing" is testable without
  # sabotaging the interpreter that has to run preflight.py a moment later.
  # This is the only seam of its kind in this script.
  local pair key value known
  for pair in ${XEDOWN_PREFLIGHT_FACTS-}; do
    key="${pair%%=*}"
    value="${pair#*=}"
    for known in "${FACT_NAMES[@]}"; do
      if [ "$key" = "$known" ]; then
        printf -v "fact_$key" '%s' "$value"
        break
      fi
    done
  done
}

run_preflight() {
  local args=()
  local name var
  for name in "${FACT_NAMES[@]}"; do
    var="fact_$name"
    args+=("$name=${!var-}")
  done
  set +e
  python3 "$STAGE/xedown/preflight.py" "${args[@]}"
  local status=$?
  set -e
  return "$status"
}

preflight_gate() {
  # An archive built before the compatibility check existed does not carry
  # preflight.py. Python exits 2 when it cannot open a file, which is the
  # same code preflight.py uses for "refused" -- so without this guard every
  # pre-1.0 tarball would be refused with no findings printed and no way to
  # tell the two cases apart. Publishing the installer separately from the
  # archive is exactly what invites that pairing.
  if [ ! -f "$STAGE/xedown/preflight.py" ]; then
    say "This archive predates xedown's compatibility check, so nothing was"
    say "verified about this machine. Installing anyway."
    return 0
  fi
  probe_facts
  local status=0
  run_preflight || status=$?
  case "$status" in
    0) return 0 ;;
    1) say ""; say "Installing anyway: nothing above prevents xedown from running,"
       say "but this machine is outside what xedown is tested on."
       say "See https://github.com/Ahmad-danaf/xedown/blob/main/docs/compatibility.md"
       say ""; return 0 ;;
    2) if [ "$FORCE" = 1 ]; then
         say ""; say "Installing anyway because --force was given."
         say "xedown may not load at all until the above is fixed."; say ""
         return 0
       fi
       say ""
       say "Refusing to install: xedown cannot run on this machine as it is."
       say "Fix the above, or re-run with --force if you know better."
       exit 2 ;;
    *) die "preflight check could not be run (exit $status)" ;;
  esac
}

# --- switching it on -----------------------------------------------------
#
# `active-plugins` is xed's setting, not xedown's, so it is never written
# without being asked. The list is edited in Python rather than by shell
# string surgery: gsettings prints a Python-ish list literal, and rebuilding
# it with sed is how the other entries get mangled.

XED_SCHEMA="org.x.editor.plugins"
XED_KEY="active-plugins"

xed_is_running() { pgrep -x xed >/dev/null 2>&1; }

plugins_list() { gsettings get "$XED_SCHEMA" "$XED_KEY" 2>/dev/null || true; }

plugin_is_enabled() {
  python3 - "$(plugins_list)" <<'PYTHON'
import ast, sys
try:
    current = ast.literal_eval(sys.argv[1])
except Exception:
    sys.exit(2)
sys.exit(0 if "xedown" in current else 1)
PYTHON
}

enable_plugin() {
  local updated
  updated="$(python3 - "$(plugins_list)" <<'PYTHON'
import ast, sys
current = list(ast.literal_eval(sys.argv[1]))
if "xedown" not in current:
    current.append("xedown")
print(repr(current))
PYTHON
)" || die "could not read $XED_SCHEMA $XED_KEY"
  gsettings set "$XED_SCHEMA" "$XED_KEY" "$updated" \
    || die "could not write $XED_SCHEMA $XED_KEY"
}

enable_step() {
  if [ "$ENABLE" = "no" ]; then
    return 0
  fi
  if ! command -v gsettings >/dev/null 2>&1; then
    say "gsettings is not available, so xedown was not switched on."
    return 0
  fi
  if plugin_is_enabled; then
    say "xedown is already enabled in xed."
    return 0
  fi
  if xed_is_running; then
    say "xed is running, so xedown was not switched on: xed rewrites its"
    say "plugin list when it exits and would discard the change."
    say "Close xed and re-run with --enable, or tick Xedown in"
    say "Preferences -> Plugins."
    return 0
  fi
  if [ "$ENABLE" != "yes" ]; then
    # No terminal means no question. A script running this must not hang,
    # and must not silently change a desktop setting either.
    [ -t 0 ] || return 0
    local reply=""
    printf 'Switch xedown on in xed now? [y/N] '
    read -r reply || true
    case "$reply" in [yY]*) ;; *) return 0 ;; esac
  fi
  enable_plugin
  say "Enabled xedown in xed."
}

# --- main ----------------------------------------------------------------

SOURCE="$(resolve_source)"
stage_source "$SOURCE"
check_staged
preflight_gate

PREVIOUS="$(installed_version)"
install_plugin

if [ -n "$PREVIOUS" ]; then
  say "Upgraded xedown $PREVIOUS -> $STAGED_VERSION in $PLUGIN_DIR"
else
  say "Installed xedown $STAGED_VERSION in $PLUGIN_DIR"
fi
if [ -d "$CONFIG_DIR" ]; then
  say "Your settings in $CONFIG_DIR were not touched."
fi
enable_step
if ! plugin_is_enabled 2>/dev/null; then
  say "Enable it in xed under Preferences -> Plugins, then tick Xedown."
fi
if xed_is_running; then
  say "Restart xed to pick up this version."
fi
