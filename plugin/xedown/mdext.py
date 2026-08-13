"""xedown's own Markdown extensions: task lists, strikethrough, lists that
interrupt a paragraph, and a handful of CommonMark-conformance overrides
(heading hashes need a following space; ordered-list markers may end in
`)` as well as `.`; fenced code accepts an indented fence and a real info
string instead of only a bare word).

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


def fence_lang(info):
    """The language class for a fence's info string, or None.

    The remainder of the info string (`no_run`, `title="x"`) is free text a
    doc tool reads for its own purposes; xedown does not understand it and
    discards it rather than emitting it.
    """
    if not info:
        return None
    match = _FENCE_LANG_TOKEN.match(info.strip())
    return match.group(0) if match else None


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
# (fenced_code.py:56-67), widened in exactly two ways:
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
# The vendored `{attrs}` and bare `hl_lines="..."` branches are dropped
# rather than carried forward: nothing in the fixtures or the audit corpus
# uses either, and the info-string rule above already says what happens to
# text after the language -- it is read, not re-parsed.
_FENCED_BLOCK_RE = re.compile(
    r"""
    ^(?P<indent>[ ]{0,3})(?P<fence>~{3,}|`{3,})[ ]*  # opening fence
    (?P<info>[^\n]*)\n                                # info string, to end of line
    (?P<code>.*?)(?<=\n)                              # the code block
    [ ]{0,3}(?P=fence)[ ]*$                           # closing fence
    """,
    re.MULTILINE | re.DOTALL | re.VERBOSE,
)


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
        `vendoring.MARKDOWN_EXTENSIONS`), and `AttrListExtension`, though
        loaded, only ever flips a boolean the vendored `run` reads back on
        itself. There is nothing installed on the vendored class for a
        subclass to lose by not inheriting from it.
        """

        def run(self, lines):
            text = "\n".join(lines)
            index = 0
            while True:
                m = _FENCED_BLOCK_RE.search(text, index)
                if m is None:
                    break
                lang = fence_lang(m.group("info"))
                code = _dedent_fence_body(m.group("code"), len(m.group("indent")))
                code = code_escape(code)
                class_attr = (
                    f' class="language-{escape_attrib_html(lang)}"' if lang else ""
                )
                html = f"<pre><code{class_attr}>{code}</code></pre>"
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
        ListInterruptExtension(),
    ]
