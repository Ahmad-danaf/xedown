# Manual smoke test

Run before tagging a release, on a clean install produced from the release archive:

```bash
scripts/build-release.sh
mkdir -p ~/.local/share/xed/plugins
rm -rf ~/.local/share/xed/plugins/xedown ~/.local/share/xed/plugins/xedown.plugin
tar -xzf dist/xedown-*.tar.gz -C ~/.local/share/xed/plugins
```

Testing the archive rather than the working tree is the whole point: the two are
meant to be identical, and this is how you find out when they are not. Point the
shutdown harness at the same artifact before starting the rows:

```bash
ARCHIVE="$(ls dist/xedown-*.tar.gz)"
XEDOWN_INSTALL_FROM_ARCHIVE="$ARCHIVE" scripts/run-shutdown-tests.sh
```

Run it that way rather than plainly — a normal run installs the working tree and
leaves it installed, which would quietly turn every row below into a test of the
working tree instead of the artifact you are about to ship.

Automated coverage stops at the GTK boundary, so these steps are the last gate.

`scripts/run-integration-tests.sh` drives a real xed instance and asserts on the live
widget tree: the save/revert host-state hazard, `show_all()` in both modes, the scroll
round trip through a mode switch, a save never resetting scroll or reloading the page,
a real in-page anchor click routing to the preview instead of the desktop file opener,
the buffer never being reloaded by the plugin on its own, closing a tab quickly,
**moving a tab to another window without destroying its preview**, disabling the plugin
for real (via the same `active-plugins` gsettings key the Preferences dialog uses) and
confirming the `_xedown_controller` attribute is fully removed, several independent
Markdown tabs, and `Gtk.Action.is_sensitive()` on both a `.md` and a `.txt` tab. Run it
first — it takes a couple of minutes and catches regressions in exactly those hazards.

Some rows below cover ground the harnesses also touch. They are kept deliberately, for
what a human's eyes catch that a structural assertion cannot — a visual glitch, an
unexpected flicker, a real click landing wrong. **The rest of this checklist is for what
the harnesses genuinely cannot see at all**: rendering quality, real mouse and keyboard
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
rows 13–15 and rows 32–34. Use `tests/fixtures/edge-cases.md` specifically for rows
16 and 17 (missing and remote images): its broken references are deliberate test
cases, not mistakes — see `tests/fixtures/README.md` before changing anything in it.
While `edge-cases.md` is open, it is also worth glancing over its basic
bidirectional-text cases (an Arabic paragraph, heading, list, table, blockquote, and
a Python fence with Arabic comments that must stay left-to-right) and its
demonstration of the known GFM paragraph/list gap tracked in `docs/known-issues.md`
— neither has its own numbered row, but both are real content in that file and
worth a look while it is on screen. Rows 32–34 also need a scratch stylesheet at
`~/.config/xedown/mine.css`, which row 36 removes.

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
| 10 | With Preview showing, change the file outside xed and accept xed's reload prompt | The preview follows the new content by itself, about a quarter second after the buffer changes — you never have to switch modes to see it |
| 11 | Save, then revert, while Preview is active, watching closely | No visible flicker to the source editor at any point — the harness asserts the end state; this is about the transition looking clean |
| 12 | Modify the file outside the editor, then reload when xed offers | Preview refreshes; xed's own "reload?" prompt appears — the plugin does not silently reload on its own |
| 13 | Click the external link in `tests/fixtures/showcase.md` | Opens in the default browser, not in the preview |
| 14 | Click the relative link to `linked.md` in `tests/fixtures/showcase.md` | Opens in a new xed tab |
| 15 | Click the anchor link in `tests/fixtures/showcase.md` | Scrolls within the preview |
| 16 | In `tests/fixtures/edge-cases.md`, reference a missing image | Inline placeholder naming the path; no blank space |
| 17 | In `tests/fixtures/edge-cases.md`, reference a remote image | Placeholder; nothing is fetched from the network (check with a network monitor if in doubt) |
| 18 | Open several Markdown files in tabs and click between them | Each keeps its own mode and scroll position, with no visible redraw glitches |
| 19 | Switch the desktop between light and dark | Preview follows without a restart |
| 20 | Set `"preview_theme": "focused"` in `~/.config/xedown/settings.json`, restart xed, open `tests/fixtures/showcase.md` | Calm, low-contrast surfaces; no rules under headings; tables with horizontal rules only |
| 21 | Repeat for `minimal` | Square corners throughout, no code-block fill, no table grid, noticeably more space |
| 22 | Repeat for `document` | Serif prose in a visibly narrower column; uppercase letterspaced `h6`; a short centred horizontal rule |
| 23 | Repeat for `repository` | Indistinguishable from xedown 0.1.0 |
| 24 | Set `"preview_theme": "nonsense"` in `~/.config/xedown/settings.json`, restart xed, open `tests/fixtures/showcase.md` | Repository renders; the preview is never unstyled |
| 25 | In each of the four themes, open `tests/fixtures/edge-cases.md` | The missing-image and remote-image placeholders are obviously placeholders in every theme, not blank gaps |
| 26 | With `tests/fixtures/showcase.md` open, narrow the window until the table no longer fits the column | The table scrolls horizontally inside its own area; the page itself never scrolls sideways, in any theme |
| 27 | Switch the desktop between light and dark in each of the four themes | Every theme follows live, and stays readable in both |
| 28 | Close a tab (click its close button) while Preview is active | Closes cleanly, no warnings |
| 29 | Open a second window with Markdown files | Both windows work independently |
| 30 | Disable the plugin from *Preferences → Plugins* while Preview is active, then re-enable it | Source editor returns in every tab on disable, with no warnings; Preview works again on re-enable |
| 31 | Drag a Markdown tab out into its own window (or *Documents → Move to New Window*) while Preview is active | Mode bar and preview arrive intact in the new window — this used to silently strand the tab in plain Source mode with no way back |
| 32 | Create `~/.config/xedown/mine.css` containing `body { background: #101820; }`, set `"custom_stylesheet": "~/.config/xedown/mine.css"` in `settings.json`, restart xed and open `tests/fixtures/showcase.md` | The preview background is that colour rather than the theme's — the stylesheet is layered over the theme, not replacing it |
| 33 | With that preview still open, open `mine.css` in xed itself, change the colour to `#201810` and save | The open preview changes colour within a moment. No restart, no reopening the document, no flicker of the wrong content |
| 34 | Delete `mine.css` from a terminal while the preview is still open | Within a moment the preview returns to the built-in theme, with a bar at the top of the page naming `mine.css` and saying it was not found. The document is still fully rendered below the bar |
| 35 | Review the terminal | No warnings, criticals, tracebacks or segfaults, with one named exception — see below. The six shutdown scenarios are automated (`scripts/run-shutdown-tests.sh`); what this row adds is the paths a script cannot drive — a real drag of a tab out of the notebook, a click on a window's close button, a close from the window menu |
| 36 | Clean up: remove `preview_theme`, `custom_stylesheet`, `content_width_rem` and `text_size_px` from `~/.config/xedown/settings.json` (or set them back to their defaults), and delete `~/.config/xedown/mine.css` if it is still there | Your normal settings are restored — `"nonsense"` from row 24 is not left in the file for your next real xed session |

Any crash, traceback, segfault, warning or `Gtk-CRITICAL` at shutdown is a release
blocker, not a cosmetic issue — **with exactly one named exception**: the assertion

```
(xed:PID): Gtk-CRITICAL **: HH:MM:SS.mmm: gtk_action_group_get_action: assertion 'GTK_IS_ACTION_GROUP (action_group)' failed
```

printed at window close after the "move a tab to another window" step (row 31).
This is a confirmed **xed 3.8.9 core bug**, not a xedown defect — it reproduces
byte-identically with xedown completely uninstalled. That is not taken on
trust from an old report: `XEDOWN_CONTROL=1 scripts/run-shutdown-tests.sh
move-tab` re-runs the identical scenario with xedown absent from the plugin
directory entirely, and it is worth re-running whenever the exception is
questioned.

Expect to meet its other face while working through row 31: the same xed bug
sometimes segfaults instead of printing the assertion (identical stack, in
xed's own `received_clipboard_contents` — see
[known-issues.md](known-issues.md)). A crash there is **not** covered by this
exception and is not something to wave through; confirm it is the same stack
with `coredumpctl info <pid>` and that it still happens under
`XEDOWN_CONTROL=1`. Anything that needs xedown installed to reproduce is a
blocker.

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
