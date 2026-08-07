# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
- A settings file at `~/.config/xedown/settings.json`, shared by every window
  and applied everywhere the moment it changes. Most of these values have no
  consumer yet — the settings window and the rest of the features that read
  them come later in v0.2. See [docs/settings.md](docs/settings.md).

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
  intervening blank line, unlike GFM. See
  [docs/known-issues.md](docs/known-issues.md). Targeted for v0.2.
