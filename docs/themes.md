# Preview themes

xedown ships four preview themes. A theme controls how the rendered document
looks; it does **not** control light or dark. Every theme has a full light and
a full dark palette and follows your desktop's own appearance setting while xed
is running, exactly as xedown 0.1.0 did.

| Identifier | Name | For |
| --- | --- | --- |
| `focused` | Focused | A calm, editor-adjacent page: surfaces close together, one accent, no heading rules. |
| `repository` | Repository | Clean and familiar, for README files and technical documentation. **The default.** |
| `minimal` | Minimal | Decoration removed: quiet borders, generous space, one typeface, square corners. |
| `document` | Document | Long-form reading: serif type, a narrower column, a classical heading hierarchy. |

`repository` is the design xedown 0.1.0 shipped, so upgrading changes nothing
until you choose otherwise.

## Choosing one

Set `preview_theme` in `~/.config/xedown/settings.json`:

```json
{
  "preview_theme": "document"
}
```

xedown reads the file when a Markdown tab opens, so restart xed — or close and
reopen the file — after editing it by hand. Once a settings **window** arrives
later in v0.2, changing the theme there will apply to every open preview in
every window immediately, with no restart. [docs/settings.md](settings.md)
covers how the file is read and what happens when it is malformed.

## Contrast

Legibility is a gate this project enforces, in `tests/unit/test_contrast.py`,
across all four themes in both appearances:

| What | Minimum |
| --- | --- |
| Body text, headings, muted text, links, code text, error text | 4.5:1 |
| Focus indicators | 3:1 — WCAG 1.4.11's own threshold for non-text contrast |
| Syntax colours, in the three themes xedown authors | 4.5:1 |
| Syntax colours in `repository` | 3:1 |

The last row is the one exception, and it is deliberate. `repository` has to
stay identical to 0.1.0, and 0.1.0's code colours come from the bundled
highlight.js stylesheet. Measured against its code background, its weakest
tokens are **3.28:1** in light (built-in names and symbols) and **3.27:1** in
dark (section headings). Raising them would change what an upgrading user sees,
so they stay — recorded here rather than left for someone to discover.

Border and separator colours are not held to a minimum. They carry no
information, and 0.1.0's 1px rules sit well below any text threshold.

## What a theme cannot do

- **Reach the network.** No theme loads a font, image, stylesheet or script
  from anywhere. Nothing xedown does ever touches the network.
- **Use a font you do not have.** Themes name only families that ship with
  Linux Mint, and every stack ends in a generic family, so an unusual system
  still gets something sensible.
- **Touch xed itself.** Theme CSS applies inside the preview and nowhere else.

## When a theme cannot be loaded

An unknown identifier falls back to `repository` silently. A theme whose
stylesheet is missing or unreadable also falls back to `repository`, and that
case is noted on standard error. The preview is never unstyled. If `repository`
itself cannot be read the installation is broken, and xedown says so on the
page instead of rendering anything.

**Stylesheet validity is not checked at run time.** xedown does not parse CSS,
and a syntactically broken stylesheet would be partly applied rather than
rejected. What is checked — the palette contract, contrast, the absence of
remote references — is checked by the test suite, against the stylesheets
xedown ships.
