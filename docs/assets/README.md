# v1.0 media capture checklist

This directory contains real xedown captures. The media is part of the
compatibility and product evidence; do not replace it with mockups or generated
UI.

Capture from the officially supported Linux Mint 22.3, xed 3.8.9, Python
3.12.3, WebKitGTK 2.52.3 / API 4.1, X11 environment.

## Captured files

- `xedown-demo.gif` — an 8–12 second loop: Preview with the mode bar visible,
  switch to Markdown, make an obvious edit, switch back, and show the rendered
  result. Keep a higher-quality MP4 or WebM source outside Git or alongside it
  if its size is reasonable.
- `preview-repository.png` — hero capture using the Repository theme and a
  polished, non-personal fixture containing a heading, prose, task list, table,
  code block, and local image.
- `preview-markdown.png` — the same document and approximate section in source
  mode, suitable for a side-by-side comparison.
- `preview-dark.png` — the edited document in dark appearance.
- `preview-light.png` — the same document in light appearance, captured from a
  fresh xed process after changing both the desktop theme and xed's own dark
  preference, then restoring both.
- `preferences.png` — the complete preferences window with all groups legible.
- `remote-images-blocked.png` — a blocked-image placeholder and the mode-bar
  image count/Load control.

## Capture rules

- Remove usernames, home paths, notifications, unrelated tabs, and personal
  documents.
- Keep the **Preview | Markdown** bar visible in workflow images.
- Use consistent window dimensions and desktop appearance.
- Capture PNG at native scale; do not upscale.
- Optimize without making UI text blurry.
- Give every image meaningful Markdown alt text when adding it to README.md.
- Record the capture and optimization commands in the release pull request.

The README uses the demo as its primary visual, the light/dark pair to show
live appearance support, and the blocked-image capture where privacy behavior
is explained. `preview-markdown.png`, `preview-repository.png`, and
`preferences.png` remain available for release notes and focused guides.
