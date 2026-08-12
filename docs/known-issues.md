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

## A case-insensitive preview search can miss a Greek word-final sigma

Case-insensitive search folds the rendered text to lowercase one character at
a time, rather than lowercasing the whole string in one call. That is
deliberate: U+0130 — the dotted capital `İ` that opens Turkish words like
`İstanbul` — is the one character in all of Unicode that becomes two UTF-16
units when lowercased, and the search tracks matches by position in the
original text. Fold the whole string at once and that one character throws
the positions out of step with the text they came from, so a match could
highlight the wrong stretch of the document, or claim a match and highlight
nothing. Folding a character at a time avoids that by leaving such a
character as itself instead of letting it grow.

The cost lands on Greek: lowercasing a whole string in one call knows to
write a word-final capital sigma as `ς` rather than `σ`, but that rule needs
to see the whole word, and folding one character at a time never gets to.
So a case-insensitive query typed `οδος` (with the word-final form) no
longer matches all-caps `ΟΔΟΣ`; typed `οδοσ` instead, it does.
Case-sensitive search, and every other language, are unaffected. This was
taken deliberately, not missed: a Greek query occasionally needing its other
spelling costs less than a search that can highlight the wrong text.

## The source buffer keeps its old text after an external change

**What you see:** something rewrites the open file. The preview updates. You
switch to Markdown mode and the editor still shows the previous text — and xed
puts up its own bar offering to reload it.

**Why:** xedown never writes to the text buffer. It renders the preview from
the file on disk when the buffer has no unsaved edits, and leaves the buffer to
xed, which owns it. xed checks the file when the source view takes keyboard
focus, and switching to Markdown mode is precisely when that happens — so the
offer to reload arrives exactly when the stale text becomes visible.

**What to do about it:** accept xed's **Reload**, or use *File → Revert*.
Nothing is lost either way: with unsaved edits, xed asks first.

## A file written continuously updates only when the writing pauses

**What you see:** a program appends to the open file without stopping. The
preview does not update until it stops.

**Why:** every file event restarts a 300 ms settle window, so that one save
arriving as several filesystem events becomes one update rather than three.
A writer that never pauses never lets that window expire. This is the
deliberate trade against runaway refreshing; every real case — a rebase, an
editor saving, an agent working in a loop — writes in bursts with gaps.

**What to do about it:** nothing. The preview catches up as soon as the
writing stops.

## An external change on a network filesystem may go unnoticed

**What you see:** a file on an NFS or SMB mount is changed from another
machine, and the preview does not follow it.

**Why:** the watch is built on the kernel's own file-change notifications,
which see writes made on this machine and not writes made on another.

**What to do about it:** use *File → Revert*, or switch to Markdown mode and
accept xed's own **Reload** bar — the source view taking keyboard focus is
what triggers xed's own check; neither `Ctrl+Shift+R` nor a plain mode switch
re-reads the file themselves. If the watching is costing more than it gives on
such a mount, set `"watch_external_changes": false`.

## Whether an in-place preview update can reach a screen reader is untested

**What you see:** the debounced auto-refresh path (`update_body()` /
`window.xedown.replaceBody()`, `plugin/xedown/preview.py:91-106`) updates the
rendered page in place while Preview is already showing and already has
focus. Reading `update_body()` confirms it only runs a JavaScript body swap:
nothing about it moves keyboard focus, changes any GTK widget's accessible
state, or calls `ModeBar.announce()` (see below) — so nothing fires that a
screen reader would react to.

**Why:** an earlier version of this entry said GTK 3's ATK "has no
widget-level equivalent of an ARIA live region — no API to say 'this GTK
widget's content changed, say so anyway.'" That was wrong, and shipped code
now disproves it: `Atk.Object` has exactly such an API, its `announcement`
signal, and xedown uses it in `ModeBar.announce()` to make the
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> mode switch speak its new mode
by name. That the signal reaches Orca 46.1 **unconditionally — whether or
not the emitting object currently has focus** — was measured with a
standalone throwaway test emitting the signal from both a focused and an
unfocused `Gtk.Button`, outside xed entirely (see
`docs/orca-verification/measurements.md`'s "Method" section and
`plugin/xedown/modebar.py`'s `ModeBar.announce()` docstring, which cites the
same finding). `scripts/run-orca-tests.sh` itself cannot demonstrate the
focused half against xedown's own UI: its emitter is the mode bar's
`Gtk.Box`, which is never itself keyboard-focusable, and — separately —
`set_mode` deliberately withholds the emission whenever a mode toggle button
itself holds focus, so that a Tab-then-activate switch is not announced
twice — checked against a live Orca run by `row-97-activate-focused-button`
in `scripts/run-orca-tests.sh`, which exercises exactly that path but is
deliberately left out of the automated `ROWS`/`SILENT_ROWS` gate (see the
"deliberately not asserted" comment above `evaluate_rows`'s call in that
script, next to the `row-97-activate-focused-button` marker itself):
`evaluate_rows`'s substring and silence checks cannot tell one utterance
from two, which is the one thing this row needs to show. It was verified
instead by hand-reading the raw Orca log directly (see
`docs/orca-verification/measurements.md`'s `row-97-activate-focused-button`
entry). What the mechanism is *not*
wired to is `update_body()`: the in-place refresh path never calls
`announce()`, so a change that lands while Preview is already showing still
produces nothing to hear — inferred from reading `update_body()`'s own code
(it runs a JavaScript body swap only), not separately measured against Orca.
`Atk.Object`'s `announcement` signal is a real but versioned upstream ATK
feature — this project never tested against an ATK build older than what
ships on this machine, and does not know at which version the signal was
added. `ModeBar.announce()` never raises even where the signal does not
exist: on an ATK too old to have it, the call becomes a silent no-op, and
every mode switch it covers goes back to being as silent as before this
work.

An `aria-live` region in xedown's *own* rendered markup (`renderer.py`) is a
second, separate avenue that was never tried: WebKit implements ARIA on the
pages it renders, independently of GTK's ATK layer, and whether such a
region would reach Orca through WebKitGTK's own accessibility bridge is an
open question — more interesting now than when this entry was first
written, since the entry below measures that same WebView emitting *zero*
AT-SPI events of any kind for a different interaction (keyboard scrolling),
which cuts both ways: it could mean an `aria-live` region has nothing to
attach to either, or it could be unrelated to how ARIA state changes are
reported. Untried either way.

**What to do about it:** today, a mode switch
(<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> twice) is the update path
measured to speak. Routing `update_body()` through the same
`ModeBar.announce()` xedown already uses for the mode switch is a live
option now that the mechanism is proven to reach Orca — but it has not been
done, and whether it would read well in practice (for example, whether it
would talk over a user who is mid-scroll) has not been tried or checked
against Orca. Trying an `aria-live` region in the rendered page and checking
it against Orca is the other untried option, and would need its own
measurement before this entry could call it either way.

**Status:** open question, not a settled limitation. The claim that GTK 3
gives xedown no way to signal a change that moves no focus was wrong and is
corrected above; whether routing auto-refresh through the now-proven
mechanism, or an `aria-live` region in the rendered page, is worth doing —
and how either would sound — has not been investigated.

## Keyboard-scrolling the preview produces no screen-reader feedback

**What you see:** with Preview showing, pressing <kbd>Down</kbd> or
<kbd>Page Down</kbd> without clicking first scrolls the document, but Orca
says nothing at all.

**Why:** measured directly against the raw AT-SPI event log, not inferred
from silence: the window between the key presses and whatever happens next
contains no accessibility event of any kind — confirmed independently every
time it has been measured, from the earliest live runs through the final
runs of this project's Orca verification work. This is not merely
unpresented speech; Orca receives nothing to present. WebKit2's
`enable-caret-browsing`
(off by default; xedown never sets it) was tried as the most likely cause —
a temporary, reverted one-line change forced it on — and made no measurable
difference; the WebView still produced zero AT-SPI activity. The actual
cause is inside WebKit2GTK's own AT-SPI bridge, a C/C++ codebase outside
xedown's Python and outside what this project can instrument.

**What to do about it:** nothing xedown-side is known to fix this. This is
not a xedown code-path defect with an available fix, and it is not
presented as fixed — enabling caret browsing, the one hypothesis tested,
changed nothing.

**Status:** outstanding, upstream of xedown. Revisit if a future WebKitGTK
version changes this, or if someone instruments WebKit2GTK itself.

## The stale indicator and the manual-refresh cue are not announced

**What you see:** with `"auto_refresh": false`, when the preview falls
behind the document a dot appears beside the Refresh button and the button's
description changes to explain why. Neither event is announced by itself —
the only speech at that moment, if any, is the ordinary "document modified"
title change any edit produces, which says nothing about the preview.
Reaching the Refresh button afterward *is* announced, in full: "Refresh the
preview push button." followed by its description, "The preview is out of
date — refresh it (Ctrl+Shift+R)" — measured via a direct focus call in the
probe, not an actual Tab press, though Tab should reach the same button.

**Why:** both real AT-SPI events fire — the dot's own `showing` state
change, and the Refresh button's `accessible-description` change — but both
are suppressed by mechanisms outside xedown's control: Orca filters the
dot's event by its role, and the button's description-change event is
processed but most likely never presented because the button is not the
current focus at that moment (the event firing, and not being presented, is
measured; the reason is `docs/orca-verification/measurements.md`'s own
`row-100-stale` inference, not separately confirmed). Switching mode with
the Refresh button (not a mode toggle)
focused still announces the mode change normally — measured — so this is
not the same suppression that deliberately silences a mode toggle's own
double-announcement; only the two mode toggle buttons do that.

**What to do about it:** tab to the Refresh button to hear why it is
marked, or watch for the dot. The same `Atk.Object` announcement now used
for the mode switch (see the entries above) could in principle be wired to
the stale transition too, but this has not been done or measured against
Orca.

**Status:** open question, not fixed.

## Screen-reader verification is real but narrow

**What you see:** nothing wrong — this is about how much testing stands
behind the claims elsewhere in this file and in the README, not a bug.
`scripts/run-orca-tests.sh` drove Orca 46.1 against a real xed session and
measured, reproducibly across multiple runs, that
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> announces the new mode both
ways, tabbing to the Source toggle announces it by name and pressed state
(its neighbors in the bar were reached by direct focus calls in the probe,
not measured via Tab), and the external-change warning bar is announced.
That is real, not inferred — but several adjacent things were checked and
found **unknown**, not working:

- The View menu's *Toggle Markdown Preview* entry and a mouse click on a
  mode-bar button were never exercised by the probe. Both run through the
  same `TabController.set_mode` funnel the keyboard shortcut does, so they
  very likely announce the same way, but that has not been measured.
- The reverse suppression direction — tabbing back to the already-focused,
  now-unpressed Preview button and activating it — was not separately
  measured; only activating the Source button from inside the bar was.
- Pressing <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> while a mode toggle
  button already has keyboard focus, *without* activating that button —
  focus merely parked there from an earlier Tab, then the shortcut used
  instead of Space — was never separately measured either. The suppression
  check (`ModeBar.has_focus_inside()`) reads the same either way, so this
  route almost certainly suppresses too, but "almost certainly" is an
  inference, not a measurement: the probe's own coverage of the suppression
  path (`row-97-activate-focused-button`) goes through Space-activating a
  focused toggle, not the accelerator with focus merely resting on one.
- The search bar's own row (manual smoke test row 99) is not asserted by
  the automated harness: the probe's fixed six-Tab-press count sweeps focus
  past the search bar's own last control and into xed's surrounding chrome
  (one of the utterances measured is `"Show or hide the side pane in the
  current window."`, not a search-bar control at all), so a clean pass/fail
  slice is not possible with the probe as it stands. The controls the probe
  does reach are announced correctly by name; nothing more than that should
  be read into the row being unasserted.
- Everything was run on one machine, one Orca version (46.1), one
  WebKitGTK build, on X11. Wayland was never tried.

**Why:** the probe drives one specific sequence of keyboard actions against
one desktop; it was built to measure exactly what it measures, not to
survey every route to the same code.

**What to do about it:** none of the above blocks anything today — the
measured route (the keyboard shortcut, on this machine) is the one
documented as working. Extending the probe to the View menu, a synthesized
mouse click, the reverse suppression direction and the focus-parked
accelerator route, re-scoping the search-bar Tab count to the bar's own
controls, and testing under Wayland would each close one gap.

**Status:** outstanding — each bullet above is an untested route, not a
known problem.

## A document opened through a symbolic link never follows changes to its file

**What you see:** you open `notes.md`, which is a symbolic link to a file
somewhere else, and edit that file from a terminal. The preview does not
update, and no bar appears. Opening the same file by its real name works
normally.

**Why:** the watch is placed on the path the document was opened with, and a
file monitor on a symbolic link watches the link itself rather than what it
points at. Nothing writes to the link — a write goes to the target — so no
event is ever raised. This is not limited to writes that use the target's own
name: measured on this system, a monitor on a link saw nothing whether the
file was written by its real name *or* through the link.

**What to do about it:** open the file by its real path if you want the preview
to follow it. Failing that, use *File → Revert*, or switch to Markdown mode and
accept xed's own **Reload** bar. Nothing is lost either way — this affects only
whether a change is *noticed*, never the document's contents.
