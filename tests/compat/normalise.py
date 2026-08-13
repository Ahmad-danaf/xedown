"""Canonical form for comparing two renderings of the same document.

A raw diff of two HTML strings drowns in cosmetic difference: attribute
order, void-element spelling, entity choice, whitespace between blocks.
None of that is a compatibility finding. This module reduces both sides to
a form where equality means "these say the same thing", so that what
survives a diff is worth a human's attention.

The hard constraint is the opposite of the obvious one: it must not
normalise so hard that real differences vanish. Every rule here is
narrow and named for what it forgives.
"""

import pathlib
import re
from html.parser import HTMLParser

# Inside these, whitespace IS content and collapsing it would hide a real
# rendering difference.
PRESERVE_WHITESPACE_TAGS = frozenset({"pre", "code"})

_VOID_TAGS = frozenset({"br", "hr", "img", "input", "col"})

# Attributes xedown adds that cmark-gfm has no reason to produce. Ignoring
# them is not charity to xedown -- an `id` the toc extension generates is
# not a compatibility claim, and triaging thirty of them per document would
# bury the findings that matter.
_IGNORED_ATTRIBUTES = frozenset({"id"})

# Class tokens that are xedown's own machinery rather than document
# content. `language-*` is deliberately NOT here: a code block losing its
# language IS a finding.
_IGNORED_CLASS_TOKENS = ("hljs", "headerlink", "footnote-backref")

_WHITESPACE = re.compile(r"\s+")


class _Canonicaliser(HTMLParser):
    def __init__(self, base_dir=None):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._preserve_depth = 0
        self._base_prefix = None
        if base_dir:
            resolved = pathlib.Path(base_dir).resolve()
            self._base_prefix = resolved.as_uri().rstrip("/") + "/"

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        self.parts.append(f"<{tag}{self._render(attrs)}>")
        if tag in PRESERVE_WHITESPACE_TAGS:
            self._preserve_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.parts.append(f"<{tag.lower()}{self._render(attrs)}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in PRESERVE_WHITESPACE_TAGS and self._preserve_depth:
            self._preserve_depth -= 1
        if tag in _VOID_TAGS:
            # Void elements are emitted once by handle_starttag; a stray
            # </br> from either renderer must not become a difference.
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._preserve_depth:
            self.parts.append(data)
            return
        collapsed = _WHITESPACE.sub(" ", data)
        if collapsed.strip() == "":
            # Whitespace that only separates blocks carries no meaning.
            # One space, so `a <em>b</em>` does not equal `a<em>b</em>`.
            if collapsed:
                self.parts.append(" ")
            return
        self.parts.append(collapsed)

    def handle_comment(self, data):
        return

    def _render(self, attrs):
        kept = {}
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower()
            if name in _IGNORED_ATTRIBUTES:
                continue
            value = raw_value if raw_value is not None else ""
            if name == "class":
                value = self._filter_class(value)
                if not value:
                    continue
            elif name in ("href", "src"):
                value = self._relativise(value)
            kept[name] = value
        return "".join(f' {name}="{kept[name]}"' for name in sorted(kept))

    @staticmethod
    def _filter_class(value):
        tokens = [
            token
            for token in (value or "").split()
            if not any(token.startswith(prefix) for prefix in _IGNORED_CLASS_TOKENS)
        ]
        return " ".join(sorted(tokens))

    def _relativise(self, value):
        """Undo xedown's base-directory resolution so both sides match.

        xedown turns `a.md` into `file:///docs/a.md`; cmark leaves it as
        written. Mapping the absolute form back is the only way a link
        comparison says anything about compatibility rather than about
        which renderer resolves URIs.
        """
        if self._base_prefix and value.startswith(self._base_prefix):
            return value[len(self._base_prefix) :]
        return value


def canonicalise(html, base_dir=None):
    """Return a canonical string form of `html`, for equality comparison."""
    parser = _Canonicaliser(base_dir=base_dir)
    parser.feed(html or "")
    parser.close()
    return "".join(parser.parts).strip()
