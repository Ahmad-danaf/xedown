import os

import pytest
from xedown import renderer


@pytest.fixture
def base(tmp_path):
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    (tmp_path / "other.md").write_text("# other")
    return str(tmp_path)


def test_fragment_renders_core_markdown():
    html = renderer.render_fragment(
        "# Title\n\nSome **bold** and *italic* text.\n\n- one\n- two\n\n1. first\n"
    )
    assert "<h1" in html and "Title" in html
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<ul>" in html and "<ol>" in html


def test_fragment_renders_tables_quotes_rules_and_code():
    html = renderer.render_fragment(
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n> quoted\n\n---\n\n"
        "`inline` and\n\n```python\nx = 1\n```\n"
    )
    assert "<table>" in html
    assert "<blockquote>" in html
    assert "<hr" in html
    assert "<code>inline</code>" in html
    assert 'class="language-python"' in html


def test_fragment_renders_task_lists():
    html = renderer.render_fragment("- [ ] todo\n- [x] done\n")
    assert "<input" in html
    assert "checked" in html


def test_relative_image_is_resolved_to_an_absolute_file_uri(base):
    html = renderer.render_fragment("![pic](pic.png)", base_dir=base)
    assert "file://" + os.path.join(base, "pic.png") in html


def test_relative_link_is_resolved_to_an_absolute_file_uri(base):
    html = renderer.render_fragment("[other](other.md)", base_dir=base)
    assert "file://" + os.path.join(base, "other.md") in html


def test_relative_image_without_a_base_becomes_a_placeholder():
    # Controller amendment 1: an unresolvable image src (here, no base
    # directory to resolve a relative reference against, e.g. an unsaved
    # document) must not be left to fail silently in the browser — the
    # sanitizer replaces it with a visible placeholder at render time.
    html = renderer.render_fragment("![pic](pic.png)")
    assert "<img" not in html
    assert "xedown-image-error" in html


def test_remote_and_anchor_targets_are_left_alone(base):
    html = renderer.render_fragment(
        "[site](https://example.com) and [here](#section)", base_dir=base
    )
    assert "https://example.com" in html
    assert 'href="#section"' in html


def test_remote_image_becomes_a_placeholder_naming_the_address(base):
    # Controller amendment 1: a remote image src can never resolve to a
    # local file: or data: URI (and the CSP would block the fetch anyway),
    # so it is replaced with a placeholder that names the blocked address,
    # rather than emitting an <img> that will never load.
    html = renderer.render_fragment(
        "![pic](https://example.com/pic.png)", base_dir=base
    )
    assert "<img" not in html
    assert "xedown-image-error" in html
    assert "https://example.com/pic.png" in html


def test_resolvable_local_image_still_renders_as_an_img(base):
    html = renderer.render_fragment("![pic](pic.png)", base_dir=base)
    assert "<img" in html
    assert "xedown-image-error" not in html


def test_data_image_still_renders_as_an_img():
    html = renderer.render_fragment("![pic](data:image/png;base64,iVBORw0KGgo=)")
    assert "<img" in html
    assert "data:image/png" in html
    assert "xedown-image-error" not in html


def test_injected_script_never_survives(base):
    html = renderer.render_fragment(
        "<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n", base_dir=base
    )
    assert "alert" not in html
    assert "onerror" not in html


def test_document_is_complete_and_self_contained():
    page = renderer.render_document("# Hi", nonce="test-nonce")
    assert page.startswith("<!DOCTYPE html>")
    assert f'id="{renderer.CONTENT_ELEMENT_ID}"' in page
    # No element references a network resource. This does not assert that no
    # "http://"/"https://" substring appears anywhere in the page: the
    # vendored highlight.min.js legitimately carries such strings inside its
    # own warning-message text and license header (see
    # tests/unit/test_resources.py, which scopes the same check to
    # preview.css/preview.js for the identical reason and deliberately
    # excludes the highlight bundle). The CSP (default-src 'none', img-src
    # file: data:, style-src/script-src pinned to the nonce) is what actually
    # guarantees nothing is fetched over the network.
    assert 'src="http:' not in page and 'src="https:' not in page
    assert 'href="http:' not in page and 'href="https:' not in page


def test_document_carries_a_strict_csp_with_the_nonce():
    page = renderer.render_document("# Hi", nonce="test-nonce")
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page
    assert "base-uri 'none'" in page
    assert "'nonce-test-nonce'" in page


def test_document_has_no_base_element():
    # base-uri 'none' would block it; URIs are pre-resolved instead.
    assert "<base" not in renderer.render_document("# Hi", nonce="n")


def test_inline_style_and_script_carry_the_nonce():
    page = renderer.render_document("# Hi", nonce="abc")
    assert 'style nonce="abc"' in page
    assert 'script nonce="abc"' in page


def test_document_inlines_the_highlight_bundle_and_preview_script():
    page = renderer.render_document("```python\nx=1\n```", nonce="n")
    assert "window.xedown" in page
    assert "hljs" in page


def test_dark_mode_selects_the_dark_theme():
    assert 'class="dark"' in renderer.render_document("# Hi", dark=True, nonce="n")
    assert 'class="light"' in renderer.render_document("# Hi", dark=False, nonce="n")


def test_highlight_theme_code_padding_wins_over_preview_css():
    # Verified CSS conflict (controller amendment 2): the vendored highlight
    # theme's `code.hljs { padding: 3px 5px }` (specificity 0,1,1) and
    # `.hljs { background: #0d1117 }` (0,1,0) both outrank preview.css's
    # `pre code { padding: 0; background: none }` (0,0,2) on specificity
    # alone, regardless of source order. preview.css must carry an override
    # of at least equal specificity to the theme's most specific colliding
    # rule, `pre code.hljs { padding: 1em }` (0,1,2) — a tie broken by
    # source order — so preview.css's override rule must also come after
    # the theme in the composed stylesheet.
    page = renderer.render_document("# Hi", nonce="n")
    style_start = page.index("<style")
    style_end = page.index("</style>")
    style_block = page[style_start:style_end]
    # The theme itself already contains one "pre code.hljs" occurrence
    # (`pre code.hljs{display:block;overflow-x:auto;padding:1em}`), so the
    # override in preview.css must be the *last* occurrence, not merely any
    # occurrence, to win the specificity tie by source order.
    theme_index = style_block.index(".hljs{color:")
    override_index = style_block.rindex("pre code.hljs")
    assert theme_index < override_index, "the override must come after the theme"
    assert (
        style_block.count("pre code.hljs") >= 2
    ), "expected both the theme's own rule and preview.css's override"


def test_each_render_uses_a_fresh_nonce():
    first = renderer.render_document("# Hi")
    second = renderer.render_document("# Hi")
    assert first != second


def test_render_failure_returns_an_error_page_not_an_exception(monkeypatch):
    def explode(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(renderer, "render_fragment", explode)
    page = renderer.render_document("# Hi")
    assert "boom" in page
    assert page.startswith("<!DOCTYPE html>")
