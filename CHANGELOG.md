# Changelog

All notable user-facing changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-17

The first stable public release, and the first public release since 0.2.0.
v1.0 hardens the existing same-tab Markdown preview rather than trying to
implement every Markdown feature.

0.3.0 below was a development milestone that was never tagged or published, so
everything it introduced reaches readers for the first time here. This section
therefore describes the upgrade from 0.2.0, the newest version anyone can
already be running.

### Added

- Remote HTTPS images, blocked by default, with per-tab and global permission.
- Privacy-preserving fetch controls: public destinations only, redirect checks,
  no credentials or ambient browser headers, bounded downloads, bounded decode
  dimensions, and an in-memory cache.
- Safe install, upgrade, and uninstall scripts with compatibility preflight.
- Large-document guards that stop live rendering past 131,072 characters and
  defer an initial preview past 262,144 characters.
- Rendering for collapsible sections, keyboard text, definition lists,
  abbreviations, captions, aligned blocks, and opted-in Markdown inside HTML.
- Public installation, uninstall, preferences, privacy, compatibility,
  troubleshooting, contribution, conduct, and security documentation.

### Changed

- Compatibility claims now name the exact live-tested runtime. Nearby versions
  are expected to work but explicitly unverified; Python 3.10 and 3.11 are
  described as CI unit-tested only.
- Markdown rendering is closer to GitHub for list nesting, fenced blocks,
  heading syntax, hard line breaks, ordered-list starts, table alignment, and
  relative links containing fragments.
- Repeated headings no longer trigger disproportionate render time.
- Release hardening: plugin activation, deactivation, and editor shutdown are
  now verified by twelve automated lifecycle scenarios, and the installer
  flows by a sandboxed install/upgrade/uninstall harness.

### Security

- The preview remains isolated by an allowlist sanitizer and strict CSP.
- xedown itself makes network requests only for permitted remote images; the
  page never receives general `http:` or `https:` access.
- Inline and remote measurable images are refused above 25 megapixels or
  32,768 pixels on either side.

### Known limitations

- Markdown inside block HTML requires `markdown="1"`; several smaller
  differences from GitHub remain documented in
  [docs/markdown-compatibility.md](docs/markdown-compatibility.md).
- Rendering still occurs on xed's main thread, so a requested large render can
  pause the editor.
- xed 3.8.9 has an intermittent tab-move shutdown crash that also reproduces
  without xedown installed.
- Remote AVIF is unsupported, a running image fetch can delay shutdown by up to
  15 seconds, and a blind DNS-rebinding race remains accepted.

Detailed compatibility, performance, security, accessibility, and lifecycle
evidence remains in the focused documents under `docs/`.

## [0.3.0] - 2026-08-13 — never released

Kept as a development record. 0.3.0 was never tagged or published; the only
public releases before 1.0.0 are 0.2.0 and 0.1.0. Everything below shipped to
readers in 1.0.0.

### Added

- Remote HTTPS images, blocked by default and permitted per tab or globally.
- Fetch isolation, destination checks, redirect policy, byte/decode limits,
  concurrency bounds, and memory-only caching.
- Distinct blocked, loading, offline, failed, and oversized image states.

### Changed

- The old image-display `remote_images` setting became `image_fallback`; legacy
  values migrate automatically. `remote_images` now controls network policy.

### Known limitations

- Remote AVIF is unsupported.
- A running image fetch can delay shutdown by up to 15 seconds.
- A blind DNS-rebinding race remains accepted.

## [0.2.0] - 2026-08-12

### Added

- A complete preferences window and JSON settings store.
- Focused, Repository, Minimal, and Document themes with live light/dark
  appearance, adjustable width and size, and custom CSS.
- Preview search, keyboard mode/refresh shortcuts, code-copy buttons, table and
  image layout improvements, right-to-left layout, remembered file modes, and
  configurable refreshing.
- Preview updates for changes made outside xed without writing to the source
  buffer.
- Accessibility naming, focus, contrast, and narrow Orca verification.

### Fixed

- Lists can interrupt paragraphs in the common GitHub-compatible cases.
- Error pages can refresh back into rendered documents.

## [0.1.0] - 2026-08-05

### Added

- Same-tab **Preview | Markdown** workflow for `.md` and `.markdown` files.
- Bundled Markdown rendering and syntax highlighting.
- Tables, task lists, strikethrough, footnotes, attribute lists, local images,
  safe links, sanitization, CSP isolation, scroll memory, and live preview
  refresh.
