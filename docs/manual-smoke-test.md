# Manual smoke test

Run before tagging a release, on a clean install produced from the release archive.
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
exactly those hazards. Rows below that overlap with the harness (18, 20, 22, 23) are still
listed deliberately, reframed for what a human's eyes catch that a structural assertion
cannot — a visual glitch, an unexpected flicker, a real click landing wrong — not because
the harness leaves those scenarios untested. **The rest of this checklist is for what the
harness genuinely cannot see at all**: rendering quality, real mouse and keyboard
interaction, and theme switching.

Start with a terminal visible: `xed` prints warnings and tracebacks there, and a silent
terminal is itself one of the checks.

| # | Step | Expected |
| --- | --- | --- |
| 1 | Enable **Xedown** in *Preferences → Plugins* | Enables with no error dialog and no terminal output |
| 2 | Open a `.md` file | Opens in Preview mode with a mode bar at the top of the tab |
| 3 | Open a `.markdown` file | Same behaviour |
| 4 | Open a `.txt` file | No mode bar; *View → Toggle Markdown Preview* is visibly greyed out |
| 5 | Click **Markdown** | Source appears with text and cursor position intact |
| 6 | Click **Preview** | Rendered document returns at its previous scroll position |
| 7 | Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> | Toggles the same way as the buttons |
| 8 | Edit in Markdown mode, switch to Preview | Preview shows the edited content |
| 9 | Type in Markdown mode | No rendering work happens until you switch (no lag, no flicker) |
| 10 | Edit while Preview is visible via another means (e.g. an external tool saving the file) | Preview refreshes within roughly a quarter second |
| 11 | Save, then revert, while Preview is active, watching closely | No visible flicker to the source editor at any point — the harness asserts the end state; this is about the transition looking clean |
| 12 | Modify the file outside the editor, then reload when xed offers | Preview refreshes; xed's own "reload?" prompt appears — the plugin does not silently reload on its own |
| 13 | Click an external link | Opens in the default browser, not in the preview |
| 14 | Click a relative link to another `.md` file | Opens in a new xed tab |
| 15 | Click a heading anchor link | Scrolls within the preview |
| 16 | Reference a missing image | Inline placeholder naming the path; no blank space |
| 17 | Reference a remote image | Placeholder; nothing is fetched from the network (check with a network monitor if in doubt) |
| 18 | Open several Markdown files in tabs and click between them | Each keeps its own mode and scroll position, with no visible redraw glitches |
| 19 | Switch the desktop between light and dark | Preview follows without a restart |
| 20 | Close a tab (click its close button) while Preview is active | Closes cleanly, no warnings |
| 21 | Open a second window with Markdown files | Both windows work independently |
| 22 | Disable the plugin from *Preferences → Plugins* while Preview is active, then re-enable it | Source editor returns in every tab on disable, with no warnings; Preview works again on re-enable |
| 23 | Drag a Markdown tab out into its own window (or *Documents → Move to New Window*) while Preview is active | Mode bar and preview arrive intact in the new window — this used to silently strand the tab in plain Source mode with no way back |
| 24 | Review the terminal | No warnings, criticals, tracebacks or segfaults |

A crash or `Gtk-CRITICAL` at shutdown means a controller left something connected.
Teardown correctness is a release blocker, not a cosmetic issue.
