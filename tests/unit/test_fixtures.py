"""Regression guard for the fixtures in tests/fixtures/.

`showcase.md` and `edge-cases.md` exist to do opposite jobs (see
tests/fixtures/README.md): one must render with no error placeholder at
all, the other must always produce at least one. That pairing is the point
of this file — a showcase that quietly grew a broken reference, or an
edge-cases file that quietly got "fixed" by adding the missing files back,
should both fail these tests.
"""

import pathlib

from xedown import direction, renderer

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
    # render_fragment does not pass fetch_remote, so it defaults to False:
    # this is the reader-has-not-allowed-it wording, not "never fetched".
    # The real per-document permission reaches the renderer through the
    # controller, which this fixture-level test deliberately does not go
    # through -- the default is what a document gets before anyone allows it.
    body = renderer.render_fragment(EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR))
    assert "xedown-image-error" in body
    assert "Remote image, not loaded: https://example.com/not-fetched.png" in body


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


RTL_PATH = FIXTURES_DIR / "rtl.md"
MIXED_PATH = FIXTURES_DIR / "mixed-direction.md"

RTL_TEXT = RTL_PATH.read_text(encoding="utf-8")
MIXED_TEXT = MIXED_PATH.read_text(encoding="utf-8")


def test_the_direction_fixtures_are_present_and_non_empty():
    assert RTL_TEXT.strip()
    assert MIXED_TEXT.strip()


def test_both_direction_fixtures_detect_right_to_left():
    assert direction.detect(RTL_TEXT) == direction.RTL
    # Arabic-majority on purpose: the English in it is content to lay out,
    # not a vote. If this ever fails, add Arabic prose — do not delete the
    # English, which is the entire point of the fixture.
    assert direction.detect(MIXED_TEXT) == direction.RTL


def test_the_left_to_right_fixtures_still_detect_left_to_right():
    # This is "must not regress any left-to-right document", made checkable.
    # edge-cases.md carries a substantial Arabic section and is still an
    # English document.
    assert direction.detect(SHOWCASE_TEXT) == direction.LTR
    assert direction.detect(EDGE_CASES_TEXT) == direction.LTR


def test_the_direction_fixtures_render_complete_documents():
    for text, marker, nonce in (
        (RTL_TEXT, "دليل xedown بالعربية", "test-rtl"),
        (MIXED_TEXT, "اتجاهان في مستند واحد", "test-mixed"),
    ):
        page = renderer.render_document(text, base_dir=str(FIXTURES_DIR), nonce=nonce)
        assert page.startswith("<!DOCTYPE html>")
        assert marker in page
        assert 'dir="rtl"' in page
        assert "Cannot render this document" not in page
        assert "Installation incomplete" not in page


def test_neither_direction_fixture_has_an_error_placeholder():
    # Both are "does this look good" fixtures, like showcase.md. A broken
    # reference in either is a real regression, not a deliberate case.
    for text in (RTL_TEXT, MIXED_TEXT):
        body = renderer.render_fragment(text, base_dir=str(FIXTURES_DIR))
        assert "xedown-image-error" not in body


def test_the_rtl_fixture_exercises_everything_with_a_side():
    body = renderer.render_fragment(RTL_TEXT, base_dir=str(FIXTURES_DIR))
    assert "<table>" in body  # column order
    assert "<blockquote>" in body  # the quote bar
    assert "<input" in body  # a task list
    assert 'id="fnref:' in body  # a footnote marker
    assert 'class="language-python"' in body  # a fence that must stay LTR
    assert body.count("<ul>") >= 2, "the nested list did not nest"
    assert 'id="lists"' in body, "the explicit anchor id did not survive"
    assert "sample.png" in body


def test_the_mixed_fixture_carries_both_escape_hatches():
    # The author's own way to mark a run the renderer cannot infer. If the
    # sanitizer ever stops allowing these, this fixture stops covering them.
    body = renderer.render_fragment(MIXED_TEXT, base_dir=str(FIXTURES_DIR))
    assert "<bdi>" in body
    assert 'dir="ltr"' in body


def test_the_edge_cases_fixture_no_longer_claims_rtl_is_unsupported():
    # Corrected by brief 7. The sentence was true when it was written and is
    # not any more; leaving it would make the fixture document a limitation
    # the plugin no longer has.
    assert "not full right-to-left support" not in EDGE_CASES_TEXT


def test_the_edge_cases_fixture_no_longer_calls_the_list_gap_a_defect():
    # Corrected by brief 16. The section was accurate when it was written and
    # told the reader not to fix it; leaving that in would document a defect
    # the plugin no longer has.
    assert "Known GFM gap" not in EDGE_CASES_TEXT


def test_the_edge_cases_fixture_renders_its_list_after_a_paragraph():
    # The positive half: the construct is still in the file, and it renders
    # as a list rather than as three lines of one paragraph.
    body = renderer.render_fragment(EDGE_CASES_TEXT, base_dir=str(FIXTURES_DIR))
    assert "<li>item one</li>" in body
    assert "<li>item two</li>" in body
