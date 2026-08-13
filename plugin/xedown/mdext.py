"""xedown's own Markdown extensions: task lists, strikethrough, lists that
interrupt a paragraph, and a handful of CommonMark-conformance overrides
(heading hashes need a following space; ordered-list markers may end in
`)` as well as `.`; fenced code accepts an indented fence and a real info
string instead of only a bare word; list content is re-indented from
CommonMark's continuation column onto the fixed four-space nesting the
vendored list processors insist on).

Built by a factory rather than at import time, because these subclass types from
the vendored Markdown module, which only exists on sys.path once `vendoring` has
placed it there.
"""

import importlib
import re
from xml.etree.ElementTree import Element

# Matches a leading task marker only at the very start of a list item's text.
_TASK_MARKER = re.compile(r"^\[([ xX])\]\s+")

_STRIKETHROUGH_PATTERN = r"(~{2})(.+?)~{2}"

# A backslash immediately followed by a newline is a hard line break in
# CommonMark, the same as two trailing spaces (the vendored `linebreak`
# pattern, `LINE_BREAK_RE = r'  \n'`, already handles that spelling). The
# vendored `escape` inline pattern (priority 180, `ESCAPE_RE = r'\\(.)'`
# compiled with `re.DOTALL`) runs first and *does* match a backslash before
# a newline, but declines it -- `\n` is not in `Markdown.ESCAPED_CHARS` --
# which leaves the raw "\\\n" text untouched for this pattern to claim at a
# lower priority. A backslash that escapes another backslash
# (`"a\\\\\nb"`) is consumed whole by `escape` before this pattern ever
# sees it, so that case is unaffected.
_BACKSLASH_BREAK_PATTERN = r"\\\n"

# A list marker allowed to interrupt a paragraph: up to three spaces of
# indent, then `-`, `*`, `+`, `1.` or `1)`, then a space and real content.
#
# `1.`/`1)` rather than `\d+[.)]` is GFM's own rule, and it is what keeps
# prose that wraps onto a line starting with a number ("...was\n1985. What a
# year.") a paragraph rather than an `<ol start="1985">`. `1)` was added
# alongside `1.` for the same reason and under the same restriction (task 14 /
# F20) -- CommonMark accepts both spellings of an ordered marker, and
# "1985) what a year" must stay prose exactly as "1985. what a year" does.
# The lookahead is GFM's rule that an empty list item cannot interrupt.
# Three spaces is the tolerance the vendored list processors already use.
_INTERRUPTING_MARKER = re.compile(r"^[ ]{0,3}(?:[*+-]|1[.)])[ ]+(?=\S)")


def find_list_interrupt(block):
    """Index of the first line in `block` that starts a list, or None.

    Line 0 is never a candidate: a block that *begins* with a list marker is
    already a list, and this only ever looks for a list interrupting text
    above it.
    """
    lines = block.split("\n")
    for index, line in enumerate(lines[1:], 1):
        if _INTERRUPTING_MARKER.match(line):
            return index
    return None


# A list item exactly as the vendored list processors define one: a marker,
# then at least one space, then real content. Deliberately *not* wider than
# they are -- a content-less marker (`-` alone on a line) is a list item in
# CommonMark but not to `OListProcessor.RE`, and treating it as one here
# would open a level of nesting the parser downstream refuses to enter, and
# swallow the sub-items into a paragraph (task 15 / F5).
_LIST_ITEM = re.compile(
    r"^(?P<indent>[ ]*)(?P<marker>[*+-]|\d{1,9}[.)])(?P<gap>[ ]+)(?=\S)"
)

# A thematic break, which outranks a list item in CommonMark and is claimed
# at priority 50 by `HRProcessor` here -- the same shape as its own
# `SEARCH_RE`, anchored to one line because that is all this pass has. The
# v0.2 design could say "we never have to tell `---` from `- - -`, because
# we are never shown any of them"; that holds at priority 12 and not in a
# preprocessor. `- - -` is a marker, a space and content to the regex above,
# and treating it as an item would indent a rule into a literal `- -` list.
_THEMATIC_BREAK = re.compile(
    r"^[ ]{0,3}(?=(?P<run>(-+[ ]{0,2}){3,}|(_+[ ]{0,2}){3,}|(\*+[ ]{0,2}){3,}))"
    r"(?P=run)[ ]*$"
)

# The markers GFM lets a list use to interrupt a paragraph -- the same rule
# `_INTERRUPTING_MARKER` above encodes, needed again here as a set because
# this pass has already matched the marker and only has to classify it. A
# marker that cannot interrupt is prose that happens to look like a marker
# ("...was\n1985. What a year."), and must not open an item.
_INTERRUPTING_MARKERS = frozenset({"-", "*", "+", "1.", "1)"})


def normalize_list_indentation(lines, tab_length=4):
    """Re-indent list content onto `tab_length`-per-level nesting.

    CommonMark nests by *continuation column*: content indented to where the
    parent item's own content starts belongs to that item, so `- Flask` /
    `  - apiflask` is a sublist. The vendored parser nests by a fixed
    `tab_length` instead -- `ListIndentProcessor` tests
    `block.startswith(' ' * tab_length)` and `OListProcessor.CHILD_RE`
    accepts a marker at 0-3 spaces as a *sibling* -- so a two-space sublist
    is flattened into its parent (task 15 / F5) and content indented past
    the continuation column, but under the four spaces the parser wants, is
    left as literal text (F6). `tab_length=2` is not the fix: it would read
    one four-space indent as two levels.

    This pass is the translation between the two models, and it rewrites
    nothing but leading whitespace. An item's marker line moves to
    `tab_length * (depth - 1)`; a block of its own inside that item moves to
    `tab_length * depth`, carrying any offset of four or more columns past
    the continuation column, since that offset is a code block's indent and
    is content. Every other line stays exactly where it was written, bar the
    one exception the hazards below name. A document that already indents
    `tab_length` per level comes through byte-identical.

    It runs as a preprocessor rather than a block processor because the
    decision needs the whole document's line-by-line list nesting, which no
    single block carries. That is the position the v0.2 design
    (`docs/superpowers/specs/2026-08-10-xedown-v0.2-gfm-lists-design.md`,
    section 4) names as the trap, and the trap is closed here by *where in
    the preprocessor chain this sits* rather than by re-deriving structure:
    at priority 18 both stashing preprocessors have already run, so a fenced
    code block (`fenced_code_block`, 25) and a raw HTML block (`html_block`,
    20) have been lifted out into the HTML stash and replaced by
    placeholders before this sees a single line. Indentation that is content
    is not text this pass declines to touch; by the time it runs, it is not
    text.

    Two hazards remain that indentation alone can spring, and both are
    closed by narrowness rather than by inspection:

    - A line that is *not* a marker keeps its own indentation, except for a
      blockquote marker (F6's case) and except in a block of its own. A
      tight item's continuation lines are handed to the parser raw --
      `OListProcessor.get_items` appends them without dedenting -- so moving
      one changes which block processor claims the *whole* block. Dedenting
      `  ---` under `- a` would turn a list and a rule into an `<h2>` whose
      text is `- a`; dedenting `  # x` would lift the heading out of the
      item. A `>` line can be claimed by nothing above `quote` (20) that it
      could not be claimed by already, which is what makes it the one safe
      exception -- and the useful one, since `BlockQuoteProcessor.RE`
      tolerates exactly three spaces.
    - An over-indented line stays over-indented. Four or more spaces past
      the continuation column is indented code in CommonMark, and code
      cannot interrupt a paragraph, so such a line is prose that must not be
      pulled down into `OListProcessor.INDENT_RE`'s four-to-seven-space
      window and turned into a nested item.
    """
    out = []
    # The source content column of every open list item, outermost first.
    open_items = []
    after_blank = True  # the start of the document behaves like a blank line
    after_marker = False
    own_block = False  # this block began after a blank line, not on a marker
    for line in lines:
        if not line.strip():
            out.append(line)
            after_blank = True
            after_marker = False
            continue
        indent = len(line) - len(line.lstrip(" "))
        # The items this line is still inside, by indentation alone.
        depth = len(open_items)
        while depth and indent < open_items[depth - 1]:
            depth -= 1
        column = open_items[depth - 1] if depth else 0
        match = _LIST_ITEM.match(line)
        is_item = (
            match is not None
            # At four spaces past the continuation column the line is
            # indented code, and code never opens a list item.
            and indent < column + tab_length
            and _THEMATIC_BREAK.match(line) is None
            and (
                after_blank
                or after_marker
                or match.group("marker") in _INTERRUPTING_MARKERS
            )
        )
        if not is_item and not after_blank and depth < len(open_items):
            # Lazy continuation: too far left for the item it continues, but
            # a paragraph is open, so the item does not close and the line
            # keeps the indentation the parser already handles correctly.
            out.append(line)
            after_marker = False
            after_blank = False
            continue
        del open_items[depth:]
        if is_item:
            open_items.append(
                indent + len(match.group("marker")) + len(match.group("gap"))
            )
            out.append(" " * (tab_length * depth) + line[indent:])
            own_block = False
        else:
            if after_blank:
                own_block = True
            offset = indent - column
            if not depth:
                out.append(line)
            elif own_block:
                # A block of its own inside the item: `ListIndentProcessor`
                # will dedent it by `tab_length * depth`, so put it there.
                # An offset of one to three columns past the continuation
                # column is insignificant to every block construct, and
                # dropping it is what keeps a document that already indents
                # `tab_length` per level byte-identical through this pass.
                # Four or more is the indent of a code block and is content,
                # so it is carried through.
                carried = offset if offset >= tab_length else 0
                out.append(" " * (tab_length * depth + carried) + line[indent:])
            elif offset < tab_length and line[indent] == ">":
                out.append(" " * (tab_length * (depth - 1) + offset) + line[indent:])
            else:
                out.append(line)
        after_marker = is_item
        after_blank = False
    return out


# The language class for a fenced code block is the first whitespace- or
# comma-delimited token of its info string (task 13 / F2). "```rust,no_run"
# and "```js title=\"x\"" are ordinary doc-tool info strings -- GFM defines
# only the first word as the language name, and the vendored
# `FENCED_BLOCK_RE` (fenced_code.py:58) narrows that further, to a single
# *bare* word: a comma, a space or a brace anywhere in the info string makes
# the *whole opening-fence match* fail, so the fence never opens at all. The
# closing fence is then left unmatched, and goes on to open one of its own
# for whatever follows -- the desynchronisation this task exists to stop.
_FENCE_LANG_TOKEN = re.compile(r"[^\s,]+")

# The shape the vendored fence regex used to require of the *entire* info
# string, now used the other way around: as a check on the one token pulled
# out of it. `class="language-..."` reaches the rendered page unexamined --
# `sanitizer._ALLOWED_CLASS_PREFIXES` is a prefix check for blocking style
# injection, not a semantic validator, and is not the layer that catches a
# malformed token. A token that fails this (a stray `{` left over from an
# unclosed attribute list, an embedded quote, ...) gets no class at all,
# not an escaped-but-nonsensical one: cmark-gfm's *raw* output would put it
# in `lang=` on `<pre>`, but `lang` is not an attribute the sanitizer allows
# there, so cmark's *sanitized* output -- the audit's actual yardstick --
# has nothing at all in that case either.
_PLAUSIBLE_LANG = re.compile(r"[\w#.+-]+")


def _plausible_lang(token):
    """Whether `token` looks like a language identifier at all."""
    return bool(token) and _PLAUSIBLE_LANG.fullmatch(token) is not None


def fence_lang(info):
    """The language class for a fence's info string, or None.

    The remainder of the info string (`no_run`, `title="x"`) is free text a
    doc tool reads for its own purposes; xedown does not understand it and
    discards it rather than emitting it. Also None if the first token
    itself is not a plausible language identifier -- see `_plausible_lang`.
    """
    if not info:
        return None
    match = _FENCE_LANG_TOKEN.match(info.strip())
    if match is None:
        return None
    token = match.group(0)
    return token if _plausible_lang(token) else None


def _dedent_fence_body(code, width):
    """Strip up to `width` leading spaces from each line of a fence body.

    CommonMark strips the opening fence's own indentation (0-3 spaces, task
    13 / F3) from every content line, capped per line at however much
    leading whitespace that particular line actually has -- a shorter line
    never goes negative.
    """
    if not width:
        return code
    stripped = []
    for line in code.split("\n"):
        cut = 0
        while cut < width and cut < len(line) and line[cut] == " ":
            cut += 1
        stripped.append(line[cut:])
    return "\n".join(stripped)


# Same shape as the vendored `FencedBlockPreprocessor.FENCED_BLOCK_RE`
# (fenced_code.py:56-67), widened in one way and narrowed in another:
#
#  - `(?P<indent>[ ]{0,3})` in front of the fence -- CommonMark tolerates up
#    to three leading spaces on both the opening and the closing fence, the
#    same tolerance the vendored list processors already use elsewhere in
#    this file (task 13 / F3). Four or more stays indented code: at four
#    spaces, `[ ]{0,3}` can consume at most three, which always leaves at
#    least one space directly in front of the fence characters, so the
#    match fails there regardless of how the group backtracks.
#  - `(?P<info>[^\n]*)` in place of `(\.?(?P<lang>[\w#.+-]*)[ ]*)?` -- any
#    text is now a valid info string, not just a bare word. `fence_lang`
#    above pulls the language out of it afterwards.
#
# The `{attrs}` branch is carried forward unchanged (same group name and
# position as the vendored regex) because it is live, not dead: `attr_list`
# is loaded (`vendoring.MARKDOWN_EXTENSIONS`) and "```{.python #myid}" is
# how a document sets an id on a fenced block. Without this branch, the
# widened `info` alternative below would swallow the whole "{.python #myid}"
# as info-string text instead, and its first token -- "{.python", not a
# plausible language identifier -- would previously have surfaced as a
# malformed class (`_plausible_lang` now blocks that too, independently).
#
# The bare `hl_lines="..."` branch (outside of `{attrs}`) is the one piece
# actually dropped rather than carried forward: grepped `renderer.py`,
# `preview.js`, `preview.css` and the highlight.js bundle build script for a
# consumer and found none anywhere in xedown -- genuinely dead code here.
_FENCED_BLOCK_RE = re.compile(
    r"""
    ^(?P<indent>[ ]{0,3})(?P<fence>~{3,}|`{3,})[ ]*  # opening fence
    ((\{(?P<attrs>[^\n]*)\})|(?P<info>[^\n]*))        # {attrs}, or an info string
    \n                                                # newline (end of opening fence)
    (?P<code>.*?)(?<=\n)                              # the code block
    [ ]{0,3}(?P=fence)[ ]*$                           # closing fence
    """,
    re.MULTILINE | re.DOTALL | re.VERBOSE,
)


def _handle_fence_attrs(attrs):
    """Pull an id and a class list out of a `{...}` attribute list.

    A narrowed `FencedBlockPreprocessor.handle_attrs` (fenced_code.py:165):
    `hl_lines`/pygments/bool-option keys are dropped along with the rest of
    that dead branch (see `_FENCED_BLOCK_RE` above) rather than carried
    forward. Any other key/value pair (`{data-x=1}`) is silently ignored,
    the same as the vendored preprocessor does whenever `attr_list` itself
    is not loaded to render it as a key/value pair on the tag.
    """
    id_value = None
    classes = []
    for key, value in attrs:
        if key == "id":
            id_value = value
        elif key == ".":
            classes.append(value)
    return id_value, classes


def make_extensions(markdown_module):
    """Return xedown's extension instances, bound to `markdown_module`."""
    Extension = markdown_module.extensions.Extension
    Treeprocessor = markdown_module.treeprocessors.Treeprocessor
    BlockProcessor = markdown_module.blockprocessors.BlockProcessor
    Preprocessor = markdown_module.preprocessors.Preprocessor
    SimpleTagInlineProcessor = markdown_module.inlinepatterns.SimpleTagInlineProcessor
    SubstituteTagInlineProcessor = (
        markdown_module.inlinepatterns.SubstituteTagInlineProcessor
    )
    HashHeaderProcessor = markdown_module.blockprocessors.HashHeaderProcessor
    code_escape = markdown_module.util.code_escape
    escape_attrib_html = markdown_module.serializers._escape_attrib_html
    # `markdown_module.extensions.sane_lists` is not yet an attribute of the
    # `extensions` package at this point -- nothing has imported that
    # submodule yet, since `make_extensions` runs *before* the `Markdown()`
    # call that would load it as one of `vendoring.MARKDOWN_EXTENSIONS`.
    # `importlib.import_module`, keyed off `markdown_module.__name__` (which
    # is already the vendored package, resolved once by
    # `vendoring.import_markdown()`), reaches the same vendored submodule
    # without a bare top-level `import markdown...` in this file -- which
    # would risk resolving to a non-vendored copy if this module happened to
    # be imported before the vendoring guard runs.
    SaneOListProcessor = importlib.import_module(
        f"{markdown_module.__name__}.extensions.sane_lists"
    ).SaneOListProcessor
    # Same reasoning as `SaneOListProcessor` above: `attr_list` is one of
    # `vendoring.MARKDOWN_EXTENSIONS`, but not yet imported as a submodule
    # at this point, since that only happens once `Markdown()` itself loads
    # it -- after `make_extensions` has already returned.
    get_attrs_and_remainder = importlib.import_module(
        f"{markdown_module.__name__}.extensions.attr_list"
    ).get_attrs_and_remainder

    class TaskListTreeprocessor(Treeprocessor):
        def run(self, root):
            for parent in root.iter():
                if parent.tag not in ("ul", "ol"):
                    continue
                converted = False
                for item in list(parent):
                    if item.tag != "li":
                        continue
                    if self._convert_item(item):
                        converted = True
                if converted:
                    self._add_class(parent, "task-list")

        def _convert_item(self, item):
            text = item.text or ""
            match = _TASK_MARKER.match(text)
            if match is None:
                return False
            checkbox = Element("input")
            checkbox.set("type", "checkbox")
            checkbox.set("disabled", "disabled")
            if match.group(1) in ("x", "X"):
                checkbox.set("checked", "checked")
            remainder = text[match.end() :]
            item.text = ""
            item.insert(0, checkbox)
            checkbox.tail = remainder
            self._add_class(item, "task-list-item")
            return True

        @staticmethod
        def _add_class(element, name):
            existing = element.get("class", "")
            names = existing.split()
            if name not in names:
                names.append(name)
            element.set("class", " ".join(names))

    class TaskListExtension(Extension):
        def extendMarkdown(self, md):
            md.treeprocessors.register(TaskListTreeprocessor(md), "xedown_tasklist", 25)

    class StrikethroughExtension(Extension):
        def extendMarkdown(self, md):
            md.inlinePatterns.register(
                SimpleTagInlineProcessor(_STRIKETHROUGH_PATTERN, "del"),
                "xedown_strikethrough",
                175,
            )

    class BackslashBreakExtension(Extension):
        def extendMarkdown(self, md):
            md.inlinePatterns.register(
                SubstituteTagInlineProcessor(_BACKSLASH_BREAK_PATTERN, "br"),
                "xedown_backslash_break",
                170,
            )

    class SpacedHashHeaderProcessor(HashHeaderProcessor):
        """CommonMark requires a space (or end of line) after the `#`
        markers; the vendored regex has no such requirement, so `#NoSpace`
        becomes an `<h1>` and `####### Seven` becomes an `<h6>` with a
        literal `#` left in its text (task 12 / F9, F10).

        `test` and `run` are inherited unchanged from the vendored
        processor -- both just use `self.RE` -- so overriding `RE` alone is
        enough. `[ ]+` is required after the hashes, except when they run
        straight into the end of the line: a bare `#` (or `###` alone) is a
        valid, empty ATX heading in CommonMark, and must keep rendering as
        one.
        """

        RE = re.compile(
            r"(?:^|\n)(?P<level>#{1,6})(?:[ ]+|(?=\n|$))"
            r"(?P<header>(?:\\.|[^\\])*?)#*(?:\n|$)"
        )

    class HashHeaderOverrideExtension(Extension):
        def extendMarkdown(self, md):
            # Same name and priority as the vendored processor it replaces
            # (`Registry.register` swaps an existing name in place), so it
            # sits exactly where `hashheader` already sat in the chain.
            md.parser.blockprocessors.register(
                SpacedHashHeaderProcessor(md.parser), "hashheader", 70
            )

    class ParenOListProcessor(SaneOListProcessor):
        """CommonMark accepts `)` as well as `.` to end an ordered-list
        marker; the vendored processor only accepts `.` (task 14 / F20), so
        `1) one\\n2) two` fell through to a single paragraph instead of an
        `<ol>`.

        `markdown.extensions.sane_lists` (loaded via
        `vendoring.MARKDOWN_EXTENSIONS`, ahead of xedown's own extensions in
        the list `Markdown()` is built with) already replaces the vendored
        `olist` with `SaneOListProcessor`, which sets `SIBLING_TAGS = ['ol']`
        (so a `ul` followed by an `ol` across a blank line stays two lists,
        not one merged list), `LAZY_OL = False` (an explicit start number
        survives into `start=`), and narrows `CHILD_RE` to drop the `[*+-]`
        alternative. Registering under the same name replaces that processor
        outright, so this subclasses `SaneOListProcessor` itself rather than
        the plain vendored `OListProcessor` -- inheriting `SIBLING_TAGS` and
        `LAZY_OL` instead of copying them, so a change to `sane_lists` at the
        next re-vendor is picked up automatically rather than silently going
        stale. An earlier version of this fix *did* copy them, and lost both
        without any local test catching it -- only
        `test_fragment_renders_core_markdown` in `test_renderer.py`, which
        merged a trailing `1. first` into a preceding `ul`, three files away
        from this one.

        Only `RE`, `CHILD_RE` and `INDENT_RE` are widened for `)` here, since
        those are the three `sane_lists` does not claim ownership of by
        inheritance alone: `CHILD_RE` is `SaneOListProcessor`'s own
        (narrower, no `[*+-]`) shape with `[.)]` substituted for the literal
        `\\.`; `RE` and `INDENT_RE` are genuinely untouched by `sane_lists`
        and keep rebuilding the vendored `OListProcessor` defaults (the
        latter still with its `[*+-]` alternation, for detecting a nested
        item of either type) with the same substitution.
        """

        def __init__(self, parser):
            super().__init__(parser)
            indent = self.tab_length - 1
            self.RE = re.compile(rf"^[ ]{{0,{indent}}}\d+[.)][ ]+(.*)")
            self.CHILD_RE = re.compile(rf"^[ ]{{0,{indent}}}((\d+[.)]))[ ]+(.*)")
            self.INDENT_RE = re.compile(
                rf"^[ ]{{{self.tab_length},{self.tab_length * 2 - 1}}}"
                r"((\d+[.)])|[*+-])[ ]+.*"
            )

    class ParenOListExtension(Extension):
        def extendMarkdown(self, md):
            # Same name and priority as the vendored `olist` it replaces.
            md.parser.blockprocessors.register(
                ParenOListProcessor(md.parser), "olist", 40
            )

    class FencedCodePreprocessor(Preprocessor):
        """Recognise the fences `_FENCED_BLOCK_RE` widens the vendored
        preprocessor to accept (task 13 / F2, F3).

        Registered under the same name and priority as the vendored
        `FencedBlockPreprocessor` ("fenced_code_block", 25), so
        `Registry.register` swaps it in place rather than adding a second
        preprocessor. This is a fresh `Preprocessor`, not a subclass of the
        vendored one: introspecting the assembled `Markdown()` pipeline
        (`md.preprocessors` and `md.registeredExtensions`) shows nothing
        narrows or wraps `FencedBlockPreprocessor` the way `sane_lists`
        narrows `OListProcessor` -- `md.preprocessors` holds it under this
        name and no other, `CodeHiliteExtension` is never loaded (not in
        `vendoring.MARKDOWN_EXTENSIONS`), and `AttrListExtension` registers
        only its own treeprocessor (priority 8, for `{: #id .class}` after
        headings and the like) -- it never touches the preprocessor this
        replaces. There is nothing installed on the vendored class for a
        subclass to lose by not inheriting from it; `get_attrs_and_remainder`
        below is `attr_list`'s own parser for `{...}` text, reused directly
        rather than reimplemented, which is a different thing from
        inheriting the class.
        """

        def run(self, lines):
            text = "\n".join(lines)
            index = 0
            while True:
                m = _FENCED_BLOCK_RE.search(text, index)
                if m is None:
                    break
                if m.group("attrs") is not None:
                    attrs, remainder = get_attrs_and_remainder(m.group("attrs"))
                    if remainder:
                        # Malformed `{...}` syntax -- explicitly skip over
                        # it, the same way the vendored preprocessor does,
                        # so the next search doesn't just find the same
                        # broken match again.
                        index = m.end("attrs")
                        continue
                    id_value, classes = _handle_fence_attrs(attrs)
                    lang = classes[0] if classes else None
                    if lang is not None and not _plausible_lang(lang):
                        lang = None
                else:
                    id_value = None
                    lang = fence_lang(m.group("info"))
                code = _dedent_fence_body(m.group("code"), len(m.group("indent")))
                code = code_escape(code)
                id_attr = f' id="{escape_attrib_html(id_value)}"' if id_value else ""
                class_attr = (
                    f' class="language-{escape_attrib_html(lang)}"' if lang else ""
                )
                html = f"<pre{id_attr}><code{class_attr}>{code}</code></pre>"
                placeholder = self.md.htmlStash.store(html)
                text = f"{text[:m.start()]}\n{placeholder}\n{text[m.end():]}"
                # Continue from after the replaced text, same as the
                # vendored preprocessor -- an index inside the old match
                # would loop.
                index = m.start() + 1 + len(placeholder)
            return text.split("\n")

    class FencedCodeOverrideExtension(Extension):
        def extendMarkdown(self, md):
            # Same name and priority as the vendored `fenced_code_block` it
            # replaces.
            md.preprocessors.register(
                FencedCodePreprocessor(md), "fenced_code_block", 25
            )

    class ListIndentationPreprocessor(Preprocessor):
        """Run `normalize_list_indentation` over the document's lines.

        A fresh `Preprocessor` under a name of xedown's own, registered at
        18. Introspecting the assembled `Markdown()` pipeline shows
        `md.preprocessors` holding exactly three entries --
        `normalize_whitespace` (30), xedown's own `fenced_code_block` (25)
        and `html_block` (20) -- so 18 is below every one of them and this
        pass is the last thing to touch the raw lines. That order is the
        design, not a free choice: `normalize_whitespace` has already
        expanded tabs (so a column count is a space count), and the two
        stashing preprocessors have already removed the text whose
        indentation is content. `tab_length` is read off the `Markdown`
        instance rather than assumed, since it is what every vendored list
        processor builds its own regexes from.
        """

        def run(self, lines):
            return normalize_list_indentation(lines, self.md.tab_length)

    class ListIndentationExtension(Extension):
        def extendMarkdown(self, md):
            md.preprocessors.register(
                ListIndentationPreprocessor(md), "xedown_list_indent", 18
            )

    class ListInterruptProcessor(BlockProcessor):
        """Split a paragraph block where a list starts inside it.

        Registered below every other block processor and just above
        `paragraph`, so every block it is offered has already been declined
        by `setextheader`, `hr`, `olist`, `ulist` and the rest: priority 12
        guarantees that no existing heading, rule, fence, indented code
        block, table or nested list is ever destroyed by this processor,
        which is also what makes a first-line guard against blocks that are
        already lists unnecessary. It does not guarantee what happens to the
        lower half `run` pushes back onto the queue: that half re-enters the
        chain at priority 100, where a processor registered above 12 can
        still claim it.
        """

        def test(self, parent, block):
            return find_list_interrupt(block) is not None

        def run(self, parent, blocks):
            block = blocks.pop(0)
            lines = block.split("\n")
            index = find_list_interrupt(block)
            # The half above the split has no interrupting marker left in it
            # by construction, so `test` declines it and `paragraph` takes it.
            self.parser.parseBlocks(parent, ["\n".join(lines[:index])])
            blocks.insert(0, "\n".join(lines[index:]))

    class ListInterruptExtension(Extension):
        def extendMarkdown(self, md):
            md.parser.blockprocessors.register(
                ListInterruptProcessor(md.parser), "xedown_list_interrupt", 12
            )

    return [
        TaskListExtension(),
        StrikethroughExtension(),
        BackslashBreakExtension(),
        HashHeaderOverrideExtension(),
        ParenOListExtension(),
        FencedCodeOverrideExtension(),
        ListIndentationExtension(),
        ListInterruptExtension(),
    ]
