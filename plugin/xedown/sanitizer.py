"""Structural HTML sanitizer.

Parses HTML and rebuilds it from an explicit allowlist. Sanitizing with regular
expressions or string replacement is not sound and is forbidden here.
"""

import html as html_module
from html.parser import HTMLParser

ALLOWED_ELEMENTS = frozenset(
    {
        "a",
        "blockquote",
        "br",
        "code",
        "del",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "img",
        "input",
        "li",
        "ol",
        "p",
        "pre",
        "s",
        "span",
        "strong",
        "sup",
        "sub",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)

# Elements whose *content* must be discarded along with the tag.
_DROP_CONTENT_ELEMENTS = frozenset({"script", "style", "svg", "math", "template"})

_VOID_ELEMENTS = frozenset({"br", "hr", "img", "input"})

_GLOBAL_ATTRIBUTES = frozenset({"id", "title"})

ALLOWED_ATTRIBUTES = {
    "a": frozenset({"href", "name"}),
    "img": frozenset({"src", "alt", "width", "height"}),
    "code": frozenset({"class"}),
    "span": frozenset({"class"}),
    "div": frozenset({"class"}),
    "li": frozenset({"class"}),
    "ul": frozenset({"class"}),
    "input": frozenset({"type", "checked", "disabled"}),
    "td": frozenset({"align", "colspan", "rowspan"}),
    "th": frozenset({"align", "colspan", "rowspan"}),
    "sup": frozenset({"class"}),
}

ALLOWED_URI_SCHEMES = frozenset({"http", "https", "mailto", "file"})

# Only these class values survive; anything else is dropped so content cannot
# reach into the plugin's own styling.
_ALLOWED_CLASS_PREFIXES = ("language-", "hljs", "task-list", "footnote", "headerlink")

# Raster image types only. "svg+xml" is deliberately excluded: SVG is itself
# an HTML-like, scriptable document format (it can carry <script>, event
# handler attributes, etc.), so letting it through the data-image allowance
# would undermine the <svg>-content-drop above via a `src="data:..."` side
# door. This is an explicit allowlist, not a denylist of "text/html" alone.
_SAFE_DATA_IMAGE_SUBTYPES = frozenset(
    {"png", "jpeg", "jpg", "gif", "webp", "avif", "bmp"}
)


def _strip_control_characters(value):
    # Control characters and whitespace are used to smuggle schemes such as
    # "java\tscript:". Removing them before scheme inspection is normalization,
    # not sanitization — the allowlist below is what actually decides.
    return "".join(ch for ch in value if ord(ch) > 0x20 and ord(ch) != 0x7F)


def _is_safe_uri(value, allow_data_image=False):
    unescaped = html_module.unescape(value or "")
    candidate = _strip_control_characters(unescaped)
    if not candidate:
        return False
    if candidate.startswith("#"):
        return True
    head, separator, _ = candidate.partition(":")
    if not separator:
        return True  # relative path
    scheme = head.lower()
    if scheme in ALLOWED_URI_SCHEMES:
        return True
    if allow_data_image and scheme == "data":
        return _is_safe_data_image_uri(candidate)
    return False


def _is_safe_data_image_uri(candidate):
    lowered = candidate.lower()
    prefix = "data:image/"
    if not lowered.startswith(prefix):
        return False
    media_subtype = lowered[len(prefix) :].split(";", 1)[0].split(",", 1)[0]
    return media_subtype in _SAFE_DATA_IMAGE_SUBTYPES


def _filter_class(value):
    kept = [
        cls
        for cls in (value or "").split()
        if any(cls.startswith(prefix) for prefix in _ALLOWED_CLASS_PREFIXES)
    ]
    return " ".join(kept)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._suppress_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENT_ELEMENTS:
            self._suppress_depth += 1
            return
        if self._suppress_depth or tag not in ALLOWED_ELEMENTS:
            return
        rendered = self._render_attributes(tag, attrs)
        if tag in _VOID_ELEMENTS:
            self.parts.append(f"<{tag}{rendered} />")
        else:
            self.parts.append(f"<{tag}{rendered}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        if tag in _DROP_CONTENT_ELEMENTS or self._suppress_depth:
            return
        if tag not in ALLOWED_ELEMENTS:
            return
        self.parts.append(f"<{tag}{self._render_attributes(tag, attrs)} />")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _DROP_CONTENT_ELEMENTS:
            if self._suppress_depth:
                self._suppress_depth -= 1
            return
        if self._suppress_depth or tag not in ALLOWED_ELEMENTS:
            return
        if tag in _VOID_ELEMENTS:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._suppress_depth:
            return
        self.parts.append(html_module.escape(data, quote=False))

    def handle_comment(self, data):
        return  # comments are never emitted

    def _render_attributes(self, tag, attrs):
        allowed = ALLOWED_ATTRIBUTES.get(tag, frozenset()) | _GLOBAL_ATTRIBUTES
        rendered = []
        seen = set()
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            if name in seen or name not in allowed:
                continue
            seen.add(name)
            value = raw_value if raw_value is not None else ""
            if name in ("href", "src"):
                if not _is_safe_uri(value, allow_data_image=(name == "src")):
                    continue
                value = _strip_control_characters(html_module.unescape(value))
            elif name == "class":
                value = _filter_class(value)
                if not value:
                    continue
            rendered.append(f'{name}="{html_module.escape(value, quote=True)}"')
        if tag == "input":
            # Task-list checkboxes are display only; never interactive.
            rendered = [a for a in rendered if not a.startswith("disabled")]
            rendered.append("disabled")
        return (" " + " ".join(rendered)) if rendered else ""


def sanitize(html):
    """Return `html` reduced to the allowlist."""
    parser = _Sanitizer()
    parser.feed(html or "")
    parser.close()
    return "".join(parser.parts)
