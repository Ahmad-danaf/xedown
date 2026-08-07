# Known issues

## xed can crash when closing a window after moving a tab between windows (xed bug)

**What you see:** move a tab into another window, switch tabs, then close the
window. Usually it closes normally. Sometimes xed prints this to the terminal:

```
(xed:PID): Gtk-CRITICAL **: HH:MM:SS.mmm: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP (action_group)' failed
```

and sometimes it does not print anything and simply dies with `SIGSEGV`.

**These are the same bug, not two.** The stack is identical in both cases:

```
#0  gtk_action_group_get_action   (libgtk-3.so.0)
#1  received_clipboard_contents   (libxed.so)
#2  ... GTK signal emission, main loop, g_application_run
```

xed's own clipboard callback reaches an action group that is already gone. When
the freed memory still happens to be readable, GTK's type check catches it and
you get the assertion above. When it does not, the same read is a segfault. The
assertion is therefore a *warning shot from a memory-safety bug*, not cosmetic
noise — which is why the description here changed: an earlier version of this
file called it harmless, and that was wrong.

**Whose bug it is:** xed 3.8.9's. Every frame in that stack is xed or GTK —
there are no xedown, Python or libpeas frames in it at all — and it reproduces
with xedown absent from the plugin directory entirely. That is checkable rather
than asserted:

```
XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh move-tab
```

runs the scenario with xedown uninstalled and still reproduces it.

**How often:** roughly a quarter to a third of the time under the harness's
scripted sequence (10 failures in 35 runs with xedown installed; 2 in 8 with it
uninstalled — same rate within these sample sizes, no sign that xedown affects
it). That sequence moves a tab, switches tabs and closes a window within a few
seconds, which is far faster than anyone works by hand, and the bug is
timing-dependent, so ordinary use should hit it much less often. It is not
something xedown can fix or work around: nothing in this plugin touches xed's
clipboard handling.

**What to do about it:** nothing is lost that was saved. Save before dragging
tabs between windows if you have unsaved work, which is good practice anyway.

**Why the allowlist exists:** the assertion is the single exception in xedown's
release gate, which otherwise treats *any* warning, critical, traceback or
segfault at shutdown as a blocker. Both harnesses allowlist exactly that one
line, anchored end to end so it cannot excuse anything else on the same line,
and `tests/unit/test_shutdown_allowlist.py` fails if the exception ever widens.
The **crash** is not allowlisted and never should be: `run-shutdown-tests.sh`
reports it as `CRASHED`, checks `coredumpctl` when a slow core dump would
otherwise make it look like a hang, and fails the run.

**Status:** upstream. Revisit if a future xed release fixes
`received_clipboard_contents`, at which point both the allowlist and this entry
should be deleted rather than kept "just in case".

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

## A bare path or URL in right-to-left prose can break at its edges

**What you see:** a file path or URL typed straight into an Arabic or Hebrew
sentence, with no backticks and no markup, reads correctly letter by letter —
but its leading slash, or a trailing dot or colon, appears at the wrong end
of it:

```markdown
افتح /usr/local/share ثم تابع.
```

**Why:** a slash, a dot and a colon are *neutral* characters to the Unicode
bidirectional algorithm. A neutral between two runs of different direction
takes the paragraph's direction, so in a right-to-left paragraph the path's
leading slash is pulled to the right-hand end of the run.

**Whose bug it is:** nobody's, quite. The algorithm is doing what it is
specified to do. Fixing it needs an *element* around the run, and there is no
element around unmarked text — CSS cannot reach it. xedown deliberately does
not guess which runs are paths: that guess would also wrap `either/or`,
`9/10` and `a.b` in every document it ever rendered.

**What to do about it:** mark the run, with either of two one-character
changes.

```markdown
افتح `/usr/local/share` ثم تابع.
افتح <bdi>/usr/local/share</bdi> ثم تابع.
```

Backticks make it code, which xedown already isolates. `<bdi>` — or
`<span dir="ltr">…</span>` — isolates it without styling it as code. Both are
kept by the preview. A path used as a **link's** text needs nothing: xedown
isolates every link already.
