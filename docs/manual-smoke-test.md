# Manual smoke test

Run before tagging a release, on a clean install produced from the release archive:

```bash
scripts/build-release.sh
mkdir -p ~/.local/share/xed/plugins
rm -rf ~/.local/share/xed/plugins/xedown ~/.local/share/xed/plugins/xedown.plugin
tar -xzf dist/xedown-0.1.0.tar.gz -C ~/.local/share/xed/plugins
```

Testing the archive rather than the working tree is the whole point: the two are
meant to be identical, and this is how you find out when they are not. The
shutdown harness can be pointed at the same artifact —
`XEDOWN_INSTALL_FROM_ARCHIVE=dist/xedown-0.1.0.tar.gz scripts/run-shutdown-tests.sh`
— which is worth doing once per release before working through the rows by hand.

Automated coverage stops at the GTK boundary, so these steps are the last gate.

`scripts/run-integration-tests.sh` now drives a real xed instance and asserts on the live
widget tree for everything that can be checked without a human: the save/revert host-state
hazard, `show_all()` in both modes, search controls not floating over the preview, the
scroll round trip through a mode switch, a save never resetting scroll or reloading the
page, closing a tab quickly, **moving a tab to another window without destroying its
preview**, disabling the plugin for real (via the same `active-plugins` gsettings key the
Preferences dialog uses) and confirming the `_xedown_controller` attribute is fully
removed, several independent Markdown tabs, and `Gtk.Action.is_sensitive()` on both a `.md`
and a `.txt` tab. Run it first — it takes a couple of minutes and catches regressions in
exactly those hazards. Rows below that overlap with the two harnesses (18, 20, 21, 22, 23,
24) are still listed deliberately, reframed for what a human's eyes catch that a structural
assertion cannot — a visual glitch, an unexpected flicker, a real click landing wrong — not
because the harnesses leave those scenarios untested. **The rest of this checklist is for
what they genuinely cannot see at all**: rendering quality, real mouse and keyboard
interaction, and theme switching.

`scripts/run-shutdown-tests.sh` covers the other half of that gate: shutdown. The
integration harness above runs one long sequence, so it can only ever observe a single
shutdown — and because that sequence disables the plugin near the end, the shutdown it
sees is one where xedown is no longer active. The shutdown harness gives each scenario
its own xed launch and closes the window(s) the way a user does (a real window-manager
close request, never a signal, so xed runs its normal shutdown and plugin-unload path),
then checks that launch's stderr on its own. Six scenarios: closing a Markdown tab,
closing several Markdown tabs, closing several xed windows, moving a tab between
windows, disabling the plugin before closing, and closing xed with previews live.
Run it before tagging; it takes a few minutes.

Start with a terminal visible: `xed` prints warnings and tracebacks there, and a silent
terminal is itself one of the checks.

Two ready-made documents in `tests/fixtures/` give the checklist below something
concrete to open. Use `tests/fixtures/showcase.md` for everything that should render
and behave correctly — every mode-switching, editing and window-management row, plus
rows 13–15. Use `tests/fixtures/edge-cases.md` specifically for rows 16 and 17
(missing and remote images): its broken references are deliberate test cases, not
mistakes — see `tests/fixtures/README.md` before changing anything in it. While
`edge-cases.md` is open, it is also worth glancing over its basic bidirectional-text
cases (an Arabic paragraph, heading, list, table, blockquote, and a Python fence with
Arabic comments that must stay left-to-right) and its demonstration of the known GFM
paragraph/list gap tracked in `docs/known-issues.md` — neither has its own numbered
row, but both are real content in that file and worth a look while it is on screen.

| # | Step | Expected |
| --- | --- | --- |
| 1 | Enable **Xedown** in *Preferences → Plugins* | Enables with no error dialog and no terminal output |
| 2 | Open a `.md` file, for example `tests/fixtures/showcase.md` | Opens in Preview mode with a mode bar at the top of the tab |
| 3 | Open a `.markdown` file (a copy of `tests/fixtures/showcase.md` renamed) | Same behaviour |
| 4 | Open a `.txt` file | No mode bar; *View → Toggle Markdown Preview* is visibly greyed out |
| 5 | Click **Markdown** | Source appears with text and cursor position intact |
| 6 | Click **Preview** | Rendered document returns at its previous scroll position |
| 7 | Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> | Toggles the same way as the buttons |
| 8 | Edit in Markdown mode, switch to Preview | Preview shows the edited content |
| 9 | Type in Markdown mode | No rendering work happens until you switch (no lag, no flicker) |
| 10 | Edit while Preview is visible via another means (e.g. an external tool saving the file) | Preview refreshes within roughly a quarter second |
| 11 | Save, then revert, while Preview is active, watching closely | No visible flicker to the source editor at any point — the harness asserts the end state; this is about the transition looking clean |
| 12 | Modify the file outside the editor, then reload when xed offers | Preview refreshes; xed's own "reload?" prompt appears — the plugin does not silently reload on its own |
| 13 | Click the external link in `tests/fixtures/showcase.md` | Opens in the default browser, not in the preview |
| 14 | Click the relative link to `linked.md` in `tests/fixtures/showcase.md` | Opens in a new xed tab |
| 15 | Click the anchor link in `tests/fixtures/showcase.md` | Scrolls within the preview |
| 16 | In `tests/fixtures/edge-cases.md`, reference a missing image | Inline placeholder naming the path; no blank space |
| 17 | In `tests/fixtures/edge-cases.md`, reference a remote image | Placeholder; nothing is fetched from the network (check with a network monitor if in doubt) |
| 18 | Open several Markdown files in tabs and click between them | Each keeps its own mode and scroll position, with no visible redraw glitches |
| 19 | Switch the desktop between light and dark | Preview follows without a restart |
| 20 | Close a tab (click its close button) while Preview is active | Closes cleanly, no warnings |
| 21 | Open a second window with Markdown files | Both windows work independently |
| 22 | Disable the plugin from *Preferences → Plugins* while Preview is active, then re-enable it | Source editor returns in every tab on disable, with no warnings; Preview works again on re-enable |
| 23 | Drag a Markdown tab out into its own window (or *Documents → Move to New Window*) while Preview is active | Mode bar and preview arrive intact in the new window — this used to silently strand the tab in plain Source mode with no way back |
| 24 | Review the terminal | No warnings, criticals, tracebacks or segfaults, with one named exception — see below. The six shutdown scenarios are automated (`scripts/run-shutdown-tests.sh`); what this row adds is the paths a script cannot drive — a real drag of a tab out of the notebook, a click on a window's close button, a close from the window menu |

A crash, traceback, segfault, warning or `Gtk-CRITICAL` at shutdown means a
controller left something connected, and is a release blocker, not a cosmetic
issue — **with exactly one named exception**: the assertion

```
(xed:PID): Gtk-CRITICAL **: HH:MM:SS.mmm: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP (action_group)' failed
```

printed at window close after the "move a tab to another window" step (row 23).
This is a confirmed **xed 3.8.9 core bug**, not a xedown defect — it reproduces
byte-identically with xedown completely uninstalled. That is not taken on
trust from an old report: `XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh
move-tab` re-runs the identical scenario with xedown absent from the plugin
directory entirely, and it is worth re-running whenever the exception is
questioned.

Both harnesses carry the same allowlist, **anchored to a whole log line**
(`^...$`) rather than matched as a substring, so it cannot excuse a second
message printed on the same line. `tests/unit/test_shutdown_allowlist.py`
enforces that: it reads the pattern out of both scripts, fails if they drift
apart, and fails if the pattern starts admitting a different assertion in the
same function, the same assertion at a different log level, the same text from
another process, or the known line with anything else attached to it.

It is known and benign: do not treat it as a release blocker. This exception
does not generalize — any other warning, critical, traceback or segfault,
including a *different* assertion inside the same `gtk_action_group_get_action`
call, still blocks the release.
