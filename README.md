# xedown

A lightweight Markdown preview plugin for xed, with rendered Preview and source
Markdown modes inside the same tab.

## Features

- Rendered preview for `.md` and `.markdown` files (matched case-insensitively),
  covering headings, paragraphs, bold and italic text, strikethrough, ordered
  and unordered lists, task lists, links, local images, blockquotes, horizontal
  rules, tables, inline code and fenced code blocks.
- Footnotes and attribute lists (for example attaching an `id` to a heading to
  link to it). Footnote references and back-references are in-page anchor
  links, and clicking one scrolls the preview to the matching note instead of
  leaving the page.
- Syntax highlighting for fenced code blocks, from a bundled highlight.js build
  covering 31 languages: bash, C, C++, C#, CSS, diff, Dockerfile, Go, INI, Java,
  JavaScript, JSON, Kotlin, Lua, Makefile, Markdown, Objective-C, Perl, PHP,
  plain text, Python, R, Ruby, Rust, SCSS, shell, SQL, Swift, TypeScript, XML
  and YAML. A fence with no language, or one outside that list, still renders
  as a plain styled block.
- Four preview themes — Focused, Repository, Minimal and Document — each with a
  full light and dark palette that follows the desktop theme live, with no
  restart required. Every theme's text is held to WCAG AA contrast in both
  appearances, with one documented exception — see
  [docs/themes.md](docs/themes.md).
- Adjustable content width and text size, and your own stylesheet layered over
  the built-in theme.
- Preview and Markdown modes switch in place, in the same tab. Preview is the
  default for a Markdown file. Each mode remembers its own scroll position,
  and the underlying text buffer is never touched, so switching modes never
  risks the file's content or your cursor position.
- The preview refreshes automatically about a quarter second after an edit,
  but only while it is actually visible; edits made while in Markdown mode
  are rendered the next time you switch to Preview.
- **Refreshing, under your control.** Turn automatic refresh off with
  `auto_refresh` and the mode bar grows a **Refresh** button, marked when the
  preview is behind the document; <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>
  refreshes on demand either way. `refresh_delay_ms` sets how long xedown waits
  after a change.
- **The preview follows the file on disk.** When git, a terminal command,
  another editor or an AI coding agent rewrites the open file, the preview
  updates at the scroll position it had, with no dialog and nothing to press.
  With unsaved edits nothing is replaced: the preview keeps showing your work
  and a dismissible bar offers **Reload…**, which hands off to xed's own
  Revert. xedown never writes to your text. Turn it off with
  `watch_external_changes`.
- **Find in the preview.** <kbd>Ctrl</kbd>+<kbd>F</kbd> searches the rendered
  document — match count, wrapping navigation, a case toggle, highlighting
  themed for all four themes in both appearances. See *Finding text* below.
- **A copy button on every code block**, revealed on hover and reachable by
  keyboard. It copies exactly what the author wrote and says so when a copy
  fails rather than pretending it worked. Turn it off with
  `code_copy_buttons`.
- **Task-list checkboxes drawn from the theme** rather than by the browser, in
  both light and dark. They stay read-only: xedown never writes to your file.
- **Wide tables scroll inside their own area**, with a shadow at whichever edge
  has more to show, instead of being squeezed into unreadable columns. The page
  itself never scrolls sideways.
- **Images fit the reading column**, and a very tall one fits the window too,
  keeping its proportions. A small image keeps its own size, and an image you
  sized yourself in HTML is left alone.
- External links open in your default browser. Local links to other Markdown
  files open in a new xed tab. Other local files are handed to your desktop's
  file opener, which asks for confirmation first for anything that can run
  code — not just a file with the executable bit set or a `.desktop` entry,
  but any shell, Python, Perl or Ruby script, Windows/desktop executable or
  installer, JAR, AppImage, or shared library, judged by its extension
  whether or not it is marked executable.
- Relative links and images resolve against the document's own directory,
  rather than guessing a path.
- Remote images are never fetched. A visible placeholder is shown in their
  place instead. Nothing xedown does ever reaches out to the network.
- Right-to-left documents: Arabic and Hebrew lay out as well as they read.
  Bullets, indentation, quote bars, table columns, footnote markers and the
  copy button all move to the correct side, while each paragraph, heading and
  table cell still picks its own direction from its own content — so mixed
  documents read correctly in both directions. A list item is the exception:
  it aligns with its list rather than with itself, so every bullet in a list
  stays on the same side, and the item's text still reads in its own
  direction. Code stays
  left-to-right whatever surrounds it. Override the automatic choice for a
  whole document with `text_direction` in
  [docs/settings.md](docs/settings.md). One limitation remains: a bare,
  unmarked file path or URL typed straight into right-to-left prose can put
  its leading slash on the wrong end — wrap it in backticks or in
  `<bdi>…</bdi>`.
- **Driven from the keyboard.** <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>
  switches modes, <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd> and
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd> go straight to one,
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> refreshes now. All four are in
  the *View* menu, and none of them takes a key xed already uses.
- **Copy what you can see.** Copy and select-all act on the rendered document
  while the preview is showing, and on the source while it is not.
- **Opens how you want.** Choose the mode Markdown files open in, or have
  xedown reopen each file in the mode you left it in.
- **A settings window** covering every xedown setting, reachable from
  *Preferences → Plugins → Xedown → Preferences* and from *View → Markdown
  Preview Settings*. Changes apply to every open preview as you make them,
  and **Restore defaults** returns to xedown 0.1.0's behaviour. See
  [docs/settings.md](docs/settings.md).

## Requirements

- xed 3.0 or newer
- Python 3.10 or newer
- `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`

Markdown rendering and syntax highlighting are bundled with the plugin. There is
nothing to install with `pip`.

## Installation

From a release archive — nothing else required:

```bash
mkdir -p ~/.local/share/xed/plugins
tar -xzf xedown-0.2.0.tar.gz -C ~/.local/share/xed/plugins
```

Or from a checkout:

```bash
mkdir -p ~/.local/share/xed/plugins
cp -r plugin/xedown plugin/xedown.plugin ~/.local/share/xed/plugins/
```

Then enable **Xedown** in xed under *Preferences → Plugins*.

To build the archive yourself, run `scripts/build-release.sh`. It refuses to
build from a tree with uncommitted changes, produces the same bytes for the
same commit, and unpacks the result into a scratch directory to check that it
renders using only its own bundled dependencies.

## Usage

Open a `.md` or `.markdown` file. It opens in Preview mode with a
`Preview | Markdown` bar at the top of the tab. Switch modes with those buttons or
with <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>, or from *View → Toggle Markdown
Preview*. Both the shortcut and the menu entry are greyed out for files that
are not Markdown. Preview and Markdown each remember their own scroll position,
and viewing never changes the file.

### Finding text

`Ctrl+F` while the preview is showing opens a search bar for the rendered
document; `Ctrl+F` while the Markdown source is showing opens xed's own find.
Typing searches as you type, `Enter` and `Shift+Enter` move between matches
and wrap around, `Aa` toggles case sensitivity, and `Escape` closes the bar,
clears the highlighting and puts focus back on the page.

The search covers what you can see: rendered text, not Markdown syntax. A
match never spans a blank line or a paragraph break, and very broad queries
stop being highlighted after 2000 matches (the count then reads `2000+`).

## Known limitations

- Go-to-line operates on the source text and is inert while Preview is
  showing; switch to Markdown mode to use it.
- The preview follows changes made to the file outside xed, but the **source
  buffer does not**: xedown never writes to your text. After an external
  change the preview shows the file and the editor still holds what you had.
  Switching to Markdown mode is where you meet that, and it is also where xed
  itself offers to reload. Turn the whole behaviour off with
  `"watch_external_changes": false`.
- There is no scroll synchronisation between Preview and Markdown modes —
  each mode keeps its own independent scroll position.
- **Remote images are never fetched.** A `https://` image shows a
  placeholder naming the address. No setting changes this — the preview's
  content security policy blocks the request whatever the settings say.
  `remote_images` only chooses whether there is a placeholder, and how it looks.
- **On a non-Latin keyboard layout** (Cyrillic, Greek, Arabic and others),
  <kbd>Ctrl</kbd>+<kbd>C</kbd> and <kbd>Ctrl</kbd>+<kbd>A</kbd> in the preview
  fall through to xed's own Copy and Select All, which act on the Markdown
  source rather than on the rendered page. Right-click the preview for **Copy**
  and **Select All**, which are unaffected. See
  [docs/known-issues.md](docs/known-issues.md).
- **A document opened through a symbolic link never follows changes to its
  file.** A file monitor on a link watches the link, and nothing writes to the
  link. Open the file by its real path, or use *File → Revert*.
- xedown supports selected GitHub-flavored Markdown features (tables, task
  lists, strikethrough, fenced code, footnotes, and lists that interrupt a
  paragraph), not full GFM compatibility.
- xed 3.8.9 itself can crash when you close a window after moving a tab
  between windows. This happens with xedown uninstalled and is not something
  the plugin can fix or avoid; save before dragging tabs between windows.
  Details and the stack trace are in
  [docs/known-issues.md](docs/known-issues.md).
- A custom stylesheet cannot load anything from the network, and cannot load a
  font file even from your own disk — install the font and name it instead.
  See [docs/themes.md](docs/themes.md).
- **A remembered mode belongs to a path, not to a file.** Rename or move a
  file inside xed and its mode follows. Do it outside xed and the old path
  keeps its entry: a *new* file created at that path later opens in the old
  one's mode until the entry falls out of the 200 most recent. Switching mode
  once fixes it.
- **Automatic refresh covers less than the name suggests.** xedown never shows
  both surfaces at once, so nothing renders while you type in Markdown mode —
  the switch back is what renders. What automatic refresh governs is a change
  reaching the document *while the preview is showing*: an undo, a
  find-and-replace. A reload from disk — xed's own revert, or accepting its
  prompt after an external change — re-renders the preview regardless of this
  setting.

## Accessibility

xedown is built to be driven entirely from the keyboard, and every control it
creates — the mode buttons, the refresh button, the stale indicator, the
search bar and the info bars — takes its accessible name from a single source
of truth. Switching modes moves keyboard focus to the surface you land on and
changes that surface's checked state to match; it also speaks the new mode's
name through an `Atk.Object` announcement, unless one of the two mode toggle
buttons already has keyboard focus at the moment the switch happens — Tab to
a toggle and press it, but also <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>
pressed while focus merely sits on one — in which case the announcement is
suppressed so it is not heard twice. The Refresh button, though also in the
mode bar, does not count for this and never suppresses it. The rendered
document page carries a `role="main"` landmark and, when your desktop's
language is known, a `lang` attribute — an error page carries neither: it is
xedown speaking, not the document, and there is no document to detect a
language from. The focus ring's contrast against every surface it is drawn on
meets WCAG's 3:1 non-text threshold, in all four preview themes, light and
dark.

**The screen-reader speech has been checked, on one machine, with one
reader.** `scripts/run-orca-tests.sh` drives a real xed session under Orca
46.1 on Linux Mint (X11) and records what it says. Measured: pressing
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> announces the new mode both
ways ("Markdown source", then "Preview"); tabbing to the Source toggle
announces it by name and pressed state (its neighbors in the bar were
reached by direct focus calls in the probe, not measured via Tab); the
external-change warning bar is announced. Also measured: keyboard-scrolling
the preview (<kbd>Down</kbd>, <kbd>Page Down</kbd>) produces no
screen-reader feedback at all — the cause lies inside WebKit2GTK's own
AT-SPI bridge, not in xedown's code — and the stale indicator and the
manual-refresh cue are not announced; the only speech when the preview goes
stale is the ordinary "document modified" title change. This project still
will not claim that xedown "works with" or "is accessible to" a screen
reader in general: only one machine, one
Orca version and one WebKitGTK build were tested, on X11 only; the View menu's
route to a mode change and a mouse click on a mode button were never
separately measured. See [docs/known-issues.md](docs/known-issues.md) and the
Orca rows in [docs/manual-smoke-test.md](docs/manual-smoke-test.md).

The rendered preview's *content* is exposed to a screen reader by WebKit
rather than by xedown, so how well a given document reads is largely WebKit's
behaviour, not something xedown controls or has measured.

The `lang` attribute is taken from your desktop's language, not from the
document: xedown does not detect what language a document is written in, and
a wrong `lang` reads worse than none.

## Documentation

See [docs/index.md](docs/index.md) for the documentation index, including the
manual smoke test used before tagging a release.

## License

[MIT](LICENSE)
