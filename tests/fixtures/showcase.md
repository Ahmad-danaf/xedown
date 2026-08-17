# Xedown Showcase

Everything on this page renders **correctly**: no missing images, no dead
links, no unresolved references. If you need a screenshot of Preview mode,
or a first impression of what a rendered document should look like, take it
from this file. For the deliberately broken cases used in the manual smoke
test, see [edge-cases.md](edge-cases.md) instead.

## Text formatting

A paragraph with **bold text**, *italic text*, ~~strikethrough text~~, and
`inline code`, combined in one sentence to confirm they nest cleanly.

## Lists

An unordered list:

- First item
- Second item
- Third item

An ordered list:

1. First step
2. Second step
3. Third step

A task list:

- [x] Completed task
- [ ] Outstanding task

## Blockquote

> A short blockquote, to confirm indentation and the border render the way
> they should.

## Horizontal rule

Above this line is one section; below it is another.

---

## Table

| Feature | Bundled | Notes |
| --- | --- | --- |
| Tables | Yes | GFM table syntax |
| Task lists | Yes | Rendered as disabled checkboxes |
| Footnotes | Yes | In-page anchors, with a back-reference |

## Code blocks

A Python fenced block, one of the 31 bundled highlighting languages:

```python
def greet(name):
    return f"Hello, {name}!"
```

A Bash fenced block, another of the 31:

```bash
echo "Rendering complete"
```

## Images

A local image, resolved relative to this file:

![A small generated gradient](pics/sample.png)

## Links

- [An external link](https://example.com) opens in the default browser.
- [A relative link to another fixture](linked.md) opens the linked document.
- [Jump back up to the table](#table) is an in-page anchor link — it should
  scroll within the preview, not open anything else.

## Footnote

This sentence carries a footnote reference[^1], which should scroll to the
note below and back again.

[^1]: This is the footnote text, reached by clicking the reference above.

## A table wider than the column

| Feature | Status | Owner | Since | Notes | Ticket | Reviewed by | Follow-up |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Preview | Ready | ahmad | 0.1.0 | In-tab, no extra window | #1 | ahmad | none |
| Themes | Ready | ahmad | 0.2.0 | Four complete designs | #12 | ahmad | none |
| Copy buttons | Ready | ahmad | 0.2.0 | Host writes the clipboard | #31 | ahmad | none |

## A very tall image

It should fit the window rather than running for several screens, and it
should keep its proportions while doing so.

![A tall test image](pics/tall.png)

## A very small image

It must stay its own size. Nothing here should stretch it.

![A small test image](pics/tiny.png)

## A collapsible section

<details markdown="1">
<summary>Show the long version</summary>

Everything inside stays hidden until the reader asks for it, which is why
a README uses one. Inside it: a list, and a fence.

- first
- second

```sh
echo "inside a details block"
```

</details>

Press <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>M</kbd> to switch modes.

<div align="center">

A centred block.

</div>
