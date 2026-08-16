#!/usr/bin/env bash
# Removes xedown from your xed plugins directory.
#
#   ./uninstall.sh            # remove the plugin, keep your settings
#   ./uninstall.sh --purge    # also remove ~/.config/xedown
#   ./uninstall.sh --force    # remove the files even while xed is running
set -euo pipefail

PLUGIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/xed/plugins"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/xedown"
XED_SCHEMA="org.x.editor.plugins"
XED_KEY="active-plugins"

PURGE=0
FORCE=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --purge) PURGE=1; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

xed_is_running() { pgrep -x xed >/dev/null 2>&1; }

disable_plugin() {
  if xed_is_running || ! command -v gsettings >/dev/null 2>&1; then
    return
  fi
  local current updated
  current="$(gsettings get "$XED_SCHEMA" "$XED_KEY" 2>/dev/null || true)"
  if [ -n "$current" ]; then
    # `|| say ...` on the whole chain, not bare: under `set -e` a failing
    # gsettings would otherwise abort the uninstall halfway, leaving the
    # files in place with no message about why.
    { updated="$(python3 - "$current" <<'PYTHON'
import ast, sys
current = [name for name in ast.literal_eval(sys.argv[1]) if name != "xedown"]
print(repr(current))
PYTHON
)" && gsettings set "$XED_SCHEMA" "$XED_KEY" "$updated" \
      && say "Removed xedown from xed's plugin list."
    } || say "Could not update xed's plugin list; remove xedown from it by hand."
  fi
}


if [ ! -e "$PLUGIN_DIR/xedown" ] && [ ! -e "$PLUGIN_DIR/xedown.plugin" ]; then
  disable_plugin
  say "xedown is not installed in $PLUGIN_DIR — nothing to do."
  if [ "$PURGE" = 1 ] && [ -d "$CONFIG_DIR" ]; then
    rm -rf "$CONFIG_DIR"
    say "Removed $CONFIG_DIR."
  fi
  exit 0
fi

# Both paths above are computed from XDG_DATA_HOME or HOME, and a computed
# path is exactly the kind that becomes a catastrophe when a variable is
# empty. Nothing here deletes a directory that has not first been shown to
# be a xedown install.

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' \
           "$PLUGIN_DIR/xedown/__init__.py" 2>/dev/null || true)"
if [ -z "$VERSION" ] || [ ! -f "$PLUGIN_DIR/xedown.plugin" ]; then
  say "$PLUGIN_DIR/xedown does not look like a xedown install:"
  say "no xedown/__init__.py carrying a __version__, or no xedown.plugin"
  say "beside it. Nothing has been deleted. Remove it by hand if you are sure."
  exit 1
fi

if xed_is_running && [ "$FORCE" = 0 ]; then
  say "xed is running. Close xed first and run this again."
  say ""
  say "Not a precaution about open files: xed rewrites its plugin list when"
  say "it exits, so removing xedown from that list underneath a running xed"
  say "is silently undone. Use --force to remove the files anyway and leave"
  say "the plugin list alone."
  exit 1
fi

say "Removing xedown $VERSION from $PLUGIN_DIR"


disable_plugin


rm -rf "$PLUGIN_DIR/xedown"
rm -f "$PLUGIN_DIR/xedown.plugin"
say "Removed the plugin files."

if xed_is_running; then
  say ""
  say "Close xed, then run this script again to remove the stale entry from"
  say "xed's active-plugin list. The second run works with no plugin files present."
fi


if [ "$PURGE" = 1 ]; then
  if [ -d "$CONFIG_DIR" ]; then
    say ""
    say "Removing your xedown settings:"
    find "$CONFIG_DIR" -type f -printf '  %p\n' 2>/dev/null || true
    rm -rf "$CONFIG_DIR"
  fi
elif [ -d "$CONFIG_DIR" ]; then
  say ""
  say "Your settings were kept, in $CONFIG_DIR:"
  find "$CONFIG_DIR" -maxdepth 1 -type f -printf '  %p\n' 2>/dev/null || true
  say ""
  say "Reinstalling later will find them. Remove them with:"
  say "  ./uninstall.sh --purge"
fi
