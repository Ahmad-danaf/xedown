"""Which way a document reads. Pure logic — no GTK imports belong in this module.

Two directions matter to a preview, and they are not the same thing. The
*document's* is decided here, from its own content or from the user's
override, and lands on the article. The *desktop's* is what xedown's own
chrome follows, and lands on `<html>`; `coerce_ui` is its only entry point,
kept here so both halves of the vocabulary live in one place.

Deciding the document's direction is a whole-document question, so it is
answered by counting rather than by taking the first strong character the way
HTML's `dir="auto"` does: a document whose first paragraph happens to be in
English but which is otherwise Arabic is exactly the case the counting rule
gets right and the first-strong rule does not.
"""

import re
import unicodedata
from collections import Counter

from . import settings

LTR = "ltr"
RTL = "rtl"
AUTO = "auto"

_STRONG_LTR = "L"
_STRONG_RTL = frozenset({"R", "AL"})

# Removed before counting, in this order, because a fence can contain anything
# that looks like the patterns after it. Code is Latin by convention and would
# drown a short Arabic document; a URL is not prose, though a link's text is.
#
# Indented code is deliberately NOT removed: telling it from a list
# continuation needs block context a regex does not have, and guessing wrong
# would delete real prose from the count, biasing exactly the documents this
# module exists for. Leaving it in can only add weight it already had.
#
# These select what to ignore and are not sanitization -- the sanitizer still
# rebuilds every document from its own allowlist.
_STRIPPED = (
    # A fenced block, opening marker through matching closing marker. An
    # unterminated fence matches nothing here, which is also how
    # Python-Markdown reads it.
    re.compile(
        r"^(?P<fence>```+|~~~+)[^\n]*\n.*?^(?P=fence)[^\n]*$", re.MULTILINE | re.DOTALL
    ),
    # An inline code span, on one line.
    re.compile(r"(?P<ticks>`+)[^\n]*?(?P=ticks)"),
    # A link or image destination; the text before it survives.
    re.compile(r"\]\([^)\n]*\)"),
    # A link reference definition.
    re.compile(r"^[ \t]*\[[^\]\n]*\]:[^\n]*$", re.MULTILINE),
    # A raw HTML tag. Its content survives, so <bdi>text</bdi> still counts.
    re.compile(r"<[^\n>]*>"),
)


def _without_code(text):
    """`text` with the parts whose direction is not the document's removed.

    Each match becomes a newline rather than nothing, so removing a block
    cannot join two lines and defeat the line-anchored patterns after it.
    """
    for pattern in _STRIPPED:
        text = pattern.sub("\n", text)
    return text


def detect(text):
    """`"rtl"` when right-to-left strong characters outnumber left-to-right ones.

    Counted through `Counter` — which runs at C speed over the whole string —
    and then one `unicodedata.bidirectional` lookup per DISTINCT character. A
    real document has a few hundred distinct characters whatever its length,
    and this runs on the debounced typing path, where a lookup per character
    would be roughly a million calls on a one-megabyte file.

    A document with no strong characters at all — empty, digits, punctuation —
    is left-to-right. Anything that is not a string is too: `render_document`
    is called directly by `scripts/render-themes.sh` and by the tests, so a
    bad argument has to answer rather than raise.
    """
    if not isinstance(text, str) or not text:
        return LTR
    ltr = rtl = 0
    for character, occurrences in Counter(_without_code(text)).items():
        category = unicodedata.bidirectional(character)
        if category == _STRONG_LTR:
            ltr += occurrences
        elif category in _STRONG_RTL:
            rtl += occurrences
    return RTL if rtl > ltr else LTR


def resolve(setting_value, text):
    """The document's direction: the user's choice, or detection under `auto`.

    Coerced through the settings descriptor rather than compared as a string,
    so a value that is missing, misspelled or of the wrong type falls back to
    `auto` — and therefore to detection — instead of raising or pinning a
    direction the user never chose. Mirrors what `render_document` already
    does with `code_copy_buttons` and `image_display`, and for the same
    reason.
    """
    chosen, _ = settings.by_name(settings.TEXT_DIRECTION).coerce(setting_value)
    return detect(text) if chosen == AUTO else chosen


def coerce_ui(value):
    """The desktop's direction, as one of exactly two strings. Never raises."""
    return RTL if value == RTL else LTR
