import pytest
from xedown.sanitizer import ImagePlaceholder, sanitize


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
