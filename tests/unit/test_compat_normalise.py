"""Canonicalisation for the differential audit (tests/compat/normalise.py).

Lives in tests/unit rather than beside the module it tests because it must
run in CI, and CI collects only tests/unit. normalise.py imports nothing
that CI lacks -- that is the reason the module is split out from
differential.py, which does.
"""

import pathlib
import sys

TESTS_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from compat import normalise


def test_insignificant_whitespace_is_collapsed():
    assert normalise.canonicalise("<p>a   \n  b</p>") == normalise.canonicalise(
        "<p>a b</p>"
    )


def test_whitespace_inside_pre_is_preserved():
    tight = normalise.canonicalise("<pre>a b</pre>")
    spaced = normalise.canonicalise("<pre>a   \n  b</pre>")
    assert tight != spaced


def test_whitespace_inside_code_is_preserved():
    assert normalise.canonicalise("<code>a b</code>") != normalise.canonicalise(
        "<code>a   b</code>"
    )


def test_attributes_are_sorted():
    assert normalise.canonicalise('<img alt="x" src="y" />') == normalise.canonicalise(
        '<img src="y" alt="x" />'
    )


def test_void_elements_spell_the_same_way():
    assert normalise.canonicalise("<p>a<br>b</p>") == normalise.canonicalise(
        "<p>a<br />b</p>"
    )


def test_entities_are_decoded():
    assert normalise.canonicalise("<p>&quot;x&quot;</p>") == normalise.canonicalise(
        '<p>"x"</p>'
    )


def test_xedown_heading_ids_are_ignored():
    # Python-Markdown's toc extension adds an id; cmark-gfm does not. That
    # is not a divergence anyone should have to triage.
    assert normalise.canonicalise('<h1 id="title">T</h1>') == normalise.canonicalise(
        "<h1>T</h1>"
    )


def test_xedown_hljs_classes_are_ignored():
    assert normalise.canonicalise(
        '<code class="hljs language-python">x</code>'
    ) == normalise.canonicalise('<code class="language-python">x</code>')


def test_absolute_file_uris_map_back_to_relative():
    # xedown resolves a relative href against the document's directory;
    # cmark leaves it alone. Comparing them raw would flag every link.
    assert normalise.canonicalise(
        '<a href="file:///docs/a.md">x</a>', base_dir="/docs"
    ) == normalise.canonicalise('<a href="a.md">x</a>', base_dir="/docs")


def test_text_content_differences_still_show():
    # The guard against a canonicaliser so aggressive it makes everything
    # equal: this pair must NOT collapse.
    assert normalise.canonicalise("<p>a</p>") != normalise.canonicalise("<p>b</p>")


def test_tag_differences_still_show():
    assert normalise.canonicalise("<em>a</em>") != normalise.canonicalise(
        "<strong>a</strong>"
    )


def test_escaped_entities_are_not_double_decoded():
    # `&amp;lt;` is the escaped form of the literal text `&lt;`. Decoding
    # it twice would turn it into a `<` and quietly invent markup that the
    # document never contained.
    assert normalise.canonicalise("<p>&amp;lt;</p>") != normalise.canonicalise(
        "<p><</p>"
    )


def test_literal_angle_brackets_do_not_become_markup():
    # HTMLParser(convert_charrefs=True) decodes `&lt;`/`&gt;` on the way in.
    # Serialising that text back out without re-escaping would let literal
    # tag-like text in prose collide with an actual tag boundary -- one
    # paragraph would canonicalise the same as two.
    assert normalise.canonicalise(
        "<p>x&lt;/p&gt;&lt;p&gt;y</p>"
    ) != normalise.canonicalise("<p>x</p><p>y</p>")


def test_an_embedded_quote_does_not_become_a_second_attribute():
    # Same defect, in an attribute value: `&quot;` decodes to a literal `"`
    # on the way in. Writing it back unescaped terminates the attribute
    # early, and what follows reads as a second, bogus attribute.
    assert normalise.canonicalise(
        '<a href="x&quot; y=&quot;z">t</a>'
    ) != normalise.canonicalise('<a href="x" y="z">t</a>')


def test_literal_and_entity_ampersand_are_equivalent():
    # Both spellings decode to the same text; re-escaping on output must not
    # treat them differently (e.g. by double-escaping the entity form).
    assert normalise.canonicalise("<p>a &amp; b</p>") == normalise.canonicalise(
        "<p>a & b</p>"
    )
