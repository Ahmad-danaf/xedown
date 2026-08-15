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
Point it at the same archive, for the same reason as the shutdown harness above:

```bash
XEDOWN_INSTALL_FROM_ARCHIVE="$ARCHIVE" scripts/run-integration-tests.sh
```

Run it that way rather than plainly, same as the shutdown harness — a normal run
installs the working tree and leaves it installed, which would quietly turn every
row below into a test of the working tree instead of the artifact you are about to
ship.

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
then checks that launch's stderr on its own. Twelve scenarios: closing a Markdown
tab, closing twelve Markdown tabs, closing several xed windows, moving a tab
between windows, disabling the plugin before closing, closing xed with previews
live, closing the settings window, closing it after changing a setting, closing
xed with remote-image fetches still in flight, disabling the plugin and turning
it back on in one session, restarting xed and checking what survived, and twenty
open/close cycles measured on the process tree. Run it before tagging; it takes
several minutes.

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
a Python fence with Arabic comments that must stay left-to-right) and the list
written directly under a paragraph with no blank line, which renders as a list
— neither has its own numbered row, but both are real content in that file and
worth a look while it is on screen. Rows 32–34 also need a scratch stylesheet at
`~/.config/xedown/mine.css`, which row 46 removes.

Rows 47–53 use `tests/fixtures/rtl.md` and `tests/fixtures/mixed-direction.md`.
Both are clean documents like `showcase.md` — an error placeholder in either is
a real regression. Row 53 restores the settings file, like row 46.

Rows 95–101 need Orca (Linux Mint's screen reader) actually running. Everything
the `a11y-*` checks in `tests/integration/xedown_probe/__init__.py` (run
through `scripts/run-integration-tests.sh`) can reach — names, focus, checked
state, landmark, language — is confirmed structurally before you ever get
here. `scripts/run-orca-tests.sh` goes further: it drives a real xed session
under Orca in an isolated Xephyr display and asserts on what Orca actually
says for most of these rows, so what follows below is what it already
established, not an open question — you are confirming it rather than
discovering it. It does not replace this checklist: it needs its own display
and speaks out loud, and a couple of rows (99, and the moment the stale dot
first appears in row 100) are not things it can cleanly assert on for reasons
explained inline below.

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
| 10 | With Preview showing, use *Search → Find and Replace* to replace a word that occurs throughout the document | The preview follows the buffer by itself, about a quarter second after the change — you never have to switch modes to see it |
| 11 | Save, then revert, while Preview is active, watching closely | No visible flicker to the source editor at any point — the harness asserts the end state; this is about the transition looking clean |
| 12 | With Preview showing, edit the document, then *File → Revert* and confirm | The editor and the preview both go back to the file on disk. The plugin never reverts anything on its own — the confirmation you answered is xed's |
| 13 | Click the external link in `tests/fixtures/showcase.md` | Opens in the default browser, not in the preview |
| 14 | Click the relative link to `linked.md` in `tests/fixtures/showcase.md` | Opens in a new xed tab |
| 15 | Click the anchor link in `tests/fixtures/showcase.md` | Scrolls within the preview |
| 16 | In `tests/fixtures/edge-cases.md`, reference a missing image | Inline placeholder naming the path; no blank space |
| 17 | In `tests/fixtures/edge-cases.md`, reference a remote image, with `remote_images` left at its default `never` | A placeholder names the address and says the image was not loaded. Nothing is fetched — blocked is the default until you click **Load** or turn `remote_images` on; see rows 124–129 for what fetching actually looks like |
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
| 35 | Review the terminal | No warnings, criticals, tracebacks or segfaults, with one named exception — see below. The twelve shutdown scenarios are automated (`scripts/run-shutdown-tests.sh`); what this row adds is the paths a script cannot drive — a real drag of a tab out of the notebook, a click on a window's close button, a close from the window menu |
| 36 | Hover a code block in `tests/fixtures/showcase.md` | A **Copy** button fades in at the corner. The code does not move or resize as it appears |
| 37 | Click it, then paste somewhere | The code arrives exactly as written, including indentation. The button says **Copied** for a moment, then goes back to **Copy** |
| 38 | Tab to the copy button instead of hovering | It becomes visible with a clear focus ring, and <kbd>Enter</kbd> copies |
| 39 | Select the whole preview (<kbd>Ctrl</kbd>+<kbd>A</kbd>) and copy | The word "Copy" is nowhere in what you pasted |
| 40 | Copy from the Python fence with Arabic comments in `tests/fixtures/edge-cases.md` | The pasted code is left-to-right and byte-identical, comments included |
| 41 | Set `"code_copy_buttons": false` while a preview is open | Every button disappears at once, in every open tab, with no reload and no scroll jump |
| 42 | Open `tests/fixtures/showcase.md` and look at the task list, in each theme, light and dark | Checked and unchecked boxes are obviously different and obviously part of the theme. Clicking one does nothing and does not look broken |
| 43 | Scroll the wide table in `tests/fixtures/showcase.md` sideways | A shadow marks the side with more content and swaps as you reach each end |
| 44 | Look at the tall and small images in `tests/fixtures/showcase.md` | The tall one fits the window without distortion; the small one is its own size, not stretched |
| 45 | Set `"image_fallback": "alt"`, then `"hidden"`, with `tests/fixtures/edge-cases.md` open | Alt text alone, then nothing at all, for every image that cannot be shown — missing, remote-and-blocked, or otherwise. Both apply immediately. This is presentation only: it changes what you see, not whether anything is fetched — `remote_images` (still `never` here) is what decides that |
| 46 | Clean up: remove `preview_theme`, `custom_stylesheet`, `content_width_rem`, `text_size_px`, `image_fallback` and `code_copy_buttons` from `~/.config/xedown/settings.json` (or set them back to their defaults), and delete `~/.config/xedown/mine.css` if it is still there | Your normal settings are restored — `"nonsense"` from row 24 is not left in the file for your next real xed session |
| 47 | Open `tests/fixtures/rtl.md`, in each of the four themes, light and dark | Bullets, numbers and their indentation on the right; the nested list indented from the right; the quote bar on the right; the table's first column on the right; the footnote marker and its back-reference on the right, with the arrow pointing right |
| 48 | In the same file, hover a code block | The copy button is at the **top-left** of the block, and the code inside it still reads left to right with every line starting at the left edge |
| 49 | Scroll the wide table in `tests/fixtures/rtl.md` sideways | A shadow marks the side with more content, starting on the **left** edge — the table's first column is on the right — and swaps to the right edge as you reach it |
| 50 | Open `tests/fixtures/mixed-direction.md` | The page is right-to-left, but the English paragraph reads left to right against the left edge while the bullets of the list below it stay on the right. The path marked with `<bdi>` and the one marked `dir="ltr"` both read correctly, slashes included |
| 51 | Set `"text_direction": "ltr"` in `~/.config/xedown/settings.json`, restart xed, and reopen `tests/fixtures/rtl.md` | The layout is left-to-right — bullets and quote bars on the left — while every Arabic paragraph still reads right-to-left, stays right-aligned, and keeps its full stop on the left |
| 52 | Remove `text_direction` from `~/.config/xedown/settings.json` (row 51 left it forced to `ltr`) and restart xed, then open a new empty file, save it as `scratch.md`, switch to Markdown and type a line of Arabic, switch to Preview, and press <kbd>Ctrl</kbd>+<kbd>Z</kbd> to undo the line and <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Z</kbd> to redo it | About a quarter of a second after each key press the layout flips in place between left-to-right and right-to-left — no page reload, no flash, no lost scroll position |
| 53 | Clean up: delete `scratch.md` | Your normal settings are restored |
| 54 | With `tests/fixtures/showcase.md` open in Preview, press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd>, then <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd> again | The first shows the Markdown source; the second does nothing at all |
| 55 | Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd>, then click inside the rendered page and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> | The preview returns, then the source — the shortcut works with focus inside the preview |
| 56 | Open the *View* menu | Four xedown entries, each showing its own key combination |
| 57 | Switch to a `.txt` tab and open *View* | All four xedown entries are visibly greyed out |
| 58 | Back in Preview, drag-select a paragraph | The selection is clearly visible against the page |
| 59 | Press <kbd>Ctrl</kbd>+<kbd>C</kbd> and paste into a new tab | The rendered text arrives — no `#`, no `*`, no Markdown syntax |
| 60 | Press <kbd>Ctrl</kbd>+<kbd>A</kbd> in the preview, then <kbd>Ctrl</kbd>+<kbd>C</kbd>, and paste | The whole rendered document, without the copy buttons' word "Copy" and without any stylesheet notice |
| 61 | Switch to Markdown, press <kbd>Ctrl</kbd>+<kbd>A</kbd> then <kbd>Ctrl</kbd>+<kbd>C</kbd>, and paste | The Markdown source, exactly as xed has always copied it. Undo, cut and paste all still behave normally |
| 62 | Right-click a selection in the preview | **Copy** and **Select All**, and nothing else — no Back, no Reload, no Inspect |
| 63 | Repeat rows 58 and 62 in each of the four themes, in both light and dark | The selection stays clearly visible and legible in all eight combinations |
| 64 | Set `"auto_refresh": false`, restart xed, open a Markdown file, switch to Markdown mode and type a line, switch to Preview (which renders it), then press <kbd>Ctrl</kbd>+<kbd>Z</kbd> | The mode bar already shows a **Refresh** button; after <kbd>Ctrl</kbd>+<kbd>Z</kbd> a dot appears beside it and the page still shows the line you typed — undone in the buffer but not re-rendered |
| 65 | Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> | The page catches up, the dot disappears, and the scroll position is kept |
| 66 | Set `"default_mode": "markdown"`, restart xed, and open a Markdown file you have never opened before | It opens in Markdown mode, scrolled and with the cursor where xed put it — not jumped to the top |
| 67 | Switch it to Preview, close the tab, and reopen the same file | It opens in Preview: the remembered mode wins over the default |
| 68 | Set `"remember_mode_per_file": false`, restart xed, and reopen that same file | It opens in Markdown again — the default decides once more |
| 69 | Clean up: remove `default_mode`, `remember_mode_per_file` and `auto_refresh` from `~/.config/xedown/settings.json`, and delete `~/.config/xedown/modes.json` | Your normal settings are restored |
| 70 | Open a long `.md` file in Preview and press <kbd>Ctrl</kbd>+<kbd>F</kbd> | A search bar appears under the preview with the cursor already in it |
| 71 | Type a word that occurs several times | Matches highlight as you type, the current one is scrolled into view, and the count reads `1 of N` |
| 72 | Press <kbd>Enter</kbd> a few times, then <kbd>Shift</kbd>+<kbd>Enter</kbd> | The current match moves forward then back, the count follows, and each one is scrolled into view |
| 73 | Keep pressing <kbd>Enter</kbd> past the last match | It wraps to the first |
| 74 | Type something the document does not contain | `No matches`, and no highlighting anywhere |
| 75 | Search a word with mixed case, then click `Aa` | The count changes to the case-sensitive one |
| 76 | Select a paragraph next to a highlighted match, in each of the four themes, light and dark | The highlight is legible in every one, and is unmistakably not the selection |
| 77 | Press <kbd>Escape</kbd> | The bar goes, every highlight goes, and the arrow keys scroll the preview immediately |
| 78 | Open the bar again, then switch to Markdown mode | The bar closes |
| 79 | Press <kbd>Ctrl</kbd>+<kbd>F</kbd> in Markdown mode | xed's own find bar appears, exactly as it always has |
| 80 | In `tests/fixtures/showcase.md`, search `with bold text` — it starts in plain text and crosses into the bold word — and step to it so it is the current match | The highlight, outline included, reads as one continuous run across the boundary, not two boxes with a seam |
| 81 | Search `Hello` (it appears inside the Python fenced block in `tests/fixtures/showcase.md`), in each of the four themes, light and dark | The match highlight stays readable against the syntax-highlighting colours behind it, in every combination |
| 82 | With a search open and a match highlighted, switch the desktop between light and dark | The preview comes back themed to match, the highlighting and match count are still there, and it settles at a sensible scroll position rather than jumping |
| 83 | With a `.md` file open in Preview and nothing unsaved, run `echo '# Changed' >> file.md` in a terminal | The preview updates within a moment. No dialog, no bar, and the scroll position does not jump |
| 84 | Switch to Markdown mode | The editor still shows the old text, and xed puts up its own **Reload** bar |
| 85 | Accept xed's **Reload**, switch back to Preview | Both show the new text |
| 86 | Type a character, then run the same `echo` again | A bar appears: *This file changed on disk. Your unsaved edits are still showing.* The preview still shows what you typed |
| 87 | Click **Reload…**, then **Cancel** in xed's dialog | Nothing changes. Your edits are still there |
| 88 | Click **Reload…** again, then **Revert** | The document and the preview both show the file on disk, and the bar is gone |
| 89 | Make the bar appear again (edit, then `echo` to the file), then press <kbd>Ctrl</kbd>+<kbd>S</kbd> and accept xed's *Save Anyway* | The bar goes, the preview shows **your** text, and the file on disk matches it — the other way a divergence ends, and the one the probe cannot script because xed's confirmation is modal |
| 90 | Undo back to an unmodified document after an external change | The bar goes and the preview picks up the file |
| 91 | Run a loop of ten quick writes to the file | One settled update. xed stays responsive throughout |
| 92 | `rm` the file, then recreate it with new content | No error dialog and no error page while it is gone; the preview catches up once it is back |
| 93 | Save the file under a new name (*File → Save As*), then edit the **new** file from a terminal | The preview follows the new file. Editing the old path changes nothing |
| 94 | Set `"watch_external_changes": false`, restart xed, repeat the first row | Nothing happens until you refresh by hand |
| 95 | Reset `~/.config/xedown/settings.json` to defaults (row 94 turned `watch_external_changes` off) and restart xed. Start Orca (<kbd>Super</kbd>+<kbd>Alt</kbd>+<kbd>S</kbd>, or `orca &`), then open `tests/fixtures/showcase.md` | Orca announces the window and the preview |
| 96 | Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> to switch modes, twice | Orca says **"Markdown source"** switching to Source, then **"Preview"** switching back — measured, reproducibly, by `scripts/run-orca-tests.sh`. Confirm you hear exactly that |
| 97 | <kbd>Tab</kbd> into the mode bar, <kbd>Tab</kbd> again, then press <kbd>Space</kbd> to activate the newly-focused button | Focusing the bar announces its state: "Preview toggle button pressed." (measured via a direct focus call in the harness, not an actual Tab press — Tab should reach the same control). Tabbing to the next control announces it by name and state: "Markdown source toggle button not pressed." Activating it switches mode without repeating the mode name — deliberate: the mode announcement is suppressed while a mode toggle button itself has focus, so it is not heard twice. Don't expect silence right after, though: focus lands on the source view as part of the switch, and Orca goes on to read it (in the measured run: "pressed", then the source view's own content and cursor position) |
| 98 | With the preview showing, press <kbd>Down</kbd> and <kbd>Page Down</kbd> without clicking first | The document scrolls visually, but Orca says **nothing** — measured, reproducibly, as complete AT-SPI silence, not merely unannounced speech. This is not a xedown defect with a known fix; the cause is inside WebKit2GTK's own AT-SPI bridge (see [docs/known-issues.md](known-issues.md)). Confirm the silence, and that scrolling still happens |
| 99 | Press <kbd>Ctrl</kbd>+<kbd>F</kbd>, tab through the search bar at a normal pace | Each search-bar control is announced by name: "Match case toggle button not pressed.", "Previous match push button.", "Next match push button.", "Close search push button." — measured, once the probe's Tab presses were spaced out at a normal pace (an earlier, zero-delay burst had left Orca silent even though the events were well-formed; that was a probe defect, since fixed). This row still is not asserted automatically by `scripts/run-orca-tests.sh`, for a different, still-current reason: the probe's fixed six-press Tab count overshoots the search bar's own last control into xed's surrounding chrome (measured: "Show or hide the side pane in the current window.", not a search-bar control), and row 99 was never one of the rows this plan's brief required an automated expectation for. Stop counting controls once you reach **Close search** |
| 100 | Set `"auto_refresh": false`, restart xed, open the file in Preview, switch to Markdown, type a line, switch back to Preview (it renders), then press <kbd>Ctrl</kbd>+<kbd>Z</kbd> so the stale dot appears. With the dot showing, <kbd>Tab</kbd> to the Refresh button, then press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> while it still has focus | The stale dot's own appearance is **not** announced — measured; the only speech at that moment is the ordinary "document modified" title change, nothing about staleness. Reaching the Refresh button *is* announced in full: "Refresh the preview push button." then "The preview is out of date — refresh it (Ctrl+Shift+R)" (measured via a direct focus call in the harness, not an actual Tab press — Tab should reach the same button). Pressing Ctrl+Shift+M with the Refresh button focused still announces the mode change ("Markdown source") — the double-announcement suppression covers only the two mode toggle buttons, not the Refresh button, which is also in the mode bar |
| 101 | Remove `auto_refresh` from `~/.config/xedown/settings.json`, restart xed, then trigger the external-change bar (edit the file from a terminal while it has unsaved edits) | The bar's warning text is announced: "Warning This file changed on disk. Your unsaved edits are still showing." — measured, reproducibly. (Whether tabbing to the bar's own **Reload…** button announces it by name was not part of this measurement.) |
| 102 | *Preferences → Plugins*, select **Xedown**, click **Preferences** | The settings panel opens inside the plugin manager's own dialog |
| 103 | Change **Theme** there with a preview open behind | The preview restyles while the dialog is still open |
| 104 | *View → Markdown Preview Settings* | The same settings appear, in our own window |
| 105 | Open a non-Markdown file | **Markdown Preview Settings** stays enabled; the other four xedown entries grey out |
| 106 | Tab from the top of the window to the bottom | Focus reaches every control in the order they appear, ending on **Close** |
| 107 | With a screen reader running, Tab through the window | Each control speaks its label and its current value |
| 108 | **Browse…** beside *Custom stylesheet*, pick a `.css` file | The path appears and every open preview picks it up |
| 109 | Point *Custom stylesheet* at a file that does not exist | A notice under the row says so, naming the file |
| 110 | Type `5000` into *Content width* and press Enter | It snaps to 100 in front of you, not silently later |
| 111 | **Restore defaults…**, then **Cancel** | Nothing changes |
| 112 | **Restore defaults…**, then **Restore** | All twelve controls snap back and every preview follows |
| 113 | Open both entry points at once, change a value in one | The other follows immediately |
| 114 | Run xed under an RTL desktop locale and open the window | Labels right, controls left, nothing clipped |
| 115 | Open and close the window ten times, then close xed | No warnings on standard error |
| 116 | With `tests/fixtures/showcase.md` open in Preview, open *View → Markdown Preview Settings* and set **Content width** to 30, then 100; then set **Text size** to 28 | The column narrows and widens as you change it, and the text grows with the whole document — headings, code and table text scale together, not just body text. No page reload and no scroll jump at any point |
| 117 | Set **Refresh delay** to 2000 ms, close the settings window, and with Preview showing press <kbd>Ctrl</kbd>+<kbd>Z</kbd> in the tab | The preview waits about two seconds before catching up, rather than a quarter second — the new delay reached a tab that was already open |
| 118 | Open two Markdown files in Preview, click the other tab and come back, then press <kbd>Down</kbd> and <kbd>Page Down</kbd> without clicking the page first | The preview scrolls straight away. The keyboard stays with what you can see, rather than with the hidden source |
| 119 | Copy an image beside a Markdown document of your own, reference it, then `chmod 000` the image and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> | A placeholder says the image could not be read, naming it, with your alt text alongside — not "not found", and not a blank space |
| 120 | Add `![diagram](http://[::1/a.png)` — a malformed address — to that document and refresh | A placeholder says the reference could not be resolved. Nothing is fetched, and the rest of the document renders normally |
| 121 | In the same document, write a paragraph and start a `-` list on the very next line, with no blank line between them | It renders as a list under the paragraph, the way GitHub renders it — not as one run-on paragraph |
| 122 | *Preferences → Plugins*, select **Xedown** | The version reads **0.3.0** |
| 123 | Clean up: **Restore defaults…** in the settings window, `chmod 644` the image from row 119, and delete the scratch document and image rows 119–121 used | Your settings are back to defaults and nothing from these rows is left behind |
| 124 | Create a new Markdown document referencing a real `https://` image you can reach (any image URL from a GitHub README works), save it, and open it in Preview, with `remote_images` left at its default `never` | A placeholder names the address and says the image was not loaded, and the mode bar shows a chip reading `1 remote image` next to a **Load** button |
| 125 | Click **Load** | The placeholder is replaced by a loading skeleton, then by the real image once it arrives; the chip and **Load** button disappear once nothing is left blocked |
| 126 | Add `![insecure](http://example.com/x.png)` to the same document and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> | A placeholder says the address is not encrypted (`http://`) and names it. It is never loaded, whether or not you have already clicked **Load**, and it does not add to the chip's count |
| 127 | Open `tests/fixtures/edge-cases.md` again and click its chip's **Load** | The generic "not loaded" wording on its remote image is replaced by the real reason xedown got back attempting `https://example.com/not-fetched.png` — a fetch is actually made this time, not merely refused |
| 128 | Back in the document from row 124, disconnect from the network (turn off Wi-Fi, or unplug the cable) and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> | A placeholder says you appear to be offline and to refresh once you are back online — immediately, not after a multi-second wait |
| 129 | Reconnect to the network and press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd> again | The image loads normally now that the connection is back |
| 130 | Add `![huge](data:image/png;base64,iVBORw0KGgoAAAAASUhEUgAAdTAAAHUw)` — a 24-byte PNG header declaring 30000×30000 pixels — to any document and view it in Preview | `Image is too large to display safely (30000×30000 pixels) — "huge"`: a placeholder, not an attempted decode. This applies to every image xedown can measure, inline or remote, and no setting turns it off |
| 131 | Add `![huge2](data:image/png,%89PNG%0D%0A%1A%0A%00%00%00%0DIHDR%00%00u0%00%00u0%08%00%00%00%00)` — the same header, percent-encoded instead of base64 — and refresh | The same placeholder, naming the same 30000×30000. The cap is on the image, not on the spelling: a percent-encoded `data:` URL is an ordinary form browsers render, and it used to slip past the measurement entirely |
| 132 | Clean up: delete the scratch document(s) rows 124–131 used | Nothing from these rows is left behind |
| 133 | In `tests/fixtures/showcase.md`, find *A collapsible section*. Click **Show the long version**, then click it again. Then <kbd>Tab</kbd> to the same line and press <kbd>Enter</kbd> | It starts closed, showing one line with a disclosure triangle. The first click opens it onto the list and the fence inside; the second closes it again. <kbd>Tab</kbd> reaches it with a visible focus ring and <kbd>Enter</kbd> does the same thing the click does. Before this release the section could not close at all: everything inside was permanently on screen and the summary was a stray line of text above it |
| 134 | In the same file, look at *A centred block* just below, in each of the four themes, light and dark | The line is centred in the content column in all eight combinations. A theme changes its colour and its spacing, never its alignment |
| 135 | Copy `tests/fixtures/rtl.md` to a scratch file, add the line `<p align="left">هذا السطر محاذاته إلى اليسار.</p>` to it, and open it in Preview | That one paragraph sits against the **left** edge of the content column while every other paragraph on the page stays against the right — and the Arabic inside it still reads right to left, with its full stop on the left. Delete the scratch file afterwards |
| 136 | Copy a document well past the defer threshold to a scratch file — `cp tests/compat/corpus/awesome-go.md /tmp/big.md` after `scripts/fetch-corpus.sh`, or any Markdown file over about 400,000 characters — and open it with Preview as the default mode | It opens in **Markdown** mode, not Preview, showing the source immediately. The mode bar carries a chip reading `Large document (396 KB)` next to a **Preview** button. Nothing was rendered: the window is responsive from the moment it appears, with no pause before the text draws. Click **Preview** and the preview builds — the editor does freeze for about a second while it does, which is the point: you asked for it, and the button's tooltip says so |
| 137 | Switch that document back to Markdown mode, type a few words, then switch to Preview | Nothing re-renders while you type — no lag, no flicker. In Preview the mode bar shows a **Refresh** button marked stale rather than updating by itself, and the preview keeps showing the older text until you click it or press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>R</kbd>. This holds even with `"auto_refresh": true`, which is the intended override — the size guard beats the preference, for this tab only. Delete `/tmp/big.md` afterwards |

Rows 136 and 137 are the two size limits seen from the reader's side; what
rendering costs and how both numbers were derived is in
[performance.md](performance.md). The integration probe asserts the structure —
that the tab opened without rendering, that the chip is on the bar offering the
preview, and that a keystroke does not trigger a re-render — but only an eye on
a real screen confirms the thing the limits exist for, which is that the editor
stays responsive through the two moments they cover. They cover only those two:
pressing <kbd>Ctrl</kbd>+<kbd>S</kbd> in row 137 renders the whole document and
freezes the editor while it does, which is expected, not a failure of the row.

Rows 133–135 are here because a structural assertion cannot see any of it: a
tree diff sees a `<details>` element whether or not it opens, and sees
`align="left"` whether it lands left, right, or nowhere. Row 135 is the one
that matters most — `left` has to stay physically left in a right-to-left
document rather than following the page — and it needs an eye on a real screen
to check.

Rows 116–123 use a scratch document of your own rather than a fixture: rows 119
and 120 deliberately break an image reference, and `tests/fixtures/` documents
are either clean by contract or broken in specific documented ways (see
`tests/fixtures/README.md`). Row 123 undoes everything they change.

Rows 124–129 need a real network connection (and, for row 128, the ability to
disconnect it) — the one part of this checklist that reaches past your own
machine. Rows 130 and 131 do not: an inline image is refused before anything
would be fetched, and they are here because the cap they check covers inline
images too. `example.com` in row 126 does not need to resolve to anything real:
an insecure image is refused before xedown would ever connect to it. Row 127
reuses `tests/fixtures/edge-cases.md`'s own remote reference rather than a
scratch document — its address is expected to fail once actually fetched, so
what row 127 checks is that the placeholder's wording changes to say why,
not that the image appears.

Row 107 is the one claim no automated check covers: the probe walks the ATK
tree without a bridge, and the plugin-manager button in row 102 is the hop the
probe reaches through peas rather than through xed's dialog.

One v0.2 behaviour deliberately has no row. An error page recovering into a
document on refresh is asserted by the integration harness
(`error-page-recovers-on-refresh`), and the only way to produce an error page
by hand is to damage the installed plugin part-way through this checklist —
which would turn every row after it into a test of something you broke.

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
