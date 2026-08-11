"""What the file on disk means for the preview. Pure logic — no GTK imports.

The question this module answers is deliberately narrow: given the bytes on
disk and the text in the buffer, is there anything the preview should do about
it? Everything that decides lives here so CI can test it; `filewatch.py` knows
about events and timing and nothing about meaning, and `controller.py` acts on
the answer without forming one.

**The comparison is of content, not of timestamps**, and that single choice is
what makes a save from xed itself a no-op — after one, the file matches the
buffer. No ignore-flag, no suppression window, no timing assumption. It also
means a `touch`, a permission change, and a rebase that ends where it started
all cost one read and no render.

Three normalisations stand between the raw bytes and a comparison that means
anything. Each is here because without it the answer is wrong on ordinary
files; the trailing-newline rule most of all, since without it *every*
well-formed file compares as different.
"""

UNCHANGED = "unchanged"
UPDATE = "update"
WARN = "warn"
UNREADABLE = "unreadable"


def read(path):
    """The file's bytes, or None when they cannot be had. Never raises.

    A file caught mid-write, deleted a moment ago, or replaced by a directory
    is an ordinary event here rather than an error: the watcher will settle
    again and ask a second time.
    """
    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def decode(data, charset):
    """`data` as text, or None when it cannot be decoded. Never raises.

    `charset` is the document's own encoding, as xed reports it. It is tried
    first and UTF-8 second, so a document xed opened as ISO-8859-1 is read back
    the same way, while a missing, empty or unrecognised name still gets the
    answer that is right almost always.
    """
    if data is None:
        return None
    for candidate in (charset, "utf-8"):
        if not candidate or not str(candidate).strip():
            continue
        try:
            return data.decode(str(candidate).strip())
        except (LookupError, UnicodeDecodeError):
            continue
    return None


def normalize(text, implicit_trailing_newline):
    """The text a GtkTextBuffer would hold after loading `text` from disk.

    Two conversions, both of them the loader's own:

    - **Line endings.** A buffer always holds `\\n`; CRLF and CR are converted
      on the way in. So a file whose only change is CRLF to LF correctly reads
      as unchanged — the rendered document would be identical.
    - **The implicit trailing newline.** With the flag set (xed's default) the
      final newline is stripped on load and restored on save. Exactly one is
      removed here, so a file deliberately ending in a blank line still differs
      from one that does not.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if implicit_trailing_newline and text.endswith("\n"):
        text = text[:-1]
    return text


def evaluate(disk_bytes, buffer_text, modified, charset, implicit_trailing_newline):
    """Return `(outcome, disk_text)`.

    `disk_text` is None for every outcome but `UPDATE`, where it is the
    normalised text — what the preview should render, and what a reload would
    have produced.

    `UNREADABLE` is not an error condition. It is "ask again later", and the
    caller's correct response to it is to do nothing at all: no error page, no
    dialog, and no disturbance to what the preview is already showing.
    """
    text = decode(disk_bytes, charset)
    if text is None:
        return UNREADABLE, None
    text = normalize(text, implicit_trailing_newline)
    if text == buffer_text:
        return UNCHANGED, None
    if modified:
        return WARN, None
    return UPDATE, text
