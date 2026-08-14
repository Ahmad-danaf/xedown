# xedown documentation

- Installation — see [README.md](../README.md); build the release archive with
  `scripts/build-release.sh`
- Manual smoke test — [manual-smoke-test.md](manual-smoke-test.md), which also
  describes the automated harnesses that run before it:
  `scripts/run-integration-tests.sh` (live widget-tree behaviour),
  `scripts/run-shutdown-tests.sh` (clean shutdown after each of eight
  scenarios) and `scripts/run-orca-tests.sh` (what a screen reader actually
  says, in an isolated display)
- Known issues — [known-issues.md](known-issues.md)
- Markdown compatibility — [markdown-compatibility.md](markdown-compatibility.md),
  every known difference from GitHub's own rendering and why each one is the
  way it is, measured by diffing xedown against cmark-gfm over a corpus of 31
  real READMEs that `scripts/fetch-corpus.sh` reproduces from pinned commit
  SHAs
- Security — [../SECURITY.md](../SECURITY.md), the network boundary around
  remote images and the properties that are enforced and tested, not merely
  intended
- Screen-reader evidence — [orca-verification/](orca-verification/), the raw
  measurements behind every claim in the README's *Accessibility* section
- Test fixtures — [../tests/fixtures/README.md](../tests/fixtures/README.md), the
  documents the manual smoke test and `tests/unit/test_fixtures.py` are both run
  against
- Settings — [settings.md](settings.md), the settings file's location, keys,
  defaults and recovery behaviour, and
  [the settings window](settings.md#the-settings-window) that edits them live
- Preview appearance — [themes.md](themes.md), the four built-in themes, your
  own stylesheet, content width and text size, and the contrast policy.
  `scripts/render-themes.sh` renders every fixture in every theme, light and
  dark, plus the extremes of width and size, for review in a browser
- Architecture — planned
- Troubleshooting — planned
