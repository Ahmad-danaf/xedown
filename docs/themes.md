# Preview appearance

How the preview looks: the four built-in themes, your own stylesheet on top of
one, and the width and size of the text. The filename stays `themes.md` so
existing links keep working.

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

xedown reads the file once per xed session — the first Markdown tab you open
creates the shared settings store, and every tab after that reuses it — so a
hand edit takes effect only after you restart xed; closing and reopening the
file is not enough. Once a settings **window** arrives later in v0.2, changing
the theme there will apply to every open preview in every window immediately,
with no restart. [docs/settings.md](settings.md) covers how the file is read
and what happens when it is malformed.

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
- **Use a font you do not have.** No theme ever downloads a font — each stack
  only names families and always ends in a generic one, so a system with none
  of the named fonts still gets something sensible.
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

## Your own stylesheet

Point `custom_stylesheet` at a CSS file and it is applied **on top of** the
selected theme, so it can change a few details or override the whole
appearance.

```json
{ "custom_stylesheet": "~/.config/xedown/mine.css" }
```

`~` is expanded. A relative path is taken relative to the folder holding
`settings.json`. Environment variables are not expanded — `$HOME/mine.css` is a
path with a dollar sign in it.

Editing that file and saving it updates every open preview. You do not need to
restart xed or reopen the file.

Two hooks worth knowing, because they are what separates a stylesheet that
works from one that fights the theme. The body element carries the desktop's
appearance and the selected theme:

```css
body.dark p            { color: #ddd; }   /* only in a dark desktop */
body.xedown-theme-document h1 { color: #333; }  /* only under Document */
```

Clear the setting — set it to `null` — and the preview goes back to the plain
built-in theme.

### What a custom stylesheet cannot do

xedown never touches the network, and the preview's content security policy
enforces it rather than trusting the stylesheet. This is the part that
surprises people, so it is spelled out:

| In your stylesheet | Result |
| --- | --- |
| `font-family: "Iosevka"` — a font installed on this machine | **works** |
| `background-image: url(file:///home/you/paper.png)` | **works** |
| `background-image: url(data:image/png;base64,…)` | **works** |
| `@import url(…)` — **including a local file** | does nothing |
| `@font-face { src: url(…) }` — including a local font file | does nothing |
| anything at an `http://` or `https://` address | does nothing |

To use a font, install it (drop it in `~/.local/share/fonts` and run
`fc-cache -f`) and then name it. A web font, or a font file loaded through
`@font-face`, will silently do nothing.

Your stylesheet also only ever affects the preview. It cannot reach xed's own
menus, tabs or editor.

### When a stylesheet cannot be used

The preview still renders, using the selected built-in theme, and a bar at the
top of the page says which file is at fault and why:

| Condition | What the bar says |
| --- | --- |
| the file does not exist | *was not found* |
| it is a folder, a device, or a pipe | *is not a file* |
| it cannot be opened | *could not be read (…)* |
| it is not UTF-8 text | *is not valid UTF-8 text* |
| it is empty, or only whitespace | *is empty* |
| it is over 512 KiB | *is larger than the 512 KiB limit* |
| it contains the text `</style` | *contains "</style", which cannot be embedded safely* |

That last one is refused rather than patched around: the sequence would end
the preview's stylesheet early and put the rest of your file into the page as
markup. It only reaches a stylesheet through a pasted HTML fragment.

**CSS syntax is not checked**, the same as for the themes xedown ships. A
stylesheet with a typo in it is partly applied rather than rejected, and you
will see the parts that worked.

## Content width and text size

| Setting | Range | Default |
| --- | --- | --- |
| `content_width_rem` | 30 to 100 | 46 |
| `text_size_px` | 11 to 28 | 16 |

Both are **base** values that each theme multiplies by its own scales, so the
number you set is not always the number rendered — `document` deliberately
renders a narrower column than its base width suggests. The defaults reproduce
xedown 0.1.0 exactly.

Content width is the reading measure. Roughly what each part of the range
suits, at the default text size:

| `content_width_rem` | ≈ characters per line | Suits |
| --- | --- | --- |
| 30 | ~52 | a focused, narrow column |
| 38 | ~68 | the classic ideal measure |
| 46 | ~84 | the default |
| 60 | ~112 | wide prose |
| 72–100 | ~136–190 | wide tables, code, and large displays |

The top of that range is **not** a comfortable measure for prose. It is there
because wide tables and technical documents genuinely want the room, and
because a limit exists to stop nonsense rather than to enforce typography.

When the window is narrower than your chosen width, the content fits the
window instead. The page itself never scrolls sideways at any setting: code
blocks and tables scroll inside their own area, and images always fit the
column.

Text size scales the whole document together — body text, headings, lists,
code, tables, captions and placeholders all keep their relationships. It is
not a body-text-only change.
