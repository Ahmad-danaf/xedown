import pytest
from xedown import sanitizer
from xedown.sanitizer import ALLOWED_ELEMENTS, ImagePlaceholder, RemoteImage, sanitize


def test_keeps_ordinary_markup():
    html = "<h1>Title</h1><p>Hello <strong>world</strong> and <em>friends</em>.</p>"
    assert sanitize(html) == html


def test_drops_script_elements_and_their_content():
    result = sanitize("<p>before</p><script>alert(1)</script><p>after</p>")
    assert "alert" not in result
    assert "<script" not in result
    assert "before" in result and "after" in result


def test_drops_style_elements_and_css_injection():
    result = sanitize("<style>body{background:url(http://x/y)}</style><p>ok</p>")
    assert "background" not in result
    assert "<style" not in result
    assert "ok" in result


def test_drops_iframe_object_and_embed():
    for tag in ("iframe", "object", "embed"):
        result = sanitize(f"<{tag} src='http://x'></{tag}><p>ok</p>")
        assert tag not in result
        assert "ok" in result


def test_mixed_case_tags_and_attributes_are_still_filtered():
    result = sanitize("<ScRiPt>alert(1)</ScRiPt><IMG SRC='a.png' OnErRoR='evil()'>")
    assert "alert" not in result
    assert "onerror" not in result.lower()
    assert "evil" not in result


def test_event_handler_attributes_are_removed():
    result = sanitize("<p onclick='evil()' onmouseover='evil()'>text</p>")
    assert "onclick" not in result and "onmouseover" not in result
    assert "text" in result


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "java&#115;cript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "  javascript:alert(1)",
        "\x01javascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
    ],
)
def test_dangerous_link_schemes_are_dropped(href):
    result = sanitize(f'<a href="{href}">click</a>')
    assert "javascript" not in result.lower()
    assert "vbscript" not in result.lower()
    assert "text/html" not in result.lower()
    assert "click" in result  # the text survives, only the href is dropped


def test_safe_link_schemes_survive():
    for href in (
        "https://example.com/a",
        "mailto:a@b.c",
        "file:///tmp/a.md",
        "#anchor",
    ):
        assert href in sanitize(f'<a href="{href}">x</a>')


def test_data_uris_allowed_only_for_images_and_only_image_types():
    ok = sanitize('<img src="data:image/png;base64,iVBORw0KGgo=">')
    assert "data:image/png" in ok
    bad = sanitize('<img src="data:text/html;base64,PHNjcmlwdD4=">')
    assert "data:text/html" not in bad


def test_svg_content_is_dropped():
    result = sanitize("<svg><script>alert(1)</script></svg><p>ok</p>")
    assert "svg" not in result and "alert" not in result
    assert "ok" in result


def test_style_attributes_are_removed():
    result = sanitize('<p style="background:url(http://x)">text</p>')
    assert "style" not in result
    assert "text" in result


def test_srcset_is_removed():
    result = sanitize('<img src="a.png" srcset="http://x/y.png 2x" alt="a">')
    assert "srcset" not in result
    assert 'src="a.png"' in result


def test_malformed_nested_html_does_not_leak_scripts():
    result = sanitize("<p><b>bold<script>alert(1)</p></b></script><p>after")
    assert "alert" not in result and "<script" not in result
    assert "bold" in result and "after" in result


def test_text_is_escaped_not_reinterpreted():
    assert "&lt;script&gt;" in sanitize("<p>&lt;script&gt;</p>")


def test_allowed_code_block_classes_survive():
    html = '<pre><code class="language-python">x=1</code></pre>'
    assert 'class="language-python"' in sanitize(html)


def test_task_list_checkbox_input_is_allowed_but_forced_disabled():
    result = sanitize('<input type="checkbox" checked>')
    assert "<input" in result
    assert "disabled" in result


def test_svg_data_uris_are_rejected_even_though_declared_as_image():
    # SVG is itself an HTML-like, scriptable document format (it can carry
    # <script>, onload=, etc.). The brief already drops raw <svg> markup for
    # this reason (test_svg_content_is_dropped); allowing
    # "data:image/svg+xml" through the img-src "it's just an image" allowance
    # would smuggle the same capability back in through a side door and rely
    # on the host WebKit view to sandbox SVG-as-image scripting correctly.
    # That is exactly the kind of "trust the renderer" assumption this
    # module must not make.
    svg_script = (
        "data:image/svg+xml;base64," "PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+"
    )
    result = sanitize(f'<img src="{svg_script}" alt="a">')
    assert "svg+xml" not in result
    assert "base64" not in result


def test_resolver_hook_rewrites_allowed_uris():
    def resolve(name, value):
        return "file:///base/" + value

    result = sanitize('<img src="a.png">', resolve_uri=resolve)
    assert 'src="file:///base/a.png"' in result


def test_resolver_hook_can_drop_an_attribute():
    result = sanitize('<img src="a.png" alt="x">', resolve_uri=lambda name, value: None)
    assert "src=" not in result
    assert 'alt="x"' in result


def test_resolver_hook_never_sees_a_rejected_scheme():
    seen = []

    def resolve(name, value):
        seen.append(value)
        return value

    sanitize('<a href="javascript:alert(1)">x</a>', resolve_uri=resolve)
    assert seen == []


def test_without_an_on_image_hook_an_img_is_emitted_unchanged():
    result = sanitize('<img src="https://example.com/a.png" alt="A">')
    assert "<img" in result
    assert "xedown-image-error" not in result


def test_on_image_may_return_a_replacement_src():
    result = sanitize(
        '<img src="a.png" alt="A" title="T">',
        on_image=lambda reference, alt: "file:///x/a.png",
    )
    assert 'src="file:///x/a.png"' in result
    assert 'alt="A"' in result
    assert 'title="T"' in result


def test_on_image_may_return_a_placeholder():
    result = sanitize(
        '<img src="https://e/a.png" alt="A">',
        on_image=lambda reference, alt: ImagePlaceholder("error", "no: " + reference),
    )
    assert '<span class="xedown-image-error">no: https://e/a.png</span>' in result
    assert "<img" not in result


def test_the_alt_kind_gets_its_own_class():
    result = sanitize(
        '<img src="https://e/a.png" alt="A logo">',
        on_image=lambda reference, alt: ImagePlaceholder("alt", alt),
    )
    assert '<span class="xedown-image-alt">A logo</span>' in result


def test_an_unknown_placeholder_kind_falls_back_to_the_error_class():
    result = sanitize(
        '<img src="a.png">',
        on_image=lambda reference, alt: ImagePlaceholder("nonsense", "t"),
    )
    assert 'class="xedown-image-error"' in result


def test_on_image_may_return_nothing_at_all():
    result = sanitize(
        '<img src="https://e/a.png" alt="A">', on_image=lambda reference, alt: None
    )
    assert "img" not in result
    assert "span" not in result


def test_on_image_receives_the_reference_and_the_alt_text():
    seen = []

    def record(reference, alt):
        seen.append((reference, alt))

    sanitize('<img src="pics/a.png" alt="Company logo">', on_image=record)
    assert seen == [("pics/a.png", "Company logo")]


def test_placeholder_text_is_escaped():
    result = sanitize(
        '<img src="a.png">',
        on_image=lambda reference, alt: ImagePlaceholder(
            "error", "<script>alert(1)</script>"
        ),
    )
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_an_img_whose_src_fails_the_scheme_allowlist_emits_nothing():
    calls = []

    def record(reference, alt):
        calls.append(reference)
        return "x"

    result = sanitize('<img src="javascript:alert(1)" alt="A">', on_image=record)
    assert result == ""
    assert calls == []


def test_an_img_with_no_src_at_all_emits_nothing():
    assert sanitize('<img alt="A">', on_image=lambda reference, alt: "x") == ""


def test_on_image_returning_an_unsafe_scheme_emits_nothing():
    # The callback is trusted code, but the sanitizer's job is rebuilding
    # HTML from an explicit scheme allowlist -- so its own output is
    # re-checked before being emitted, same as any other src.
    result = sanitize(
        '<img src="a.png" alt="A">',
        on_image=lambda reference, alt: "javascript:alert(1)",
    )
    assert result == ""
    assert "javascript" not in result.lower()


def test_on_image_set_means_resolve_uri_is_never_consulted_for_img():
    # The bypass this pins: when on_image is set, <img src> goes through
    # on_image alone. resolve_uri existing and being armed to answer must
    # not matter -- it should simply never be called for an <img>.
    resolve_calls = []

    def resolve_uri(name, value):
        resolve_calls.append((name, value))
        return "SHOULD-NOT-BE-USED"

    on_image_calls = []

    def on_image(reference, alt):
        on_image_calls.append((reference, alt))
        return "file:///resolved/a.png"

    result = sanitize(
        '<img src="a.png" alt="A">',
        resolve_uri=resolve_uri,
        on_image=on_image,
    )
    assert resolve_calls == []
    assert on_image_calls == [("a.png", "A")]
    assert 'src="file:///resolved/a.png"' in result


def test_content_cannot_spoof_the_image_error_placeholder_class():
    # xedown- must never join _ALLOWED_CLASS_PREFIXES: the placeholder span
    # sanitize() writes for a blocked image is trusted only because ordinary
    # content can never produce that class itself.
    result = sanitize('<span class="xedown-image-error">fake</span>')
    assert "xedown-image-error" not in result


def test_dir_survives_with_each_of_its_three_valid_values():
    for value in ("ltr", "rtl", "auto"):
        result = sanitize(f'<p dir="{value}">text</p>')
        assert f'dir="{value}"' in result


def test_dir_is_matched_ignoring_case_and_surrounding_space():
    assert 'dir="rtl"' in sanitize('<p dir=" RTL ">text</p>')


def test_any_other_dir_value_is_dropped_along_with_the_attribute():
    # A value allowlist, not a denylist: anything unrecognised leaves no
    # attribute behind at all.
    for value in ("", "auto ltr", "inherit", "rtl;", "javascript:", "1"):
        result = sanitize(f'<p dir="{value}">text</p>')
        assert "dir=" not in result, value
        assert "text" in result


def test_dir_is_allowed_on_every_element_that_survives():
    for tag in ("span", "div", "li", "td", "blockquote", "h2"):
        assert 'dir="ltr"' in sanitize(f'<{tag} dir="ltr">x</{tag}>')


def test_dir_goes_with_an_element_that_is_dropped():
    assert "dir=" not in sanitize('<marquee dir="rtl">x</marquee>')
    assert "dir=" not in sanitize('<script dir="rtl">x</script>')


def test_align_survives_on_a_div():
    assert 'align="center"' in sanitizer.sanitize('<div align="center">x</div>')


def test_align_survives_on_a_heading_and_a_table():
    assert 'align="center"' in sanitizer.sanitize('<h1 align="center">T</h1>')
    assert 'align="right"' in sanitizer.sanitize('<table align="right"></table>')


def test_align_survives_on_an_image():
    # img goes through _emit_img, a separate attribute loop from every
    # other element. It is the reason Task 6 extracted the shared filter.
    out = sanitizer.sanitize('<img src="a.png" align="center" alt="x">')
    assert 'align="center"' in out


def test_align_takes_an_allowlist_of_values():
    for good in ("left", "center", "right", "justify"):
        assert f'align="{good}"' in sanitizer.sanitize(f'<p align="{good}">x</p>')
    for bad in ("middle", "javascript:alert(1)", "", "center; x", "CENTER)"):
        assert "align" not in sanitizer.sanitize(f'<p align="{bad}">x</p>')


def test_align_is_case_insensitive_like_dir():
    assert 'align="center"' in sanitizer.sanitize('<p align="CENTER">x</p>')


def test_align_is_not_allowed_on_arbitrary_elements():
    # An allowlist per element, not a global attribute: `align` on a span
    # or a list item is not something a README needs and not something
    # this pass promised.
    assert "align" not in sanitizer.sanitize('<span align="center">x</span>')
    assert "align" not in sanitizer.sanitize('<li align="center">x</li>')


def test_div_keeps_class_alongside_the_new_align_entry():
    # ALLOWED_ATTRIBUTES["div"] gained "align" by editing the existing
    # entry, not by a second "div" key -- a duplicate key would silently
    # drop "class", which the renderer's own markup depends on.
    out = sanitizer.sanitize('<div class="hljs" align="center">x</div>')
    assert 'class="hljs"' in out
    assert 'align="center"' in out


def test_ol_start_survives_sanitization():
    # Python-Markdown already emits <ol start="7"> for a list that begins
    # at 7 (vendor/markdown/blockprocessors.py:402); ALLOWED_ATTRIBUTES
    # simply had no "ol" entry to let it through.
    assert 'start="7"' in sanitizer.sanitize('<ol start="7"><li>x</li></ol>')


def test_ol_start_rejects_a_non_numeric_value():
    assert "start" not in sanitizer.sanitize('<ol start="abc"><li>x</li></ol>')


def test_ol_start_accepts_a_negative_value():
    # HTML permits a countdown list; a leading "-" is not a scripting
    # surface, so it is honoured like any other digit run.
    assert 'start="-5"' in sanitizer.sanitize('<ol start="-5"><li>x</li></ol>')


def test_ol_start_rejects_an_empty_value():
    assert "start" not in sanitizer.sanitize('<ol start=""><li>x</li></ol>')


def test_ol_start_rejects_an_absurdly_long_digit_run():
    # Not a security boundary -- an oversized number can't execute or
    # fetch -- but an unbounded literal is still content reaching the page
    # unexamined, so it is capped well above anything a real list needs.
    huge = "1" * 40
    assert "start" not in sanitizer.sanitize(f'<ol start="{huge}"><li>x</li></ol>')


def test_ol_start_is_not_allowed_on_a_ul():
    assert "start" not in sanitizer.sanitize('<ul start="7"><li>x</li></ul>')


def test_bdi_survives_and_keeps_its_text():
    result = sanitize("<p>افتح <bdi>/usr/local/share</bdi> ثم تابع.</p>")
    assert "<bdi>" in result and "</bdi>" in result
    assert "/usr/local/share" in result


def test_bdi_carries_dir_like_anything_else():
    assert 'dir="ltr"' in sanitize('<bdi dir="ltr">/usr/local</bdi>')


def test_bdi_gains_no_other_attribute():
    result = sanitize('<bdi class="hljs" onclick="evil()">x</bdi>')
    assert "onclick" not in result
    assert "class" not in result


def test_mark_is_not_an_allowed_element():
    # Load-bearing, not trivia: preview.js inserts <mark> for every search hit
    # and clearSearch() unwraps *every* mark in the article without asking
    # whose it is. That is only safe because a document can never produce one
    # -- and it is why the two mark rules are `ADDITIONS` in the v0.1 parity
    # guard rather than a change to what an upgrading user sees.
    assert "mark" not in ALLOWED_ELEMENTS


def test_a_mark_in_the_source_document_never_reaches_the_page():
    html = sanitize("<p>a <mark>highlight</mark> b</p>")
    assert "<mark" not in html
    # The tag goes; the words the author wrote stay.
    assert "highlight" in html


def test_the_private_scheme_is_never_accepted_from_document_content():
    # THE bypass. If `xedown-image:` ever enters ALLOWED_URI_SCHEMES, a
    # hostile document can mint its own fetchable URL and the whole
    # preference becomes decorative. This test is the guard on that.
    html = '<img src="xedown-image:https%3A%2F%2Fevil.example%2Fpixel.png">'
    assert "xedown-image" not in sanitize(html)
    assert "xedown-image" not in sanitize(html, on_image=lambda ref, alt: ref)


def test_the_private_scheme_is_not_in_the_allowlist():
    from xedown import remoteimages, sanitizer

    assert remoteimages.SCHEME not in sanitizer.ALLOWED_URI_SCHEMES


def test_a_remote_image_result_carries_xedowns_own_class():
    html = '<img src="https://e.com/a.png" alt="a diagram">'
    out = sanitize(html, on_image=lambda ref, alt: RemoteImage("xedown-image:x"))
    assert 'class="xedown-remote"' in out
    assert 'alt="a diagram"' in out
    assert 'src="xedown-image:x"' in out


def test_document_content_cannot_produce_the_remote_class():
    html = '<img src="a.png" class="xedown-remote">'
    out = sanitize(html, on_image=lambda ref, alt: "file:///tmp/a.png")
    assert "xedown-remote" not in out


def test_a_remote_image_with_an_unusable_uri_emits_nothing():
    html = '<img src="https://e.com/a.png">'
    out = sanitize(html, on_image=lambda ref, alt: RemoteImage("javascript:alert(1)"))
    assert "<img" not in out


def test_class_filtering_is_identical_on_img_and_non_img():
    # _render_attributes and _emit_img filter `class` separately. Before
    # extracting that duplication, pin the behaviour both must keep.
    assert 'class="hljs"' in sanitizer.sanitize('<span class="hljs">x</span>')
    assert "class" not in sanitizer.sanitize('<span class="evil">x</span>')


def test_dir_filtering_is_identical_on_img_and_non_img():
    assert 'dir="rtl"' in sanitizer.sanitize('<p dir="rtl">x</p>')
    assert "dir" not in sanitizer.sanitize('<p dir="sideways">x</p>')


def test_img_keeps_a_valid_dir_and_drops_an_invalid_one():
    kept = sanitizer.sanitize('<img src="a.png" dir="rtl" alt="x">')
    dropped = sanitizer.sanitize('<img src="a.png" dir="sideways" alt="x">')
    assert 'dir="rtl"' in kept
    assert "dir" not in dropped


def test_align_filtering_is_identical_on_img_and_non_img():
    assert 'align="center"' in sanitizer.sanitize('<p align="center">x</p>')
    assert "align" not in sanitizer.sanitize('<p align="middle">x</p>')
    kept = sanitizer.sanitize('<img src="a.png" align="center" alt="x">')
    dropped = sanitizer.sanitize('<img src="a.png" align="middle" alt="x">')
    assert 'align="center"' in kept
    assert "align" not in dropped


def test_img_never_receives_a_class_attribute_from_content():
    # Unlike `dir`, `class` is not in ALLOWED_ATTRIBUTES["img"] and is not a
    # _GLOBAL_ATTRIBUTES entry either, so a content-authored <img class=...>
    # is dropped by the `name not in allowed` check before either emit
    # path's class-filtering branch is ever reached -- true whether `<img>`
    # goes through _render_attributes (no on_image) or _emit_img (on_image
    # set), and true for both an allowlisted and a non-allowlisted value.
    assert "class" not in sanitizer.sanitize('<img src="a.png" class="hljs" alt="x">')
    assert "class" not in sanitizer.sanitize('<img src="a.png" class="evil" alt="x">')
    assert "class" not in sanitizer.sanitize(
        '<img src="a.png" class="hljs" alt="x">',
        on_image=lambda ref, alt: "file:///tmp/a.png",
    )


def test_details_and_summary_survive():
    # Before this, a collapsible section rendered as its label run inline
    # into permanently-visible body text -- the single most damaging thing
    # the allowlist did to a real README.
    out = sanitizer.sanitize("<details><summary>More</summary><p>hidden</p></details>")
    assert "<details>" in out
    assert "<summary>More</summary>" in out
    assert "<p>hidden</p>" in out


def test_nested_details_survive_both_levels():
    out = sanitizer.sanitize(
        "<details><summary>Outer</summary>"
        "<details><summary>Inner</summary>deep</details></details>"
    )
    assert out.count("<details>") == 2
    assert out.count("</details>") == 2


def test_details_keeps_open_and_drops_a_handler():
    out = sanitizer.sanitize(
        '<details open onclick="steal()"><summary>S</summary>b</details>'
    )
    assert "open" in out
    assert "onclick" not in out
    assert "steal" not in out


def test_definition_lists_survive():
    out = sanitizer.sanitize("<dl><dt>Term</dt><dd>Definition</dd></dl>")
    assert "<dl>" in out and "<dt>Term</dt>" in out and "<dd>Definition</dd>" in out


def test_kbd_survives():
    assert "<kbd>Ctrl</kbd>" in sanitizer.sanitize("Press <kbd>Ctrl</kbd>")


def test_abbr_survives_with_its_title():
    out = sanitizer.sanitize('<abbr title="HyperText">HTML</abbr>')
    assert "<abbr" in out and 'title="HyperText"' in out


def test_abbr_drops_a_handler():
    out = sanitizer.sanitize('<abbr title="x" onmouseover="steal()">HTML</abbr>')
    assert "onmouseover" not in out and "steal" not in out


def test_table_caption_and_colgroup_survive():
    out = sanitizer.sanitize(
        "<table><caption>Cap</caption><colgroup><col></colgroup>"
        "<tr><td>1</td></tr></table>"
    )
    assert "<caption>Cap</caption>" in out
    assert "<colgroup>" in out
    assert "<col />" in out


def test_the_new_elements_add_no_uri_surface():
    # The point of choosing these ten elements is that none of them can
    # reference anything. If that stops being true, this fails.
    for markup in (
        '<details src="http://evil/x">a</details>',
        '<kbd href="http://evil/x">a</kbd>',
        '<abbr src="http://evil/x">a</abbr>',
        '<col src="http://evil/x">',
    ):
        assert "evil" not in sanitizer.sanitize(markup)


def test_uri_scheme_allowlist_is_unchanged():
    # A widening must never ride along quietly with an element addition.
    assert sanitizer.ALLOWED_URI_SCHEMES == frozenset(
        {"http", "https", "mailto", "file"}
    )


def test_content_dropping_elements_are_unchanged():
    for tag in ("script", "style", "svg", "math", "template"):
        out = sanitizer.sanitize(f"<{tag}>SECRET</{tag}>")
        assert "SECRET" not in out
