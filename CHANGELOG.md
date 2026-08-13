# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [0.3.0] - 2026-08-13

Remote images — blocked by default, offered per document, and available
globally when you want them — plus a decode-size guard that closes a
pre-existing hole in every inline image too.

### Upgrading from 0.2.0

Everything renders exactly as it did, with one exception: a document
containing an enormous inline (`data:`) image — one whose declared size
would cost hundreds of megabytes to decode — now shows a placeholder where
it previously rendered. See *Fixed* below. Nothing else changes until you
turn on `remote_images` or click a document's own **Load**.

### Added

- **Remote images, off by default.** A `https://` image in a document is
  never fetched until you say so: blocked, it shows a placeholder naming the
  address; the mode bar grows a chip — "N remote images [Load]" — that
  says how many a document has and fetches them for that tab, for as long as
  the tab stays open. Turn fetching on for every document instead with
  `"remote_images": "https"` in *Preferences → Images and changes made
  outside xed*, whose help text spells out what loading an image discloses:
  your IP address, roughly where you are, and when you opened the document.
  `http://` is never fetched, under any setting or button — there is no
  escape hatch. See [README.md](README.md) and [SECURITY.md](SECURITY.md).
- **xedown fetches, and nothing else does.** The preview page itself is
  never granted `http:` or `https:` — its content security policy is
  unchanged in that respect. Only xedown's own fetch code reaches the
  network: only for images, only over https, only to destinations that
  resolve to public addresses, and never with cookies, a `Referer`, or
  credentials in the URL. Nothing fetched is ever written to disk.
- Loading, broken, offline, refused and over-size states each get their own
  wording, and an image shows a loading skeleton while its fetch is in
  flight rather than an empty gap.
- `remote_images` is renamed. It is now the fetch policy above —
  `never`/`https`, defaulting to `never` — and the setting it used to be,
  which decided how any image that could not be shown at all appeared
  (`placeholder`/`alt`/`hidden`), is now `image_fallback`. A settings file
  written before this rename still works: an old-style `remote_images`
  value is read as `image_fallback` automatically, without rewriting the
  file. See [docs/settings.md](docs/settings.md#remote-images).

### Fixed

- **Every image xedown can measure is now capped at 25 megapixels and 32768
  pixels on a side before xedown will decode it — inline (`data:`) images as
  well as the new remote ones.** A document containing an enormous inline
  image rendered it in full before this release, at a decode cost of up to
  hundreds of megabytes of memory for a file only kilobytes long; it now
  shows a placeholder saying the image is too large to display safely
  instead. Inline payloads are measured in either spelling, base64 or
  percent-encoded. An inline image in a format xedown cannot measure (AVIF)
  is still shown as it always was. No setting raises or removes this cap.

### Known issues

- Closing xed can be delayed by up to 15 seconds by a remote image fetch
  already in progress: a queued fetch is cancelled, a running one is not,
  and 15 seconds is the wall-clock deadline on one whole fetch. (The
  5-second timeout on the connection is a socket timeout — it bounds a
  single read, not the transfer.)
- AVIF images cannot be loaded remotely; inline `data:` AVIF is unaffected.
- A DNS-rebinding race against the destination check is a known, accepted
  residual — blind, with no channel for a document to learn what it found.

  See [docs/known-issues.md](docs/known-issues.md) for these and smaller
  surprises, each with what to do about it.

## [0.2.0] - 2026-08-12

Settings and a settings window, four preview themes, find in the preview, a
preview that follows the file on disk, right-to-left layout, copy buttons on
code blocks, and keyboard control of all of it.

### Upgrading from 0.1.0

Your files open exactly as they did, and every setting ships at 0.1.0's
behaviour: Preview is still the mode a Markdown file opens in, **Repository**
is still the theme and is still 0.1.0's stylesheet, and the content width and
text size are 0.1.0's. Five things look different straight away, each of them
deliberate:

- Code blocks show a **Copy** button when you hover them
  (`"code_copy_buttons": false` removes it).
- Task-list checkboxes are drawn by xedown in the theme's colours instead of
  by the browser.
- A very tall image is scaled to fit the window instead of running past it.
- A table too wide for its column scrolls inside its own area instead of being
  squeezed into it.
- Selected text has a colour the theme owns.

Nothing else changes until you change a setting, and **Restore defaults** in
the settings window puts everything back.

### Added

- **A settings window** covering every xedown setting, reachable from
  *Preferences → Plugins → Xedown → Preferences* and from *View → Markdown
  Preview Settings*. Changes apply to every open preview as you make them, and
  **Restore defaults** returns to xedown 0.1.0's behaviour.
- **A settings file** at `~/.config/xedown/settings.json`, shared by every
  window, for the same settings without the window. xedown reads it when it
  starts, so restart xed after editing it by hand. See
  [docs/settings.md](docs/settings.md).
- **Four preview themes** — **Focused**, **Repository**, **Minimal** and
  **Document** — each a complete design rather than a recolour, and each with a
  full light and dark palette that keeps following your desktop. Repository is
  the default and is 0.1.0's design, so the theme you are reading does not
  change until you pick another. See [docs/themes.md](docs/themes.md).
- **Content width and text size**, as `content_width_rem` (30–100, default 46)
  and `text_size_px` (11–28, default 16). Text size scales the whole document
  together rather than only the body text. Both defaults are 0.1.0's.
- **Your own stylesheet**, layered on top of the built-in theme. Point
  `custom_stylesheet` at a CSS file; saving an edit to that file updates every
  open preview. If the file is missing, unreadable, empty, over 512 KiB or
  otherwise unusable, the preview keeps working on the built-in theme and a bar
  at the top says which file is at fault and why. Nothing in a stylesheet can
  reach the network — web fonts and `@import` silently do nothing, by design.
  See [docs/themes.md](docs/themes.md).
- **Find in the preview.** <kbd>Ctrl</kbd>+<kbd>F</kbd> searches the rendered
  document, with match counting, wrapping navigation, a case toggle and
  highlighting themed for all four themes in both appearances.
  <kbd>Ctrl</kbd>+<kbd>F</kbd> over the Markdown source is still xed's own
  find. This closes the gap 0.1.0 documented.
- **The preview follows changes made to the file outside xed** — by git, by a
  terminal command, by another editor, by an AI coding agent. With no unsaved
  edits it simply updates, at the scroll position it had, with no dialog and
  nothing to press. With unsaved edits nothing is replaced: the preview keeps
  showing your work and a dismissible bar says the file changed on disk,
  offering **Reload…**, which hands off to xed's own Revert and its own
  confirmation. **xedown never writes to your text.** One save by another
  program is one update, not a flicker of several, and a burst of writes
  settles into a single render. Deleting the file, replacing it, and moving it
  away and back are all handled quietly. Set `"watch_external_changes": false`
  to switch the whole thing off, and it stops in every tab already open.
- **Four keyboard shortcuts**, all of them also in the *View* menu with their
  keys shown: <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> switches between
  the two modes, <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd> goes to Preview,
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd> goes to Markdown, and
  <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> refreshes the preview now.
  Going to the mode you are already in does nothing. They work whether focus is
  in the editor or the preview, they are greyed out for files that are not
  Markdown, and none of them takes a key xed already uses — checked against the
  installed xed rather than assumed.
- **Copy and select-all act on what you can see.** While the preview is
  showing, <kbd>Ctrl</kbd>+<kbd>C</kbd> copies the rendered selection and
  <kbd>Ctrl</kbd>+<kbd>A</kbd> selects the rendered document; right-clicking a
  selection offers **Copy**, and the preview offers nothing else a browser
  would. In Markdown mode every editing key behaves exactly as xed always has.
  Selected text now has a colour each theme owns, legible in light and dark.
- **The mode a file opens in.** `"default_mode": "markdown"` opens Markdown
  files in the source instead of the preview, and `"remember_mode_per_file"`
  (on by default) reopens each file in whichever mode you last left it in.
  Remembered modes live in `~/.config/xedown/modes.json` and are capped at the
  200 most recent files.
- **Control over refreshing.** `"auto_refresh": false` stops the preview
  re-rendering by itself; the mode bar then shows a **Refresh** button, marked
  when the preview is behind the document. `"refresh_delay_ms"` sets how long
  xedown waits after a change, and a new value reaches tabs that are already
  open.
- **Right-to-left documents now lay out as well as they read.** In an Arabic or
  Hebrew document the list bullets and their indentation, the quote bar, the
  table's column order, the footnote marker and its back-reference, and the
  copy button on a code block all move to the correct side, while each
  paragraph, heading and cell still picks its own direction from its own
  content — so an English paragraph inside an Arabic document still reads left
  to right. A list item aligns with its list rather than with itself, so every
  bullet in a list stays on the same side; the item's own text still reads in
  its own direction. Fenced blocks, inline code and a link whose text is a URL
  or a path stay left-to-right and no longer disturb the sentence around them.
  Set `"text_direction"` to `ltr` or `rtl` to override the automatic choice for
  the whole document. xedown's own interface follows your desktop's direction,
  not your document's. You can also mark a run yourself with `<bdi>…</bdi>` or
  `dir="ltr"`, which the preview now keeps.
- **A copy button on every code block**, revealed on hover and reachable by
  keyboard. It copies exactly what the author wrote, confirms briefly, and says
  so when a copy fails rather than pretending it worked. Turn it off with
  `"code_copy_buttons": false` and it disappears from every open preview at
  once.
- **Task-list checkboxes drawn from the selected theme** instead of the
  browser's default control, in both light and dark. They remain read-only:
  xedown never writes to your file.
- **Wide tables now scroll inside their own area**, with a shadow at whichever
  edge has more to show, instead of being squeezed into unreadable columns. The
  page itself never scrolls sideways.
- **Images fit the reading column**, and a very tall one now fits the window
  too, keeping its proportions. A small image keeps its own size, and an image
  you sized yourself in HTML is left alone.
- **An image that cannot be shown now says which of four things happened**: not
  found, could not be read, remote and never fetched, or a reference xedown
  could not make sense of at all. Your alt text is shown alongside.
  `"remote_images"` chooses how they all appear — `placeholder`, `alt` or
  `hidden`. All three are presentation only; xedown still fetches nothing.
- **The preview keeps the keyboard while it is showing.** Whenever focus lands
  on the hidden source text instead — switching to the tab, or dismissing
  something that had focus — the preview takes it back, so the arrow keys and
  <kbd>Page Down</kbd> scroll what you are reading straight away.
- **An accessibility pass over everything v0.2 built.** Every control xedown
  creates takes its accessible name from a single source of truth — the mode
  buttons, the refresh button, the stale indicator, the search bar and the info
  bars — and the preview itself is named; a live audit against xed's own
  accessible tree confirms every one of those names. Switching modes moves
  keyboard focus to the surface you land on, changes its checked state to
  match, and announces the mode you switched to; the announcement is suppressed
  while a mode button itself has keyboard focus, so activating one does not say
  the mode twice. The rendered document page carries a `role="main"` landmark
  and, when your desktop's language is known, a `lang` attribute — an error
  page carries neither. The focus ring meets WCAG 1.4.11's 3:1 non-text
  threshold against every surface it is drawn on, in all four themes, light and
  dark, along with every semantic colour pair xedown draws. **Screen-reader
  speech was measured against Orca 46.1 on Linux Mint (X11), on one machine**:
  what was measured, what was inferred, and what stays silent — keyboard
  scrolling of the preview, and the stale/refresh cue — are set out in the
  README's *Accessibility* section and in
  [docs/known-issues.md](docs/known-issues.md).

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

### Known issues

- xedown supports selected GitHub-flavored Markdown features (tables, task
  lists, strikethrough, fenced code, footnotes, and lists that interrupt a
  paragraph), not full GFM compatibility.
- The smaller limitations — a bare path in right-to-left prose, copy on a
  non-Latin keyboard layout, a document opened through a symbolic link, and
  what a screen reader does and does not say — are described in
  [docs/known-issues.md](docs/known-issues.md), each with what to do about it.

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
  intervening blank line, unlike GFM (fixed in 0.2.0).
