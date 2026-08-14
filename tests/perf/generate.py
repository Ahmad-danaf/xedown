"""Deterministic synthetic documents, by shape and size.

Shape matters more than size: at 100 KB the spread between prose and
tables is 5x, and duplicated headings are 80x. A generator that varied
its output per run could not detect a regression, so nothing here is
random -- repetition and a counter are the only variation.

Sizes are in *characters*, not bytes, because Python-Markdown operates on
`str` and that is what the cost tracks. For the ASCII shapes here the two
are the same number anyway; saying characters keeps the harness and
`perflimits` speaking the same units.
"""

SIZES = (100_000, 250_000, 500_000, 1_000_000)

_PROSE = "Some ordinary prose about a topic, at a workaday length. "


def _prose(n):
    return "".join(f"{_PROSE * 3}Paragraph {i}.\n\n" for i in range(n))


def _headings_unique(n):
    return "".join(f"## Section {i} of the document\n\ntext\n\n" for i in range(n))


def _headings_duplicate(n):
    # The changelog shape: the same few headings under every version.
    names = ("Fixed", "Added", "Changed", "Removed")
    return "".join(f"### {names[i % len(names)]}\n\ntext\n\n" for i in range(n))


def _tables(n):
    head = "| alpha | beta | gamma | delta |\n|---|---|---|---|\n"
    return head + "".join(
        f"| cell {i}a | cell {i}b | cell {i}c | cell {i}d |\n" for i in range(n)
    )


def _list_items(n):
    return "".join(f"- item {i} in a bulleted list\n" for i in range(n))


def _code_blocks(n):
    return "".join(f"```python\nvalue = {i}\n```\n\n" for i in range(n))


def _links(n):
    return "".join(
        f"See [document {i}](./docs/page-{i}.md) for more.\n\n" for i in range(n)
    )


def _images(n):
    return "".join(f"![figure {i}](./img/figure-{i}.png)\n\n" for i in range(n))


def _inline_emphasis(n):
    return "".join(
        f"Some *emphatic* and **strong** and `code` text, run {i}.\n\n"
        for i in range(n)
    )


_BUILDERS = {
    "prose": _prose,
    "headings-unique": _headings_unique,
    "headings-duplicate": _headings_duplicate,
    "tables": _tables,
    "list-items": _list_items,
    "code-blocks": _code_blocks,
    "links": _links,
    "images": _images,
    "inline-emphasis": _inline_emphasis,
}

SHAPES = tuple(_BUILDERS)


def build(shape, target_chars):
    """`shape` repeated until it is about `target_chars` long.

    Overshoots rather than truncates: cutting mid-construct would produce
    an unclosed fence or a half-written table row, and the parser's
    handling of malformed input is the compatibility suite's subject, not
    this harness's.
    """
    builder = _BUILDERS[shape]
    probe = builder(8)
    per_unit = max(1, len(probe) // 8)
    return builder(max(1, round(target_chars / per_unit)))
