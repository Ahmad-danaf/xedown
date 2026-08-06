# Settings

xedown stores its settings as JSON in `~/.config/xedown/settings.json`
(or `$XDG_CONFIG_HOME/xedown/settings.json` when that is set).

**As of v0.2 brief 1 nothing reads these values yet.** The store exists so the
rest of v0.2 has one place to keep user choices; the preferences window that
edits them, and the features that read them, arrive later in the version.

The file holds only the settings you have actually changed, so a fresh install
has no file at all. Anything absent uses its default.

| Key | Values | Default |
| --- | --- | --- |
| `default_mode` | `preview`, `markdown` | `preview` |
| `remember_mode_per_file` | `true`, `false` | `true` |
| `preview_theme` | `cursor`, `github`, `minimal`, `document` | `github` |
| `custom_stylesheet` | a file path, or `null` | `null` |
| `content_width_rem` | 30 to 100 | `46` |
| `text_size_px` | 11 to 28 | `16` |
| `auto_refresh` | `true`, `false` | `true` |
| `refresh_delay_ms` | 50 to 2000 | `250` |
| `remote_images` | `placeholder`, `alt`, `hidden` | `placeholder` |
| `code_copy_buttons` | `true`, `false` | `true` |
| `text_direction` | `auto`, `ltr`, `rtl` | `auto` |
| `watch_external_changes` | `true`, `false` | `true` |

Most of these defaults reproduce xedown 0.1.0 exactly: the preview keeps the
same look, width, text size, refresh timing and starting mode.

Three have no v0.1 equivalent, because the capability did not exist in v0.1 —
`code_copy_buttons`, `remember_mode_per_file` and `watch_external_changes`.
Each ships **On**, so when the features that read them arrive later in v0.2
they will be active without you doing anything. Set any of them to `false`
here to opt out.

## Editing the file by hand

You can, and xedown tries hard to make sense of what it finds:

- A value that is out of range is **brought into range**, not rejected.
  `"content_width_rem": 5000` reads as 100.
- A choice is matched ignoring case and surrounding space, so `"GitHub"` works.
- A value of the wrong type falls back to that setting's default. Booleans must
  be real JSON booleans: `"auto_refresh": "yes"` is not recognised, and reads
  as the default.
- A misspelled key is ignored, and is kept in the file rather than deleted.
- `custom_stylesheet` is stored as you write it, apart from surrounding
  whitespace. `~` is not expanded.

If the file cannot be used at all — truncated, not a JSON object, not readable,
or not valid UTF-8 — xedown starts from defaults and **keeps your copy** at
`~/.config/xedown/settings.json.corrupt`, naming both paths on standard error.
If even that move fails, your file is left exactly where it is and the message
says so. A second corruption replaces the preserved copy. An empty file is
treated as "no settings yet" rather than as damage, since that is what a write
interrupted part-way leaves behind.

If the file cannot be written — a read-only home, a full disk — your change
still applies for the rest of the session; it just will not survive a restart.

## Limitations

- Settings are global. There are no per-file or per-window settings.
- All of xed's windows normally share one process, so a change applies to every
  open tab in every window immediately. `xed --standalone` starts a second
  process: neither process will overwrite the other's saved settings, but a
  running second process will not see a change until it restarts.
- `XEDOWN_CONFIG_DIR` overrides the location entirely. The live test harnesses
  set it so a test run cannot touch your real settings.
