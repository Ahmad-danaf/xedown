# Known issues

## `Gtk-CRITICAL` in the terminal after moving a tab between windows (xed bug)

**What you see:** if you run xed from a terminal, move a tab to another window,
switch tabs in the original window, and then close it, xed prints:

```
(xed:PID): Gtk-CRITICAL **: HH:MM:SS.mmm: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP (action_group)' failed
```

**What it means for you:** nothing. The window closes normally, no work is lost,
and nothing is left running. It is noise on stderr, not a failure — and it is
invisible unless you launched xed from a terminal.

**Whose bug it is:** xed 3.8.9's, not xedown's. It reproduces with xedown absent
from the plugin directory entirely, from a plugin that only calls Xed/Gtk/Gio
APIs and never references xedown. This is checkable rather than asserted:

```
XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab
```

runs that scenario with xedown uninstalled and still prints the assertion.

**Why it is recorded here anyway:** it is the single exception in xedown's
release gate, which otherwise treats *any* warning, critical, traceback or
segfault at shutdown as a blocker. Both harnesses allowlist exactly this one
line, anchored end to end so it cannot excuse anything else on the same line,
and `tests/unit/test_shutdown_allowlist.py` fails if that exception ever widens
— including to a different assertion inside the same call, the same assertion at
a different log level, or the same text from another process.

**Status:** upstream. Nothing to fix in xedown; revisit if a future xed release
stops producing it, at which point the allowlist should be deleted rather than
kept "just in case".

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
