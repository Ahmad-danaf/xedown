# Contributing to xedown

Thank you for helping make xedown safer, clearer, and more reliable. Bug
reports, compatibility results, documentation improvements, tests, and code
changes are welcome.

Please follow the [Code of Conduct](CODE_OF_CONDUCT.md). Report security issues
privately using [SECURITY.md](SECURITY.md), not a public issue.

## Before opening an issue

Check [Troubleshooting](docs/troubleshooting.md),
[Known issues](docs/known-issues.md), and
[Markdown compatibility](docs/markdown-compatibility.md). For a new bug, include
the exact Linux Mint or distribution version, xed version, Python version,
WebKitGTK version, display server, steps to reproduce, and the smallest safe
Markdown document that demonstrates it.

Compatibility reports are useful even when no code change is proposed. Say
whether the result came from the unit suite or a live xed session; those are
different kinds of evidence.

## Development setup

Create a virtual environment and install the development requirements:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Run the default checks:

```bash
.venv/bin/python -m pytest
.venv/bin/ruff check .
.venv/bin/black --check .
```

Run one test while iterating with, for example:

```bash
.venv/bin/python -m pytest tests/unit/test_renderer.py::test_name
```

Unit tests deliberately avoid a GTK dependency. Keep logic that can run
without `gi` in focused modules such as `renderer.py`, `sanitizer.py`,
`settings.py`, `remoteimages.py`, and `imagefetch.py`.

## Desktop and release checks

These checks need the dependencies documented by their scripts:

```bash
scripts/run-install-tests.sh
scripts/run-integration-tests.sh
scripts/run-shutdown-tests.sh
scripts/run-orca-tests.sh
```

The install harness uses an isolated temporary home. The integration,
shutdown, and Orca harnesses install into the current user's xed plugin
directory and temporarily change xed's active-plugin setting; they refuse to
run while xed is already open and restore state on exit.

Use [docs/manual-smoke-test.md](docs/manual-smoke-test.md) for GTK behavior that
automation cannot completely verify. Performance and Markdown-differential
tools live in `tests/perf/` and `tests/compat/`.

`scripts/build-release.sh` builds and validates the archive in `dist/`. It
requires a clean worktree and is a release check, not a normal editing loop.

## Project layout

- `plugin/xedown/` — plugin implementation
- `plugin/xedown/resources/` — runtime CSS, JavaScript, and themes
- `plugin/xedown/vendor/` — generated third-party sources
- `tests/unit/` — default test suite
- `tests/fixtures/` — reusable Markdown documents and images
- `tests/integration/` — live xed probes
- `tests/compat/` and `tests/perf/` — compatibility and performance tooling
- `docs/` — user guides, references, and release evidence

Do not hand-edit `plugin/xedown/vendor/`. Regenerate the pinned Python-Markdown
and highlight.js copies only with `scripts/update-vendor.sh`.

## Expectations for a change

- Keep modules narrowly scoped and use Black-compatible Python with four-space
  indentation.
- Use `snake_case` for modules, functions, variables, and tests; `PascalCase`
  for classes; and `UPPER_CASE` for constants.
- Add regression tests beside the affected logic, including failure and
  security-sensitive paths where relevant.
- Preserve the rule that xedown never writes to the document text buffer.
- Treat Markdown as untrusted input. Sanitizer, URI, CSP, link-opening, and
  remote-image changes require explicit security tests and documentation.
- Update user documentation and `CHANGELOG.md` when behavior changes.
- Include screenshots or screen-reader evidence for visible or accessibility
  changes.
- Call out platform assumptions, configuration migration, and vendoring.

Commit messages use a concise imperative scope prefix such as `feat:`, `fix:`,
`test:`, `docs:`, or `build:`. Keep each commit focused.

## Pull requests

Explain the user-visible outcome and why the chosen behavior is appropriate.
List every command run, link relevant issues, and include evidence requested by
the pull-request template. A pull request need not run every desktop harness,
but it should say which checks were not run and why.
