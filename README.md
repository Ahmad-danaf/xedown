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
- External links open in your default browser. Local links to other Markdown
  files open in a new xed tab. Other local files are handed to your desktop's
  file opener, which asks for confirmation first for anything that can run
  code — not just a file with the executable bit set or a `.desktop` entry,
  but any shell, Python, Perl or Ruby script, Windows/desktop executable or
  installer, JAR, AppImage, or shared library, judged by its extension
  whether or not it is marked executable.
- Relative links and images resolve against the document's own directory,
  rather than guessing a path. In a document that has never been saved there
  is no directory to resolve against: a relative image says so in place of the
  image, while a relative link is rendered inert — see the limitations below.
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
tar -xzf xedown-0.1.0.tar.gz -C ~/.local/share/xed/plugins
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
  showing; switch to Markdown mode to use it. Find is no longer among them —
  `Ctrl+F` in Preview searches the rendered document (see *Finding text*).
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
- In a document that has never been saved, relative links cannot be resolved:
  they render as inert text with no click target and no on-page message.
  Relative images in the same situation do get an explanatory placeholder.
  Save the file to give relative links and images a location to resolve
  against.
- xedown supports selected GitHub-flavored Markdown features (tables, task
  lists, strikethrough, fenced code, footnotes, and lists that interrupt a
  paragraph), not full GFM compatibility.
- xed 3.8.9 itself can crash when you close a window after moving a tab
  between windows. This happens with xedown uninstalled and is not something
  the plugin can fix or avoid; save before dragging tabs between windows.
  Details and the stack trace are in
  [docs/known-issues.md](docs/known-issues.md).
- Appearance settings — the theme, content width, text size and custom
  stylesheet — are chosen by editing `~/.config/xedown/settings.json`, and
  xedown reads that file once when xed starts. The settings window that will
  edit them, and apply a change to open previews immediately, is not in this
  release. The one exception is the custom stylesheet **file**: its contents
  are watched, so saving an edit to it updates open previews straight away.
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
changes that surface's checked state to match; both are mechanisms a screen
reader can use to signal what happened. The rendered page carries a
`role="document"` landmark and, when your desktop's language is known, a
`lang` attribute. The focus ring's contrast against every surface it is drawn
on meets WCAG's 3:1 non-text threshold, in all four preview themes, light and
dark.

**The screen-reader speech itself has not been tested.** Everything above is
checked against xed's live accessible tree or by unit test — not by listening
with a screen reader. **Orca on Linux Mint** is the only screen reader this
project targets or has any plan to test against; it has not been run yet, and
until it has, this file will not claim that xedown "works with" or "is
accessible to" a screen reader. See
[docs/known-issues.md](docs/known-issues.md) and the Orca rows in
[docs/manual-smoke-test.md](docs/manual-smoke-test.md).

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
