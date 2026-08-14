# Markdown compatibility

xedown renders selected GitHub-flavored Markdown — tables, task lists,
strikethrough, fenced code, footnotes, and lists that interrupt a paragraph —
not all of GFM. This file lists every difference from GitHub's own rendering
that is known, says why each one is the way it is, and tells you what to write
instead where anything can be done about it.

## How this was measured

The differences below are not a reading of two specifications. They come from
rendering real documents twice and diffing the results:

- **The oracle is cmark-gfm**, the parser GitHub itself uses, reached through
  the `cmarkgfm` package and rendered in its unsafe mode so that raw HTML in a
  document survives to be compared rather than being escaped away.
- **The corpus is 31 real README files** — 1,827,710 bytes from public
  projects, chosen across five strata: 15 mainstream projects, 5 documentation
  tools, 4 "awesome" lists, 4 non-Latin documents (Arabic, Hebrew, Japanese,
  Chinese) and 3 enormous ones. Every entry is pinned to a commit SHA recorded
  in `tests/compat/corpus/MANIFEST.json`, so `scripts/fetch-corpus.sh` fetches
  the same bytes months later and the measurement stays reproducible. The
  corpus is not committed; the script rebuilds it.
- **Four synthetic documents** stand beside it (`tests/compat/synthetic/`) for
  constructs real READMEs happen not to contain.

Each document is rendered three ways — cmark-gfm raw, cmark-gfm put through
xedown's own sanitizer, and xedown's own pipeline — which separates a parser
difference from something xedown's HTML allowlist removed. Counts are taken by
an element-and-attribute census of the two renders, not by counting diff
chunks: a chunk boundary is an artifact of how the text was split, and one
chunk routinely holds several unrelated causes.

**What the corpus cannot tell you:** a construct that appears nowhere in
1.8 MB of real READMEs is measured as zero before and zero after, which proves
nothing either way. Where a claim below rests on a synthetic fixture rather
than on real documents, it says so.

## What the compatibility pass closed

Elements and attributes GitHub renders that xedown's allowlist used to remove,
before this release and now:

| Construct | Before | Now | Evidence |
| --- | --- | --- | --- |
| `<details>` | 66, in 4 documents | 0 | real corpus |
| `<summary>` | 66, in 4 documents | 0 | real corpus |
| `align=` | 59, in 10 documents | 2, in 2 documents | real corpus |
| `<ol start>` | 56, in 3 documents | 0 | real corpus (1 document) and synthetic |
| `<kbd>` | 3 | 0 | **synthetic fixture only** |
| `<dl>` / `<dt>` / `<dd>` | 1 / 2 / 2 | 0 | **synthetic fixture only** |
| `<caption>` | 1 | 0 | **synthetic fixture only** |
| `<abbr>` | 1 | 0 | **synthetic fixture only** |

The first four rows are the ones that carry weight: they come from documents
people actually published. The last four occur nowhere in the 31 READMEs, so
their real evidence is a deliberately-written battery
(`tests/compat/synthetic/constructs.md`) that exists precisely so those rows
have something to move. They show the widening works on those constructs; they
do not show anyone needed it.

The two remaining `align=` attributes are on `<picture>` and on `<tbody>` —
one element xedown does not render at all (below) and one where the attribute
would do nothing.

On the parser side, over the same 35 documents, divergences from cmark-gfm
fell from **3195 to 619**. The number of documents carrying at least one fell
only from 35 to 33, and that is the honest shape of it: almost every README
has a badge image, and a blocked remote image is a deliberate difference that
will never go away.

## Differences by design

### A bare URL or email address is not turned into a link

GitHub links `https://example.com` typed into running prose. xedown displays
it as written.

Nothing is lost or misstated — the address is on screen in full and can be
selected and copied. Autolinking is a GFM extension, and xedown targets
selected GFM rather than all of it. Write `<https://example.com>` or
`[example](https://example.com)` and both renderers agree.

### A remote image is not fetched, and says so

GitHub loads every image. xedown shows a placeholder naming the address, the
alt text and the reason.

This is xedown's central privacy decision, not a gap: opening a document
should not tell a stranger's server your IP address, roughly where you are,
and when you read it. The placeholder is also more use than a broken-image
icon, because it names what is missing. Allow fetching for one tab with
**Load** in the mode bar, or for every document with `"remote_images":
"https"` in Preferences. See [settings.md](settings.md#remote-images) and
[../SECURITY.md](../SECURITY.md).

Measured on the corpus with fetching off — the default a new reader gets —
this accounts for 150 placeholders across 25 of the 31 READMEs, which is why
so few documents reach zero differences.

### `<b>` and `<i>` keep their words and lose their emphasis

`<p>a <b>bold</b> word</p>` renders on GitHub as **bold**; xedown renders the
words, unemphasised.

No content is dropped and nothing reads wrongly, which is why this was ruled a
difference rather than damage. It is still an inconsistency — `**bold**` works
and `<b>bold</b>` does not — and `b`, `i` and `u` would satisfy the allowlist's
own rule (no URI, no scripting surface). They were left out because the
compatibility pass widened to exactly the constructs the design spec named, not
because they were refused on principle. Use `**bold**` and `*italic*`.

Measured: 94 occurrences across 3 documents.

### `<picture>` shows its fallback image

A `<picture>` element offering a dark-mode and a light-mode source renders on
GitHub as the source matching your theme. xedown drops `<picture>` and
`<source>` and keeps the `<img>` inside.

That is the correct degradation, and it is deliberate — `<picture>` is out of
scope by the design spec. The fallback `<img>` is exactly the image the author
designated for the case where nothing else applies, and it was verified present
in all four corpus occurrences. The only loss is the variant: a logo drawn for
a light background may appear on a dark preview.

### `target`, `rel`, `style` and other presentational attributes are dropped

GitHub keeps `target="_blank"`, `rel`, `cellpadding` and inline `style`.
xedown's sanitizer rebuilds every element from an allowlist and these are not
on it.

None of them changes what you see. `target="_blank"` is already how the
preview behaves — an external link goes to your desktop browser whatever the
attribute says. `style` is the attribute the sanitizer exists to refuse:
document content reaching into the plugin's own styling is the failure the
rebuild-from-allowlist design is there to prevent. `cellpadding` and a
floating image's `align` are superseded by the preview stylesheet.

### A code block's language rides on the `<code>` element

cmark-gfm writes ```` ```sh ```` as `<pre lang="sh">`; xedown writes
`<pre><code class="language-sh">`.

Both spellings are in use in the wild, and xedown's is the one highlight.js
reads, so this difference is in xedown's favour: syntax highlighting works.
It is recorded here only so that a future measurement does not read 143
missing `pre lang` attributes as 143 code blocks that lost their language.
They did not.

## Known limitations

These are differences xedown would rather not have. Each is knowingly shipped,
with the reason.

### Markdown inside block-level HTML is only parsed when the element opts in

**What you see:** Markdown written inside a `<details>`, a `<div>` or any other
block-level HTML element renders as its own source. Backticks show as
backticks; `[text](url)` shows as `[text](url)`.

```markdown
<details>
<summary>S</summary>

See [docs](#docs) and `code`.

</details>
```

GitHub renders that as a link and a code span. xedown renders the line
literally.

**Why:** the vendored `md_in_html` extension parses the contents of an element
only when the element says so:

```markdown
<details markdown="1">
<summary>S</summary>

See [docs](#docs) and `code`.

</details>
```

renders correctly. There is no unconditional mode, and matching GitHub would
mean reimplementing a CommonMark HTML-block state machine outside the vendored
tree — a parser beside the parser.

**What it costs:** this is the largest remaining difference in the corpus.
463 code spans and 175 links render as literal text across two documents.
In awesome-go the whole 145-entry table of contents lives inside `<details>`,
so it renders as a list of link syntax rather than a navigable index; in the
Arabic JavaScript-questions README every answer sits inside `<div dir="rtl">`.
Exactly one of the 31 READMEs — cobra — already writes `markdown="1"`, and its
content parses correctly.

**What to do about it:** add `markdown="1"` to the opening tag. Nothing on
GitHub is harmed by it; the attribute never reaches the rendered page.

### Two blockquotes separated by a blank line merge into one

**What you see:**

```markdown
> one

> two
```

GitHub draws two quotations. xedown draws one, containing two paragraphs.

**Why:** the vendored blockquote processor reuses a preceding `blockquote`
sibling rather than starting a new one. It has nothing to do with list
indentation, though it was found while measuring that.

**What it costs:** the boundary between two quotations, twice in the corpus.
Both quotations are present and readable; what is lost is that they were
separate. Separate them with something that is not a blank line — a paragraph,
a rule — if the distinction matters.

### A nested list inside a blockquote is flattened

**What you see:**

```markdown
> - a
>   - b
```

GitHub nests `b` under `a`. xedown renders them as siblings.

**Why:** the indentation pass that fixed two-space nesting everywhere else
reads a line's absolute indentation, and a `>` prefix moves the content column
somewhere it does not look. Teaching it to strip quote prefixes means a second
parser's worth of per-quote-level state.

**What it costs:** nothing measured — this shape occurs nowhere in the corpus.
It is pinned by a test so that it cannot change without someone noticing.

### A fenced code block indented inside a list item escapes the item

**What you see:**

````markdown
- item

  ```sh
  echo hi
  ```
````

GitHub keeps the code block inside the list item. xedown closes the list first
and puts the block after it. Where the list continues afterwards, xedown starts
a second list — with the right numbers, because `<ol start>` now survives, but
visibly as two lists rather than one.

**Why:** the fence is lifted out of the document and replaced by a placeholder
at column 0 before the list is parsed, which closes the list around it. That
predates the compatibility pass and was not made worse by it — but only for
the loose shape above, where a blank line already separates `item` from the
fence. A *tight* item, with no blank line before the fence, used to keep the
block inside the `<li>` as garbled inline code instead; this pass fixed the
code and, as a side effect, now splits the list here too.

**What it costs:** one list item in the corpus, plus seven ordered lists across
three documents that split into pieces. The code block itself renders
correctly, with its language, in the right place in reading order.

### A `)` ordered marker can leak into a heading

**What you see:** a document that puts a rule or a setext underline directly
under a deeply-indented ordered item written with `)`:

```markdown
- a
    1) b
    ---
```

renders `1) b` as a heading, marker included.

**Why:** `1)` was accepted as an ordered-list marker in this release, which is
what CommonMark asks for. That put it at parity with the `.` spelling — and the
`.` spelling has behaved this way in every previous version of xedown. Writing
the same document with `1.` produces the same heading in xedown 0.3.0.
Narrowing the marker rule to close this would re-break the two-space `1) b`
nesting the same release fixed.

**What it costs:** nothing measured. It occurs zero times in the 31 READMEs and
was found only by exhaustively enumerating thousands of generated shapes; 20 to
42 of them leak, depending on which axes the enumeration varies. Every one of
them leaks identically with a `.` marker.

### A table whose header row omits its outer pipes is not a table

**What you see:**

```markdown
API | Description
|:---|:---|
| a | b |
```

GitHub renders a table. xedown renders a paragraph of pipe-separated text.
Writing the header row as `| API | Description |`, or the delimiter row as
`:---|:---`, renders a table in both.

**Why:** GFM lets the header row leave off its leading and trailing pipes
independently of the delimiter row; the vendored tables extension does not.

**What it costs:** one table of 27 rows, in one corpus document. This one is
worth fixing and is not fixed: it was found while re-measuring for this
document, after the pass had closed, and it is pre-existing — the same document
rendered the same way before any of this work. It is the only known difference
here that a reader would call the document damaged rather than different.

## Reproducing any of this

```bash
scripts/fetch-corpus.sh                          # rebuild the corpus from its pinned SHAs
.venv/bin/python tests/compat/run_audit.py --kind parser --top 20
.venv/bin/python tests/compat/run_audit.py --kind allowlist --top 20
```

`tests/compat/` is deliberately outside the unit-test run: it needs the corpus
and a `cmarkgfm` build that CI does not install. `tests/compat/differential.py`
documents the three renders and the two diffs, and
`tests/compat/normalise.py` documents every cosmetic difference the comparison
is allowed to forgive.

Read the cluster output as a pointer, not as a count. It splits on `><`, and
cmark-gfm puts whitespace between block tags, so one cluster commonly holds
several unrelated causes. Every number in this file was taken by censusing the
elements and attributes of both renders instead.
