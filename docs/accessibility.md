# Accessibility

This page states what has been **measured**, on what, and what is known not to
work. It is deliberately narrow: xedown's screen-reader behavior has been
checked on one machine with one reader, and that is not a claim of general
screen-reader support.

## Keyboard

Every control xedown adds — the **Preview | Markdown** buttons, **Refresh**,
the search bar, and the info bars — is reachable with <kbd>Tab</kbd> and
carries an accessible name. Names come from one table in `a11y.py` rather than
from literals scattered through the widget code, so a control and its
announcement cannot drift apart.

Mode switching, refreshing, and search all have shortcuts; see the table in
[the README](../README.md#keyboard-shortcuts). Switching mode moves keyboard
focus to the surface you land on and updates that surface's checked state.

On a non-Latin keyboard layout, <kbd>Ctrl</kbd>+<kbd>C</kbd> and
<kbd>Ctrl</kbd>+<kbd>A</kbd> can reach xed's hidden source view instead of the
preview; use the preview's own right-click **Copy** or **Select All**. See
[Troubleshooting](troubleshooting.md).

## Contrast

The focus indicator meets WCAG 1.4.11's 3:1 non-text threshold against every
surface it is drawn on, in all four preview themes, in both light and dark
appearance. Body, link, muted, and code text meet their own thresholds in the
same matrix. These are checked by `tests/unit/test_contrast.py` on every run,
not by inspection. [Preview appearance](themes.md) covers what a custom
stylesheet can and cannot change.

## The rendered page

A rendered document is exposed as a `role="main"` landmark, and carries a
`lang` attribute when your desktop's language can be determined. An error page
carries neither: that is xedown speaking rather than a document, and there is
no document to take a language from.

## What was measured with a screen reader

`scripts/run-orca-tests.sh` drives a real xed session under Orca 46.1 on Linux
Mint (X11) and records what is spoken. Measured working:

- <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> announces the mode you land in,
  in both directions ("Preview", "Markdown source").
- Tabbing to a mode button announces it by name and pressed state.
- Focusing **Refresh** announces its name and description.
- The external-change warning bar is announced when it appears.
- The search bar's own controls are named and given correct roles.

The mode announcement is suppressed in exactly one case: when one of the two
mode buttons already has keyboard focus, because Orca then announces the
toggle's own state change and the mode would otherwise be heard twice. Focus on
**Refresh** does not suppress it.

## Known limitations

- **Scrolling the preview with the keyboard is silent.** With Preview showing,
  <kbd>Down</kbd> and <kbd>Page Down</kbd> scroll the document but produce no
  AT-SPI events at all — not merely unspoken ones. The cause is inside
  WebKitGTK's own accessibility bridge, outside xedown; enabling WebKit2's
  caret browsing was tested and changed nothing.
- **The stale-preview indicator is not announced.** When the preview falls out
  of date, the indicator and the Refresh button's description both change and
  both fire real events, but Orca does not present either. Only the ordinary
  "document modified" title change is heard.
- **The evidence is narrow.** One machine, one Orca version (46.1), one
  WebKitGTK build, X11 only. Wayland was never tried, and no other screen
  reader was tested.

Reports from other readers, versions, and display servers are welcome; see
[Contributing](../CONTRIBUTING.md).

## Evidence

The per-assertion record, including what was deliberately left unasserted and
why, is in [Screen-reader measurements](orca-verification/measurements.md),
with the raw run in
[`transcript.json`](orca-verification/transcript.json). The two limitations
above are written up at length in [Known issues](known-issues.md).
