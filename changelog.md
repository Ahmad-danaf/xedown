# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- The preview follows changes made to the file outside xed — by git, by a
  terminal command, by another editor, by an AI coding agent. With no unsaved
  edits it simply updates, at the scroll position it had, with no dialog and
  no button to press. With unsaved edits nothing is replaced: the preview
  keeps showing your work and a dismissible bar says the file changed on disk,
  offering **Reload…**, which hands off to xed's own Revert and its own
  confirmation. **xedown never writes to your text.** One save by another
  program is one update, not a flicker of several, and a burst of writes
  settles into a single render. Deleting the file, replacing it, and moving it
  away and back are all handled quietly. Set `"watch_external_changes": false`
  to switch the whole thing off, and it stops in every tab already open.
- Four keyboard shortcuts, all of them also in the *View* menu with their keys
  shown: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> switches between the
  two modes, <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd> goes to Preview,
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd> goes to Markdown, and
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> refreshes the preview now.
  Going to the mode you are already in does nothing. They work whether focus
  is in the editor or the preview, they are greyed out for files that are not
  Markdown, and none of them takes a key xed already uses — checked against
  the installed xed rather than assumed.
- Copy and select-all now act on what you can see. While the preview is
  showing, <kbd>Ctrl</kbd>+<kbd>C</kbd> copies the rendered selection and
  <kbd>Ctrl</kbd>+<kbd>A</kbd> selects the rendered document; right-clicking a
  selection offers **Copy**, and the preview offers nothing else a browser
  would. In Markdown mode every editing key behaves exactly as xed always
  has. Selected text now has a colour each theme owns, legible in light and
  dark.
- `"default_mode": "markdown"` opens Markdown files in the source instead of
  the preview, and `"remember_mode_per_file"` (on by default) reopens each
  file in whichever mode you last left it in. Remembered modes live in
  `~/.config/xedown/modes.json` and are capped at the 200 most recent files.
- `"auto_refresh": false` stops the preview re-rendering by itself; the mode
  bar then shows a **Refresh** button, marked when the preview is behind the
  document. `"refresh_delay_ms"` sets how long xedown waits after a change,
  and a new value reaches tabs that are already open.
- Right-to-left documents now lay out as well as they read. In an Arabic or
  Hebrew document the list bullets and their indentation, the quote bar, the
  table's column order, the footnote marker and its back-reference, and the
  copy button on a code block all move to the correct side, while each
  paragraph, heading and cell still picks its own direction from its own
  content — so an English paragraph inside an Arabic document still reads
  left to right. A list item aligns with its list rather than with itself, so
  every bullet in a list stays on the same side; the item's own text still
  reads in its own direction.
  Fenced blocks, inline code and a link whose text is a URL or
  a path stay left-to-right and no longer disturb the sentence around them.
  Set `"text_direction"` to `ltr` or `rtl` in
  `~/.config/xedown/settings.json` to override the automatic choice for the
  whole document. xedown reads that file when it starts, so restart xed after
  editing it. xedown's own interface follows your desktop's direction, not
  your document's. You can also mark a run yourself with `<bdi>…</bdi>` or
  `dir="ltr"`, which the preview now keeps.
- A copy button on every code block, revealed on hover and reachable by
  keyboard. It copies exactly what the author wrote, confirms briefly, and
  says so when a copy fails rather than pretending it worked. Turn it off
  with `"code_copy_buttons": false` and it disappears from every open
  preview at once.
- Task-list checkboxes drawn from the selected theme instead of the
  browser's default control, in both light and dark. They remain read-only:
  xedown never writes to your file.
- Wide tables now scroll inside their own area, with a shadow at whichever
  edge has more to show, instead of being squeezed into unreadable columns.
  The page itself never scrolls sideways.
- Images fit the reading column, and a very tall one now fits the window
  too, keeping its proportions. A small image keeps its own size, and an
  image you sized yourself in HTML is left alone.
- An image that cannot be shown now says which of four things happened: not
  found, could not be read, remote and never fetched, or unresolvable
  because the document has not been saved. Your alt text is shown alongside.
  `"remote_images"` chooses how they all appear — `placeholder`, `alt` or
  `hidden`. All three are presentation only; xedown still fetches nothing.
- Your own stylesheet on top of the built-in theme. Point `custom_stylesheet`
  at a CSS file in `~/.config/xedown/settings.json`; saving an edit to that
  file updates every open preview. If the file is missing, unreadable, empty,
  over 512 KiB or otherwise unusable, the preview keeps working on the built-in
  theme and a bar at the top says which file is at fault and why. Nothing in a
  stylesheet can reach the network — web fonts and `@import` silently do
  nothing, by design. See [docs/themes.md](docs/themes.md).
- Content width and text size, as `content_width_rem` (30–100, default 46) and
  `text_size_px` (11–28, default 16). Text size scales the whole document
  together rather than only the body text. Both defaults reproduce 0.1.0
  exactly.
- Four preview themes — **Focused**, **Repository**, **Minimal** and
  **Document** — each a complete design rather than a recolour, and each with a
  full light and dark palette that keeps following your desktop. Choose one
  with `preview_theme` in `~/.config/xedown/settings.json`. **Repository is the
  default and is identical to 0.1.0**, so upgrading changes nothing until you
  pick another. See [docs/themes.md](docs/themes.md).
- A settings file at `~/.config/xedown/settings.json`, shared by every window.
  See [docs/settings.md](docs/settings.md) for what each one does and the
  settings window (below) that edits them.
- Find in the preview: `Ctrl+F` searches the rendered document, with match
  counting, wrapping navigation, a case toggle and highlighting themed for all
  four themes in both appearances. `Ctrl+F` over the Markdown source is still
  xed's own find. Closes v0.1's documented gap.
- While the preview is showing, the keyboard now stays with it: whenever
  focus lands on the hidden source text instead — switching to the tab, or
  dismissing something that had focus — the preview takes it back, so the
  arrow keys and <kbd>Page Down</kbd> scroll what you are reading straight
  away.
- An accessibility pass over everything v0.2 built. Every control xedown
  creates takes its accessible name from a single source of truth — the mode
  buttons, the refresh button, the stale indicator, the search bar and the
  info bars — and the preview itself is named; a live audit against xed's own
  accessible tree confirms every one of those names, and confirms that
  switching modes moves keyboard focus to the surface you land on and changes
  its checked state to match — both mechanisms a screen reader can use to
  signal what happened. The same live audit confirms the rendered document
  page carries a `role="main"` landmark and, when your desktop's language is
  known, a `lang` attribute — an error page carries neither. The focus ring's
  contrast — against the page
  background and the code-block background, in all four themes, light and
  dark — meets WCAG 1.4.11's 3:1 non-text threshold, along with every
  semantic colour pair xedown draws, checked by unit test. **Screen-reader
  speech has now been checked against Orca 46.1 on Linux Mint** (X11,
  `scripts/run-orca-tests.sh`), on one machine: the mode switch announces
  (below), tabbing to the Source toggle announces it by name and pressed
  state (its neighbors in the bar were reached by direct focus calls in the
  probe, not measured via Tab), and the external-change warning bar is
  announced.
  Keyboard-scrolling the preview and the stale/refresh indicator are not
  announced — see [docs/known-issues.md](docs/known-issues.md).
- The <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> mode switch now announces
  itself to a screen reader: switching to Markdown source says "Markdown
  source", switching back says "Preview", spoken through `Atk.Object`'s
  `announcement` signal from the mode bar's own accessible object — both
  directions measured live, reproducibly, against Orca 46.1 on Linux Mint.
  The announcement is suppressed only while a mode toggle button itself has
  focus, so tabbing to a mode button and activating it does not repeat the
  mode name a second time; switching from anywhere else, including with the
  Refresh button focused (also in the mode bar, but not a mode toggle),
  still announces normally. The suppression itself was measured live for the
  Source-ward direction (tabbing to and activating the "Markdown source"
  button); the reverse — tabbing back to an already-focused, now-unpressed
  Preview button and activating it — was not separately measured, though the
  check in `set_mode` is not direction-specific.
- A settings window covering every xedown setting, reachable from
  *Preferences → Plugins → Xedown → Preferences* and from *View → Markdown
  Preview Settings*. Changes apply to every open preview as you make them,
  and **Restore defaults** returns to xedown 0.1.0's behaviour.

### Fixed

- A list now starts a list when it follows a paragraph directly, with no blank
  line between them, the way GitHub renders it. This works for `-`, `*`, `+`
  and `1.`, and inside blockquotes, list items and footnotes as well as at the
  top level. As on GitHub, an ordered list has to start at `1.` to interrupt a
  paragraph — one starting at any other number still needs a blank line, which
  is what keeps prose that wraps onto a line beginning with a number ("…was /
  1985. What a year.") a paragraph.
- A preview showing an error page could never be refreshed back into a
  document: the swap-in-place path cannot reach an error page, and marked the
  preview up to date anyway. It now reloads instead.

## [0.1.0] - 2026-08-05

### Added

- In-tab Markdown preview for `.md` and `.markdown` files, with Preview and
  Markdown modes and no extra tab or window.
- Rendering for headings, paragraphs, bold and italic text, strikethrough,
  ordered and unordered lists, task lists, links, local images, blockquotes,
  horizontal rules, tables, inline code and fenced code blocks.
- Footnotes and attribute lists, with in-page scrolling to footnote anchors.
- Syntax highlighting from a bundled custom highlight.js build covering 31 languages.
- Light and dark themes that follow the desktop.
- Automatic preview refresh while the preview is visible.
- External links open in the default browser; local Markdown links open in a new tab.
- Relative links and images resolved from the document's directory.
- Per-mode scroll memory, with text and cursor position preserved across switches.
- Bundled Markdown and highlighting dependencies, so no `pip` step is required.
- A downloadable release archive that unpacks straight into the xed plugins
  directory, with no checkout, `apt` or `pip` step.
- Basic bidirectional text correctness: paragraphs, headings, list items,
  table cells, and blockquote text pick up the correct base direction
  automatically for right-to-left content such as Arabic or Hebrew, while
  code stays left-to-right regardless of surrounding text. This is
  per-block automatic direction detection, not a right-to-left interface.

### Known issues

- xedown supports selected GitHub-flavored Markdown features (tables, task
  lists, strikethrough, fenced code, and footnotes), not full GFM
  compatibility. A list does not currently interrupt a paragraph without an
  intervening blank line, unlike GFM (fixed in Unreleased).
