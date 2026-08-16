#!/usr/bin/env bash
# Drives install.sh and uninstall.sh through every flow that has to be
# boring, without touching anything you own.
#
#   THIS IS THE ONE HARNESS THAT DOES NOT INSTALL INTO YOUR REAL PLUGINS
#   DIRECTORY.
#
# run-integration-tests.sh, run-shutdown-tests.sh and run-orca-tests.sh all
# install the working tree into ~/.local/share/xed/plugins and rewrite the
# live `org.x.editor.plugins active-plugins` gsetting. This one does not. It
# builds a throwaway HOME under a mktemp directory, points XDG_DATA_HOME and
# XDG_CONFIG_HOME inside it, and puts stub `xed`, `gsettings` and `pgrep`
# binaries at the front of PATH. No desktop session, no root, safe in CI.
#
# Usage:
#   scripts/run-install-tests.sh              # every scenario
#   scripts/run-install-tests.sh fresh-install # one, by name
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Guarded loudly: under `set -uo pipefail` (no `set -e`), an unchecked
# `mktemp -d` failure would leave WORKSPACE empty, which would make
# SANDBOX (below) collapse to a root-level path feeding `rm -rf`.
WORKSPACE="$(mktemp -d)" || { printf 'mktemp -d failed\n' >&2; exit 1; }
FAILURES=0
CURRENT=""

cleanup() { rm -rf "$WORKSPACE"; }
trap cleanup EXIT

# --- the sandbox ---------------------------------------------------------

new_sandbox() {
  # Belt-and-braces on top of the WORKSPACE guard above: this is where the
  # dangerous `rm -rf` actually lives, and an empty WORKSPACE or CURRENT
  # would make SANDBOX a root-level path (e.g. "/fresh-install") instead of
  # a temp directory.
  [ -n "$WORKSPACE" ] && [ -n "$CURRENT" ] || { printf 'new_sandbox: WORKSPACE or CURRENT is empty, refusing to proceed\n' >&2; exit 1; }
  SANDBOX="$WORKSPACE/$CURRENT"
  rm -rf "$SANDBOX"
  export HOME="$SANDBOX/home"
  export XDG_DATA_HOME="$HOME/.local/share"
  export XDG_CONFIG_HOME="$HOME/.config"
  export PLUGIN_DIR="$XDG_DATA_HOME/xed/plugins"
  export CONFIG_DIR="$XDG_CONFIG_HOME/xedown"
  mkdir -p "$PLUGIN_DIR" "$XDG_CONFIG_HOME" "$SANDBOX/bin"

  # What the stubs answer. Each scenario may override before running.
  export STUB_XED_VERSION="xed - Version 3.8.9+zena"
  export STUB_XED_RUNNING=0
  export GSETTINGS_STORE="$SANDBOX/gsettings-active-plugins"
  printf "['docinfo', 'time']\n" > "$GSETTINGS_STORE"
  # A fully supported baseline, not `unset`. Probing these from the host
  # would make every result depend on whether the machine running the tests
  # happens to have python3-gi -- and a sandbox whose outcome depends on the
  # host is not a sandbox. A scenario overriding one fact restates them all.
  export XEDOWN_PREFLIGHT_FACTS="has_gi=1 gtk3_typelib=1 webkit41_typelib=1"

  cat > "$SANDBOX/bin/xed" <<'STUB'
#!/usr/bin/env bash
[ "${1-}" = "--version" ] && printf '%s\n' "$STUB_XED_VERSION"
STUB

  # `gsettings get SCHEMA KEY` and `gsettings set SCHEMA KEY VALUE`, backed
  # by a file so a scenario can read what the installer wrote.
  cat > "$SANDBOX/bin/gsettings" <<'STUB'
#!/usr/bin/env bash
case "${1-}" in
  get) cat "$GSETTINGS_STORE" ;;
  set) printf '%s\n' "${4-}" > "$GSETTINGS_STORE" ;;
  *) exit 2 ;;
esac
STUB

  cat > "$SANDBOX/bin/pgrep" <<'STUB'
#!/usr/bin/env bash
exit $(( STUB_XED_RUNNING == 1 ? 0 : 1 ))
STUB

  chmod +x "$SANDBOX/bin"/*
  export PATH="$SANDBOX/bin:$ROOT_PATH"
}

# --- running the scripts under test --------------------------------------

run_install() {
  OUTPUT="$("$ROOT/install.sh" "$@" 2>&1)"
  STATUS=$?
  return 0
}

run_uninstall() {
  OUTPUT="$("$ROOT/uninstall.sh" "$@" 2>&1)"
  STATUS=$?
  return 0
}

# --- assertions ----------------------------------------------------------

fail() {
  printf '    FAIL: %s\n' "$1" >&2
  [ -n "${OUTPUT-}" ] && printf '%s\n' "$OUTPUT" | sed 's/^/      | /' >&2
  SCENARIO_FAILED=1
}

assert_status() {
  [ "$STATUS" = "$1" ] || fail "expected exit $1, got $STATUS"
}

assert_installed() {
  [ -f "$PLUGIN_DIR/xedown/__init__.py" ] || fail "xedown/__init__.py not installed"
  [ -f "$PLUGIN_DIR/xedown.plugin" ] || fail "xedown.plugin not installed"
}

assert_not_installed() {
  [ ! -e "$PLUGIN_DIR/xedown" ] || fail "xedown/ is still installed"
  [ ! -e "$PLUGIN_DIR/xedown.plugin" ] || fail "xedown.plugin is still installed"
}

assert_absent() {
  [ ! -e "$1" ] || fail "expected not to exist: $1"
}

assert_present() {
  [ -e "$1" ] || fail "expected to exist: $1"
}

assert_output_contains() {
  printf '%s' "$OUTPUT" | grep -qF -- "$1" || fail "output did not mention: $1"
}

assert_output_lacks() {
  printf '%s' "$OUTPUT" | grep -qF -- "$1" && fail "output should not have mentioned: $1"
  return 0
}

assert_plugins_setting() {
  local actual; actual="$(cat "$GSETTINGS_STORE")"
  [ "$actual" = "$1" ] || fail "active-plugins is $actual, expected $1"
}

# --- the scenario runner -------------------------------------------------

scenario() {
  CURRENT="$1"
  if [ "${#WANTED[@]}" -gt 0 ] && ! printf '%s\n' "${WANTED[@]}" | grep -qx "$1"; then
    return 0
  fi
  printf '==> %s\n' "$1"
  SCENARIO_FAILED=0
  new_sandbox
  "scenario_${1//-/_}"
  if [ "$SCENARIO_FAILED" = 0 ]; then
    printf '    PASS\n'
  else
    FAILURES=$((FAILURES + 1))
  fi
}

# --- scenarios -----------------------------------------------------------

scenario_fresh_install() {
  run_install --no-enable
  assert_status 0
  assert_installed
  # Nothing is written to the config directory by installing: a fresh
  # install has no settings file at all, which is what makes "the file
  # holds only what you changed" true from the first run.
  assert_absent "$CONFIG_DIR"
  # And nothing is enabled without being asked.
  assert_plugins_setting "['docinfo', 'time']"
  assert_output_contains "Preferences"
}

scenario_upgrade_replaces() {
  # An existing install carrying a v0.2 settings file and a module that no
  # longer exists in the new version. Copying over this would leave the
  # orphan behind; replacing must not.
  mkdir -p "$PLUGIN_DIR/xedown" "$CONFIG_DIR"
  printf '__version__ = "0.2.0"\n' > "$PLUGIN_DIR/xedown/__init__.py"
  printf 'Version=0.2.0\n' > "$PLUGIN_DIR/xedown.plugin"
  printf 'gone in 1.0\n' > "$PLUGIN_DIR/xedown/removed_in_1_0.py"
  mkdir -p "$PLUGIN_DIR/xedown/__pycache__"
  printf 'stale\n' > "$PLUGIN_DIR/xedown/__pycache__/removed_in_1_0.pyc"
  local settings_file="$CONFIG_DIR/settings.json"
  printf '{"preview_theme": "focused", "remote_images": "alt"}\n' > "$settings_file"
  local before; before="$(cat "$settings_file")"

  run_install --no-enable
  assert_status 0
  assert_installed
  assert_absent "$PLUGIN_DIR/xedown/removed_in_1_0.py"
  assert_absent "$PLUGIN_DIR/xedown/__pycache__"
  [ "$(cat "$settings_file")" = "$before" ] || fail "settings.json was modified"
  assert_output_contains "0.2.0"
}

scenario_install_from_archive() {
  local archive
  archive="$(ls -1t "$ROOT"/dist/xedown-*.tar.gz 2>/dev/null | head -1)"
  if [ -z "$archive" ]; then
    printf '    SKIP: no archive in dist/ (run scripts/build-release.sh)\n'
    return 0
  fi
  run_install --from "$archive" --no-enable
  assert_status 0
  assert_installed
}

# --- main ----------------------------------------------------------------

ROOT_PATH="$PATH"
WANTED=("$@")

scenario fresh-install
scenario upgrade-replaces
scenario install-from-archive

if [ "$FAILURES" -ne 0 ]; then
  printf '\n%s scenario(s) failed\n' "$FAILURES" >&2
  exit 1
fi
printf '\nAll scenarios passed.\n'
