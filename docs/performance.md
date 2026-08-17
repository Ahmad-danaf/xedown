# Performance

xedown renders Markdown **synchronously, on the GTK main thread**. Nothing
yields while a render runs, so the freeze you feel is exactly the render time
in the tables below. That single fact is why this file exists, why there are
two size limits, and what *The known next steps* is about.

This file publishes what rendering costs, how the two limits were derived from
that cost, and — as plainly as the numbers allow — what the limits cannot see
and which renders they do not govern at all.

## How this was measured

`tests/perf/` times four layers separately: `parse` (a fresh Python-Markdown
converter plus `convert()`), `sanitize`, `fragment` (`renderer.render_fragment`,
the real path) and the whole self-contained page (`renderer.render_document`).
Three populations are measured: nine synthetic shapes at about 100,000
characters, two shapes swept across four sizes, and the same 31-README corpus
the compatibility pass used, which `scripts/fetch-corpus.sh` rebuilds from
pinned commit SHAs.

Every number below was taken on one machine — an i7-8750H laptop under the
`powersave` governor — and is the **best of several repeats across four
passes**. Best-of, not mean, because a benchmark on a desktop competes with
whatever else is running and the minimum is the run least disturbed by
something that is not the code under test. Absolute times will differ on your
hardware; the *ratios* are what the limits were derived from, and those held
across every pass.

**What that merge guarantees, and what it does not.** Each cell is minimised
independently, so the four columns of one row may come from four different
passes. That makes every individual figure a sound lower bound on its own
layer, and it is why the µs/char columns are stable. It does **not** make a row
internally coherent, so **arithmetic between two columns of one row is not
always valid**. Three of the 49 merged rows have a whole-page time *below*
their own `fragment` time — `headings-duplicate` (−11%), system-design-primer
(−4%) and build-your-own-x (−2%) — which cannot happen in a single sample,
because `render_document` calls `render_fragment`. Those are two minima drawn
from different passes, not a measurement of anything. Read each column as a
lower bound; where a difference *between* layers is quoted below, it is taken
within a single pass and says so.

`fragment` is the number that matters throughout: it is what the debounced edit
path runs. Wrapping it in the full self-contained page — inlined CSS,
JavaScript and the highlight.js bundle — is the `page` column of the
size-scaling table below. Taken within a single pass, that wrap costs about
**15–19% on prose and 2–3% on tables**: much the same absolute cost in both,
against a fragment time that differs eightfold.

**The `parse` and `sanitize` columns do not sum to `fragment`, and are
indicative rather than a decomposition.** `sanitize` times a bare
`sanitize(raw)` with none of the callbacks the real render always supplies,
so it undercounts — by how much depends on the document. The clearest
demonstration is in the table below: the same 100,000-character document of
3,030 image references costs 277 ms when the references resolve to nothing and
373 ms when they resolve to real files on disk, because `render_fragment`
passes an `on_image` callback that does a `stat` per reference — about 32 µs
each. The `sanitize` column reads 65 ms and 64 ms for those two runs. It cannot
see the difference at all.

## What costs what

Nine synthetic shapes, each generated to about 100,000 characters, plus the
images shape measured a second time against references that resolve to real
files. Times in milliseconds.

| Shape | Characters | parse | sanitize | **fragment** | µs/char |
| --- | ---: | ---: | ---: | ---: | ---: |
| prose | 101,057 | 40 | 4 | **43** | 0.42 |
| list items | 109,591 | 140 | 27 | **169** | 1.54 |
| inline emphasis | 104,264 | 181 | 47 | **227** | 2.18 |
| links | 110,828 | 179 | 47 | **235** | 2.12 |
| images, unresolvable | 115,950 | 179 | 65 | **277** | 2.39 |
| code blocks | 110,890 | 222 | 68 | **285** | 2.57 |
| headings, all distinct | 107,232 | 242 | 47 | **290** | 2.70 |
| tables | 108,093 | 255 | 73 | **348** | 3.22 |
| images, 3,030 real files | 115,950 | 186 | 64 | **373** | 3.22 |
| headings, repeated | 100,008 | 471 | 92 | **646** | 6.46 |

### The repeated-headings row is density, not slowness

The last row is roughly 2× the headings-all-distinct row, and it is worth
saying exactly what that is and is not.

It is **not** a residue of the duplicate-anchor cliff this release fixed. That
cliff is gone: the same shape measured **4,443 ms** in this pass's before
reading and **646 ms** after — the cost went from quadratic in the number of
repeated headings to linear, and `tests/unit/test_toc_unique.py` pins the
operation count so it cannot come back unnoticed.

Nor was that cliff only reachable from a synthetic document: programming-jp,
a real README in the corpus, collides **42** slugs because `toc.slugify`
strips a Japanese heading to the empty string — see *What this limit knowingly
does not cover* below. This shape made the cliff large enough to measure; a
CJK README is what walks it in ordinary use.

What is left is heading *density*. `### Fixed` is a third the length of
`## Section N of the document`, so the repeated-headings document packs
**5,556 headings into 100,008 characters** against **2,778 in 107,232** —
exactly twice as many headings for the same character budget. Normalised per
heading the two shapes cost **116 µs** and **104 µs**. That 11% is the
difference; the 2× is arithmetic.

### Size scaling

Two shapes, the cheapest and an expensive one, across four sizes.

| Shape | Characters | parse | sanitize | **fragment** | page | µs/char |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| prose | 101,057 | 40 | 4 | **43** | 52 | 0.43 |
| prose | 252,878 | 107 | 9 | **109** | 129 | 0.43 |
| prose | 507,054 | 202 | 19 | **227** | 264 | 0.45 |
| prose | 1,015,030 | 412 | 37 | **469** | 552 | 0.46 |
| tables | 108,093 | 263 | 68 | **349** | 355 | 3.23 |
| tables | 276,843 | 655 | 173 | **856** | 880 | 3.09 |
| tables | 559,797 | 1,360 | 402 | **1,960** | 2,018 | 3.50 |
| tables | 1,163,925 | 3,072 | 875 | **3,963** | 4,081 | 3.40 |

Seven of those eight rows have their `fragment` and `page` minima from the same
pass, so the difference between the two columns is readable here; the caveat
above is why that had to be checked rather than assumed.

Cost is close to linear in characters within a shape — the µs/char column
barely moves across a 10× size range. What changes is the constant, and
between these two shapes the constant differs by about 8×.

A megabyte of prose freezes the editor for about half a second. A megabyte of
tables freezes it for four. Both are on the same main thread as your cursor.

## Shape beats size

At 100,000 characters, prose costs 43 ms and tables 348 ms — an **8× spread**
between two shapes a reader would think of as equally ordinary. Against the
repeated-headings shape's 646 ms it is **15×**.

Real documents show the same thing at lower amplitude. Across the 31-README
corpus the per-character rate runs from **0.84 µs** (hugo) to **2.74 µs**
(public-apis) — a 3.3× spread among documents people actually published. The
consequence is easiest to see in a single comparison:

| Document | Characters | **fragment** |
| --- | ---: | ---: |
| public-apis | 232,413 | **636 ms** |
| awesome-go | 404,874 | **514 ms** |

**awesome-go is 74% larger and renders 19% faster.** public-apis is a wall of
tables; awesome-go is mostly links and list items. No character count can tell
those apart before paying for the render, which is the whole difficulty the
next two sections are about.

The ten slowest corpus documents, for reference:

| Document | Characters | parse | sanitize | **fragment** | µs/char |
| --- | ---: | ---: | ---: | ---: | ---: |
| public-apis | 232,413 | 453 | 155 | **636** | 2.74 |
| awesome-go | 404,874 | 399 | 94 | **514** | 1.27 |
| awesome-selfhosted | 327,534 | 387 | 105 | **496** | 1.52 |
| free-programming-books | 198,430 | 233 | 60 | **317** | 1.60 |
| programming-jp | 98,280 | 155 | 45 | **206** | 2.10 |
| system-design-primer | 109,682 | 144 | 28 | **179** | 1.63 |
| awesome-python | 83,417 | 98 | 23 | **126** | 1.51 |
| build-your-own-x | 46,643 | 87 | 18 | **112** | 2.41 |
| javascript-questions (ar) | 54,313 | 38 | 11 | **51** | 0.95 |
| javascript-algorithms (he) | 22,064 | 37 | 10 | **48** | 2.15 |

All 31 together render in 2.9 seconds. Seventeen of them are under 20 ms each.
**For the documents most people open, none of this is a problem at all** —
which is the reason the limits below sit where they do rather than lower.

## The two limits

Both live in `plugin/xedown/perflimits.py`. Both are constants rather than
settings, for the same reason `imagelimits.MAX_PIXELS` is: they are a floor
under a failure mode, not a preference.

They are not consulted in the same places. The **first** is re-evaluated on
every buffer change, so a document crosses it by being typed into or pasted
over just as readily as by being opened. The **second** is asked once, when the
tab decides which mode to open in — pasting half a megabyte into a tab that is
already showing a preview does not retroactively defer anything, because there
is nothing left to defer. *Which renders the limits govern, and which they do
not*, below, is the full list.

### 131,072 characters — the preview stops following your typing

The rule: **the size at which a typical document's render exceeds the debounce
interval.** `refresh_delay_ms` defaults to 250 ms, so past this size a reader
typing continuously leaves the editor busy more often than idle and the
debounce stops being a debounce.

Measured against the corpus, which is the population this limit serves:
nothing below 131,072 characters crosses 250 ms. The largest document under it,
system-design-primer at 109,682 characters, renders in 179 ms; the slowest per
character under it, programming-jp at 98,280 characters, in 206 ms. Fitting the
corpus's own rate — **1.60 µs/char**, least squares through the origin over all
31 documents — puts 250 ms at about **155,800 characters**.

So the limit sits about **16% below** the measured crossing, deliberately on the
low side. Being early costs a visible button; being late costs a stuttering
editor.

**What changes above it:** the preview stops re-rendering as you type, whatever
`auto_refresh` says. A **Refresh** button appears in the mode bar while Preview
is showing, marked when the preview is behind the buffer, and
<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> does the same thing. The override
is per-tab and derived — it is never written to your settings, so the same
reader opening a small document in the next tab gets live refresh exactly as
configured. A reader who turned live refresh on expressed a preference about
ordinary documents, not a request to have the editor freeze on a large one.

### 262,144 characters — an unrequested preview is not built

The rule: **the size at which an unrequested render costs about a second.**

**The corpus cannot supply this crossing, and saying otherwise would be the
easy dishonesty here: no real README measured reaches a second.** The slowest
is public-apis at 636 ms for 232,413 characters, and the largest, awesome-go at
404,874 characters, costs only 514 ms. Extrapolating the corpus's central rate
of 1.60 µs/char would put a second near **623,000 characters**.

It is calibrated against the most expensive shape **real documents actually
exhibit** instead. Dense tables are that shape — public-apis, the corpus's
worst document per character, is a wall of them — and the synthetic tables
shape was swept directly across the crossing to place the number:

| Characters | **fragment** | µs/char |
| ---: | ---: | ---: |
| 108,093 | **356 ms** | 3.29 |
| 220,629 | **734 ms** | 3.33 |
| 276,843 | **889 ms** | 3.21 |
| 333,111 | **1,099 ms** | 3.30 |
| 389,379 | **1,309 ms** | 3.36 |
| 445,593 | **1,497 ms** | 3.36 |

That is one pass at repeat 7, kept together so the curve is internally
consistent; the merged size table above gives 856 ms for the same generated
276,843-character document, a 4% disagreement that is the run-to-run spread of
this machine. Interpolating between the 276,843 and 333,111 rows puts 1,000 ms
at about **305,000 characters** — so the limit sits about **14% below** it, and
every real-document rate measured is cheaper still: at the corpus's worst
per-character rate, 262,144 characters would cost 718 ms.

Anywhere between 262,144 and 305,000 the choice turns out not to matter: the
*same two* of the 31 corpus documents — awesome-selfhosted and awesome-go —
defer at either end, and neither takes much more than half a second to render
anyway (496 ms and 514 ms).

### What this limit knowingly does not cover

The repeated-headings shape at the top of this file costs **6.46 µs/char** —
roughly double dense tables. At that rate a document of 262,144 characters
costs about **1.7 seconds**, not one, and the 1,000 ms crossing arrives near
**155,000 characters**. A very large changelog is the document that would hit
this. **That residual is accepted, not overlooked**, and the reasoning is worth
stating because the alternative looks superficially safer:

- **It is a stress shape, not a population.** The generator repeats each of
  four headings 1,389 times inside 100,000 characters. Nothing in the corpus is
  within two orders of magnitude of that: the worst genuinely repeated heading
  text is system-design-primer's "Sources and further reading", **16 times**,
  and the largest slug collision of any kind is the 42 empty slugs in
  programming-jp, where `toc.slugify` strips Japanese headings to nothing.
  **That last figure is the real justification for the anchor fix**: a
  published CJK README walks the duplicate-anchor path 42 times just by being
  written in Japanese, so the quadratic cliff was reachable from a document
  someone actually has, not only from a synthetic changelog. The shape exists
  in `tests/perf/generate.py` to make that cliff big enough to see, and it did
  exactly that — see the note under the shape table.
- **Calibrating on it would cost more than it saves.** A threshold near 155,000
  would sit almost on top of `LIVE_REFRESH_MAX_CHARS` at 131,072, collapsing
  two deliberately distinct behaviours into one narrow band, and it would
  defer **four of the 31 corpus documents — which render in 317 to 636 ms**.
  Interrupting a third-of-a-second render with a button is a worse failure than
  letting a 1.7-second one through, because it fires on documents that were
  never a problem.

So the honest claim is the narrower one: this limit keeps an *unrequested*
render under about a second for every shape real documents were measured to
have, and a pathologically heading-dense document of exactly threshold size
costs about 1.7 seconds instead. If dense-heading documents ever stop being
pathological, this is the number to revisit — and the section on rendering off
the main thread is the better answer to it than a lower threshold.

**What changes above it:** a tab that would have opened in Preview mode opens
in **Markdown** mode instead, with a chip in the mode bar reading
`Large document (396 KB)` next to a **Preview** button. Click it and the
preview is built. Only the *initial* build is deferred — choosing Preview from
the mode bar is a request, and requests are honoured at any size.

### Both numbers are round, and that is on purpose

131,072 and 262,144 are 128 × 1024 and 256 × 1024. They were not fitted to a
measurement and then dressed up; they are round numbers that measurement was
asked to license, and it does — each sits inside the ±25% band the plan set,
measured against the shapes named above. A crossing measured at 155,800 is not
evidence for a threshold of 155,800; it is evidence that a threshold of 131,072
is not in the wrong place.

Neither is conservative against *every* shape, and the preceding two sections
say against which ones they are not: tables exceed the debounce interval well
below 131,072, and a heading-dense document exceeds a second well below
262,144. A single number cannot be conservative against a 15× spread without
being wrong for almost everything.

The two are ordered — `DEFER_INITIAL_MIN_CHARS > LIVE_REFRESH_MAX_CHARS` — so
the states nest: a document big enough to defer is certainly big enough to stop
live refresh. `tests/unit/test_perflimits.py` pins that relationship, and the
behaviour at each exact boundary, without pinning either literal value.

### Which renders the limits govern, and which they do not

**The two limits govern two triggers: typing, and opening a tab.** Every other
route into a render is exactly what it was before this release, and renders the
whole document synchronously at any size. That is the honest scope of the
feature, and the rest of this section is the list.

Governed:

- **Typing.** `_on_buffer_changed` re-applies the guard on every buffer change,
  and `LIVE_REFRESH_MAX_CHARS` is what suppresses the debounced re-render above
  that size — which is why the guard also catches a document that crosses a
  threshold by being pasted into rather than opened.
- **Opening a tab.** `_build_if_markdown` consults `DEFER_INITIAL_MIN_CHARS`
  and opens in Markdown mode instead of building; `_on_document_loaded` takes
  the same decision again when xed's asynchronous file read lands after the
  build rather than before it.

Not governed — each of these still renders in full:

- **Save.** A stale preview in Preview mode re-renders on
  <kbd>Ctrl</kbd>+<kbd>S</kbd> (`_on_document_saved`). This is the reachable
  one, and it compounds with the first limit rather than being covered by it:
  above 131,072 characters live refresh is off, so the preview is stale
  whenever you have typed, and every save then pays a whole render. At the size
  of public-apis — 232,413 characters — that is the 636 ms in the corpus table
  above, on each save.
- **Revert, and an accepted external reload**, once Preview has shown the
  reader real content (`_on_document_loaded`'s ordinary branch, which
  re-applies the guard to *live refresh* and then reloads the page regardless).
- **An external change the watcher picks up** (`_on_file_settled`'s `UPDATE`
  branch; `watch_external_changes` defaults to on).
- **Two cache-reconciliation renders**: `_on_file_settled` retiring a
  `_disk_text` that turned out to match the buffer, and `_on_modified_changed`
  correcting a preview that is known to be showing the file rather than the
  buffer.

None of this is a regression. Every one of them predates the limits, and before
them the typing path re-rendered on every keystroke anyway, so nothing about
this release made any of them slower. But it is why the README and the
changelog say the preview stops following your *typing* rather than promising
that a large document can no longer freeze the editor: the guard makes a large
document quiet, not free.

**And the guard measures the buffer, not the text that is rendered.**
`_apply_size_guard` counts `GtkTextBuffer.get_char_count()`, which is O(1) and
is the whole reason it can run per keystroke; `_render_text()` returns
`_disk_text` instead when the file changed underneath an unmodified buffer. The
two differ only inside that window, and the difference cannot move the reader
or misreport staleness — that was traced. It is named here because it is the
structural reason the `UPDATE` branch above is invisible to the limits: the
guard is not consulted on that path, and on that path it would be measuring the
wrong text if it were. Gating these paths is recorded as future work under
*The known next steps* below.

## Why the limit is counted in characters, not bytes

Python-Markdown operates on `str`. Cost tracks **characters**, and
`GtkTextBuffer.get_char_count()` is O(1) where encoding the buffer is not — on
a path that runs on every keystroke, that difference is itself the kind of
performance bug the guard exists to prevent.

Counting bytes would also be wrong on the merits. A CJK or Arabic document
encodes to up to 3× its character count in UTF-8, so a byte-counted guard would
fire early on exactly the documents the compatibility pass worked hardest to
support — programming-jp is 98,280 characters and 151,853 bytes, and it renders
in 206 ms. Bytes appear in exactly one place in xedown: the human-readable
label on the mode bar's chip, built once when the chip appears, because bytes
are the number you recognise from your file manager.

**A character count cannot see shape, and this is the limitation to carry away
from this file.** A table-heavy document reaches its practical limit
considerably sooner than the numbers above suggest: at 3.3 µs/char, tables
exceed the debounce interval at around 76,000 characters — well under the
131,072 the guard uses. Prose does not exceed it until about 555,000.

The guard is a **rough floor, not a predictor**. It is used anyway because a
size is the only thing knowable *before* paying the render, and the render is
the cost being avoided. It errs both ways, and the two sections above name
which documents fall on each side: mostly it is early, costing an unnecessary
button on a document that would have rendered fine; on the heading-dense
extreme it is late, and the freeze is longer than the rule it enforces. A
single number set against a 15× spread in cost per character cannot do better
than that, which is why the real fix is *Render off the main thread* below
rather than a better constant.

## Memory is not the constraint

Peak Python allocation during a full `render_document`, by `tracemalloc` —
`run_bench --memory`, whose output this table is. **MB here is 10⁶ bytes**, not
a mebibyte; the mode-bar chip's own size label is the other way round, and says
so in `perflimits.describe_bytes`.

| Case | Characters | Peak | Above the floor | × characters |
| --- | ---: | ---: | ---: | ---: |
| empty document | 0 | 0.74 MB | — | — |
| prose | 1,015,030 | 7.97 MB | 7.2 MB | 7× |
| public-apis (corpus) | 232,413 | 11.87 MB | 11.1 MB | 48× |
| awesome-go (corpus) | 404,874 | 9.57 MB | 8.8 MB | 22× |
| tables | 1,163,925 | 54.14 MB | 53.4 MB | 46× |
| headings, repeated | 1,000,008 | 124.71 MB | 124.0 MB | 124× |

Unlike the timing tables, this one is a single pass and needs no repeats: peak
allocation is deterministic where wall clock is not. It does need a warm
interpreter, and `--memory` discards one render before it starts measuring —
the *first* render in a process also pays Python-Markdown's lazy import of its
extension modules and every regex they compile, which is an empty document
peaking at 4.9 MB cold against 0.74 MB warm.

There is a fixed floor of about **0.74 MB** — the self-contained page inlines
its CSS, its JavaScript and the highlight.js bundle, which is most of it, and
`vendoring.read_vendor_file` re-reads that bundle on every render, so the floor
is a genuine per-render cost rather than a one-off. Above it the marginal cost
is tens of times the document size, varying by shape the same way time does.

The absolute numbers are what matter, and they are small: **the heaviest
document in the entire corpus peaks at 11.9 MB**, and it takes a synthetic
megabyte of the most pathological shape available to reach 125 MB. Nothing here
approaches a constraint on a machine that can run a web engine. Time is the
scarce resource; memory is not, and no limit in xedown is set by it.

## The known next steps

Everything above follows from one design decision: **the render is synchronous
on the GTK main thread**, so freeze time equals render time and the only lever
available is to render less often.

### Gate the render paths the limits do not govern

*Which renders the limits govern* above lists them: save, revert and an
accepted external reload, the watcher's `UPDATE` branch, and two
cache-reconciliation renders. Each still renders a document of any size
synchronously, and save is the one a reader meets — every
<kbd>Ctrl</kbd>+<kbd>S</kbd> on a large document in Preview pays a full render
precisely because the first limit turned live refresh off.

Deferring those to the same Refresh button the typing path already uses is a
small change to make and a hard one to justify late: it would alter four
behaviours whose only exercise is an integration scenario a human has to run on
a live desktop, and it would trade a freeze the reader asked for by saving
against a preview that silently stops following a revert — which is not
obviously the better trade. It is deliberately
not a release-branch change. Nothing is missing on the measurement side —
`perflimits.classify` is pure and takes a character count, so gating a path
costs one call — and the one thing to get right is named in the same section:
the guard counts the buffer, while `_disk_text` is what the `UPDATE` branch
actually renders, so that path has to be measured against the text it will
render rather than against `get_char_count()`.

### Render off the main thread

Moving the render to a worker thread would remove the ceiling rather than
manage it. The parse-and-sanitize pipeline is pure — `renderer`, `sanitizer`
and `mdext` touch no GTK object — so the work itself is movable; what is not
free is the coordination: cancelling a render the reader has already
invalidated, ordering results that return out of order, and keeping the
document text stable across the handoff.

**It was deliberately not done for 1.0.** It adds concurrency to the core
render path — the one path that must never raise and must never show a blank
pane — and doing that in the release that also changed the parser is one risk
too many. The two limits are the smaller, wholly synchronous answer, and the
measurement above says they are adequate for the documents in the corpus.

The size-scaling table is the measurement that would justify revisiting it. If
documents past a few hundred thousand characters become ordinary rather than
exceptional, the 1,960 ms and 3,963 ms rows are what a worker thread would be
buying back, and a deferral chip is a poor substitute for simply rendering.

## Reproducing any of this

```bash
scripts/fetch-corpus.sh                                          # 31 READMEs, pinned SHAs
.venv/bin/python -m tests.perf.run_bench --all --repeat 5
.venv/bin/python -m tests.perf.run_bench --corpus --repeat 9 --json after.json
.venv/bin/python -m tests.perf.run_bench --memory
```

`--shapes`, `--sizes`, `--images-on-disk`, `--corpus` and `--memory` run the
five populations individually, and `--all` runs all five; `--json` writes every
row for comparison against a later run. The corpus is not committed — an absent
corpus is a skip with an instruction, not an error and not a download, and
`--memory` still prints its four synthetic rows without it.

One table here is **not** behind a flag. The tables sweep across the 1,000 ms
crossing — the six-row table under *262,144 characters — an unrequested preview
is not built* — uses sizes that are not in `generate.SIZES`, and
`generate.SIZES` is the only thing `--sizes` sweeps. Those rows come from a
loop written by hand, kept in one pass so the curve is internally consistent:

```python
from tests.perf import generate, measure
for target in (100_000, 200_000, 250_000, 300_000, 350_000, 400_000):
    print(measure.time_layers(generate.build("tables", target), repeat=7))
```

`tests/perf/` is deliberately outside the unit-test run. Wall-clock assertions
flake on a shared runner and get deleted within a month; the permanent guard
against the one cliff this pass found is an **operation count**, in
`tests/unit/test_toc_unique.py`. This harness is the tool a human runs when
they want the curve.
