"""xedown's own Markdown extensions: task lists, strikethrough, and
lists that interrupt a paragraph.

Built by a factory rather than at import time, because these subclass types from
the vendored Markdown module, which only exists on sys.path once `vendoring` has
placed it there.
"""

import re
from xml.etree.ElementTree import Element

# Matches a leading task marker only at the very start of a list item's text.
_TASK_MARKER = re.compile(r"^\[([ xX])\]\s+")

_STRIKETHROUGH_PATTERN = r"(~{2})(.+?)~{2}"

# A list marker allowed to interrupt a paragraph: up to three spaces of
# indent, then `-`, `*`, `+` or `1.`, then a space and real content.
#
# `1.` rather than `\d+\.` is GFM's own rule, and it is what keeps prose that
# wraps onto a line starting with a number ("...was\n1985. What a year.") a
# paragraph rather than an `<ol start="1985">`. The lookahead is GFM's rule
# that an empty list item cannot interrupt. Three spaces is the tolerance the
# vendored list processors already use.
_INTERRUPTING_MARKER = re.compile(r"^[ ]{0,3}(?:[*+-]|1\.)[ ]+(?=\S)")


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

    return [TaskListExtension(), StrikethroughExtension(), ListInterruptExtension()]
