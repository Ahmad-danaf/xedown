# Known issues

## A list does not interrupt a paragraph (GFM compatibility gap)

**What GFM specifies:** under GitHub-flavored Markdown (built on CommonMark), a list
can start immediately after a paragraph with no blank line between them — the list
marker itself is enough to end the paragraph and begin the list.

**What xedown currently does:** it does not. A bullet or numbered line directly
after a paragraph, with no blank line separating the two, is treated as a
continuation of the paragraph's text rather than the start of a list.

**Minimal reproduction:**

```
Some paragraph text.
- item one
- item two
```

renders as a single paragraph containing all three lines, instead of a paragraph
followed by a two-item list. Inserting a blank line before `- item one` produces
the expected list.

**User-visible effect:** a document written to GFM conventions — for example one
copied from a GitHub README, issue, or pull request description — can silently lose
list formatting for any list that immediately follows a paragraph, until a blank
line is inserted between them.

**Why this isn't fixed here:** the obvious fix is a preprocessor that inserts a
blank line before a line that looks like a list marker. That collides with a real
ambiguity, which is narrower than "list markers in general": a line consisting
*only* of hyphens (for example `---`) is not unambiguously a list marker. Depending
on what precedes it, the same hyphen-only line can also be:

- a **setext heading underline**, which turns the line immediately above it into an
  `<h2>`:

  ```
  Heading Text
  ---
  ```

- a **thematic break** (`<hr>`), when it stands on its own, separated from
  surrounding text by blank lines.

A line like `- item one` — marker, space, content — is unambiguous and is not part
of this hazard; the ambiguity is specific to hyphen-only lines, which carry more
than one meaning depending on context. Any real fix must resolve that ambiguity
correctly, and must also leave the content of fenced code blocks untouched, since a
`- item`-shaped line (or a hyphen-only line) inside a fence is literal text, not
Markdown syntax. That is real engineering work with real regression risk, so it is
deferred rather than attempted in a final fix wave with no second review pass.

**Status:** targeted for v0.2. Complete GFM-compatible paragraph interruption is
tracked there; until then, xedown documents itself as supporting selected
GitHub-flavored Markdown features (tables, task lists, strikethrough, fenced code,
and footnotes), not full GFM compatibility.
