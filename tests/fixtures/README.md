# Test fixtures

Two Markdown documents, kept deliberately separate because they do opposite
jobs.

## `showcase.md` — does this look good

Every construct in this file renders correctly: headings, text formatting,
lists, task lists, a blockquote, a horizontal rule, a table, fenced code in
two bundled languages, a working local image, a working external link, a
working relative link, an in-page anchor, and a footnote. It also carries a
table wider than the reading column, a tall image, and a small one, to
exercise the reading-polish CSS. There is no error placeholder anywhere in
it. Use it for a screenshot or a first look at Preview mode — anything that
shows a broken reference here is a real regression.

## `edge-cases.md` — does this fail well

The document behind the manual smoke test's failure-handling checks
(`docs/manual-smoke-test.md`, rows 16–17). It exercises unbundled and
languageless fenced code, the known GFM paragraph/list gap
(`docs/known-issues.md`), and a left-to-right control case for the
bidirectional-text handling — including a Python fence with Arabic comments
that must stay left-to-right.

**It also contains broken references on purpose:**

- `![Missing image](pics/does-not-exist.png)` — no such file exists in
  `pics/`.
- `![Remote image](https://example.com/not-fetched.png)` — a remote image,
  which xedown never fetches.
- `[A link to a file that is not there](does-not-exist.md)` — no such file
  exists in this directory.

**Do not "fix" these by adding the missing files or changing the
addresses.** They are what the missing-image and dead-link rows of the
manual smoke test check against; supplying them would silently delete that
coverage, not repair anything.

There is deliberately **no unreadable-image fixture**. "Could not be read"
means a file that exists and cannot be opened, and git carries no mode-000
file, so that case is covered by `tests/unit/test_images.py` instead. Do not
"repair" the apparent gap by adding a file.

## `rtl.md` — does an Arabic document read

A wholly Arabic document, and a "does this look good" fixture like
`showcase.md`: every reference in it resolves, and an error placeholder
anywhere in it is a real regression. It exercises everything that has a
*side* — bullets and their indentation, nested lists, the quote bar, table
column order, the footnote marker and its back-reference, and the copy button
— plus a Python fence with Arabic comments that must stay left-to-right, and
an in-page anchor with an explicit ASCII id (`{#lists}`) so the link target
does not depend on how Arabic headings happen to be slugified.

## `mixed-direction.md` — do both directions read at once

Deliberately Arabic-majority prose carrying English technical terms, a path,
a URL used as link text, inline code, a whole English paragraph, a
two-direction list and a two-direction table. It also carries one `<bdi>` and
one `<span dir="ltr">`: those are the author's own escape hatch for a bare
path, and this fixture is what keeps the sanitizer allowing them.

If `tests/unit/test_fixtures.py` ever reports that this file no longer
detects right-to-left, **add Arabic prose — do not delete the English**. The
English is what the fixture is for.

## `linked.md` and `pics/sample.png`

Supporting files. `linked.md` is the target of the working relative link in
`showcase.md`. `pics/sample.png` is the working local image in
`showcase.md` — a small generated gradient, reused as a placeholder-free
control case (contrast with the missing image in `edge-cases.md`).

## `v0.1-preview.css`

Not a Markdown fixture, and not something to regenerate casually. It is a
frozen copy of the stylesheet xedown 0.1.0 shipped.
`tests/unit/test_v01_parity.py` compares it, declaration for declaration,
against the base sheet plus `themes/repository.css` — which is what lets this
project claim `repository` renders identically to 0.1.0. If 0.1.0's
stylesheet genuinely needs revisiting, that belongs in that test's
`SUBSTITUTIONS` table, with a reason; replacing this file would just make the
comparison stop meaning anything.

## Regression test

`tests/unit/test_fixtures.py` renders both files through the real renderer
and asserts on this same split: `showcase.md` must never contain an error
placeholder, and `edge-cases.md` must always contain one for both the
missing image and the remote image. If either assertion starts failing,
something in the renderer changed, not the fixtures.

The two placeholder cases are **not** covered symmetrically, and it matters:

- The **remote** image is refused in Python, so the primary render — the one
  with `base_dir` set, as a saved document — produces its placeholder and the
  test asserts on exactly that.
- The **missing local** image is not. Nothing in the Python pipeline checks
  whether a local file exists, so with `base_dir` set it resolves to an
  ordinary-looking `file:` URI and only becomes a placeholder in a real
  browser, when the load fails and `preview.js` swaps it out. To reach a
  server-side placeholder at all, that assertion re-renders the same
  reference with `base_dir=None` — which exercises the *unsaved document*
  path, a genuinely different scenario that happens to share the outcome.

So the everyday missing-image case has **no automated coverage** at any
level: there is no JavaScript test infrastructure in this repository either.
It is covered only by row 16 of [manual-smoke-test.md](../../docs/manual-smoke-test.md),
which is why that row stays manual. Do not read the assertions above as
proof that a broken local image still degrades gracefully — open
`edge-cases.md` and look.

## `xed-accelerators.json`

Not a document fixture. It is xed's own keyboard accelerators, extracted from
the installed application by `scripts/extract-xed-accelerators.sh`, and
`tests/unit/test_shortcuts.py` uses it to prove none of xedown's four shortcuts
collides with one of xed's — in CI, where no xed is installed. Regenerate it
after upgrading xed; do not hand-edit it.
