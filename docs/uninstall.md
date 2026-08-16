# Uninstalling

Close xed before uninstalling. xed rewrites its active-plugin list when it
exits, so changing that list underneath a running process can be silently
undone.

From the directory containing the release scripts or a repository checkout:

```bash
./uninstall.sh
```

This removes the plugin from xed's active-plugin list when possible and deletes
the plugin files. It keeps your preferences and remembered file modes in
`~/.config/xedown/`, so a later reinstall finds them.

To remove those files as well:

```bash
./uninstall.sh --purge
```

`--purge` removes the whole xedown configuration directory, including
`settings.json`, `modes.json`, and any quarantined settings file.

With custom XDG paths, plugin files are under
`$XDG_DATA_HOME/xed/plugins` and configuration under
`$XDG_CONFIG_HOME/xedown`.

## If xed cannot be closed

```bash
./uninstall.sh --force
```

This removes the plugin files while xed is running but deliberately leaves
xed's active-plugin setting alone. Close xed afterward, then run
`./uninstall.sh` again. That second run removes the stale active-plugin entry
even though the plugin files are already gone.

## Manual removal

If the script is unavailable, close xed and remove only these paths:

```text
~/.local/share/xed/plugins/xedown/
~/.local/share/xed/plugins/xedown.plugin
```

Remove `~/.config/xedown/` separately only if you also want to discard your
preferences and remembered modes.
