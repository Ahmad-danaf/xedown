# Test fixtures

Two Markdown documents, kept deliberately separate because they do opposite
jobs.

## `showcase.md` — does this look good

Every construct in this file renders correctly: headings, text formatting,
lists, task lists, a blockquote, a horizontal rule, a table, fenced code in
two bundled languages, a working local image, a working external link, a
working relative link, an in-page anchor, and a footnote. There is no error
placeholder anywhere in it. Use it for a screenshot or a first look at
Preview mode — anything that shows a broken reference here is a real
regression.

## `edge-cases.md` — does this fail well

The document behind the manual smoke test's failure-handling checks
(`docs/manual-smoke-test.md`, rows 16–17). It exercises unbundled and
languageless fenced code, the known GFM paragraph/list gap
(`docs/known-issues.md`), and basic bidirectional text correctness for
Arabic content — including a Python fence with Arabic comments that must
stay left-to-right.

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

## `linked.md` and `pics/sample.png`

Supporting files. `linked.md` is the target of the working relative link in
`showcase.md`. `pics/sample.png` is the working local image in
`showcase.md` — a small generated gradient, reused as a placeholder-free
control case (contrast with the missing image in `edge-cases.md`).

## Regression test

`tests/unit/test_fixtures.py` renders both files through the real renderer
and asserts on this same split: `showcase.md` must never contain an error
placeholder, and `edge-cases.md` must always contain one for both the
missing image and the remote image. If either assertion starts failing,
something in the renderer changed, not the fixtures.
