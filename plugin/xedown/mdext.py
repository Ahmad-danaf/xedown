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

    The vendored function resolves a slug collision by restarting its
    `_1, _2, _3...` probe from the beginning every time, so the nth
    duplicate of one slug costs n steps -- 1,529 ms for 1600 identical
    headings against 212 ms for 1600 distinct ones. The shape that hits
    it is a changelog, with `### Fixed` under every released version.

    `memo` maps an input string to the last id returned for it, and is
    what makes this linear. Resuming there is safe, and gives byte-identical
    output, because of an invariant the vendored loop establishes: it
    advances from one candidate to the next only when the current one is
    already in `used`, and adds its answer on the way out. So after a call
    for `s` returns `s_k`, every one of `s, s_1, ... s_k` is in `used`, and
    resuming a later call at `s_k` skips only values already proven
    occupied. It can never skip a *free* value, which is the only way the
    answer could differ.

    Byte-identical output is a requirement, not a nicety: anchors are part
    of the rendered document's contract and in-page links resolve against
    them. `tests/unit/test_toc_unique.py` differential-tests this against
    the vendored function and pins that function's behaviour, so a
    re-vendor that changes it fails loudly instead of leaving a
    replacement that quietly no longer matches.

    Single-threaded by construction -- rendering happens on the GTK main
    thread -- so `memo` needs no locking. It is created per document.
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

# A setext underline: a run of `=` or `-` and nothing else.
# `SetextHeaderProcessor` (60) is *above* `HRProcessor` (50) in the
# registry, so it is tried first and a run of three or more hyphens is not
# reliably a rule -- it escapes setext only when it is not line two of its
# block, which `RE = ^.*?\n[=-]+[ ]*(\n|$)` and a `.match` require.
# Position in the block is not something this pass can know once the
# parser starts re-queueing halves, so every `=`/`-` run is treated as an
# underline, which is the stricter of the two answers. `- - -` and `***`
# are not runs of `[=-]` and stay rules.
_SETEXT_UNDERLINE = re.compile(r"^(?:=+|-+)[ ]*$")

# An ATX heading as `SpacedHashHeaderProcessor` (70) defines one: at most
# six hashes, and a space or end of line after them.
_ATX_HEADING = re.compile(r"^#{1,6}(?:[ ]|$)")


REWIND = "rewind"
STOP = "stop"


def _ends_list_tracking(content, column, level, tab_length):
    """How a block splitter inside a list ends this pass's tracking of one.

    `REWIND`, `STOP` or None. Three processors *split* the block they are
    given and re-queue the halves: `hr` (50), `setextheader` (60) and
    `hashheader` (70). Each is claimed near the left margin and not at
    `tab_length` columns in, which is what makes them the hazard for a pass
    that moves marker lines to the right: `ListIndentProcessor` dedents
    every tight line under a nested marker by `tab_length`, and one of
    these three arriving at the margin can take the list with it.

    **`column` and `level` are in the coordinates this pass emits, not the
    ones it read.** `column` is where the line will actually be written --
    `_place_continuation` decides that and is called for this and for the
    emission itself, so the two cannot drift -- and `level` is the emitted
    nesting depth of the item the line follows. Measuring in source
    coordinates is what let a rule at four columns under a three-column
    sub-item read as "over-indented, harmless" while the sub-item above it
    had already been rewritten to four: the two spaces disagreed and the
    rule reached the margin anyway.

    Given those, `landing` is the column the line reaches after the
    dedents. `looseDetab` takes `tab_length` off a line only when the line
    has that much to give, so a line runs out of indentation before it runs
    out of levels -- hence the `min`.

    - **A setext underline** absorbs the line *above* it into the heading,
      so a marker line this pass has moved becomes the heading's text: `- b`
      renders as an `<h1>` reading "- b" rather than as an item. Nothing
      about its column saves it, so it always `REWIND`s.
    - **A rule or an ATX heading at the margin** -- close enough to be
      claimed where it stands -- cuts the block at its own line. The half
      above is a whole list, re-parsed with its nesting intact, so there is
      nothing to undo; but the list is over as far as the parser is
      concerned, so tracking must `STOP` or a later line is measured
      against an item that no longer exists. `### Heading` directly under a
      list line is a shape real READMEs contain, and rewinding it would
      cost real sublists.
    - **A rule or an ATX heading that only reaches the margin after the
      dedents** descends into the item instead, and cuts a sub-item away
      from the parent it was just nested under -- `REWIND`. Landing further
      in than that, it is claimed by nothing above `ulist`, and the fix can
      stay: None.
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
        # A block of its own inside the item: `ListIndentProcessor` will
        # dedent it by `tab_length * depth`, so put it there. An offset of
        # one to three columns past the continuation column is
        # insignificant to every block construct, and dropping it is what
        # keeps a document that already indents `tab_length` per level
        # byte-identical through this pass. Four or more is the indent of a
        # code block and is content, so it is carried through.
        return tab_length * depth + (offset if offset >= tab_length else 0)
    if offset < tab_length and line[indent] == ">":
        return tab_length * (depth - 1) + offset
    return indent


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
    text. That argument reaches exactly as far as the stashing
    preprocessors do and no further: `_FENCED_BLOCK_RE` tolerates three
    spaces of indent, so a fence indented four or more inside a list item is
    never stashed, and this pass can and does move its body. That shape
    diverges from cmark-gfm both before and after this change -- the fence
    is not recognised as a fence at all -- so nothing regresses, but the
    guarantee above is about fences the stashing preprocessor matched, not
    about every line that looks like one.

    It is deliberately **not** idempotent, and nothing calls it twice: a
    preprocessor runs once per conversion. The continuation columns it reads
    are the *source* document's, while the indentation it writes is the
    parser's fixed `tab_length` model, so its output is in the other
    coordinate system and feeding that back in translates a second time (a
    code block inside a two-column item drifts 6 -> 8 -> 10). Making it a
    fixed point would mean emitting an item whose content column is
    `tab_length * depth`, which is not what a marker line's content column
    is.

    Three hazards remain that indentation alone can spring, and each is
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
    - A rule, a setext underline or an ATX heading tight inside a list ends
      the tracking, and sometimes undoes it. Declining to *move* the rule is
      not enough: `HRProcessor` (50) splits the block at the rule and
      re-queues both halves, so whatever follows re-enters the chain with no
      list context, and `tab_length` spaces there mean indented code (80)
      rather than a sub-item -- `- a` / `  ---` / `  - b` would put the
      bullet in a code box. `_ends_list_tracking` says which of the two is
      needed and why. With a blank line around it the rule is its own block,
      `ListIndentProcessor` still carries the item across, and the list
      survives -- which is why the guard asks whether a blank line preceded.
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
            # Either way the list is over for this pass; `REWIND`
            # additionally puts back the lines already emitted for this
            # block and hands the rest over untouched, so the block renders
            # exactly as it did before this pass existed. Rewinding rather
            # than merely stopping is what the deeper forms need: by the
            # time the splitter is reached the marker lines above it have
            # already been moved, and leaving them moved is what turns
            # `- b` / `    ---` into an `<h2>` reading `- b` with the next
            # sub-item in a code box.
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
            # An outermost item is left exactly where it was written. Its
            # marker is already inside the nought-to-three columns every
            # vendored list processor tolerates, so moving it buys nothing,
            # and moving it *left* can walk a marker out from under an
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
            # Leading whitespace is spaces by now -- `normalize_whitespace`
            # (30) expanded tabs long before this pass -- so rebuilding the
            # line from a column is lossless.
            out.append(" " * placed + line[indent:])
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
    _sane_lists = importlib.import_module(
        f"{markdown_module.__name__}.extensions.sane_lists"
    )
    SaneOListProcessor = _sane_lists.SaneOListProcessor
    SaneUListProcessor = _sane_lists.SaneUListProcessor
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

    class ParenUListProcessor(SaneUListProcessor):
        """The other half of task 14 / F20, which task 15 surfaced.

        `INDENT_RE` is how a list processor spots a *nested* item of either
        type, so `ulist` carries its own copy of the ordered-marker shape --
        and `sane_lists` leaves it at `OListProcessor.__init__`'s `\\d+\\.`,
        which does not know `)`. Widening `olist` alone therefore left
        `- a` / `  1) b` with no nested `<ol>`: the `1)` line went to
        `get_items`' fallback and stayed literal text.

        It stayed hidden while a two-space sublist was flattened anyway --
        the line landed at three columns, `xedown_list_interrupt` (12)
        recognised the marker there and split the item, and the nesting came
        out right by a route that had nothing to do with `INDENT_RE`. Once
        `xedown_list_indent` moves that line to four columns the fallback is
        the only route left, so the gap became visible. `RE` and `CHILD_RE`
        are untouched: an unordered list's own item is `[*+-]`, never a
        number, and `sane_lists` narrows `CHILD_RE` for a reason.
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

    # The heading-anchor cliff. `toc.unique` is a module-level function
    # called from `TocTreeprocessor.run`, and `run` is forty lines of
    # vendored logic -- subclassing it would copy that logic into xedown,
    # where the next re-vendor would silently make the copy wrong. So the
    # treeprocessor already registered under "toc" keeps its own `run`, and
    # only the collision resolver is swapped, for the duration of one call.
    #
    # This is a replacement registered from xedown's own code, which is the
    # sanctioned route; the vendored file is untouched. See `unique_id`
    # above for why the answer is byte-identical.
    toc_module = importlib.import_module(f"{markdown_module.__name__}.extensions.toc")

    class FastTocExtension(Extension):
        def extendMarkdown(self, md):
            # `Registry` implements `__contains__` and `__getitem__` but
            # NOT `.get` -- checked against the vendored `util.Registry`.
            if "toc" not in md.treeprocessors:
                # `markdown.extensions.toc` is not loaded. Nothing to speed
                # up, and nothing to break. `test_toc_unique.py` asserts the
                # normal case, so this cannot go unnoticed.
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
