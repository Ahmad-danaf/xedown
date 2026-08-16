"""The rule, stated once and tested against every vector we know of:

    Markdown may display content, but it must never execute content.

Every other test module checks one layer in isolation -- `test_sanitizer.py`
feeds hand-written HTML to `sanitize()`, `test_links.py` asks `classify_link`
about one URI, `test_imagefetch.py` drives one fetch. This module asks the
question the reader actually cares about: given a *Markdown document* an
attacker wrote, what reaches the page?

That distinction has teeth. The sanitizer is not the only thing between a
document and the DOM -- Python-Markdown parses first, and its output is not
the HTML the author typed. `<scr<script>ipt>` is rewritten before the
sanitizer ever sees it; an autolink invents an `<a href>` that appears
nowhere in the source. A vector can therefore be dead at the sanitizer and
alive through the pipeline, or the reverse, and only an end-to-end test tells
the two apart. So the payloads below go in as Markdown and the assertions are
made on the rendered page.

`assert_inert` is the centrepiece. It does not grep the output for the
payload it just sent: a test that greps only ever finds what its author
thought of. It re-parses the *result* and holds every element, attribute and
URI in it against the sanitizer's own allowlists, so a payload that produces
some construct nobody anticipated fails here just as loudly as `<script>`
does. That is what makes this a security boundary test rather than a
collection of anecdotes.
"""

import html
import re
from html.parser import HTMLParser

import pytest
from xedown import (
    errors,
    imagefetch,
    images,
    remoteimages,
    renderer,
    sanitizer,
)

# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

# The one class the sanitizer puts on an <img> itself, for an image it is
# handing to xedown's own fetch path. Document content can never produce it
# (`_filter_class` refuses the `xedown-` prefix), which is exactly why the
# auditor can treat it as ours and not as something that leaked through.
_SANITIZER_OWNED_IMG_ATTRIBUTES = {"class": {sanitizer.REMOTE_IMAGE_CLASS}}

# A scheme the page is permitted to address. `xedown-image:` is *not* in
# `ALLOWED_URI_SCHEMES` on purpose -- document content can never mint it --
# but the sanitizer emits it for an image the render was permitted to fetch,
# so the auditor has to know it is a legitimate thing to find in output.
_EMITTABLE_SCHEMES = frozenset(sanitizer.ALLOWED_URI_SCHEMES) | {remoteimages.SCHEME}

_EVENT_HANDLER = re.compile(r"^on[a-z]+$", re.IGNORECASE)

# Attributes that must never be emitted, written out here rather than derived
# from `sanitizer.ALLOWED_ATTRIBUTES`.
#
# This is the one part of the audit that does not read the allowlists, and it
# exists because of how the rest of it fails. `_Auditor` checks the output
# against the sanitizer's own tables, so widening a table widens the audit
# with it: adding `style` to `_GLOBAL_ATTRIBUTES` makes the sanitizer emit it
# *and* makes the auditor accept it, and every test in this file keeps
# passing. Confirmed by mutation, not assumed -- that exact edit passed the
# whole suite before this list existed.
#
# So these names are pinned independently. Each is inert on its own and
# dangerous in the way this project cares about: `style` is content reaching
# into the plugin's own presentation, the rest are off-document references or
# navigation targets that would put a URI somewhere `_check_uri` does not
# look.
_NEVER_EMITTED_ATTRIBUTES = frozenset(
    {
        "style",
        "srcset",
        "sizes",
        "background",
        "formaction",
        "action",
        "poster",
        "data",
        "codebase",
        "ping",
        "srcdoc",
        "xlink:href",
        "http-equiv",
        "content",
        "rel",
        "target",
        "usemap",
        "autofocus",
        "contenteditable",
    }
)


class _Auditor(HTMLParser):
    """Collects everything wrong with a rendered fragment.

    Deliberately accumulates rather than raising on the first problem: when a
    payload breaks through, the useful report is everything it produced, not
    the first symptom.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems = []
        self.uris = []

    def handle_starttag(self, tag, attrs):
        self._check(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._check(tag, attrs)

    def handle_comment(self, data):
        # The sanitizer never emits one. A comment in the output would mean
        # something reached the page unparsed, and comments are also how
        # conditional-comment and mXSS tricks re-enter a document.
        self.problems.append(f"comment in output: {data!r}")

    def handle_decl(self, decl):
        self.problems.append(f"declaration in output: {decl!r}")

    def handle_pi(self, data):
        self.problems.append(f"processing instruction in output: {data!r}")

    def _check(self, tag, attrs):
        tag = tag.lower()
        if tag not in sanitizer.ALLOWED_ELEMENTS:
            self.problems.append(f"<{tag}> is not an allowed element")
            return
        allowed = sanitizer.ALLOWED_ATTRIBUTES.get(tag, frozenset()) | (
            sanitizer._GLOBAL_ATTRIBUTES
        )
        owned = _SANITIZER_OWNED_IMG_ATTRIBUTES if tag == "img" else {}
        for raw_name, value in attrs:
            name = (raw_name or "").lower()
            if _EVENT_HANDLER.match(name):
                self.problems.append(f"<{tag} {name}=…> is an event handler")
                continue
            if name in _NEVER_EMITTED_ATTRIBUTES or name.startswith("data-"):
                self.problems.append(f"<{tag} {name}=…> must never be emitted")
                continue
            if name in owned:
                if value not in owned[name]:
                    self.problems.append(f"<{tag} {name}={value!r}> is not ours")
                continue
            if name not in allowed:
                self.problems.append(f"<{tag} {name}=…> is not an allowed attribute")
                continue
            if name in ("href", "src"):
                self._check_uri(tag, name, value or "")

    def _check_uri(self, tag, name, value):
        self.uris.append(value)
        head, separator, _ = value.partition(":")
        if not separator or value.startswith("#"):
            return  # relative reference or in-page anchor
        scheme = head.lower()
        if scheme == "data":
            if not sanitizer._is_safe_data_image_uri(value):
                self.problems.append(f"<{tag} {name}=…> carries {value[:40]!r}")
            return
        if scheme not in _EMITTABLE_SCHEMES:
            self.problems.append(f"<{tag} {name}=…> carries the {scheme}: scheme")


def assert_inert(fragment):
    """Fail unless `fragment` can only be displayed, never executed.

    Two independent checks, because they fail in different ways. The parse
    audit is the real one -- it holds the output against the allowlists, so a
    construct this file never anticipated fails just as loudly as `<script>`.
    The literal scan after it is a backstop for the case the audit cannot
    see: markup that is inert to a parser reading the fragment *now* but
    would not be if the browser's own tokenizer disagreed with Python's about
    where a tag ends.

    That backstop scans only for `<tag`, never for a scheme string. The
    difference is whether escaped text can satisfy it. `<` is escaped
    everywhere the sanitizer emits text, so a literal `<script` in the output
    can only be a real tag -- but `javascript:` has no `<` and appears
    verbatim the moment a document *writes about* a javascript URL, which is
    an ordinary thing for a README to do. Scanning the whole fragment for it
    would fail that document while proving nothing: whether a scheme can
    execute depends on its being a URI, and `_check_uri` already decides that
    against the allowlist, for every `href` and `src` actually emitted.
    """
    auditor = _Auditor()
    auditor.feed(fragment)
    auditor.close()
    assert not auditor.problems, "\n".join(auditor.problems)

    lowered = fragment.lower()
    for forbidden in (
        "<script",
        "<style",
        "<svg",
        "<math",
        "<iframe",
        "<object",
        "<embed",
        "<base",
        "<meta",
        "<form",
        "<link",
        "<template",
    ):
        assert forbidden not in lowered, f"{forbidden!r} survived into: {fragment!r}"


def emitted_uris(fragment):
    """Every `href`/`src` value the render actually put in the page.

    Assertions about URIs are made against this rather than against the
    fragment as a string, because a *placeholder* legitimately quotes the
    reference it is refusing -- "Image not found: /tmp/../secret.txt" is the
    sanitizer reporting a refusal, not a path reaching the DOM. Scanning the
    whole fragment cannot tell those apart; scanning the emitted URIs can.
    """
    auditor = _Auditor()
    auditor.feed(fragment)
    auditor.close()
    return auditor.uris


def addresses_a_fetch(fragment):
    """Whether the render handed the page a URI that would fetch anything.

    The colon matters: `remoteimages.SCHEME` is `xedown-image`, which is a
    substring of the `xedown-image-error` class the sanitizer puts on a
    *refusal* placeholder. Testing for the bare scheme name would therefore
    report a fetch for the exact markup that proves no fetch is happening.
    """
    return any(
        uri.startswith(remoteimages.SCHEME + ":") for uri in emitted_uris(fragment)
    )


def render(markdown_text, **kwargs):
    """One attacker-authored document, through the whole pipeline."""
    kwargs.setdefault("base_dir", "/tmp")
    return renderer.render_fragment(markdown_text, **kwargs)


def test_the_auditor_notices_a_fragment_that_is_not_inert():
    """The invariant check must be able to fail.

    Everything else in this file asserts `assert_inert` passes. Without this,
    a helper that silently accepted anything would make every one of those
    assertions vacuous -- the failure mode a security test can least afford.
    """
    for escaped in (
        "<p onclick='x'>hi</p>",
        "<script>alert(1)</script>",
        '<a href="javascript:alert(1)">x</a>',
        '<img src="data:text/html,x">',
        "<p><!-- comment --></p>",
        "<marquee>hi</marquee>",
    ):
        with pytest.raises(AssertionError):
            assert_inert(escaped)


# ---------------------------------------------------------------------------
# 1. <script>
# ---------------------------------------------------------------------------

SCRIPT_PAYLOADS = [
    "<script>alert(1)</script>",
    "<ScRiPt>alert(1)</ScRiPt>",
    '<script src="https://evil.example/x.js"></script>',
    '<script type="text/javascript">alert(1)</script>',
    # An attribute value containing `>`: the tokenizer must not end the tag
    # early and leave the rest as text.
    '<script a=">">alert(1)</script>',
    # The classic filter-defeat: a naive "remove <script>" pass rewrites this
    # into a working tag. Python-Markdown mangles it before we see it, which
    # is precisely why this is tested through the pipeline and not the
    # sanitizer alone.
    "<scr<script>ipt>alert(1)</script>",
    # An unterminated comment inside the block, which changes where a
    # spec-compliant tokenizer thinks the element ends.
    "<script>alert(1)<!--</script>-->",
    "<script>/* </script> */ alert(1)</script>",
]


@pytest.mark.parametrize("payload", SCRIPT_PAYLOADS)
def test_script_elements_never_reach_the_page(payload):
    """No `<script>` element survives, in any spelling.

    Deliberately *not* "the string `alert` is absent". Two of these payloads
    are mangled by Python-Markdown into something whose leftovers include the
    literal text `alert(1)` -- `<scr<script>ipt>…` renders as the visible
    prose `ipt>alert(1)`. That text is inert, and demanding its absence would
    be testing for the wrong property: the rule is that content cannot
    execute, not that it cannot mention. `assert_inert` is what enforces the
    real one.
    """
    assert_inert(render(payload))


def test_script_content_is_dropped_not_escaped_into_view():
    """The *content* goes too, not just the tag.

    An allowlist that dropped `<script>` but kept its text would put
    `alert(1)` on screen as prose -- harmless, but it would mean the reader
    saw a line the author never wrote as prose. `script` is in
    `_DROP_CONTENT_ELEMENTS` for that reason.
    """
    result = render("<p>before</p>\n\n<script>alert(1)</script>\n\n<p>after</p>")
    assert "alert" not in result
    assert "before" in result and "after" in result


def test_a_script_inside_a_code_fence_stays_visible_text():
    """The inverse failure: a document *about* scripting must still render.

    Escaping, not dropping, is what a fenced block deserves -- the reader
    asked to see the tag.
    """
    result = render("```html\n<script>alert(1)</script>\n```")
    assert_inert(result)
    assert "&lt;script&gt;" in result


# ---------------------------------------------------------------------------
# 2. javascript: URLs
# ---------------------------------------------------------------------------

SCRIPTING_URLS = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "vbscript:msgbox(1)",
    "livescript:alert(1)",
    # Control characters and whitespace smuggled into the scheme. The
    # sanitizer strips these *before* it looks at the scheme, so the
    # allowlist sees `javascript:` and refuses it.
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "java\rscript:alert(1)",
    "java\x00script:alert(1)",
    "java\x0bscript:alert(1)",
    " javascript:alert(1)",
    "\x01javascript:alert(1)",
    # Entity-encoded, which the HTML parser decodes for us.
    "&#106;avascript:alert(1)",
    "&#x6a;avascript:alert(1)",
    "javascript&colon;alert(1)",
    # Doubly-encoded: unescaping twice must not *create* a passing value.
    "&amp;#106;avascript:alert(1)",
]


@pytest.mark.parametrize("uri", SCRIPTING_URLS)
def test_a_scripting_url_never_survives_as_an_href(uri):
    result = render(f'<a href="{uri}">click</a>')
    assert_inert(result)
    # The link text survives; only the destination is taken away. A reader
    # should still see what the author wrote, just not be able to fire it.
    assert "click" in result


@pytest.mark.parametrize("uri", SCRIPTING_URLS)
def test_a_scripting_url_never_survives_as_an_image_src(uri):
    assert_inert(render(f'<img src="{uri}" alt="x">'))


def test_markdown_link_syntax_cannot_smuggle_a_scripting_url():
    """The Markdown spelling, not just the HTML one.

    `[click](javascript:…)` never passes through an `<a href>` an author
    typed -- Python-Markdown *builds* the tag -- so this is a different path
    into the sanitizer than the raw-HTML case above.
    """
    result = render("[click](javascript:alert(1))")
    assert_inert(result)
    assert "click" in result


def test_markdown_image_syntax_cannot_smuggle_a_scripting_url():
    assert_inert(render("![x](javascript:alert(1))"))


def test_a_reference_style_link_cannot_smuggle_a_scripting_url():
    """Reference links resolve at a different point in the parse."""
    assert_inert(render("[click][ref]\n\n[ref]: javascript:alert(1)"))


def test_an_autolink_cannot_smuggle_a_scripting_url():
    assert_inert(render("<javascript:alert(1)>"))


@pytest.mark.parametrize(
    "href",
    [
        "http://ok.example/a\tb",
        "http://ok.example/a\nb",
        "http://ok.example/a\rb",
        "http://ok.example/a\x00b",
        "http://ok.example/a\x0bb",
        "http://ok.example/a\x7fb",
        "  http://ok.example/x  ",
        "http://ok.example/&#9;x",
    ],
)
def test_an_emitted_uri_never_contains_a_control_character(href):
    """The value emitted is the value that was checked.

    This is the property that makes `_strip_control_characters` load-bearing,
    and it is not the same claim as "a smuggled scheme is refused" -- the
    scheme allowlist refuses `java\\tscript:` on its own, so a test that only
    checked smuggled schemes would pass with the stripping removed entirely.
    (Confirmed by mutation: deleting the function's body left every other
    test in this file green.)

    What stripping actually buys is that no control character survives *into*
    an emitted URI on an otherwise-allowed scheme, where the browser's own
    URL parser -- which strips tabs and newlines before resolving -- could
    otherwise read a different address than the one the allowlist approved.
    """
    fragment = sanitizer.sanitize(f'<a href="{href}">x</a>')
    for uri in emitted_uris(fragment):
        assert not [ch for ch in uri if ord(ch) <= 0x20 or ord(ch) == 0x7F], repr(uri)


def test_an_anchor_that_lost_its_href_is_not_left_looking_clickable():
    """A refused destination leaves `<a>` with no href at all.

    Not `href=""`, which would reload the document, and not a `#` that would
    silently jump to the top: the element is left inert and the text stays.
    """
    result = render('<a href="javascript:alert(1)">click</a>')
    assert "href" not in result
    assert "<a>click</a>" in result


# ---------------------------------------------------------------------------
# 3. Malicious HTML
# ---------------------------------------------------------------------------

MALICIOUS_HTML = [
    # Retargets every relative URI in the document.
    '<base href="https://evil.example/">',
    # Navigation without a click.
    '<meta http-equiv="refresh" content="0;url=https://evil.example">',
    '<form action="https://evil.example"><input type="submit"></form>',
    '<button formaction="https://evil.example">go</button>',
    # Styling is content reaching into the plugin's own presentation.
    "<style>body{background:url(https://evil.example/x)}</style>",
    '<p style="background:url(https://evil.example/x)">hi</p>',
    '<div style="position:fixed;inset:0;z-index:99">overlay</div>',
    '<link rel="stylesheet" href="https://evil.example/x.css">',
    '<link rel="prefetch" href="https://evil.example/x">',
    # Attribute-boundary confusion.
    '<a href="#x" title=\'" onclick="alert(1)\'>x</a>',
    '<a href="#x" title="a&quot; onclick=&quot;alert(1)">x</a>',
    '<img src="a.png" alt="x" "onerror="alert(1)">',
    # Elements whose parsing rules differ from ordinary flow content, which
    # is where sanitizer/browser disagreements live.
    "<template><script>alert(1)</script></template>",
    "<noscript><p>hi</p></noscript>",
    "<noembed><img src=x onerror=alert(1)></noembed>",
    "<textarea><img src=x onerror=alert(1)></textarea>",
    "<title><img src=x onerror=alert(1)></title>",
    "<plaintext><script>alert(1)</script>",
    "<xmp><script>alert(1)</script></xmp>",
    # Comments, including the conditional-comment form.
    "<!--[if IE]><script>alert(1)</script><![endif]-->",
    "<!-- <script>alert(1)</script> -->",
    "<![CDATA[<script>alert(1)</script>]]>",
    "<?xml-stereotype <script>alert(1)</script> ?>",
    # Deprecated but still-parsed elements.
    "<marquee onstart=alert(1)>x</marquee>",
    "<isindex action=javascript:alert(1)>",
]


@pytest.mark.parametrize("payload", MALICIOUS_HTML)
def test_malicious_html_is_reduced_to_something_inert(payload):
    assert_inert(render(payload))


def test_document_content_cannot_claim_one_of_xedowns_own_classes():
    """`class` is prefix-filtered, so `xedown-` can only ever be ours.

    This is load-bearing well past the stylesheet: `preview.js` decides an
    image is a *fetched remote* one by `classList.contains("xedown-remote")`,
    and replaces the text of a `.xedown-image-error` span with whatever the
    host says went wrong. Both would be steerable by a document if content
    could write the class.
    """
    result = render(
        '<span class="xedown-remote">a</span>'
        '<span class="xedown-image-error">b</span>'
        '<span class="xedown-match">c</span>'
        '<span class="xedown-loading language-x">d</span>'
    )
    # Every span comes out bare except the one whose class the allowlist
    # admits by prefix -- and no `xedown-` class appears anywhere.
    assert "xedown-" not in result
    assert 'class="language-x"' in result
    for letter in "abcd":
        assert f">{letter}</span>" in result


def test_a_documents_own_img_never_carries_a_class(docdir):
    """Including the one the sanitizer puts on a fetched remote image.

    `class` is not in `ALLOWED_ATTRIBUTES["img"]` at all, so this holds
    whatever the value: an `<img>` in the output carries a class only when
    this module wrote one.
    """
    result = render(
        '<img src="ok.png" class="xedown-remote" alt="d">', base_dir=str(docdir)
    )
    assert "<img" in result
    assert "class" not in result


def test_document_content_cannot_carry_a_data_attribute():
    """`setImageMessage` keys off `data-xedown-src`; content cannot write one."""
    result = render('<span data-xedown-src="x">a</span><img src="a.png" data-x="y">')
    assert "data-xedown-src" not in result
    assert "data-x" not in result


def test_a_document_cannot_displace_the_content_element():
    """`id` is not value-filtered, so a document *can* write `xedown-content`.

    That is deliberate -- `id` is how a heading anchor works -- and it is
    safe for one structural reason worth pinning: `getElementById` returns
    the first match in document order, and the real `<article>` encloses
    every scrap of document content, so a duplicate can only ever appear
    after it. `preview.js`'s `content()` therefore still finds the article,
    and `replaceBody` still swaps the right element.
    """
    page = renderer.render_document('<div id="xedown-content">hijack</div>')
    article = page.index(f'id="{renderer.CONTENT_ELEMENT_ID}"')
    imposter = page.index('id="xedown-content"', article + 1)
    assert article < imposter


def test_text_is_escaped_rather_than_reinterpreted():
    result = render("A < B & C > D and <notatag>")
    assert_inert(result)
    assert "&lt;" in result and "&amp;" in result


def test_an_attribute_value_cannot_break_out_of_its_quoting():
    """Every emitted value is escaped with `quote=True`.

    So a value carrying `"` cannot close the attribute early and start a new
    one -- which is the whole mechanism behind the `title='" onclick="…'`
    payload above.
    """
    result = render('<a href="#x" title=\'" onclick="alert(1)\'>x</a>')
    # The payload's own quote is escaped, so what looks like a second
    # attribute stays inside the value of the first. `assert_inert` re-parses
    # to confirm no `onclick` attribute exists; the `&quot;` is the mechanism
    # that makes that true.
    assert_inert(result)
    assert 'title="&quot; onclick=&quot;alert(1)"' in result


# ---------------------------------------------------------------------------
# 4. Event handlers
# ---------------------------------------------------------------------------

EVENT_HANDLER_PAYLOADS = [
    '<a href="#x" onclick="alert(1)">click</a>',
    '<p onmouseover="alert(1)">hi</p>',
    "<p onmouseover=alert(1)>hi</p>",  # unquoted
    "<p onmouseover=`alert(1)`>hi</p>",  # backtick, an old IE trick
    '<p OnMouseOver="alert(1)">hi</p>',  # case
    '<p on\tclick="alert(1)">hi</p>',  # whitespace inside the name
    '<img src="a.png" onerror="alert(1)" alt="x">',
    '<img src="a.png" ONERROR="alert(1)" alt="x">',
    '<input onfocus="alert(1)" autofocus>',
    '<details ontoggle="alert(1)" open><summary>s</summary>x</details>',
    '<td onclick="alert(1)">x</td>',
    '<summary onclick="alert(1)">x</summary>',
    '<abbr onclick="alert(1)" title="t">x</abbr>',
    '<body onload="alert(1)">',
    '<div onanimationstart="alert(1)">x</div>',
]


@pytest.mark.parametrize("payload", EVENT_HANDLER_PAYLOADS)
def test_event_handler_attributes_never_reach_the_page(payload):
    result = render(payload)
    assert_inert(result)
    assert "alert" not in result


def test_every_allowed_element_refuses_a_handler():
    """Not a sampling: each element the allowlist admits, checked.

    `ALLOWED_ATTRIBUTES` is a per-element table and grows as the
    compatibility work adds elements, so a new row that accidentally listed a
    handler would otherwise be caught only if someone thought to add a case
    here.
    """
    for tag in sorted(sanitizer.ALLOWED_ELEMENTS):
        fragment = sanitizer.sanitize(f'<{tag} onclick="alert(1)">x</{tag}>')
        assert "onclick" not in fragment, tag
        assert "alert" not in fragment, tag


def _every_allowed_attribute():
    every = set(sanitizer._GLOBAL_ATTRIBUTES)
    for names in sanitizer.ALLOWED_ATTRIBUTES.values():
        every |= set(names)
    return every


def test_no_allowed_attribute_is_an_event_handler():
    """The tables themselves, read directly rather than through a render."""
    assert not [
        name for name in _every_allowed_attribute() if _EVENT_HANDLER.match(name)
    ]


def test_no_allowed_attribute_is_one_of_the_forbidden_names():
    """The tables against the independent denylist.

    `_NEVER_EMITTED_ATTRIBUTES` is checked at render time by the auditor and
    against the tables here, because the two catch different mistakes: the
    render check catches a value that slips through some path nobody
    enumerated, this one catches a table entry added on purpose without
    anyone noticing what it admits.
    """
    assert not _every_allowed_attribute() & _NEVER_EMITTED_ATTRIBUTES
    assert not {n for n in _every_allowed_attribute() if n.startswith("data-")}


def test_the_global_attribute_set_is_the_three_inert_ones():
    """Pinned by value, because a global attribute lands on *every* element.

    `dir`, `id` and `title` carry no URI and no scripting surface, which is
    the rule an addition here is measured against. A fourth would apply to
    every element in the allowlist at once, so it deserves the same
    deliberate edit `ALLOWED_URI_SCHEMES` gets.
    """
    assert sanitizer._GLOBAL_ATTRIBUTES == frozenset({"dir", "id", "title"})


def test_style_is_refused_on_every_element_that_survives():
    """The attribute the design refuses by name.

    Content setting arbitrary CSS is the exact failure the rebuild-from-an-
    allowlist design exists to prevent -- which is why `tables` is
    reconfigured to emit `align=` rather than the sanitizer being widened to
    accept `style="text-align: …"`.
    """
    for tag in sorted(sanitizer.ALLOWED_ELEMENTS):
        fragment = sanitizer.sanitize(f'<{tag} style="color:red">x</{tag}>')
        assert "style" not in fragment, tag
        assert "color" not in fragment, tag


def test_a_task_list_checkbox_is_display_only():
    """The one interactive element the allowlist admits, forced inert.

    `disabled` is appended unconditionally and any `disabled` the document
    supplied is dropped first, so a document cannot re-enable it by writing
    `disabled="false"` (which HTML would read as disabled anyway) or by any
    other spelling.
    """
    result = render("- [ ] todo\n- [x] done\n")
    assert_inert(result)
    assert result.count("<input") == result.count("disabled")


# ---------------------------------------------------------------------------
# 5. iframe / object / embed
# ---------------------------------------------------------------------------

EMBEDDING_PAYLOADS = [
    '<iframe src="https://evil.example"></iframe>',
    '<iframe src="javascript:alert(1)"></iframe>',
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    '<iframe src="data:text/html,<script>alert(1)</script>"></iframe>',
    '<object data="https://evil.example/x.swf"></object>',
    '<object data="data:text/html,<script>alert(1)</script>"></object>',
    "<object><param name=movie value=x><script>alert(1)</script></object>",
    '<embed src="https://evil.example/x.swf">',
    '<embed src="data:text/html,<script>alert(1)</script>">',
    "<applet code=Evil.class></applet>",
    "<frameset><frame src=https://evil.example></frameset>",
    '<portal src="https://evil.example"></portal>',
    '<audio src="https://evil.example/x.mp3" autoplay></audio>',
    '<video src="https://evil.example/x.mp4" autoplay></video>',
    "<video><source src=https://evil.example/x.mp4></video>",
]


@pytest.mark.parametrize("payload", EMBEDDING_PAYLOADS)
def test_embedding_elements_never_reach_the_page(payload):
    assert_inert(render(payload))


def test_no_embedding_element_is_in_the_allowlist():
    for tag in (
        "iframe",
        "object",
        "embed",
        "applet",
        "frame",
        "frameset",
        "portal",
        "audio",
        "video",
        "source",
        "track",
        "script",
        "style",
        "link",
        "base",
        "meta",
        "form",
        "button",
        "svg",
        "math",
        "template",
    ):
        assert tag not in sanitizer.ALLOWED_ELEMENTS


def test_the_page_policy_refuses_embedding_outright():
    """A second, independent layer: even a tag that somehow reached the DOM
    could not load anything."""
    page = renderer.render_document("# hi")
    assert "frame-src 'none'" in page
    assert "object-src 'none'" in page
    assert "default-src 'none'" in page


# ---------------------------------------------------------------------------
# 6. Malicious SVG
# ---------------------------------------------------------------------------

SVG_PAYLOADS = [
    "<svg><script>alert(1)</script></svg>",
    '<svg onload="alert(1)"></svg>',
    '<svg><animate onbegin="alert(1)" attributeName="x"/></svg>',
    '<svg><set attributeName="onload" to="alert(1)"/></svg>',
    "<svg><foreignObject><p>text</p></foreignObject></svg>",
    '<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>',
    '<svg><use href="data:image/svg+xml,&lt;svg/&gt;"/></svg>',
    '<svg><image href="javascript:alert(1)"/></svg>',
    "<svg><handler>alert(1)</handler></svg>",
    "<math><mtext><script>alert(1)</script></mtext></math>",
    '<math><maction actiontype="statusline#javascript:alert(1)">x</maction></math>',
]


@pytest.mark.parametrize("payload", SVG_PAYLOADS)
def test_svg_and_mathml_are_dropped_with_their_contents(payload):
    result = render(payload)
    assert_inert(result)
    assert "alert" not in result


def test_an_unclosed_svg_swallows_the_rest_rather_than_leaking_it():
    """Fail-closed, and worth pinning as a decision rather than an accident.

    `_suppress_depth` only comes back down on a matching `</svg>`, so a
    document that never closes one loses everything after it. That is a
    visible correctness cost -- and the right side to err on: the alternative
    is guessing where foreign content ended, which is exactly the guess the
    browser and the sanitizer would make differently.
    """
    result = render("<svg><p>swallowed</p>")
    assert_inert(result)
    assert "swallowed" not in result


def test_svg_as_an_image_source_is_never_inlined():
    """An `.svg` file reference is resolved like any other path.

    It becomes a `file:` src that WebKit loads as an image -- where SVG
    cannot script -- not markup inlined into the document.
    """
    result = render("![x](diagram.svg)")
    assert_inert(result)
    assert "<svg" not in result.lower()


@pytest.mark.parametrize(
    "uri",
    [
        "data:image/svg+xml,%3Csvg onload=alert(1)%3E",
        "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+",
        "data:image/svg+xml;charset=utf-8,%3Csvg/%3E",
        "DATA:IMAGE/SVG+XML,%3Csvg/%3E",
    ],
)
def test_an_svg_data_uri_is_refused_despite_declaring_an_image_type(uri):
    """The `src="data:…"` side door around the `<svg>`-content drop.

    `_SAFE_DATA_IMAGE_SUBTYPES` is an allowlist of raster subtypes, so
    `svg+xml` is refused by not being on it -- rather than by a denylist that
    a new spelling could step around.
    """
    result = render(f'<img src="{uri}" alt="x">')
    assert_inert(result)
    assert "svg" not in result.lower()


def test_a_fetched_image_declaring_svg_is_refused_by_the_fetcher_too():
    """The remote path enforces it independently of the sanitizer."""
    result = _fetch_returning({"Content-Type": "image/svg+xml"}, b"<svg/>")
    assert result.error == imagefetch.NOT_AN_IMAGE


def test_a_fetched_image_that_is_svg_bytes_under_a_raster_type_is_refused():
    """Declared `image/png`, actually SVG: refused on the bytes, not the label.

    `pixel_verdict` matches magic bytes, and `<svg` matches no format it
    parses, so the payload comes back unmeasurable and the fetch path treats
    unmeasurable as a refusal.
    """
    result = _fetch_returning({"Content-Type": "image/png"}, b"<svg onload='x'/>")
    assert result.error == imagefetch.NOT_AN_IMAGE


# ---------------------------------------------------------------------------
# 7. Remote redirects
# ---------------------------------------------------------------------------


class _Response:
    """The parts of an HTTP response `fetch_once` actually reads."""

    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self.headers = dict(headers or {})
        self._body = body
        self._sent = False

    def read1(self, size):
        if self._sent:
            return b""
        self._sent = True
        return self._body[:size]

    def close(self):
        pass


# A 2x2 RGBA PNG: enough header for `imagelimits` to measure it.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    + (2).to_bytes(4, "big")
    + (2).to_bytes(4, "big")
    + b"\x08\x06\x00\x00\x00"
)


def _public(_host):
    return ["93.184.216.34"]


def _fetch_returning(headers, body):
    def opener(_url, _headers, _timeout, _proxies):
        return _Response(200, headers, body)

    return imagefetch.fetch_once(
        "https://ok.example/x.png", opener=opener, resolver=_public
    )


def _fetch_following(location, resolver=_public):
    """Fetch a URL whose first response redirects to `location`."""
    visited = []

    def opener(url, _headers, _timeout, _proxies):
        visited.append(url)
        if len(visited) == 1:
            return _Response(302, {"Location": location})
        return _Response(200, {"Content-Type": "image/png"}, _PNG)

    result = imagefetch.fetch_once(
        "https://ok.example/x.png", opener=opener, resolver=resolver
    )
    return visited, result


@pytest.mark.parametrize(
    "location",
    [
        "http://ok.example/x.png",  # the https -> http downgrade
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "ftp://ok.example/x.png",
        "xedown-image:https%3A%2F%2Fok.example%2Fx.png",
        "https://user:password@ok.example/x.png",
        "mailto:someone@example.com",
    ],
)
def test_a_redirect_off_https_is_refused_rather_than_followed(location):
    """Every hop is re-classified, so the first hop's guarantees are the
    last hop's guarantees.

    urllib's own redirect handler permits an https -> http downgrade, which
    is why `_urllib_opener` removes it and `fetch_once` walks the chain
    itself.
    """
    visited, result = _fetch_following(location)
    assert visited == ["https://ok.example/x.png"], "the redirect was followed"
    assert result.error == imagefetch.REDIRECT_REFUSED


def test_a_redirect_into_a_private_address_is_refused():
    """Destination checking is per-hop, not just on the document's own URL."""

    def resolver(host):
        return ["127.0.0.1"] if host == "internal.example" else ["93.184.216.34"]

    visited, result = _fetch_following(
        "https://internal.example/x.png", resolver=resolver
    )
    assert visited == ["https://ok.example/x.png"]
    assert result.error == imagefetch.BLOCKED_DESTINATION


def test_an_ordinary_https_redirect_is_still_followed():
    """The refusals above are about *where*, not about redirects as such."""
    visited, result = _fetch_following("https://cdn.example/x.png")
    assert visited == ["https://ok.example/x.png", "https://cdn.example/x.png"]
    assert result.ok


def test_a_redirect_chain_is_bounded():
    visited = []

    def opener(url, _headers, _timeout, _proxies):
        visited.append(url)
        return _Response(302, {"Location": f"https://ok.example/{len(visited)}.png"})

    result = imagefetch.fetch_once(
        "https://ok.example/x.png", opener=opener, resolver=_public
    )
    assert len(visited) == remoteimages.MAX_REDIRECTS + 1
    assert result.error == imagefetch.REDIRECT_REFUSED


def test_a_redirect_with_no_location_is_refused():
    def opener(_url, _headers, _timeout, _proxies):
        return _Response(302, {})

    result = imagefetch.fetch_once(
        "https://ok.example/x.png", opener=opener, resolver=_public
    )
    assert result.error == imagefetch.REDIRECT_REFUSED


def test_a_fetch_never_carries_credentials_or_a_referer():
    """What is on the wire is the disclosure this feature exists to control."""
    captured = {}

    def opener(_url, headers, _timeout, _proxies):
        captured.update(headers)
        return _Response(200, {"Content-Type": "image/png"}, _PNG)

    imagefetch.fetch_once("https://ok.example/x.png", opener=opener, resolver=_public)
    lowered = {name.lower() for name in captured}
    assert not lowered & {"cookie", "referer", "authorization", "origin"}


# ---------------------------------------------------------------------------
# 8. Unusual image URLs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "ftp://evil.example/x.png",
        "gopher://evil.example/x.png",
        "ws://evil.example/x.png",
        "blob:https://evil.example/uuid",
        "filesystem:https://evil.example/x.png",
        "about:blank",
        "chrome://settings",
        "resource://x",
        "view-source:https://evil.example",
        "jar:https://evil.example/x.jar!/y.png",
        "//evil.example/x.png",
        "\\\\evil.example\\share\\x.png",
    ],
)
def test_an_unusual_image_scheme_does_not_produce_a_loadable_src(uri):
    assert_inert(render(f'<img src="{uri}" alt="x">'))


def test_a_document_can_never_mint_the_private_image_scheme():
    """`xedown-image:` is not in `ALLOWED_URI_SCHEMES`, and must never be.

    That is the whole reason the private scheme is safe: the page can address
    a fetch only through a URI the *renderer* produced, for an image it
    already decided was fetchable. Content writing one itself would hand a
    document the fetch path directly, around every check in
    `classify_image`.
    """
    assert remoteimages.SCHEME not in sanitizer.ALLOWED_URI_SCHEMES
    result = render(
        f'<img src="{remoteimages.SCHEME}:https%3A%2F%2Fevil.example%2Fx.png" alt="x">'
    )
    assert remoteimages.SCHEME not in result


def test_the_scheme_handler_re_checks_its_payload_rather_than_trusting_it():
    """The handler is an entry point reached with whatever is in the DOM.

    So `parse_scheme_uri` re-runs the whole classification on the decoded
    payload instead of assuming the renderer put it there.
    """
    for payload in (
        "http%3A%2F%2Fevil.example%2Fx.png",
        "file%3A%2F%2F%2Fetc%2Fpasswd",
        "javascript%3Aalert(1)",
        "data%3Atext%2Fhtml%2C%3Cscript%3E",
        "https%3A%2F%2Fuser%3Apw%40evil.example%2Fx.png",
        f"{remoteimages.SCHEME}%3Ahttps%3A%2F%2Fa.example%2Fx",
        "",
    ):
        uri = f"{remoteimages.SCHEME}:{payload}"
        assert remoteimages.parse_scheme_uri(uri) is None, uri


def test_a_private_address_is_refused_at_fetch_time_not_at_parse_time():
    """`classify_remote` never resolves DNS, and that is deliberate.

    A hostname is not an address: `2130706433`, `0x7f000001` and a name with
    a private A record all look fine as strings. So the scheme parser lets
    the *shape* through and `check_destination` refuses on the resolved
    addresses -- which is the only check that cannot be spelled around.
    """
    uri = f"{remoteimages.SCHEME}:https%3A%2F%2F127.0.0.1%2Fx.png"
    assert remoteimages.parse_scheme_uri(uri) == "https://127.0.0.1/x.png"

    def opener(_url, _headers, _timeout, _proxies):  # pragma: no cover - never called
        raise AssertionError("the fetch should not have been attempted")

    result = imagefetch.fetch_once(
        "https://127.0.0.1/x.png",
        opener=opener,
        resolver=lambda _host: ["127.0.0.1"],
    )
    assert result.error == imagefetch.BLOCKED_DESTINATION


def test_a_remote_image_is_not_addressed_at_all_without_permission():
    """The render-time gate, before any of the fetch-time ones."""
    blocked = render("![x](https://cdn.example/x.png)", fetch_remote=False)
    assert not addresses_a_fetch(blocked)
    assert "<img" not in blocked

    allowed = render("![x](https://cdn.example/x.png)", fetch_remote=True)
    assert_inert(allowed)
    assert addresses_a_fetch(allowed)


def test_the_page_is_never_granted_http_or_https_whatever_the_setting_says():
    """The independent second layer under the render-time gate.

    xedown fetches; the page never does. So `img-src` names `file:`, `data:`
    and -- only for a permitted render -- the private scheme, and never a
    network scheme in either case.
    """
    for fetch_remote in (False, True):
        page = renderer.render_document("# hi", fetch_remote=fetch_remote)
        policy = re.search(r'Content-Security-Policy" content="([^"]*)"', page).group(1)
        img_src = re.search(r"img-src ([^;]*)", policy).group(1)
        assert "http:" not in img_src and "https:" not in img_src
        assert (f"{remoteimages.SCHEME}:" in img_src) is fetch_remote


def test_an_http_image_is_never_fetched_even_when_fetching_is_permitted():
    result = render("![x](http://cdn.example/x.png)", fetch_remote=True)
    assert_inert(result)
    assert not addresses_a_fetch(result)
    assert "not encrypted" in result


def test_an_image_url_carrying_credentials_is_never_fetched():
    result = render("![x](https://user:password@cdn.example/x.png)", fetch_remote=True)
    assert not addresses_a_fetch(result)


# ---------------------------------------------------------------------------
# 9. Path traversal
# ---------------------------------------------------------------------------


@pytest.fixture
def docdir(tmp_path):
    """A document directory with a secret one level above it."""
    (tmp_path / "secret.txt").write_text("PASSWORD")
    inner = tmp_path / "doc"
    inner.mkdir()
    (inner / "ok.png").write_bytes(_PNG)
    return inner


TRAVERSALS = [
    "../secret.txt",
    "..%2Fsecret.txt",
    "....//secret.txt",
    "./../secret.txt",
    "doc/../../secret.txt",
    "../secret.txt#x",
]


@pytest.mark.parametrize("reference", TRAVERSALS)
def test_traversal_resolves_to_a_normalized_local_path_and_nothing_more(
    reference, docdir
):
    """Traversal is not a *sandbox* escape here -- there is no sandbox.

    xedown deliberately renders a local document's local references, so
    `../secret.txt` resolving upward is the feature, not the bug. What is
    tested is the part that would be a bug: the result is always a
    normalized, percent-encoded `file:` URI, never a raw string that could
    reach the page as some other scheme, and never a path the renderer failed
    to resolve at all.
    """
    result = render(f"![x]({reference})", base_dir=str(docdir))
    assert_inert(result)
    # Asserted on the emitted URIs, not the fragment: a *refusal* placeholder
    # quotes the path it could not open, so `..` legitimately appears as
    # prose in exactly the case that proves nothing was resolved.
    for uri in emitted_uris(result):
        assert uri.startswith("file://")
        assert ".." not in uri


def test_a_traversing_reference_cannot_become_a_remote_fetch(docdir):
    """The escape that would matter: a local path turning into a network one."""
    for reference in TRAVERSALS + ["../../../../../../etc/passwd"]:
        result = render(f"![x]({reference})", base_dir=str(docdir), fetch_remote=True)
        assert not addresses_a_fetch(result)
        assert all(uri.startswith("file://") for uri in emitted_uris(result))


def test_a_local_file_is_shown_not_read_into_the_document(docdir):
    """An `<img>` src is a reference WebKit resolves; the bytes are never
    inlined into the HTML by xedown.

    So a traversing reference cannot turn a file's *contents* into page text
    that a later step might treat as markup.
    """
    result = render("![x](../secret.txt)", base_dir=str(docdir))
    assert "PASSWORD" not in result


def test_a_reference_with_an_embedded_nul_is_refused_not_crashed(docdir):
    result = render("[x](a%00b)", base_dir=str(docdir))
    assert_inert(result)
    assert "<a>x</a>" in result


def test_an_unsaved_document_resolves_nothing_at_all():
    """No base directory means relative references have nowhere to go."""
    result = render("![x](../secret.txt)\n\n[y](../secret.txt)", base_dir=None)
    assert_inert(result)
    assert "file:" not in result


# ---------------------------------------------------------------------------
# 10. data: URLs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "data:text/html,<script>alert(1)</script>",
        "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
        "data:application/javascript,alert(1)",
        "data:text/xml,<x/>",
        "data:,hello",
        "data:image/svg+xml,%3Csvg/%3E",
        "data:image/svg%2bxml,%3Csvg/%3E",
        "data:text/html;image/png,<script>alert(1)</script>",
    ],
)
def test_a_non_raster_data_uri_is_refused_as_an_image_source(uri):
    assert_inert(render(f'<img src="{uri}" alt="x">'))


@pytest.mark.parametrize(
    "uri",
    [
        "data:text/html,<b>x</b>",
        # The raster case matters most, and is the one a weaker test misses:
        # `data:text/html` is refused either way, by the subtype allowlist. A
        # `data:image/png` href is refused only because `allow_data_image` is
        # false for `href` -- flipping that flag to True leaves every
        # text/html payload still refused and this one newly allowed.
        "data:image/png;base64,iVBORw0KGgo=",
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
    ],
)
def test_a_data_uri_is_refused_outright_as_a_link_destination(uri):
    """`allow_data_image` is set only for `src`, never for `href`.

    A `data:` link is a *navigation* to a document the author controls, which
    is a different question from displaying bytes as an image -- and one the
    displayable-subtype allowlist has nothing to say about.
    """
    assert not sanitizer._is_safe_uri(uri, allow_data_image=False)
    result = render(f'<a href="{uri}">click</a>')
    assert_inert(result)
    assert "data:" not in result
    assert "<a>click</a>" in result


@pytest.mark.parametrize(
    "uri",
    [
        "data:image/png;base64,iVBORw0KGgo=",
        "DATA:IMAGE/PNG;base64,iVBORw0KGgo=",
        "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
    ],
)
def test_a_raster_data_uri_is_permitted(uri):
    """The allowance this whole section is drawing a boundary around."""
    assert sanitizer._is_safe_uri(uri, allow_data_image=True)


def test_the_data_image_subtypes_are_all_raster():
    """No entry may be a document format.

    SVG is the one that matters -- it is an HTML-like, scriptable format, and
    admitting it would reopen the `<svg>`-content drop through `src=`.
    """
    for subtype in sanitizer._SAFE_DATA_IMAGE_SUBTYPES:
        assert "svg" not in subtype and "xml" not in subtype and "html" not in subtype


def test_the_declared_subtype_is_what_governs_a_data_image():
    """Pinned because it is a decision, not an oversight.

    `data:image/png;x=base64,%3Csvg/%3E` declares a raster type and carries
    SVG. The declared type is what the sanitizer checks and what WebKit uses
    to choose a decoder -- it picks by MIME, not by sniffing -- so the bytes
    reach a PNG decoder and fail there. Two further things stand behind that:
    SVG loaded through `<img>` cannot script in WebKit at all, and the page's
    CSP admits scripts only by nonce.

    The remote path is stricter (it refuses on the bytes -- see
    `test_a_fetched_image_that_is_svg_bytes_under_a_raster_type_is_refused`)
    because there, refusing costs nothing. Here it would take away inline
    images that already work, which `images._data_uri_verdict` documents as
    the worse regression.
    """
    uri = "data:image/png;x=base64,%3Csvg/%3E"
    assert sanitizer._is_safe_uri(uri, allow_data_image=True)
    decision = images.classify_image(uri, base_dir=None)
    assert decision.status == images.OK


def test_an_oversized_data_image_is_refused_before_webkit_sees_it():
    """A decode bomb never reaches the page as a URI at all."""
    header = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + (60_000).to_bytes(4, "big")
        + (60_000).to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    import base64

    uri = "data:image/png;base64," + base64.b64encode(header).decode()
    decision = images.classify_image(uri, base_dir=None)
    assert decision.status == images.TOO_LARGE_TO_DECODE

    result = render(f'<img src="{uri}" alt="x">')
    assert "data:" not in result


# ---------------------------------------------------------------------------
# 11. file: access
# ---------------------------------------------------------------------------


def test_a_file_uri_is_the_documents_own_scheme_and_stays_allowed(docdir):
    """`file:` is on the allowlist on purpose: it is how a local document
    references the picture sitting next to it."""
    result = render("![x](ok.png)", base_dir=str(docdir))
    assert_inert(result)
    assert "file://" in result


def test_a_file_uri_is_normalized_rather_than_passed_through(docdir):
    """Every emitted `file:` URI goes through `uri_for_path`.

    So what reaches the page is an absolute, percent-encoded path -- not a
    string the document chose the encoding of, which is where a second
    decoding pass somewhere downstream could disagree about what the path
    was.
    """
    result = render(f"![x](file://{docdir}/../doc/ok.png)", base_dir=str(docdir))
    assert_inert(result)
    assert ".." not in result
    assert f"file://{docdir}/ok.png" in result


def test_a_file_uri_authority_cannot_point_at_another_host(docdir):
    """`file://evil.example/share/x` must not become a network reference."""
    result = render('<a href="file://evil.example/share/x">click</a>')
    assert_inert(result)
    assert "evil.example" not in result


def test_the_page_may_load_a_local_image_but_cannot_send_anything_anywhere():
    """Why local file access in `img-src` is not an exfiltration channel.

    `default-src 'none'` denies every fetch the page could otherwise make,
    `form-action 'none'` denies submission, and scripts run only by nonce --
    so nothing in the page can read a loaded image back out or address a
    network destination with it.
    """
    policy = re.search(
        r'Content-Security-Policy" content="([^"]*)"', renderer.render_document("# hi")
    ).group(1)
    assert "default-src 'none'" in policy
    assert "form-action 'none'" in policy
    assert "base-uri 'none'" in policy
    assert "connect-src" not in policy  # nothing widens it back out
    assert re.search(r"script-src 'nonce-[^']+'", policy)
    assert re.search(r"style-src 'nonce-[^']+'", policy)


def test_a_file_link_to_an_executable_is_never_opened_without_confirmation(tmp_path):
    """Displaying is free; running is not.

    `classify_link` is what stands between a clicked link and the desktop
    handler, and a file that can run code gets a confirmation rather than a
    launch. Checked here as part of the same rule the rest of this file is
    about: the preview may show the link, it may not act on it silently.
    """
    from xedown.links import LinkAction, classify_link

    script = tmp_path / "payload.sh"
    script.write_text("#!/bin/sh\necho pwned\n")
    decision = classify_link(str(script), str(tmp_path))
    assert decision.action is LinkAction.CONFIRM_THEN_DESKTOP

    plain = tmp_path / "notes.txt"
    plain.write_text("hi")
    plain.chmod(0o755)
    assert (
        classify_link(str(plain), str(tmp_path)).action
        is LinkAction.CONFIRM_THEN_DESKTOP
    )


# ---------------------------------------------------------------------------
# The rule, over every payload at once
# ---------------------------------------------------------------------------

ALL_PAYLOADS = (
    SCRIPT_PAYLOADS
    + MALICIOUS_HTML
    + EVENT_HANDLER_PAYLOADS
    + EMBEDDING_PAYLOADS
    + SVG_PAYLOADS
    + [f'<a href="{uri}">x</a>' for uri in SCRIPTING_URLS]
    + [f'<img src="{uri}" alt="x">' for uri in SCRIPTING_URLS]
)


def _document_body(page):
    """The article's contents, with the article's own start tag removed."""
    inside = page.split('<article class="xedown-document"', 1)[1]
    return inside.split("</article>", 1)[0].split(">", 1)[1]


@pytest.mark.parametrize("permitted", [False, True])
@pytest.mark.parametrize("payload", ALL_PAYLOADS)
def test_no_payload_produces_an_executable_page(payload, permitted):
    """The whole corpus through `render_document`, in both fetch modes.

    The fragment tests above check the body `render_fragment` returns. This
    checks the *page*: a payload could in principle escape through one of the
    pieces `render_document` assembles around that body rather than through
    the body itself.

    One payload per document, deliberately -- not all of them concatenated.
    Python-Markdown treats a run of raw HTML blocks as one block, and a
    payload part-way down that opens a raw-text element (`<xmp>`, `<plaintext>`)
    makes every payload after it come out as escaped prose. Everything would
    still pass, and it would be passing because most of the corpus was never
    parsed as markup at all.
    """
    page = renderer.render_document(payload, base_dir="/tmp", fetch_remote=permitted)
    assert not errors.is_error_page(page), payload
    assert_inert(_document_body(page))


def test_a_payload_that_kills_the_render_still_produces_a_safe_page():
    """`render_document` never raises, so a failure is an error page.

    That page is assembled from `errors.py`, whose interpolations are
    escaped -- so the failure route is not a way around the allowlist.
    """
    page = renderer.render_document(
        "<script>alert(1)</script>", base_dir="/tmp", lang='"><script>alert(1)</script>'
    )
    assert "<script>alert(1)</script>" not in page
    assert html.escape('"><script>alert(1)</script>', quote=True) in page or (
        "alert(1)" not in page
    )
