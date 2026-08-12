# Orca verification findings

This document is the tracked record behind the accessibility claims in
`docs/known-issues.md`, `README.md`, `changelog.md` and
`docs/manual-smoke-test.md`. It distills three internal task reports
(`task-4-report.md`, `task-5-report.md`, `task-6-report.md`) produced during
the branch that added `ModeBar.announce()` and re-measured what Orca says.
Those reports, their fix-round history and the intermediate transcripts they
produced live only in this session's scratch directory
(`.superpowers/sdd/2026-08-11-xedown-v0.2-orca-verification/`), which is
gitignored (`.gitignore`'s `.superpowers/` entry) — so nothing in this
repository should cite them by path. This document, and
`docs/orca-verification/transcript.json` beside it, are the tracked
substitute.

**Rule this document follows**: state exactly what was measured and how, not
what seems likely to also be true. Several claims below are explicitly
inference, not measurement, and are labelled as such rather than smoothed
into certainty. Whole sections exist only to record what was *not* checked.

## Method

- **Harness**: `scripts/run-orca-tests.sh` installs the probe plugin
  (`tests/integration/xedown_orca_probe`), launches an isolated X11 session
  (a nested `Xephyr` display, `dbus-run-session` for a private AT-SPI bus,
  `metacity` as the window manager, `orca` as the screen reader), opens a
  document, and drives a fixed sequence of keyboard actions. Each action is
  preceded by `mark(label)`, which appends a timestamped line to
  `markers.txt`.
- **Attribution**: Orca's own debug log (`orca.log`, default verbosity — no
  debug-level flag needed for `EVENT MANAGER`/`SPEECH OUTPUT` lines; the
  harness does pass `orca --debug-file=…` to capture it, see
  `scripts/run-orca-tests.sh`) is captured for the whole run. `tests/unit/orca_transcript.py`'s `slice_by_marker` cuts
  `SPEECH OUTPUT` lines into per-marker windows `[mark, next mark)`, and
  `evaluate_rows` checks each named row against an expected substring or
  exact match (`ROWS`) or expected silence (`SILENT_ROWS`); both fail on a
  missing marker, because an assertion that never ran is not a pass.
- **Hardware/software**: Orca 46.1, xed 3.8.9, X11 only (Wayland never
  tried), one single desktop machine throughout the whole effort (not
  otherwise identified in the underlying reports), one WebKitGTK build whose
  exact version was never pinned or recorded by this work.
- **Beyond the automated gate**: three techniques were used only for causal
  tracing, never wired into `ROWS`/`SILENT_ROWS`:
  1. Direct reading of raw `orca.log` lines inside a marker's window, used
     whenever a substring/silence check can't distinguish two hypotheses —
     for example, telling "said once" from "said twice" when both contain
     the same substring.
  2. A temporary, reverted one-line change to `plugin/xedown/preview.py`
     forcing WebKit2's `enable-caret-browsing` on, to test one candidate
     cause of the scrolling silence (see row 98 below). Reverted with `git
     checkout --`; confirmed via an empty `git diff` before the task
     finished.
  3. A standalone throwaway script (`announce_probe.py`, never part of this
     repository, run once inside a hand-built Xephyr/`dbus-run-session`/
     `metacity`/`orca` session) driving **two** plain `Gtk.Button`s — one
     left focused, one deliberately left unfocused — in a tiny GTK app, not
     xed, not xedown, to test whether Orca 46.1 receives `Atk.Object`'s
     `announcement` signal at all, independent of anything xedown does.
     **Result**: yes, from both. Session start confirmed Orca registers a
     real listener (`09:48:21.010284 - EVENT MANAGER: registering listener
     for: object:announcement`). Emitting the signal from the **focused**
     button produced `09:48:27.635169 - EVENT MANAGER: object:announcement
     for [push button: 'Focused button'] ... (1, 0, Announcement from the
     FOCUSED widget.)` → `09:48:27.644377 - SPEECH OUTPUT: 'Announcement
     from the FOCUSED widget.'`; emitting it from the **unfocused** button,
     three seconds later, produced the same pairing —
     `09:48:30.637476 - EVENT MANAGER: object:announcement for [push
     button: 'Unfocused button'] ... (1, 0, Announcement from the UNFOCUSED
     widget.)` → `09:48:30.646005 - SPEECH OUTPUT: 'Announcement from the
     UNFOCUSED widget.'`. Orca spoke both, verbatim: the signal reaches it
     **unconditionally**, whether or not the emitting object currently has
     focus. **What this script cannot stand in for**: `scripts/run-orca-tests.sh`
     itself never demonstrates the focused half of this against xedown's
     own UI, because the object `ModeBar.announce()` actually emits from is
     the mode bar's `Gtk.Box`, which is never itself keyboard-focusable —
     the unconditional claim for xedown's own emitter rests on this
     standalone script, not on a harness run.
- **Two attribution bugs were found and fixed in the probe itself before any
  finding was trusted** — recorded here because a probe that misattributes
  speech is worse than no probe:
  - An unmarked `grab_focus()` in what is now `step_row_97_focus_mode_bar`
    used to fire ~3 seconds after the `row-96-switch-back-to-preview` mark,
    inside that row's own `[mark, next mark)` window, because that step had
    no marker of its own. The resulting utterance ("Preview toggle button
    pressed.") was first read as evidence that switching back to Preview
    announces itself. It does not; it was spillover. Fixed by giving that
    `grab_focus()` its own marker (`row-97-focus-mode-bar`).
  - The original `step_row_99_search_bar_tab` fired six `Tab` presses in one
    mainloop turn, with no delay between them. Orca's own event-coalescing
    keeps only the most recent focus event of a burst and discards the
    rest, which measured as total silence — read, at first, as "the search
    bar is inaccessible to Tab navigation." Spacing the presses
    (`TAB_PRESS_INTERVAL_MS = 400`) turned that silence into seven real
    utterances (see row 99 below); the search bar was accessible all along,
    the probe just measured it wrong.

## What each row showed

| Row | Assertion | What Orca said | What it shows |
|---|---|---|---|
| `row-96-switch-to-source` | `ROWS`, exact: `["Markdown source"]` | "Markdown source" | Ctrl+Shift+M to Source now announces. Before the fix below, this direction was measured genuinely silent, for a specific mechanistic reason: at the moment of the press, Orca's tracked locus of focus was already the source view — established at document-open time, independently of and before xedown's own mode switch — so `self.view.grab_focus()` raised no new transition for Orca to react to. Reproduced identically on every one of the six live runs behind this document: two in Task 6, two more in the fix round that narrowed `has_focus_inside()`, two more in the final whole-branch review's fix wave. |
| `row-96-switch-back-to-preview` | `ROWS`, exact: `["Preview"]` | "Preview" | Ctrl+Shift+M back to Preview now announces. Before the fix, and once the probe's own contamination (above) was removed, this direction also measured clean-silent: focus does move to the WebView's outer accessible object, a real new AT-SPI event, but Orca's own toolkit layer classifies that object as layout-only and never presents it. Reproduced identically across the same six runs as the row above. |
| `row-97-focus-mode-bar` | not asserted (preparation step) | "Preview toggle button pressed." | The step that used to contaminate `row-96-switch-back-to-preview` (above), now correctly attributed to its own marker. Not asserted because asserting it would duplicate `row-96-switch-back-to-preview`'s finding under a different name. |
| `row-97-mode-bar-tab` | `ROWS`, exact: `["Markdown source toggle button not pressed."]` | as expected | Tabbing from the already-focused Preview toggle one press over lands on the Source toggle, and Orca names it and its pressed state correctly. The single cleanest, highest-confidence positive result in the whole investigation — reproduced identically across every live run behind this document. |
| `row-97-activate-focused-button` | deliberately **not** in `ROWS`/`SILENT_ROWS`; verified instead by reading the raw log directly | transcript: `["pressed", "text.", "# Scroll Test."]`; raw log: zero `object:announcement` events in the window, in two independent runs | Tests the suppression rule: Tab lands focus on the (unpressed) Source toggle, then Space activates it — switching mode *from inside the bar*, with a mode toggle still focused at the instant `set_mode` runs. `evaluate_rows`'s substring/silence check can't tell "announced once" from "announced twice" (both contain "Markdown source"), so this row is checked by grepping the raw log for `object:announcement` directly: zero, in both of the two final runs. Independent corroboration: three seconds later, `row-98-prepare-preview` makes a second, genuinely unsuppressed switch (focus by then is off the bar) and that one *does* announce "Preview" — a second, differently-conditioned data point for the unsuppressed path. |
| `row-98-prepare-preview` | not asserted (preparation step) | "Preview" | The unsuppressed corroboration described above. |
| `row-98-preview-scroll` | `SILENT_ROWS`: `[]` | (nothing) | Down/Page Down with the preview showing produce **zero AT-SPI events of any kind** between the mark and the next mark — not merely unpresented speech. Confirmed by reading the raw log directly (the only check that can show *zero events of any kind*, as opposed to unspoken ones) in Task 3 and Task 4; every later task asserts this row only through `SILENT_ROWS`, which checks for speech-silence by reading `SPEECH OUTPUT` lines and cannot by itself rule out a non-speech AT-SPI event, but never once surfaced one on this row either. WebKit2's `enable-caret-browsing` (off by default; xedown never sets it) was tested directly as the most likely cause and made no measurable difference — the WebView was still completely silent. The true cause was not found; it is somewhere inside WebKit2GTK's own AT-SPI bridge, a C/C++ codebase outside xedown's Python and outside what this project instrumented. |
| `row-99-search-bar-tab` | deliberately unasserted | seven utterances: `"Match case toggle button not pressed."`, `"Previous match push button."`, `"Next match push button."`, `"Close search push button."`, `"toggle button pressed."`, `"Show or hide the side pane in the current window."`, `"Markdown toggle button not pressed."` | Four of the seven correctly name real search-bar controls, at correct pace (400ms/press) — confirming the search bar's own accessible names and roles are wired correctly. The other three are a second, separate finding: the probe's *fixed six-press* Tab count sweeps focus past the search bar's own last control (`Close search`) into xed's surrounding chrome — `"Show or hide the side pane in the current window."` is xed's own file-browser toggle, not part of xedown at all. Not promoted into `ROWS`/`SILENT_ROWS`: it is not one of the rows the plan's brief named for that table, and asserting a clean expectation on a slice that includes an unrelated widget's name would encode the overshoot as if it were deliberate. |
| `row-100-prepare-stale` | not asserted (preparation step) | (nothing) | Silent, unremarkably. |
| `row-100-stale` | deliberately unasserted | the ordinary modified-title change, e.g. `"*orca-sample.md (/tmp/...)"` | The stale dot and the Refresh button's description both change at this moment, and both real AT-SPI events fire — but both are suppressed for reasons outside xedown's control: Orca filters the dot's `showing` event by its role; the button's `accessible-description` change is processed but never presented, **most likely** (an inference, not independently confirmed) because the button is not the current focus at that moment. The only utterance actually heard is the generic "document modified" title announcement any edit produces, unrelated to staleness. |
| `row-100-focus-refresh` | not asserted (preparation step) | `["orca-sample.md page tab.", "Refresh the preview push button.", "The preview is out of date — refresh it (Ctrl+Shift+R)"]` | Reaching the Refresh button (via a direct focus call, not an actual Tab press — Tab should reach the same button) is announced correctly and in full, including its description. |
| `row-100-refresh-focused-switch` | `ROWS`, substring: `["Markdown source"]` | `["text.", "# Scroll Test.", "Markdown source"]` | Regression guard: Ctrl+Shift+M with the *Refresh* button focused, not a mode toggle. An early version of the suppression check treated any focused control in the bar — including Refresh — as reason to suppress, which silenced this exact switch: the defect this work exists to remove, reintroduced in a corner nothing had exercised yet. Fixed to check only the two mode toggle buttons; the raw log confirms a genuine `object:announcement` event with text "Markdown source" in this window. |
| `row-101-external-change` | `ROWS`, substring: `["changed on disk"]` | "Warning This file changed on disk. Your unsaved edits are still showing." | Unchanged and reproduced since the earliest runs. Whether tabbing to the bar's own **Reload…** button announces it by name was not part of this measurement. |
| `done` | not asserted | see "About the promoted transcript" below | The sequence's final marker; its content differs between the runs behind this document — explained below, not glossed over. |

## About the promoted transcript

`docs/orca-verification/transcript.json` is the most recent full run,
produced by the current, final code on this branch — after the final
whole-branch review round (`d0203c1`), which closed six numbered findings
and seven small items, including real behaviour changes:
`scripts/run-orca-tests.sh`'s PID-scoped Orca kill replacing an unscoped
`pkill -x orca`, a new `pgrep -x orca` startup refusal, and a new `Exact`
comparison mode in `tests/unit/orca_transcript.py` that now holds the three
mode-switch rows to verbatim equality instead of substring containment.
(`ModeBar.has_focus_inside()`'s narrowing to the two mode toggle buttons
happened three commits earlier, in Task 6's own fix round (`de523da`) — not
this one. This final round's own documentation fix was the README's
suppression wording, which an earlier round had already touched once but
left describing the rule as conditioned on *activation* rather than focus
alone.)

It matches the run Task 6 shipped exactly, byte for byte, on all six
*asserted* rows. Two named-but-unasserted rows will never match byte for
byte across any two runs, because each embeds that run's own `/tmp` workdir
path in text Orca actually speaks — the window title includes it: `done`
(below) and `row-100-stale`, whose recorded utterance *is* that title
change. This document's run produced `"*orca-sample.md
(/tmp/tmp.7xOz6Jve2Q)"`; the run Task 6 shipped produced `"*orca-sample.md
(/tmp/tmp.CcBkD0gpfL)"`.

The other difference, in `done`: in the run behind this document, xed's own
"Save it anyway?" dialog — the ordinary confirmation xed shows when asked to
save a file it knows changed on disk — appears in the `done` window.
**Most likely** (an inference, not independently confirmed): this is
triggered by `timeout 90 xed` (`scripts/run-orca-tests.sh:149`) expiring and
sending xed its own `SIGTERM` near the end of the sequence, racing against
the probe's unsaved-edit state at that point (row 101 leaves the document
with unsaved edits and an on-disk change pending) — not the harness's own
`cleanup()` function, which only ever signals Orca and Xephyr and never
touches xed. It is not caused by anything the mode-announcement work added,
and `done` was never an asserted row in either run — the harness's own
comment already documents why (`step_done`'s `AUTO_REFRESH` restore can, in
principle, trigger a real render at that point, so `done`'s window is
deliberately left unasserted rather than pinned to "always silent"). The two
transcripts are presented as what they are — two different runs that happen
to differ, for explainable, harness-timing reasons, in two windows that were
never asserted either — rather than silently picking whichever one looks
tidier.

## What remains unknown

This is deliberately the longest section. Everything below was checked and
found **unmeasured**, not working — several are very likely to behave the
same as what *was* measured, but "very likely" is not "measured", and this
project does not blur that line.

- **The root cause of the WebView's total AT-SPI silence to keyboard
  scrolling** (`row-98-preview-scroll`). The `enable-caret-browsing`
  hypothesis was tested directly and refuted — it changed nothing. The real
  cause is somewhere inside WebKit2GTK's own AT-SPI/ATK bridge, a codebase
  outside xedown's Python and outside what this project could instrument
  further without reading or testing WebKitGTK itself.
- **Whether a human tabbing through the search bar at genuinely normal,
  unscripted speed hears what row 99 measured.** The 400ms-per-press
  spacing that produced seven utterances is still a scripted, uniform
  interval, not a person's hand. The underlying AT-SPI events for every
  search-bar control are well-formed and correctly named — that part is
  solid — but the exact experience of a real Tab-key user was never
  measured.
- **The View menu's *Toggle Markdown Preview* entry.** Never exercised by
  any probe. It runs through the same `TabController.set_mode` path the
  keyboard shortcut does, so it very likely announces the same way — but
  that is an inference from reading the code, not a measurement.
- **A mouse click on a mode-bar button.** Same funnel, same caveat: likely
  the same, never separately measured.
- **Activating an already-focused Preview toggle — the reverse suppression
  direction.** Only Source-ward was exercised (`row-97-activate-focused-button`
  tabs to and activates the *Source* toggle). Tabbing back to an
  already-focused, now-unpressed *Preview* button and activating it was not
  separately measured. The suppression check in `set_mode` reads the same
  regardless of direction, so there is no code-level reason to expect a
  difference — but that is reasoning about the code, not a second
  measurement.
- **Pressing Ctrl+Shift+M while a mode toggle button already has keyboard
  focus, without activating that button** — focus merely parked there from
  an earlier Tab, then the accelerator used instead of Space. Never
  separately measured; `ModeBar.has_focus_inside()` is conditioned on
  *focus*, not on *how* the switch was triggered, so this route almost
  certainly suppresses too — again, inference from the code, not a
  measurement.
- **Wayland.** Every run in this document was on X11. Never tried.
- **Any Orca version other than 46.1.** Never tried.
- **Any machine other than the single one used for this whole effort.**
  Never tried.
- **Any ATK build lacking the `announcement` signal.** `ModeBar.announce()`
  is written to become a silent no-op if the signal or the accessible
  object is unavailable — but that fallback path itself was never exercised
  against a real ATK build old enough to lack the signal; it is untested
  code, not an untested claim about behaviour that was ever observed.
- **Whether an `aria-live` region in xedown's own rendered markup would
  reach Orca through WebKit's own ARIA/accessibility bridge.** A second,
  separate mechanism from the `Atk.Object` one actually used — never tried.
- **Whether routing the debounced in-place refresh (`update_body()`) through
  `ModeBar.announce()` would read well in practice** — for example, whether
  it would talk over a user who is mid-scroll. The mechanism is proven to
  reach Orca (via the mode switch); wiring it to the refresh path specifically
  has not been done or measured.
- **The 263ms gap** between a Space-activation mark and the resulting
  `object:state-changed:checked` event (measured directly, in the two runs
  behind Task 6's own report — four more runs followed, in the fix round and
  the final whole-branch review wave, and the gap was not re-measured in any
  of them) was fitted to a **hypothesis** —
  `GtkButton`'s default 250ms `ACTIVATE_TIMEOUT` firing because `_press()`
  delivers a `KEY_PRESS` with no matching `KEY_RELEASE` — that was never
  verified against GTK's own source. The measured number is solid; the
  explanation for it is a plausible fit, not a confirmed cause.
- **Whether any of these results generalize beyond the one switch cycle the
  probe performs** (Preview → Source → Preview, once, plus the one
  activate-focused-button variant). A document opened directly into Source
  mode, or a second or third switch cycle later in a longer session, was
  never tested.

## Where this document's evidence came from

Everything above is distilled from `task-4-report.md` (what Orca does and
does not present, and why — including the refuted `enable-caret-browsing`
hypothesis and the standalone `announce_probe.py` measurement of the ATK
signal), `task-5-report.md` (the two probe-instrument repairs described
under "Method" above and the resulting re-measurement), and `task-6-report.md`
(the `ModeBar.announce()` mechanism, its suppression rule, and the
regression it caught and fixed against the Refresh button). Those reports —
along with their own fix-round history, brief documents and per-task
transcripts — are session artifacts under
`.superpowers/sdd/2026-08-11-xedown-v0.2-orca-verification/`, gitignored and
not part of this repository; this document and `transcript.json` beside it
are what a fresh clone can actually resolve.
