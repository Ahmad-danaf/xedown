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
- Light and dark preview themes that follow the desktop theme live, with no
  restart required.
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
- Relative links and images resolve against the document's own directory. An
  unsaved document says so in place of a link or image, instead of guessing
  a path.
- Remote images are never fetched. A visible placeholder is shown in their
  place instead. Nothing xedown does ever reaches out to the network.
- Basic bidirectional text correctness: paragraphs, headings, list items,
  table cells, and blockquote text automatically pick up the correct base
  direction for content such as Arabic or Hebrew, block by block, while
  code stays left-to-right regardless of surrounding text. This is
  automatic per-block direction detection, not a right-to-left interface —
  full right-to-left support is planned for a later version.

## Requirements

- xed 3.0 or newer
- Python 3.10 or newer
- `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1`

Markdown rendering and syntax highlighting are bundled with the plugin. There is
nothing to install with `pip`.

## Installation

```bash
mkdir -p ~/.local/share/xed/plugins
cp -r plugin/xedown plugin/xedown.plugin ~/.local/share/xed/plugins/
```

Then enable **Xedown** in xed under *Preferences → Plugins*.

## Usage

Open a `.md` or `.markdown` file. It opens in Preview mode with a
`Preview | Markdown` bar at the top of the tab. Switch modes with those buttons or
with <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd>, or from *View → Toggle Markdown
Preview*. Both the shortcut and the menu entry are greyed out for files that
are not Markdown. Preview and Markdown each remember their own scroll position,
and viewing never changes the file.

## Known limitations

- Find and go-to-line operate on the source text and are inert while Preview
  is showing; switch to Markdown mode to use them.
- There is no scroll synchronisation between Preview and Markdown modes —
  each mode keeps its own independent scroll position.
- Remote images do not load. This is by design, not a bug: xedown never
  fetches anything from the network.
- In a document that has never been saved, relative links cannot be resolved:
  they render as inert text with no click target and no on-page message.
  Relative images in the same situation do get an explanatory placeholder.
  Save the file to give relative links and images a location to resolve
  against.

## Documentation

See [docs/index.md](docs/index.md) for the documentation index, including the
manual smoke test used before tagging a release.

## License

[MIT](LICENSE)
