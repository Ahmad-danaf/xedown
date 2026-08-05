import pytest
from xedown.sanitizer import sanitize


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
