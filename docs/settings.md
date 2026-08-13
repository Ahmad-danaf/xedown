# Settings

xedown stores its settings as JSON in `~/.config/xedown/settings.json`
(or `$XDG_CONFIG_HOME/xedown/settings.json` when that is set).

Every value here is read as of v0.2: `preview_theme`, `custom_stylesheet`,
`content_width_rem`, `text_size_px`, `code_copy_buttons` and `text_direction`
— see [themes.md](themes.md); `default_mode`, `remember_mode_per_file`,
`auto_refresh` and `refresh_delay_ms` — see
[Modes and refreshing](#modes-and-refreshing) below; `watch_external_changes` —
see [Changes made outside xed](#changes-made-outside-xed). As of v0.3,
`remote_images` is the fetch policy for images from the web, and
`image_fallback` is the display setting `remote_images` used to be — see
[Remote images](#remote-images) below.

The file holds only the settings you have actually changed, so a fresh install
has no file at all. Anything absent uses its default.

Everything on this page is also in **Markdown Preview Settings**, and changing
it there applies to every open preview at once. Two ways in, both showing the
same settings:

- *Preferences → Plugins*, select **Xedown**, then **Preferences**.
- **View → Markdown Preview Settings**.

`default_mode` is the one setting the window cannot apply to a tab that is
already open, because it is read when a tab is built.

Editing the file by hand still works, and still needs a restart: nothing
watches it while xed is running.

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
| `remote_images` | `never`, `https` | `never` |
| `image_fallback` | `placeholder`, `alt`, `hidden` | `placeholder` |
| `code_copy_buttons` | `true`, `false` | `true` |
| `text_direction` | `auto`, `ltr`, `rtl` | `auto` |
| `watch_external_changes` | `true`, `false` | `true` |

## The settings window

Settings are grouped by what they affect: how files open, how the preview
looks, how it refreshes, and images and changes made outside xed. Each control
carries a short explanation where its label is not enough.

Changes apply as you make them. A switch or a menu applies the moment you
change it; a number or the stylesheet path applies a moment after you stop
typing, or straight away if you press Enter, move to another field, or pick a
file. Nothing is written just by opening the window.

**Restore defaults** puts all thirteen settings back, after asking. That
returns everything to xedown 0.1.0's behaviour except `remote_images`, whose
fetch-policy meaning is new in v0.3 and has no earlier behaviour to return
to — it goes back to `never`, already its default. Your custom stylesheet is
forgotten — the file itself is not touched.

The window also tells you about two things you would otherwise only find on
standard error: a settings file that could not be saved, and one that was
found broken at startup and set aside as `settings.json.corrupt`.

Most of these defaults reproduce xedown 0.1.0 exactly: the preview keeps the
same look, width, text size, refresh timing and starting mode.

`content_width_rem` and `text_size_px` describe a **base** value rather than
the rendered result: every theme declares its own measure and text scale to
multiply them by — see [themes.md](themes.md) — so the number you set is not
always the number rendered. `document`, for instance, renders a narrower column
than its base width alone would suggest.

`custom_stylesheet` is applied on top of the selected theme, and the stylesheet
it points at is the one thing here that *is* watched: saving an edit to that
file updates every open preview straight away. Changing which file this setting
names is an ordinary settings change, and needs a restart like the rest.
[themes.md](themes.md) covers what a custom stylesheet can and cannot do —
in particular that nothing in it can reach the network.

Two have no v0.1 equivalent, because the capability did not exist in v0.1 —
`remember_mode_per_file` and `watch_external_changes`. Each ships **On**.
Both are read as of v0.2 — see [Modes and refreshing](#modes-and-refreshing)
and [Changes made outside xed](#changes-made-outside-xed) below. Set either of
them to `false` here to opt out.

### Remote images

`remote_images` decides whether xedown's own code may fetch a `https://`
image over the network at all: `never` (the default) or `https`. This is the
one setting that reaches outside your machine, so its help text in the
settings window says plainly what that means — loading an image tells the
site that hosts it your IP address, roughly where you are, and when you
opened the document. `http://` is never fetched, under this setting or
anything else; there is no value that permits it.

Turning this on applies to every document you open. The mode bar's own
**Load** button grants the same permission to one tab at a time without
touching this setting, for as long as that tab stays open — including after
you turn this setting back to `never`, and independently of whatever other
tabs are doing. See the *Remote images* row in
[the README's feature list](../README.md#features) for what the mode bar
shows.

**Whatever this is set to, the preview page itself is never granted network
access of its own.** `img-src` never lists `http:` or `https:`; only
xedown's own fetch code reaches the network, and only for an image this
setting or the mode bar's Load button has actually permitted — the content
security policy enforces that rather than trusting either one. See
[../SECURITY.md](../SECURITY.md).

`image_fallback` decides how **any** image that cannot be shown appears — a
missing file and an unreadable one look exactly the same as a blocked or
failed remote one. Its name is older than its job: it used to be called
`remote_images`, from before a remote image could be the only thing that
needed a fallback.

| Value | What you see |
| --- | --- |
| `placeholder` | why the image is not there, plus your alt text |
| `alt` | your alt text alone, when there is any |
| `hidden` | nothing at all |

All three are purely about presentation, decided after xedown has already
worked out whether an image loads; none of them changes whether one is
fetched. `hidden` hides the message, not the reason for it.

**A settings file written before this rename still works.** An old-style
`remote_images` — `"placeholder"`, `"alt"` or `"hidden"` — is read as
`image_fallback` instead, in memory, the moment xedown starts; it is never
rewritten to the file. An explicit `image_fallback` already in the file
always wins over it.

**Every image xedown can measure is capped at 25 megapixels and 32768 pixels
on a side before it will decode it, inline (`data:`) or remote alike, and no
setting turns this off.** It is a stability guard, not a preference — a tiny
file can claim dimensions that would exhaust memory on decode, and xedown
reads the claimed size and refuses it before handing anything to WebKit. An
oversized image shows a placeholder saying it is too large to display safely,
in place of either a render that never finishes or one that pushes the
WebProcess past a gigabyte of memory for a single picture. Inline payloads
are measured however they are written — base64 or percent-encoded.

"Can measure" means PNG, JPEG, GIF, WebP and BMP, whose dimensions are
readable from their header bytes. An inline image in a format xedown cannot
read that way — AVIF, SVG — is shown as it always was, uncapped: refusing an
inline image that has always rendered would be a worse regression than the
bug the cap fixes. A *remote* image in such a format is refused instead,
which takes away nothing that ever worked; see
[known-issues.md](known-issues.md) on AVIF.

`code_copy_buttons` shows a copy button in the corner of every code block.
Set it to `false` to remove them.

`text_direction` decides which way the **document** lays out. `auto`, the
default, counts the strong right-to-left and left-to-right characters in the
document — ignoring code and URLs — and picks the winner, so a document that
opens with an English heading but is Arabic throughout still lays out
right-to-left. Set it to `ltr` or `rtl` to decide for yourself. xedown reads
`settings.json` when it starts, so restart xed after editing the file.

Forcing a direction sets the **layout** — bullets and their indentation,
quote bars, table column order, footnote markers, the copy button — and not
each block. Every paragraph, heading and table cell still picks its own
reading direction from its own content, so `"text_direction": "rtl"` does not
left-align your English paragraphs and `"ltr"` does not misplace the
punctuation in your Arabic ones.

A **list item** is the one exception, and deliberately so: it aligns with the
list it belongs to rather than with its own content, so every bullet in a
list stays on the same side. Its text is still reordered normally, so an
English item in an Arabic list reads left to right — it simply sits on the
list's side. A bullet is part of the layout, and the layout is what
`text_direction` sets.

This setting says nothing about xedown's own interface. The Preview/Markdown
bar, the stylesheet notice and the error pages follow your **desktop's**
direction, whatever the document is written in.

## Modes and refreshing

`default_mode` decides how a Markdown file opens. `remember_mode_per_file`, on
by default, overrides it with whichever mode that file was last left in; a file
xedown has never opened uses the default. Which mode a file opens in changes
only for the *next* file you open, for both settings — a tab already in front
of you is never switched out from under you.

Switching `remember_mode_per_file` on does have one immediate effect, though:
every tab already open has its current mode recorded at once, so each of
those files already carries that mode the next time you open it, with no need
to switch anything in it yourself first. `default_mode` has no such effect —
it is read only when a tab is built, so changing it never touches a tab that
is already open, in any way.

Remembered modes live in `~/.config/xedown/modes.json`, beside this file. It
holds the 200 most recently used files, newest first, and older entries fall
off the end, so it cannot grow without limit. It is xedown's own bookkeeping
rather than a setting: if it cannot be read, xedown starts from an empty one
and says nothing. Deleting it forgets every remembered mode. Setting
`remember_mode_per_file` to `false` stops xedown reading or writing it, and
leaves what is already in it alone.

A mode is filed under a file's **path**. Rename or move a file inside xed and
the entry follows it; do it in a file manager and the old path keeps its entry
until it ages out — see [known-issues.md](known-issues.md).

`auto_refresh` decides whether the preview re-renders by itself. It covers less
than the name suggests, and honestly: xedown never shows the source and the
preview at once, so nothing is rendered while you type in Markdown mode — the
switch back to Preview is what renders, and it always does, whatever this is
set to. What `auto_refresh` governs is a change that reaches the document
*while the preview is showing*: an undo or redo, a find-and-replace, a plugin's
edit. A reload from disk — xed's own revert, or accepting its prompt after an
external change — is not governed by it: that always re-renders the preview
when it is showing, whatever `auto_refresh` says. On a very large document the
re-renders `auto_refresh` does control are worth turning off.

Changing `auto_refresh` itself takes effect at once, in every tab already
open: switching it off cancels a render that is already scheduled, and
switching it back on over a stale, visible preview renders it immediately
rather than waiting for the next change.

With `auto_refresh` set to `false`, the mode bar grows a **Refresh** button
while the preview is showing, marked with a dot when the preview is behind
the document, and <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> does the same
thing from the keyboard. Both work whatever `auto_refresh` says, but both act
on the preview itself, so neither does anything in Markdown mode: the button
does not appear there at all, and the shortcut is a no-op — switching back to
Preview is what renders, exactly as it always does regardless of this
setting.

`refresh_delay_ms` is how long xedown waits after a change before re-rendering.
Unlike `default_mode` — the one setting on this page whose effect is entirely
deferred to the next file you open — it reaches tabs that are already open:
the next change uses the new value. A wait already under way keeps the delay
it started with.

## Changes made outside xed

`watch_external_changes`, on by default, keeps the preview honest when
something other than xed rewrites the file you have open — git, a terminal
command, another editor, a coding agent.

**With no unsaved edits** the preview simply updates, in place, at the scroll
position it had. There is no dialog and no button to press. One save by another
program often reaches the filesystem as several separate changes; xedown waits
for them to stop before rendering, so you see one update rather than a flicker
of three, and a rapid burst of writes settles into a single render.

**With unsaved edits xedown replaces nothing.** The preview keeps showing your
work, and a bar appears saying the file changed on disk. Its **Reload…** button
hands off to xed's own *Revert*, which asks for confirmation before discarding
anything. Cancelling that dialog leaves everything as it was. **xedown never
writes to your text**, in either case.

The bar retires by itself as soon as it has nothing left to say: when you save,
when you revert, and when you undo back to a document with no unsaved edits.

One thing this does **not** do is reload the document. The preview follows the
file; the buffer keeps the text you had until you ask xed to reload it. You will
meet that difference only by switching to Markdown mode — and xed itself notices
at exactly that moment and offers you its own **Reload**, because the source
view taking focus is what xed's own check waits for. See
[known-issues.md](known-issues.md).

Deleting the file, replacing it, and moving it away and back are all handled
without an error dialog: the preview keeps showing what it has, and catches up
when the file is there again.

Set `"watch_external_changes": false` to switch it off — worth doing on a
network filesystem, or in a directory where watching is expensive. Like
`auto_refresh`, its new value reaches tabs that are already open rather
than only ones opened later: switching it off stops the watching, and
switching it back on starts it again. Getting the new value in at all still
needs the restart every hand-edited setting on this page needs. Nothing is
watched at all for a file that has never been saved.

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
  open tab in every window at once — on the next start, as above. `xed
  --standalone` starts a second process: neither process will overwrite the
  other's saved settings, and each picks up a change when it next starts.
- `XEDOWN_CONFIG_DIR` overrides the location entirely. The live test harnesses
  set it so a test run cannot touch your real settings.
