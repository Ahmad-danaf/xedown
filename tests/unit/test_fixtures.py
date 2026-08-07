"""Regression guard for the fixtures in tests/fixtures/.

`showcase.md` and `edge-cases.md` exist to do opposite jobs (see
tests/fixtures/README.md): one must render with no error placeholder at
all, the other must always produce at least one. That pairing is the point
of this file — a showcase that quietly grew a broken reference, or an
edge-cases file that quietly got "fixed" by adding the missing files back,
should both fail these tests.
"""

import pathlib

from xedown import renderer

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent.parent / "fixtures"
SHOWCASE_PATH = FIXTURES_DIR / "showcase.md"
EDGE_CASES_PATH = FIXTURES_DIR / "edge-cases.md"

SHOWCASE_TEXT = SHOWCASE_PATH.read_text(encoding="utf-8")
EDGE_CASES_TEXT = EDGE_CASES_PATH.read_text(encoding="utf-8")


def test_fixture_files_are_present_and_non_empty():
    # Guards against the trivial failure mode: a fixture accidentally left
    # empty or deleted would otherwise still make every test below "pass"
    # by rendering nothing.
    assert SHOWCASE_TEXT.strip()
    assert EDGE_CASES_TEXT.strip()


def test_showcase_renders_a_complete_document():
    # render_document is the entry point the plugin actually calls per
    # refresh; calling it directly here means an exception would fail this
    # test outright rather than being swallowed into an error page.
    page = renderer.render_document(
        SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR), nonce="test-showcase"
    )
    assert page.startswith("<!DOCTYPE html>")
    assert f'id="{renderer.CONTENT_ELEMENT_ID}"' in page
    # A render_document failure never raises -- it quietly substitutes
    # errors.error_page instead (see renderer.py). Checking for real
    # fixture content, not just the DOCTYPE, catches that silent case too.
    assert "Xedown Showcase" in page
    assert "Cannot render this document" not in page
    assert "Installation incomplete" not in page


def test_edge_cases_renders_a_complete_document():
    page = renderer.render_document(
        EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR), nonce="test-edge-cases"
    )
    assert page.startswith("<!DOCTYPE html>")
    assert f'id="{renderer.CONTENT_ELEMENT_ID}"' in page
    assert "Xedown Edge Cases" in page
    assert "Cannot render this document" not in page
    assert "Installation incomplete" not in page


def test_showcase_has_no_error_placeholder():
    # showcase.md is the "does this look good" fixture: nothing in it may
    # fail to resolve. This is checked against render_fragment (the body
    # content only), not render_document's full page -- the full page
    # legitimately contains the literal string "xedown-image-error" twice
    # more, from the bundled preview.css rule and preview.js's own
    # placeholder-creation code, neither of which says anything about
    # whether *this document's* content is clean.
    body = renderer.render_fragment(SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR))
    assert "xedown-image-error" not in body


def test_edge_cases_remote_image_becomes_a_placeholder_naming_the_address():
    # The remote image is blocked unconditionally, regardless of base_dir:
    # resolve_to_uri never returns a local URI for an http(s) reference, so
    # this is deterministic real behaviour, not a fixture-specific quirk.
    body = renderer.render_fragment(EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR))
    assert "xedown-image-error" in body
    assert "Remote image, not fetched: https://example.com/not-fetched.png" in body


def test_edge_cases_missing_local_image_becomes_a_placeholder():
    # The half that used to be unreachable from Python. The renderer now
    # stats a local image reference, so a file that is not there is named as
    # missing at render time rather than left to fail in the browser.
    body = renderer.render_fragment(EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR))
    assert "xedown-image-error" in body
    assert "pics/does-not-exist.png" in body
    assert "not found" in body


def test_edge_cases_missing_local_image_is_unresolvable_without_a_base_dir():
    # The other reason the same reference cannot be shown: an unsaved
    # document has nothing to resolve a relative path against. Different
    # cause, different sentence.
    body = renderer.render_fragment(EDGE_CASES_TEXT, base_dir=None)
    assert "xedown-image-error" in body
    assert "pics/does-not-exist.png" in body
    assert "has not been saved" in body


def test_showcase_feature_markers_survive():
    # Structural markers, not an exact-string pin: a table, a task-list
    # checkbox, a strikethrough <del>, a footnote anchor, and a
    # language-classed fenced code block, all present in one clean render.
    body = renderer.render_fragment(SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR))
    assert "<table>" in body
    assert "<input" in body
    assert "<del>" in body
    assert 'id="fnref:' in body
    assert 'class="language-python"' in body


def test_showcase_local_image_resolves_to_an_absolute_file_uri():
    body = renderer.render_fragment(SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR))
    expected = "file://" + str(FIXTURES_DIR / "pics" / "sample.png")
    assert expected in body
    assert "xedown-image-error" not in body


def test_neither_fixture_emits_a_script_tag():
    # The sanitizer drops <script> content entirely (see sanitizer.py's
    # _DROP_CONTENT_ELEMENTS); this pins that guarantee for these two
    # specific documents. Checked on render_fragment, not render_document:
    # the full document legitimately carries two first-party <script>
    # blocks (the bundled highlighter and preview.js), which would make
    # this assertion false for a reason that has nothing to do with the
    # fixtures' own content.
    showcase_body = renderer.render_fragment(SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR))
    edge_cases_body = renderer.render_fragment(
        EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR)
    )
    assert "<script" not in showcase_body
    assert "<script" not in edge_cases_body


def test_the_showcase_exercises_the_reading_polish():
    # A table wide enough to overflow a 46rem column, an image taller than
    # the window, and one small enough that stretching it would show.
    body = renderer.render_fragment(SHOWCASE_TEXT, base_dir=str(FIXTURES_DIR))
    assert "<table>" in body
    assert "tall.png" in body
    assert "tiny.png" in body
    # And it still renders cleanly: both new images must resolve, or this
    # fixture stops being the "does this look good" half of the pair.
    assert "xedown-image-error" not in body
