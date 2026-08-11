"""What the file on disk means for the preview.

The three normalisations are where this module earns its keep. Without the
trailing-newline rule in particular, *every* well-formed file compares as
different and the whole feature fires constantly on files nobody touched.
"""

import pytest
from xedown import diskstate


def evaluate(
    disk,
    buffer_text,
    modified=False,
    charset="UTF-8",
    implicit_trailing_newline=True,
):
    """`diskstate.evaluate` with the arguments this file keeps repeating."""
    if isinstance(disk, str):
        disk = disk.encode("utf-8")
    return diskstate.evaluate(
        disk, buffer_text, modified, charset, implicit_trailing_newline
    )


# --- the four outcomes -------------------------------------------------


def test_matching_content_is_unchanged():
    outcome, text = evaluate("# Notes\n", "# Notes")
    assert outcome == diskstate.UNCHANGED
    assert text is None


def test_a_clean_buffer_over_different_content_is_an_update():
    outcome, text = evaluate("# Rewritten\n", "# Notes")
    assert outcome == diskstate.UPDATE
    assert text == "# Rewritten"


def test_a_modified_buffer_over_different_content_is_a_warning():
    outcome, text = evaluate("# Rewritten\n", "# Notes", modified=True)
    assert outcome == diskstate.WARN
    assert text is None


def test_a_modified_buffer_over_matching_content_is_still_unchanged():
    """Whatever the user typed, they typed it back to what is on disk."""
    outcome, _ = evaluate("# Notes\n", "# Notes", modified=True)
    assert outcome == diskstate.UNCHANGED


def test_absent_bytes_are_unreadable():
    outcome, text = diskstate.evaluate(None, "# Notes", False, "UTF-8", True)
    assert outcome == diskstate.UNREADABLE
    assert text is None


# --- the save-from-xed case, which is the whole point of comparing content --


def test_a_save_from_xed_reads_as_unchanged():
    """xed appends the implicit trailing newline it stripped on load.

    This single case is what makes "saving the file from xed itself must not
    be mistaken for an external change" true with no ignore-flag, no
    suppression window, and no timing assumption anywhere in the plugin.
    """
    buffer_text = "# Notes\n\nA paragraph."
    on_disk = (buffer_text + "\n").encode("utf-8")
    outcome, _ = diskstate.evaluate(on_disk, buffer_text, False, "UTF-8", True)
    assert outcome == diskstate.UNCHANGED


# --- normalisation: the implicit trailing newline ----------------------


def test_one_trailing_newline_is_stripped_when_implicit():
    assert diskstate.normalize("a\n", True) == "a"


def test_only_one_trailing_newline_is_stripped():
    assert diskstate.normalize("a\n\n", True) == "a\n"


def test_no_trailing_newline_is_left_alone():
    assert diskstate.normalize("a", True) == "a"


def test_nothing_is_stripped_when_the_newline_is_not_implicit():
    assert diskstate.normalize("a\n", False) == "a\n"


def test_a_file_without_its_trailing_newline_differs():
    outcome, text = evaluate("# Notes", "# Notes\n")
    assert outcome == diskstate.UPDATE
    assert text == "# Notes"


# --- normalisation: line endings ---------------------------------------


def test_crlf_matches_an_lf_buffer():
    """A GtkTextBuffer always holds \\n; the loader converts on the way in."""
    outcome, _ = evaluate(b"one\r\ntwo\r\n", "one\ntwo")
    assert outcome == diskstate.UNCHANGED


def test_bare_cr_matches_an_lf_buffer():
    outcome, _ = evaluate(b"one\rtwo\r", "one\ntwo")
    assert outcome == diskstate.UNCHANGED


def test_an_update_carries_normalised_text():
    """What the preview renders must be what a reload would have produced."""
    _, text = evaluate(b"# New\r\nbody\r\n", "# Old")
    assert text == "# New\nbody"


# --- normalisation: decoding -------------------------------------------


def test_a_named_charset_is_honoured():
    outcome, text = diskstate.evaluate(
        "héllo\n".encode("latin-1"), "# Old", False, "ISO-8859-1", True
    )
    assert outcome == diskstate.UPDATE
    assert text == "héllo"


def test_an_absent_charset_falls_back_to_utf8():
    for charset in (None, "", "   "):
        outcome, text = diskstate.evaluate(
            "héllo\n".encode(), "# Old", False, charset, True
        )
        assert outcome == diskstate.UPDATE, charset
        assert text == "héllo"


def test_a_charset_python_does_not_know_falls_back_to_utf8():
    outcome, text = diskstate.evaluate(
        "héllo\n".encode(), "# Old", False, "NOT-AN-ENCODING", True
    )
    assert outcome == diskstate.UPDATE
    assert text == "héllo"


def test_undecodable_bytes_are_unreadable():
    outcome, text = diskstate.evaluate(
        b"\xff\xfe\x00\x01", "# Old", False, "UTF-8", True
    )
    assert outcome == diskstate.UNREADABLE
    assert text is None


# --- the empty edges ----------------------------------------------------


def test_an_empty_file_matches_an_empty_buffer():
    outcome, _ = evaluate(b"", "")
    assert outcome == diskstate.UNCHANGED


def test_an_emptied_file_over_a_clean_buffer_is_an_update():
    outcome, text = evaluate(b"", "# Notes")
    assert outcome == diskstate.UPDATE
    assert text == ""


# --- read() never raises ------------------------------------------------


def test_read_returns_the_bytes(tmp_path):
    target = tmp_path / "notes.md"
    target.write_bytes(b"# Notes\n")
    assert diskstate.read(str(target)) == b"# Notes\n"


def test_read_of_a_missing_file_is_none(tmp_path):
    assert diskstate.read(str(tmp_path / "gone.md")) is None


def test_read_of_a_directory_is_none(tmp_path):
    assert diskstate.read(str(tmp_path)) is None


@pytest.mark.parametrize("path", [None, ""])
def test_read_without_a_path_is_none(path):
    assert diskstate.read(path) is None
