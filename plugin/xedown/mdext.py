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

# Mirrors `markdown.extensions.toc.IDCOUNT_RE` exactly. Duplicated rather
# than imported because this helper is pure -- it must be importable and
# testable without resolving the vendored package -- and pinned against
# drift by `test_the_vendored_function_still_behaves_as_characterised`.
_IDCOUNT_RE = re.compile(r"^(.*)_([0-9]+)$")


def unique_id(candidate, used, memo):
    """`toc.unique`'s answer, without its quadratic walk.

    The vendored function restarts its `_1, _2, _3...` probe from the
    beginning on every collision, so the nth duplicate of one slug costs n
    steps -- 1,529 ms for 1600 identical headings against 212 ms for 1600
    distinct. A changelog with `### Fixed` under every version hits it.

    `memo` (input string -> last id returned) is what makes this linear.
    Resuming there is safe because the vendored loop only advances past a
    candidate already in `used`, so after `s` returns `s_k` every one of
    `s, s_1, ... s_k` is occupied: resuming at `s_k` can never skip a *free*
    value, which is the only way the answer could differ.

    Byte-identical output is a requirement -- anchors are part of the
    document's contract. `tests/unit/test_toc_unique.py` differential-tests
    against the vendored function and pins its behaviour, so a re-vendor
    that changes it fails loudly.

    `memo` needs no locking: rendering is on the GTK main thread.
    """
    identifier = memo.get(candidate, candidate)
    while identifier in used or not identifier:
        match = _IDCOUNT_RE.match(identifier)
        if match:
            identifier = f"{match.group(1)}_{int(match.group(2)) + 1}"
        else:
            identifier = f"{identifier}_1"
    used.add(identifier)
    memo[candidate] = identifier
    return identifier


# A backslash before a newline is a CommonMark hard break, like two trailing
# spaces. The vendored `escape` pattern (priority 180) matches it first but
# declines it -- `\n` is not in `Markdown.ESCAPED_CHARS` -- leaving the raw
# text for this lower-priority pattern. An escaped backslash is consumed
# whole by `escape` first, so that case is unaffected.
_BACKSLASH_BREAK_PATTERN = r"\\\n"

# A list marker allowed to interrupt a paragraph: up to three spaces of
# indent, then `-`, `*`, `+`, `1.` or `1)`, then a space and real content.
#
# `1.`/`1)` rather than `\d+[.)]` is GFM's own rule, and what keeps prose
# wrapping onto "1985. What a year." a paragraph rather than an
# `<ol start="1985">`. The lookahead is GFM's rule that an empty item cannot
# interrupt; three spaces is the vendored processors' own tolerance.
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


# A list item exactly as the vendored processors define one, deliberately no
# wider: a bare `-` is an item to CommonMark but not to `OListProcessor.RE`,
# and treating it as one opens a nesting level the parser then refuses to
# enter, swallowing the sub-items into a paragraph.
_LIST_ITEM = re.compile(
    r"^(?P<indent>[ ]*)(?P<marker>[*+-]|\d{1,9}[.)])(?P<gap>[ ]+)(?=\S)"
)

# A thematic break, which outranks a list item and is claimed by
# `HRProcessor` (50). Needed because `- - -` reads as marker-space-content to
# the regex above, and indenting it would turn a rule into a literal `- -`
# list -- a distinction the pre-v0.3 design never had to make.
_THEMATIC_BREAK = re.compile(
    r"^[ ]{0,3}(?=(?P<run>(-+[ ]{0,2}){3,}|(_+[ ]{0,2}){3,}|(\*+[ ]{0,2}){3,}))"
    r"(?P=run)[ ]*$"
)

# A setext underline. `SetextHeaderProcessor` (60) outranks `HRProcessor`
# (50), so a run of hyphens is not reliably a rule: it escapes setext only
# when it is not line two of its block, which this pass cannot know once the
# parser re-queues halves. Every `=`/`-` run is treated as an underline, the
# stricter answer; `- - -` and `***` are not such runs and stay rules.
_SETEXT_UNDERLINE = re.compile(r"^(?:=+|-+)[ ]*$")

# An ATX heading as `SpacedHashHeaderProcessor` (70) defines one: at most
# six hashes, and a space or end of line after them.
_ATX_HEADING = re.compile(r"^#{1,6}(?:[ ]|$)")


REWIND = "rewind"
STOP = "stop"


def _ends_list_tracking(content, column, level, tab_length):
    """How a block splitter inside a list ends this pass's tracking of one.

    `REWIND`, `STOP` or None. Three processors split their block and re-queue
    the halves -- `hr` (50), `setextheader` (60), `hashheader` (70) -- each
    claimed near the left margin. `ListIndentProcessor` dedents every tight
    line by `tab_length`, so one of these reaching the margin can take the
    list with it.

    **`column` and `level` are in the coordinates this pass emits, not the
    ones it read**, because `_place_continuation` decides both this and the
    emission. Measuring in source coordinates let a rule at four columns
    under a three-column sub-item read as harmless while the sub-item had
    already been rewritten to four, and the rule reached the margin anyway.

    `landing` is where the line ends up after the dedents; `looseDetab` only
    takes `tab_length` off a line that has it to give, hence the `min`.

    - **A setext underline** absorbs the line *above* into the heading, so a
      moved marker line becomes heading text. Always `REWIND`.
    - **A rule or ATX heading at the margin** cuts the block at its own line.
      The half above keeps its nesting, so nothing is undone, but the list is
      over: `STOP`, or a later line is measured against a dead item.
      Rewinding instead would cost real sublists, since `### Heading` under a
      list line is a shape real READMEs contain.
    - **One that only reaches the margin after the dedents** descends into
      the item and cuts a sub-item from its parent: `REWIND`. Further in than
      that, nothing above `ulist` claims it: None.
    """
    if _SETEXT_UNDERLINE.match(content) is not None:
        return REWIND
    if _THEMATIC_BREAK.match(content) is not None:
        claimed_at = tab_length  # `HRProcessor.RE` tolerates three columns
    elif _ATX_HEADING.match(content) is not None:
        claimed_at = 1  # `HashHeaderProcessor.RE` needs the margin exactly
    else:
        return None
    if column < claimed_at:
        return STOP
    landing = column - tab_length * min(level - 1, column // tab_length)
    return REWIND if landing < claimed_at else None


def _place_continuation(line, indent, column, depth, own_block, tab_length):
    """The column a non-marker line is emitted at.

    One definition, called both to write the line and to measure where a
    block splitter on it will land, so the emission and the guard can never
    end up in different coordinate spaces.
    """
    if not depth:
        return indent
    offset = indent - column
    if own_block:
        # `ListIndentProcessor` dedents a block of its own by
        # `tab_length * depth`, so put it there. An offset of one to three
        # columns is insignificant to every block construct and dropping it
        # keeps an already-`tab_length` document byte-identical; four or more
        # is a code block's indent and is content.
        return tab_length * depth + (offset if offset >= tab_length else 0)
    if offset < tab_length and line[indent] == ">":
        return tab_length * (depth - 1) + offset
    return indent


# `_INTERRUPTING_MARKER`'s rule again as a set, because this pass has already
# matched the marker and only has to classify it. Anything else is prose that
# looks like a marker ("...was\n1985. What a year.") and must not open an item.
_INTERRUPTING_MARKERS = frozenset({"-", "*", "+", "1.", "1)"})


def normalize_list_indentation(lines, tab_length=4):
    """Re-indent list content onto `tab_length`-per-level nesting.

    CommonMark nests by *continuation column*, so `- Flask` / `  - apiflask`
    is a sublist. The vendored parser nests by a fixed `tab_length` instead
    (`ListIndentProcessor` tests `startswith(' ' * tab_length)`, and
    `OListProcessor.CHILD_RE` reads a marker at 0-3 spaces as a *sibling*),
    so a two-space sublist is flattened into its parent and content past the
    continuation column but under four spaces is left as literal text.
    `tab_length=2` is not the fix: it would read one four-space indent as two
    levels.

    This pass translates between the two models and rewrites nothing but
    leading whitespace. A marker line moves to `tab_length * (depth - 1)`; a
    block of its own inside the item moves to `tab_length * depth`, carrying
    any offset of four or more columns, which is a code block's indent. Every
    other line stays where it was written, bar the exceptions below, and an
    already-`tab_length` document comes through byte-identical.

    A preprocessor rather than a block processor, because the decision needs
    the whole document's nesting, which no single block carries. What makes
    that safe is its position at priority 18: `fenced_code_block` (25) and
    `html_block` (20) have already lifted their content into the HTML stash,
    so indentation that is content is not text by the time this runs. That
    reaches exactly as far as those stashing passes do -- `_FENCED_BLOCK_RE`
    tolerates only three spaces of indent, so a fence indented four or more
    inside a list item is never stashed and this pass does move its body.
    That shape diverges from cmark-gfm before and after, so nothing
    regresses.

    Deliberately **not** idempotent, and nothing calls it twice: it reads
    source continuation columns and writes the parser's fixed model, so
    feeding its output back in translates a second time (a code block in a
    two-column item drifts 6 -> 8 -> 10).

    Three hazards remain, each closed by narrowness rather than inspection:

    - A non-marker line keeps its own indentation, except a blockquote marker
      and except in a block of its own. Tight continuation lines reach the
      parser raw, so moving one changes which processor claims the *whole*
      block: dedenting `  ---` under `- a` makes an `<h2>` reading "- a".
      A `>` line is the one safe exception, since nothing above `quote` (20)
      could claim it that could not already.
    - An over-indented line stays over-indented: four or more spaces past the
      continuation column is indented code, which cannot interrupt a
      paragraph, so it must not be pulled into `OListProcessor.INDENT_RE`'s
      four-to-seven-space window.
    - A rule, setext underline or ATX heading tight inside a list ends the
      tracking. Declining to move it is not enough: `HRProcessor` (50) splits
      the block and re-queues both halves, so what follows re-enters with no
      list context, where `tab_length` spaces mean indented code -- `- a` /
      `  ---` / `  - b` would put the bullet in a code box. With a blank line
      around it the rule is its own block and the list survives, which is why
      the guard asks whether a blank line preceded.
    """
    out = []
    # The source content column of every open list item, outermost first.
    open_items = []
    after_blank = True  # the start of the document behaves like a blank line
    after_marker = False
    own_block = False  # this block began after a blank line, not on a marker
    # This pass emits exactly one line for every line it reads, so a block's
    # output can be put back the way it was written by index alone.
    block_start = 0
    block_source = []
    verbatim = False
    for line in lines:
        if not line.strip():
            out.append(line)
            block_start = len(out)
            block_source = []
            verbatim = False
            after_blank = True
            after_marker = False
            continue
        block_source.append(line)
        if verbatim:
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip(" "))
        # The items this line is still inside, by indentation alone.
        depth = len(open_items)
        while depth and indent < open_items[depth - 1]:
            depth -= 1
        column = open_items[depth - 1] if depth else 0
        ending = (
            _ends_list_tracking(
                line[indent:],
                _place_continuation(line, indent, column, depth, own_block, tab_length),
                len(open_items),
                tab_length,
            )
            if open_items and not after_blank
            else None
        )
        if ending is not None:
            # A block splitter inside a list -- see the third hazard above.
            # Either way the list is over for this pass. `REWIND` also puts
            # back the lines already emitted for this block, because by now
            # the marker lines above have been moved, and leaving them moved
            # turns `- b` / `    ---` into an `<h2>` reading "- b".
            if ending is REWIND:
                out[block_start:] = block_source
                verbatim = True
            else:
                out.append(line)
            open_items.clear()
            after_marker = False
            continue
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
            # An outermost item stays where it was written: its marker is
            # already inside the 0-3 columns every vendored list processor
            # tolerates, and moving it *left* can walk it out from under an
            # indented code block that was holding it.
            out.append(
                line if not depth else " " * (tab_length * depth) + line[indent:]
            )
            own_block = False
        else:
            if after_blank:
                own_block = True
            placed = _place_continuation(
                line, indent, column, depth, own_block, tab_length
            )
            # `normalize_whitespace` (30) expanded tabs long before this, so
            # rebuilding the line from a column is lossless.
            out.append(" " * placed + line[indent:])
        after_marker = is_item
        after_blank = False
    return out


# GFM takes only the first token of an info string as the language name. The
# vendored `FENCED_BLOCK_RE` narrows that to a single *bare* word, so a comma,
# space or brace anywhere in the info string fails the whole opening-fence
# match: the fence never opens, its closing fence opens one of its own for
# whatever follows, and the document desynchronises from there.
_FENCE_LANG_TOKEN = re.compile(r"[^\s,]+")

# The shape the vendored regex required of the whole info string, applied to
# the one token pulled out of it. `class="language-..."` reaches the page
# unexamined: `sanitizer._ALLOWED_CLASS_PREFIXES` blocks style injection and
# is not a semantic validator. A malformed token gets no class at all rather
# than an escaped-but-nonsensical one, which matches cmark-gfm's *sanitized*
# output -- its `lang=` on `<pre>` is not an attribute the sanitizer allows.
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

    CommonMark strips the opening fence's own 0-3 spaces from every content
    line, capped per line at the whitespace that line actually has.
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


# The vendored `FencedBlockPreprocessor.FENCED_BLOCK_RE`, with two changes:
#
#  - `(?P<indent>[ ]{0,3})` allows CommonMark's three spaces of fence indent.
#    Four or more stays indented code, because `[ ]{0,3}` always leaves at
#    least one space in front of the fence characters however it backtracks.
#  - `(?P<info>[^\n]*)` makes any text a valid info string, not just a bare
#    word; `fence_lang` above pulls the language out afterwards.
#
# The `{attrs}` branch is kept because it is live: `attr_list` is loaded, and
# "```{.python #myid}" is how a document sets an id on a fence. Without it the
# widened `info` alternative would swallow the whole thing as info text.
#
# The bare `hl_lines="..."` branch is dropped: nothing in xedown consumes it.
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

    A narrowed `FencedBlockPreprocessor.handle_attrs`, dropping the
    `hl_lines`/pygments keys with the rest of that dead branch. Any other
    pair (`{data-x=1}`) is ignored, as the vendored preprocessor does when
    `attr_list` is not loaded.
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
    # Not yet an attribute of the `extensions` package: `make_extensions`
    # runs before the `Markdown()` call that would import the submodule.
    # Keyed off `markdown_module.__name__` so it reaches the *vendored* copy
    # without a top-level `import markdown...`, which could resolve to a
    # non-vendored one if this module were imported before the guard runs.
    _sane_lists = importlib.import_module(
        f"{markdown_module.__name__}.extensions.sane_lists"
    )
    SaneOListProcessor = _sane_lists.SaneOListProcessor
    SaneUListProcessor = _sane_lists.SaneUListProcessor
    # Same reasoning as `SaneOListProcessor` above.
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
        """Require CommonMark's space after the `#` markers.

        The vendored regex does not, so `#NoSpace` becomes an `<h1>` and
        `####### Seven` an `<h6>` with a literal `#` in its text. Overriding
        `RE` alone is enough, since `test` and `run` both just use it. The
        end-of-line alternative keeps a bare `#` a valid empty ATX heading.
        """

        RE = re.compile(
            r"(?:^|\n)(?P<level>#{1,6})(?:[ ]+|(?=\n|$))"
            r"(?P<header>(?:\\.|[^\\])*?)#*(?:\n|$)"
        )

    class HashHeaderOverrideExtension(Extension):
        def extendMarkdown(self, md):
            # Same name and priority, so `Registry.register` swaps it in
            # place and it sits exactly where `hashheader` sat.
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

    class ParenUListProcessor(SaneUListProcessor):
        """Teach an unordered list to spot a nested `1)` item.

        `INDENT_RE` is how a list processor spots a nested item of *either*
        type, and `sane_lists` leaves `ulist`'s copy at the vendored
        ordered-marker shape, which does not know `)`. Widening `olist` alone
        left `- a` / `  1) b` with no nested `<ol>`.

        `RE` and `CHILD_RE` stay untouched: an unordered list's own item is
        `[*+-]`, never a number.
        """

        def __init__(self, parser):
            super().__init__(parser)
            self.INDENT_RE = re.compile(
                rf"^[ ]{{{self.tab_length},{self.tab_length * 2 - 1}}}"
                r"((\d+[.)])|[*+-])[ ]+.*"
            )

    class ParenOListExtension(Extension):
        def extendMarkdown(self, md):
            # Same names and priorities as the vendored `olist` and `ulist`
            # they replace.
            md.parser.blockprocessors.register(
                ParenOListProcessor(md.parser), "olist", 40
            )
            md.parser.blockprocessors.register(
                ParenUListProcessor(md.parser), "ulist", 30
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
            # Same name and priority as the vendored `fenced_code_block`.
            md.preprocessors.register(
                FencedCodePreprocessor(md), "fenced_code_block", 25
            )

    class ListIndentationPreprocessor(Preprocessor):
        """Run `normalize_list_indentation` over the document's lines.

        Priority 18 puts this below all three other preprocessors, so it is
        the last thing to touch the raw lines. That order is the design:
        `normalize_whitespace` (30) has already expanded tabs, so a column is
        a space, and `fenced_code_block` (25) and `html_block` (20) have
        already stashed the text whose indentation is content. `tab_length`
        is read off the `Markdown` instance because that is what every
        vendored list processor builds its regexes from.
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

        Priority 12 is below every other block processor and just above
        `paragraph`, so anything offered here has already been declined by
        `setextheader`, `hr`, `olist` and the rest -- which is why no
        first-line guard against blocks that are already lists is needed. It
        says nothing about the lower half `run` re-queues: that re-enters the
        chain at 100, where a processor above 12 can still claim it.
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

    # `toc.unique` is module-level and called from `TocTreeprocessor.run`,
    # which is forty lines of vendored logic: subclassing would copy that
    # logic here, where the next re-vendor would silently make it wrong. The
    # registered treeprocessor keeps its own `run` and only the collision
    # resolver is swapped, for one call. See `unique_id` for why the answer
    # is byte-identical.
    toc_module = importlib.import_module(f"{markdown_module.__name__}.extensions.toc")

    class FastTocExtension(Extension):
        def extendMarkdown(self, md):
            # The vendored `util.Registry` has `__contains__` and
            # `__getitem__` but no `.get`.
            if "toc" not in md.treeprocessors:
                # `toc` is not loaded: nothing to speed up or break.
                # `test_toc_unique.py` asserts the normal case.
                return
            processor = md.treeprocessors["toc"]
            original_run = processor.run
            if getattr(original_run, "_xedown_fast_toc", False):
                return

            def run(doc):
                memo = {}

                def fast_unique(candidate, used):
                    return unique_id(candidate, used, memo)

                previous = toc_module.unique
                toc_module.unique = fast_unique
                try:
                    return original_run(doc)
                finally:
                    toc_module.unique = previous

            run._xedown_fast_toc = True
            processor.run = run

    return [
        TaskListExtension(),
        StrikethroughExtension(),
        BackslashBreakExtension(),
        HashHeaderOverrideExtension(),
        ParenOListExtension(),
        FencedCodeOverrideExtension(),
        ListIndentationExtension(),
        ListInterruptExtension(),
        FastTocExtension(),
    ]
