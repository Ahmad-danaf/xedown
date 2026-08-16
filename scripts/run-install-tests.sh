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

scenario_hard_failure_refuses() {
  # An existing install must survive a refused one untouched.
  mkdir -p "$PLUGIN_DIR/xedown"
  printf '__version__ = "0.3.0"\n' > "$PLUGIN_DIR/xedown/__init__.py"
  printf 'Version=0.3.0\n' > "$PLUGIN_DIR/xedown.plugin"

  # The whole fact string is restated, not just the one being changed: a
  # missing python3-gi suppresses both typelib probes by design, so a
  # scenario that only set webkit41_typelib=0 would report nothing at all on
  # a machine without gi.
  export XEDOWN_PREFLIGHT_FACTS="has_gi=1 gtk3_typelib=1 webkit41_typelib=0"
  run_install --no-enable
  assert_status 2
  assert_output_contains "gir1.2-webkit2-4.1"
  grep -q '0\.3\.0' "$PLUGIN_DIR/xedown/__init__.py" \
    || fail "the existing install was modified by a refused install"
  # Nothing is left behind in the plugins directory either.
  [ -z "$(find "$PLUGIN_DIR" -maxdepth 1 -name '.xedown-*')" ] \
    || fail "a staging or aside directory was left behind"
}

scenario_force_overrides_a_hard_failure() {
  export XEDOWN_PREFLIGHT_FACTS="has_gi=1 gtk3_typelib=1 webkit41_typelib=0"
  run_install --no-enable --force
  assert_status 0
  assert_installed
  assert_output_contains "gir1.2-webkit2-4.1"
  assert_output_contains "--force"
}

scenario_soft_findings_warn_and_install() {
  export STUB_XED_VERSION="xed - Version 3.9.0"
  export XEDOWN_PREFLIGHT_FACTS="has_gi=1 gtk3_typelib=1 webkit41_typelib=1 distro_id=fedora distro_version_id=41 session_type=wayland"
  run_install --no-enable
  assert_status 0
  assert_installed
  assert_output_contains "3.9.0"
  assert_output_contains "fedora"
  assert_output_contains "Wayland"
}

scenario_enable_adds_to_active_plugins() {
  run_install --enable
  assert_status 0
  assert_installed
  # Every other plugin the reader had enabled is still there.
  assert_plugins_setting "['docinfo', 'time', 'xedown']"
}

scenario_enable_is_idempotent() {
  printf "['docinfo', 'xedown']\n" > "$GSETTINGS_STORE"
  run_install --enable
  assert_status 0
  assert_plugins_setting "['docinfo', 'xedown']"
  assert_output_contains "already enabled"
}

scenario_enable_is_skipped_while_xed_runs() {
  # xed rewrites active-plugins when it exits, so a change made underneath
  # a running xed is silently discarded. Better to say so than to make it.
  export STUB_XED_RUNNING=1
  run_install --enable
  assert_status 0
  assert_installed
  assert_plugins_setting "['docinfo', 'time']"
  assert_output_contains "xed is running"
}

scenario_non_interactive_never_enables() {
  # No --enable, no --no-enable, and no terminal: the quiet answer is the
  # one that changes nothing about the reader's desktop.
  #
  # This must reproduce the actual hazard the `[ -t 0 ] || return 0` guard
  # in install.sh exists for: stdin that is OPEN, non-tty, and silent --
  # the shape of a script launched from something that has not written
  # anything yet. A plain `< /dev/null` does NOT do that: `read` on an
  # already-closed stdin returns instant EOF, which the `case` statement's
  # default branch already treats as "no" -- so that shape of test would
  # still pass even if the guard were deleted, and would never catch a
  # regression.
  #
  # A FIFO whose write end is held open by a background process (but which
  # never writes anything) reproduces the real hazard: `read -r` on it
  # blocks exactly as it would on a real non-interactive, non-tty session.
  # `run_install` (command substitution) does not redirect stdin, so it is
  # not used here -- this scenario builds its own stdin explicitly rather
  # than depending on whatever the harness process happens to be attached
  # to, and bounds the run with `timeout` so a reintroduced hang becomes a
  # failed scenario instead of a hung harness.
  local fifo="$SANDBOX/stdin-fifo"
  mkfifo "$fifo"
  ( exec 3>"$fifo"; sleep 30 ) &
  local holder=$!

  OUTPUT="$(timeout 5 "$ROOT/install.sh" < "$fifo" 2>&1)"
  STATUS=$?

  kill "$holder" 2>/dev/null || true
  wait "$holder" 2>/dev/null
  rm -f "$fifo"

  if [ "$STATUS" -eq 124 ]; then
    fail "install.sh hung waiting on stdin (killed by timeout after 5s) -- the [ -t 0 ] guard did not short-circuit the prompt"
    return
  fi
  assert_status 0
  assert_installed
  assert_plugins_setting "['docinfo', 'time']"
}

scenario_uninstall_keeps_preferences() {
  run_install --enable
  mkdir -p "$CONFIG_DIR"
  printf '{"preview_theme": "focused"}\n' > "$CONFIG_DIR/settings.json"
  printf '{}\n' > "$CONFIG_DIR/modes.json"

  run_uninstall
  assert_status 0
  assert_not_installed
  assert_present "$CONFIG_DIR/settings.json"
  assert_present "$CONFIG_DIR/modes.json"
  assert_output_contains "$CONFIG_DIR"
  assert_output_contains "--purge"
  # The reader's other plugins survive.
  assert_plugins_setting "['docinfo', 'time']"
}

scenario_purge_removes_preferences() {
  run_install --no-enable
  mkdir -p "$CONFIG_DIR"
  printf '{"preview_theme": "focused"}\n' > "$CONFIG_DIR/settings.json"

  run_uninstall --purge
  assert_status 0
  assert_not_installed
  assert_absent "$CONFIG_DIR"
}

scenario_uninstall_with_nothing_installed() {
  run_uninstall
  assert_status 0
  assert_output_contains "not installed"
}

scenario_uninstall_refuses_while_xed_runs() {
  run_install --no-enable
  export STUB_XED_RUNNING=1
  run_uninstall
  assert_status 1
  assert_installed
  assert_output_contains "Close xed"
}

scenario_uninstall_refuses_a_directory_that_is_not_xedown() {
  # The plugin path is computed from XDG_DATA_HOME. A computed path is
  # exactly the kind that becomes a catastrophe when a variable is empty,
  # so anything that does not look like a xedown install is left alone.
  mkdir -p "$PLUGIN_DIR/xedown"
  printf 'not xedown\n' > "$PLUGIN_DIR/xedown/something_else.py"
  run_uninstall
  assert_status 1
  assert_present "$PLUGIN_DIR/xedown/something_else.py"
  assert_output_contains "does not look like"
}

# --- main ----------------------------------------------------------------

ROOT_PATH="$PATH"
WANTED=("$@")

scenario fresh-install
scenario upgrade-replaces
scenario install-from-archive
scenario hard-failure-refuses
scenario force-overrides-a-hard-failure
scenario soft-findings-warn-and-install
scenario enable-adds-to-active-plugins
scenario enable-is-idempotent
scenario enable-is-skipped-while-xed-runs
scenario non-interactive-never-enables
scenario uninstall-keeps-preferences
scenario purge-removes-preferences
scenario uninstall-with-nothing-installed
scenario uninstall-refuses-while-xed-runs
scenario uninstall-refuses-a-directory-that-is-not-xedown

if [ "$FAILURES" -ne 0 ]; then
  printf '\n%s scenario(s) failed\n' "$FAILURES" >&2
  exit 1
fi
printf '\nAll scenarios passed.\n'
