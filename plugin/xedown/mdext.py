"""xedown's own Markdown extensions: task lists, strikethrough, lists that
interrupt a paragraph, and a couple of CommonMark-conformance overrides
(heading hashes need a following space; ordered-list markers may end in
`)` as well as `.`).

Built by a factory rather than at import time, because these subclass types from
the vendored Markdown module, which only exists on sys.path once `vendoring` has
placed it there.
"""

import re
from typing import ClassVar
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


def make_extensions(markdown_module):
    """Return xedown's extension instances, bound to `markdown_module`."""
    Extension = markdown_module.extensions.Extension
    Treeprocessor = markdown_module.treeprocessors.Treeprocessor
    BlockProcessor = markdown_module.blockprocessors.BlockProcessor
    SimpleTagInlineProcessor = markdown_module.inlinepatterns.SimpleTagInlineProcessor
    SubstituteTagInlineProcessor = (
        markdown_module.inlinepatterns.SubstituteTagInlineProcessor
    )
    HashHeaderProcessor = markdown_module.blockprocessors.HashHeaderProcessor
    OListProcessor = markdown_module.blockprocessors.OListProcessor

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

    class ParenOListProcessor(OListProcessor):
        """CommonMark accepts `)` as well as `.` to end an ordered-list
        marker; the vendored processor only accepts `.` (task 14 / F20), so
        `1) one\\n2) two` fell through to a single paragraph instead of an
        `<ol>`.

        `markdown.extensions.sane_lists` (loaded via
        `vendoring.MARKDOWN_EXTENSIONS`, ahead of xedown's own extensions in
        the list `Markdown()` is built with) already replaces the vendored
        `olist` with one that sets `SIBLING_TAGS = ['ol']` (so a `ul`
        followed by an `ol` across a blank line stays two lists, not one
        merged list) and `LAZY_OL = False` (an explicit start number
        survives into `start=`), and narrows `CHILD_RE` to drop the
        `[*+-]` alternative. Registering under the same name replaces
        `sane_lists`' processor outright, so subclassing the *plain*
        vendored `OListProcessor` would silently lose all three -- as
        confirmed by `test_fragment_renders_core_markdown` in
        `test_renderer.py`, which merged a trailing `1. first` into the
        preceding `ul` before this was caught. Reproducing them here is
        what keeps the previous behaviour instead of quietly reverting it.

        `INDENT_RE` is untouched by `sane_lists` and keeps the vendored
        default's `[*+-]` alternation for detecting a nested item of either
        type; `[.)]` is added there too, for the same reason it is added
        everywhere else here.
        """

        SIBLING_TAGS: ClassVar = ["ol"]
        LAZY_OL = False

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
        ListInterruptExtension(),
    ]
