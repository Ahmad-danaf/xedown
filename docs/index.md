# xedown documentation

- Installation — see [README.md](../README.md); build the release archive with
  `scripts/build-release.sh`
- Manual smoke test — [manual-smoke-test.md](manual-smoke-test.md), which also
  describes the two automated harnesses that run before it:
  `scripts/run-integration-tests.sh` (live widget-tree behaviour) and
  `scripts/run-shutdown-tests.sh` (clean shutdown after each of six scenarios)
- Known issues — [known-issues.md](known-issues.md)
- Test fixtures — [../tests/fixtures/README.md](../tests/fixtures/README.md), the
  documents the manual smoke test and `tests/unit/test_fixtures.py` are both run
  against
- Settings — [settings.md](settings.md), the settings file's location, keys,
  defaults and recovery behaviour
- Preview appearance — [themes.md](themes.md), the four built-in themes, your
  own stylesheet, content width and text size, and the contrast policy.
  `scripts/render-themes.sh` renders every fixture in every theme, light and
  dark, plus the extremes of width and size, for review in a browser
- Architecture — planned
- Troubleshooting — planned
