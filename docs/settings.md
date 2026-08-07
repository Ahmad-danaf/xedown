# Settings

xedown stores its settings as JSON in `~/.config/xedown/settings.json`
(or `$XDG_CONFIG_HOME/xedown/settings.json` when that is set).

**Some of these values have no consumer yet.** `preview_theme`,
`custom_stylesheet`, `content_width_rem`, `text_size_px`, `remote_images`,
`code_copy_buttons` and `text_direction` are read as of v0.2 — see
[themes.md](themes.md). The rest exist so that the features that use them, and
the settings window that will edit them, have one place to look.

The file holds only the settings you have actually changed, so a fresh install
has no file at all. Anything absent uses its default.

| Key | Values | Default |
| --- | --- | --- |
| `default_mode` | `preview`, `markdown` | `preview` |
| `remember_mode_per_file` | `true`, `false` | `true` |
| `preview_theme` | `focused`, `repository`, `minimal`, `document` | `repository` |
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

`content_width_rem` and `text_size_px` describe a **base** value rather than
the rendered result: every theme declares its own measure and text scale to
multiply them by — see [themes.md](themes.md) — so the number you set is not
always the number rendered. `document`, for instance, renders a narrower column
than its base width alone would suggest.

`custom_stylesheet` is applied on top of the selected theme, and the file
itself is watched: saving an edit to it updates every open preview.
[themes.md](themes.md) covers what a custom stylesheet can and cannot do —
in particular that nothing in it can reach the network.

Two have no v0.1 equivalent, because the capability did not exist in v0.1 —
`remember_mode_per_file` and `watch_external_changes`. Each ships **On**, so
when the features that read them arrive later in v0.2 they will be active
without you doing anything. Set either of them to `false` here to opt out.

`remote_images` decides how **any** image that cannot be displayed appears —
not only a remote one. Its name is older than its job:

| Value | What you see |
| --- | --- |
| `placeholder` | why the image is not there, plus your alt text |
| `alt` | your alt text alone, when there is any |
| `hidden` | nothing at all |

All three are about presentation. **None of them fetches anything**, and
there is no value that would: xedown does not reach the network, and the
preview's content security policy enforces that rather than trusting the
setting. `hidden` hides the message, not the reason for it.

`code_copy_buttons` shows a copy button in the corner of every code block.
Set it to `false` and the buttons vanish from every open preview
immediately — no restart, no reopening the file.

`text_direction` decides which way the **document** lays out. `auto`, the
default, counts the strong right-to-left and left-to-right characters in the
document — ignoring code and URLs — and picks the winner, so a document that
opens with an English heading but is Arabic throughout still lays out
right-to-left. Set it to `ltr` or `rtl` to decide for yourself. xedown reads
`settings.json` when it starts, so restart xed after editing the file.

Forcing a direction sets the **layout** — bullets and their indentation,
quote bars, table column order, footnote markers, the copy button — and not
each block. Every paragraph, heading, list item and table cell still picks
its own reading direction from its own content, so `"text_direction": "rtl"`
does not left-align your English paragraphs and `"ltr"` does not misplace the
punctuation in your Arabic ones.

This setting says nothing about xedown's own interface. The Preview/Markdown
bar, the stylesheet notice and the error pages follow your **desktop's**
direction, whatever the document is written in.

## Editing the file by hand

You can, and xedown tries hard to make sense of what it finds:

- A value that is out of range is **brought into range**, not rejected.
  `"content_width_rem": 5000` reads as 100.
- A choice is matched ignoring case and surrounding space, so `"Repository"` works.
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
