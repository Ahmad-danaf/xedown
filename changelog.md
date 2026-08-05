# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-08-04

### Added

- In-tab Markdown preview for `.md` and `.markdown` files, with Preview and
  Markdown modes and no extra tab or window.
- Rendering for headings, paragraphs, bold and italic text, ordered and unordered
  lists, task lists, links, local images, blockquotes, horizontal rules, tables,
  inline code and fenced code blocks.
- Syntax highlighting from a bundled custom highlight.js build covering 31 languages.
- Light and dark themes that follow the desktop.
- Automatic preview refresh while the preview is visible.
- External links open in the default browser; local Markdown links open in a new tab.
- Relative links and images resolved from the document's directory.
- Per-mode scroll memory, with text and cursor position preserved across switches.
- Bundled Markdown and highlighting dependencies, so no `pip` step is required.
