import pytest
from xedown.document_state import (
    MARKDOWN_SUFFIXES,
    DocumentState,
    Mode,
    is_markdown_path,
)


@pytest.mark.parametrize(
    "path",
    ["notes.md", "notes.markdown", "NOTES.MD", "a/b/Read.Markdown", "/tmp/x.Md"],
)
def test_markdown_paths_are_recognised_case_insensitively(path):
    assert is_markdown_path(path) is True


@pytest.mark.parametrize("path", ["notes.txt", "notes", "notes.mdx", "md", None, ""])
def test_non_markdown_paths_are_rejected(path):
    assert is_markdown_path(path) is False


def test_suffixes_are_lowercase_and_dotted():
    assert MARKDOWN_SUFFIXES == (".md", ".markdown")


def test_preview_is_the_default_mode():
    assert DocumentState().mode is Mode.PREVIEW


def test_toggle_switches_and_returns_new_mode():
    state = DocumentState()
    assert state.toggle() is Mode.SOURCE
    assert state.mode is Mode.SOURCE
    assert state.toggle() is Mode.PREVIEW


def test_scroll_is_remembered_per_mode_independently():
    state = DocumentState()
    state.store_scroll(Mode.PREVIEW, 0.25)
    state.store_scroll(Mode.SOURCE, 0.75)
    assert state.scroll_for(Mode.PREVIEW) == 0.25
    assert state.scroll_for(Mode.SOURCE) == 0.75


def test_new_state_starts_stale_so_first_switch_renders():
    assert DocumentState().preview_stale is True
