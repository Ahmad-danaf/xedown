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

**Status:** permanent. There is no element around unmarked prose for CSS to
target, and xedown deliberately does not guess which runs are paths — that
guess would also wrap `either/or`, `9/10` and `a.b` in every document it
ever rendered. This is not tracked for a future fix; the markup above is
the fix.

## A new file can open in an old one's remembered mode

**What you see:** rename or delete a Markdown file outside xed — in a file
manager, or from a script — then later create a *different* file at that same
path. It opens in whichever mode the old file was last left in, not the
default.

**Why:** xedown files a remembered mode under a file's path. When a file is
renamed or moved *inside xed*, the entry follows it, because xedown sees it
happen. Outside xed, the rename or deletion happens without xedown watching,
so the entry stays keyed to a path that no longer has that file.

The alternative was recording each file's identity (device and inode) beside
its path. xed saves by replacing the file, which changes the inode, so that
would forget a file's mode after an ordinary save: a rare wrong mode traded
for a frequent forgotten one.

**What to do about it:** switch mode once; the entry is rewritten. Entries
also fall off the end of `~/.config/xedown/modes.json` once 200 more recent
files have been opened, and deleting that file forgets all of them.
`"remember_mode_per_file": false` turns the whole feature off.

**Status:** by design, bounded.

## Copy and select-all in the preview fall back to xed's own shortcut on a non-Latin keyboard layout

**What you see:** with the preview showing, <kbd>Ctrl</kbd>+<kbd>C</kbd> and
<kbd>Ctrl</kbd>+<kbd>A</kbd> copy and select the Markdown *source* instead of
the rendered preview, on a keyboard set to a non-Latin layout (Cyrillic,
Greek, Arabic, and others) — the exact wrong-surface mix-up xedown's own key
handling exists to prevent, on this one class of layout.

**Why:** GDK delivers a key event's `keyval` already translated through the
active layout — the same mechanism that lets a user on an AZERTY layout reach
`A` where their layout puts it. `XedownWindowActivatable._on_key_press`
(`plugin/xedown/__init__.py`) compares that translated keyval's name against
a fixed set of Latin key names, `shortcuts.HANDLED_KEYS`. On a layout where
the physical Ctrl+C key produces a Cyrillic, Greek or Arabic letter, that
name never matches, so `_on_key_press` declines the event and it falls
through to xed's own Copy and Select All, which act on the hidden source
buffer regardless of which surface is on screen.

**What to do about it:** right-click the preview. Its context menu offers
Copy (when something is selected) and Select All, driven by the mouse rather
than a keysym, so it is unaffected by layout. Switching to Markdown mode also
copies correctly, since that is the surface xed's fallback actually reaches.

**Status:** known limitation, degrading to v0.1 behaviour rather than
breaking. A real fix needs matching on hardware keycode instead of
translated keyval, which is a larger change than this fix belongs in.

## A preview search does not match across a block boundary

Searching the preview for a phrase that starts in one paragraph and finishes
in the next finds nothing, and the same goes for a heading and the text under
it. This is deliberate: the reader sees two blocks, not one line, and the
flattened text the search runs over puts a line break between them. Matching
across inline markup — a phrase containing a bold or italic word, or one the
author wrapped over two source lines — does work.

## A preview search's highlight can show a seam inside a run of whitespace

Searching for a match whose whitespace is split across an element boundary —
markup like `a <em> </em> b`, where a space sits alone inside its own inline
tag — highlights only the part of that whitespace run that falls in the
first text node. The match is still found and still counted correctly; only
its highlight is broken into two marks with an unhighlighted gap between
them, instead of one continuous strip. This needs an element boundary inside
a run of whitespace to occur at all, which is uncommon, and it is cosmetic —
it was accepted deliberately rather than missed.

## A very broad preview search stops highlighting at 2000 matches

The count reads `2000+` and `Enter` cycles the first 2000. A query that matches
more than that is filtering rather than searching, and marking tens of
thousands of elements on every keystroke would make the preview stutter.
