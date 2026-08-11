import os
import re

import pytest
from xedown import errors, renderer, stylesheets, themes, vendoring


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
    assert "src=" not in html
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


def test_document_never_emits_a_remote_image_reference():
    # This must actually exercise the property: a document with no image or
    # link at all ("# Hi") can't tell a correct render from a broken one, so
    # this renders content that contains a real remote image and a real
    # remote link. A remote <img src> must never reach the page (Amendment 1
    # turns it into a placeholder before the sanitizer ever emits the tag —
    # see test_remote_image_becomes_a_placeholder_naming_the_address for the
    # fragment-level version of this same guarantee), while a remote <a
    # href> is meant to survive untouched; this does not assert a blanket
    # absence of "http://"/"https://" anywhere in the page, because the
    # vendored highlight.min.js legitimately carries such strings inside its
    # own warning-message text and license header (see
    # tests/unit/test_resources.py, which scopes the same check to
    # preview.css/preview.js for the identical reason and deliberately
    # excludes the highlight bundle).
    page = renderer.render_document(
        "![pic](https://example.com/pic.png) and [site](https://example.com)",
        nonce="n",
    )
    assert 'src="http' not in page
    assert 'href="https://example.com"' in page


def test_document_carries_a_strict_csp_with_the_nonce():
    page = renderer.render_document("# Hi", nonce="test-nonce")
    assert "Content-Security-Policy" in page
    assert "default-src 'none'" in page
    assert "base-uri 'none'" in page
    assert "'nonce-test-nonce'" in page


def test_the_csp_is_exactly_what_the_documentation_promises():
    # docs/themes.md tells users that a custom stylesheet's @font-face and
    # @import do nothing, while url(file://) and url(data:) backgrounds work.
    # Every one of those promises is a consequence of this policy and nothing
    # else -- there is no font-src, so @font-face falls back to default-src
    # 'none'. A later change that widens the policy must break this test
    # rather than silently make the documentation wrong.
    page = renderer.render_document("# Hi", nonce="n")
    assert "img-src file: data:" in page
    assert "style-src 'nonce-n'" in page
    assert "script-src 'nonce-n'" in page
    assert "font-src" not in page
    assert "unsafe-inline" not in page
    assert "unsafe-eval" not in page


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


def test_the_body_carries_both_the_appearance_and_the_theme():
    dark = renderer.render_document("# Hi", dark=True, nonce="n")
    light = renderer.render_document("# Hi", dark=False, nonce="n")
    assert 'class="dark xedown-theme-repository"' in dark
    assert 'class="light xedown-theme-repository"' in light


def test_a_named_theme_inlines_that_theme_stylesheet():
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(theme="repository")
    )
    assert 'class="light xedown-theme-repository"' in page
    assert "--xedown-bg" in page


def test_an_unknown_theme_falls_back_to_the_default_rather_than_failing():
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(theme="no-such-theme")
    )
    assert f'xedown-theme-{themes.DEFAULT_THEME}"' in page
    assert "--xedown-bg" in page


def test_the_metrics_the_user_chose_reach_the_page():
    page = renderer.render_document(
        "# Hi",
        nonce="n",
        style=stylesheets.PreviewStyle(content_width_rem=72, text_size_px=20),
    )
    assert "--xedown-content-width: 72rem;" in page
    assert "--xedown-text-size: 20px;" in page


def test_a_user_stylesheet_is_emitted_after_the_theme():
    user = stylesheets.UserStylesheet(css="/*MINE*/", path="/x.css")
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(user=user)
    )
    style_block = page[page.index("<style") : page.index("</style>")]
    assert "/*MINE*/" in style_block
    # Last of the five layers, so it can override every one of them.
    assert style_block.index("/*MINE*/") > style_block.rindex("--xedown-content-width")


# Searched for as the emitted attribute, never as the bare string: the base
# stylesheet's own `.xedown-notice` rule is inlined into every page, so
# `"xedown-notice" not in page` is false even when no notice was emitted, and
# a test written that way could never fail.
NOTICE = 'class="xedown-notice"'


def test_a_working_stylesheet_produces_no_notice():
    user = stylesheets.UserStylesheet(css="/*MINE*/", path="/x.css")
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(user=user)
    )
    assert NOTICE not in page


def test_an_unset_stylesheet_produces_no_notice():
    assert NOTICE not in renderer.render_document("# Hi", nonce="n")


def test_a_failed_stylesheet_produces_a_notice_and_a_working_page():
    user = stylesheets.UserStylesheet(
        path="/home/you/mine.css", problem=errors.STYLESHEET_EMPTY
    )
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(user=user)
    )
    assert NOTICE in page
    assert "/home/you/mine.css" in page
    assert "is empty" in page
    # Still a real document, not an error page.
    assert f'id="{renderer.CONTENT_ELEMENT_ID}"' in page
    assert "Cannot render this document" not in page


def test_the_notice_names_the_theme_actually_being_shown():
    user = stylesheets.UserStylesheet(
        path="/x.css", problem=errors.STYLESHEET_NOT_FOUND
    )
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(theme="minimal", user=user)
    )
    assert "Showing the Minimal theme." in page


def test_the_notice_sits_outside_the_content_element():
    # update_body replaces the content element's innerHTML with a fragment
    # that knows nothing about the notice, so a notice inside it would vanish
    # on the first keystroke.
    user = stylesheets.UserStylesheet(
        path="/x.css", problem=errors.STYLESHEET_NOT_FOUND
    )
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(user=user)
    )
    assert page.index(NOTICE) < page.index(f'id="{renderer.CONTENT_ELEMENT_ID}"')


def test_an_error_page_carries_neither_the_user_css_nor_the_notice(monkeypatch):
    # An error page is not the document. A stylesheet that failed to load is
    # the last thing that should be styling the message about it.
    def explode(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(renderer, "render_fragment", explode)
    user = stylesheets.UserStylesheet(css="/*MINE*/", path="/x.css")
    page = renderer.render_document(
        "# Hi", nonce="n", style=stylesheets.PreviewStyle(user=user)
    )
    assert "/*MINE*/" not in page
    assert NOTICE not in page


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
    # Strip CSS comments before searching, so this pins the actual rule
    # rather than any prose that happens to mention its selector — deleting
    # the real rule while leaving an explanatory comment behind must fail
    # this test, not pass it.
    style_block = re.sub(r"/\*.*?\*/", "", style_block, flags=re.DOTALL)
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
    override_rule = style_block[override_index:]
    assert "padding: 0" in override_rule
    assert "background: none" in override_rule


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


def test_render_failure_page_still_carries_the_fresh_nonce(monkeypatch):
    # The error page is a document `render_document` emits too, so it must
    # not fall back to `errors.error_page`'s static default nonce — that
    # would make "every render gets a fresh nonce" false for exactly the
    # renders most likely to happen on bad input.
    def explode(*args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(renderer, "render_fragment", explode)
    page = renderer.render_document("# Hi", nonce="a-specific-nonce")
    assert 'nonce="a-specific-nonce"' in page
    assert "xedown-error" not in page


def test_a_successfully_rendered_document_is_not_an_error_page():
    assert not errors.is_error_page(renderer.render_document("# Hi", nonce="n"))


def test_an_internal_render_failure_is_recognisable_as_an_error_page(monkeypatch):
    # Regression pin for the Task 6 finding: render_document never raises, so
    # a caller cannot tell an error page from a document by asking whether it
    # passed error= itself -- it has to ask the page. Nothing here raises
    # past render_document (that is the whole point: render_document's own
    # try/except is what catches it), so the old controller logic
    # (`error is None`) would have called this a document.
    def explode(_name):
        raise vendoring.VendorError("bundled resource missing")

    monkeypatch.setattr(vendoring, "read_resource", explode)
    page = renderer.render_document("# Hi", nonce="n")
    assert errors.is_error_page(page)


def test_malformed_link_does_not_crash_the_render(base):
    # `urllib.parse.urlparse` raises ValueError on an unbalanced IPv6-literal
    # bracket. render_fragment is a public interface called directly on
    # every refresh (no try/except upstream), so this must not raise, and
    # the rest of the document must render normally around the bad link.
    html = renderer.render_fragment("before [x](http://[bad) after", base_dir=base)
    assert "before" in html and "after" in html
    assert "http://[bad" not in html


def test_malformed_image_reference_does_not_crash_the_render(base):
    html = renderer.render_fragment("before ![x](http://[bad) after", base_dir=base)
    assert "before" in html and "after" in html
    assert "<img" not in html
    assert "xedown-image-error" in html


def test_render_fragment_does_not_raise_on_a_malformed_url(base):
    # A regression pin distinct from the two tests above: this asserts only
    # that no exception propagates, independent of what the output looks
    # like, since render_fragment's "never raise" property is the thing a
    # future refactor is most likely to accidentally break.
    renderer.render_fragment("[x](http://[bad)", base_dir=base)
    renderer.render_fragment("![x](http://[bad)", base_dir=base)
    renderer.render_fragment("[x](http://[bad)")  # no base_dir either
    renderer.render_fragment("![x](http://[bad)")


def test_a_missing_local_image_says_so_by_name(tmp_path):
    html = renderer.render_fragment("![A logo](pics/gone.png)", base_dir=str(tmp_path))
    assert "xedown-image-error" in html
    assert "not found" in html
    assert "A logo" in html


def test_a_readable_local_image_is_emitted(tmp_path):
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    html = renderer.render_fragment("![A](a.png)", base_dir=str(tmp_path))
    assert "<img" in html
    assert "xedown-image-error" not in html


def test_alt_mode_replaces_every_failure_with_its_alt_text(tmp_path):
    source = "![A logo](pics/gone.png)\n\n![Remote](https://example.com/a.png)\n"
    html = renderer.render_fragment(source, base_dir=str(tmp_path), image_display="alt")
    assert html.count('class="xedown-image-alt"') == 2
    assert "xedown-image-error" not in html
    assert "example.com" not in html


def test_hidden_mode_leaves_nothing_behind(tmp_path):
    source = "![A logo](pics/gone.png)\n\n![Remote](https://example.com/a.png)\n"
    html = renderer.render_fragment(
        source, base_dir=str(tmp_path), image_display="hidden"
    )
    assert "xedown-image" not in html
    assert "<img" not in html


def test_no_display_mode_ever_emits_a_remote_source(tmp_path):
    for display in ("placeholder", "alt", "hidden"):
        html = renderer.render_document(
            "![R](https://example.com/a.png)",
            base_dir=str(tmp_path),
            image_display=display,
        )
        assert 'src="https://' not in html
        assert "img-src file: data:" in html


def test_an_unusable_display_value_renders_the_default(tmp_path):
    # Weak on its own: images.placeholder_for's unconditional `else` treats
    # any unrecognised display value as the placeholder case, so this passes
    # identically whether or not render_fragment ever coerces image_display
    # at all. It only pins that a bad value still renders something instead
    # of crashing -- the actual coercion claim is
    # test_an_unusable_display_value_never_reaches_the_page below.
    html = renderer.render_fragment(
        "![A](pics/gone.png)", base_dir=str(tmp_path), image_display="nonsense"
    )
    assert "xedown-image-error" in html


def test_an_unusable_display_value_never_reaches_the_page():
    # The body is not the only consumer: preview.js reads the display mode
    # out of the config block, so a value that was coerced for the body and
    # not for the config would leave the two disagreeing.
    html = renderer.render_document("![A](pics/gone.png)", image_display="nonsense")
    assert '"imageDisplay": "placeholder"' in html
    assert "nonsense" not in html


def test_the_page_carries_its_config():
    html = renderer.render_document("# x", code_copy_buttons=False, image_display="alt")
    assert '"codeCopy": false' in html
    assert '"imageDisplay": "alt"' in html


def test_the_config_defaults_reproduce_v01_behaviour():
    html = renderer.render_document("# x")
    assert '"codeCopy": true' in html
    assert '"imageDisplay": "placeholder"' in html


ARABIC_DOC = "# عنوان\n\nهذه فقرة باللغة العربية تُقرأ من اليمين إلى اليسار.\n"
ENGLISH_DOC = "# Title\n\nAn ordinary English paragraph.\n"


def _article_tag(page):
    # Anchored on the content element's id, not on `dir="..."` itself: the
    # four tests below use this helper to assert about `dir`, so anchoring
    # the *lookup* on that same attribute would let it match a comment
    # instead of the real element -- preview.css already names `<article
    # dir>` in a comment once, which is why this had to be tightened before,
    # and any future comment in preview.css, preview.js or an error template
    # containing the literal text `<article dir="rtl">` would do it again.
    # `CONTENT_ELEMENT_ID` is emitted unconditionally by the single
    # template, so finding the element this way is decoupled from asserting
    # anything about its direction.
    match = re.search(
        rf'<article\b[^>]*\bid="{renderer.CONTENT_ELEMENT_ID}"[^>]*>', page
    )
    assert match, f'no <article id="{renderer.CONTENT_ELEMENT_ID}"> in the page'
    return match.group(0)


def test_the_article_carries_the_detected_direction():
    assert 'dir="rtl"' in _article_tag(renderer.render_document(ARABIC_DOC))
    assert 'dir="ltr"' in _article_tag(renderer.render_document(ENGLISH_DOC))


def test_a_forced_direction_beats_the_detected_one():
    page = renderer.render_document(ARABIC_DOC, text_direction="ltr")
    assert 'dir="ltr"' in _article_tag(page)
    page = renderer.render_document(ENGLISH_DOC, text_direction="rtl")
    assert 'dir="rtl"' in _article_tag(page)


def test_an_unusable_text_direction_still_produces_a_page():
    # render_document is called directly by the render script and by the
    # tests, so a bad argument must not escape as an exception.
    for value in ("nonsense", None, 7, True, [], {}):
        page = renderer.render_document(ARABIC_DOC, text_direction=value)
        assert page.startswith("<!DOCTYPE html>")
        assert "Cannot render this document" not in page
        assert 'dir="rtl"' in _article_tag(page)


def test_the_page_carries_the_desktop_direction_independently_of_the_document():
    # An English document on an Arabic desktop: chrome mirrors, content does
    # not. This is the whole reason there are two attributes and not one.
    page = renderer.render_document(ENGLISH_DOC, ui_direction="rtl")
    assert '<html dir="rtl">' in page
    assert 'dir="ltr"' in _article_tag(page)


def test_the_desktop_direction_defaults_to_left_to_right():
    assert '<html dir="ltr">' in renderer.render_document(ENGLISH_DOC)


def test_an_unusable_ui_direction_still_produces_a_page():
    for value in ("nonsense", None, 7, object()):
        page = renderer.render_document(ENGLISH_DOC, ui_direction=value)
        assert '<html dir="ltr">' in page


def test_a_render_failure_page_still_carries_the_desktop_direction(monkeypatch):
    # The ui direction is resolved before the try, precisely so the two
    # except branches can use it.
    def boom(*_args, **_kwargs):
        raise ValueError("x")

    monkeypatch.setattr(renderer, "render_fragment", boom)
    page = renderer.render_document(ENGLISH_DOC, ui_direction="rtl")
    assert "Cannot render this document" in page
    assert '<html dir="rtl">' in page


def test_the_article_is_a_landmark():
    """A screen reader needs something to jump to; the article is the document."""
    html = renderer.render_document("# Title\n")
    assert 'role="document"' in html


def test_a_language_is_emitted_when_one_is_known():
    html = renderer.render_document("# Title\n", lang="ar-EG")
    assert 'lang="ar-EG"' in html


def test_no_language_attribute_at_all_when_none_is_known():
    """Absent beats wrong: the reader keeps its own default voice."""
    html = renderer.render_document("# Title\n", lang=None)
    assert "lang=" not in html


def test_an_empty_language_is_treated_as_unknown():
    assert "lang=" not in renderer.render_document("# Title\n", lang="")


def test_the_language_is_escaped_into_the_attribute():
    html = renderer.render_document("# Title\n", lang='en" onload="x')
    assert 'onload="x"' not in html


def test_a_language_that_is_not_a_string_is_ignored_rather_than_raising():
    """`render_document` never raises, and `lang` is a public parameter."""

    class Explode:
        def __bool__(self):
            raise RuntimeError("boom")

        def __str__(self):
            raise RuntimeError("boom")

    html_out = renderer.render_document("# Title\n", lang=Explode())
    assert "lang=" not in html_out


def test_angle_brackets_and_newlines_cannot_escape_the_language_attribute():
    html_out = renderer.render_document("# Title\n", lang="en><script>\nx")
    assert "<script>" not in html_out.split("<body")[0]
    assert "lang=" in html_out
