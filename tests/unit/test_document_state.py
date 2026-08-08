import pytest
from xedown.document_state import (
    MARKDOWN_SUFFIXES,
    MODE_SETTING_NAMES,
    DocumentState,
    Mode,
    is_markdown_path,
    mode_from_setting,
    setting_name,
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


def test_setting_names_round_trip_through_the_enum():
    for name, mode in MODE_SETTING_NAMES.items():
        assert mode_from_setting(name) is mode
        assert setting_name(mode) == name


def test_source_mode_is_written_as_markdown():
    # The name the user reads in settings.json and modes.json, not the
    # internal one: `Mode.SOURCE.value` is "source" and must never reach a
    # file a user opens.
    assert setting_name(Mode.SOURCE) == "markdown"
    assert setting_name(Mode.PREVIEW) == "preview"


@pytest.mark.parametrize("value", [" Preview ", "MARKDOWN", "Markdown"])
def test_a_hand_typed_name_is_matched_forgivingly(value):
    # Matches how settings.ChoiceSetting already treats a hand-edited value.
    assert mode_from_setting(value) is not None


@pytest.mark.parametrize("value", ["source", "", None, 3, True, "prevew"])
def test_an_unusable_name_answers_none_rather_than_raising(value):
    assert mode_from_setting(value) is None


def test_every_default_mode_setting_choice_is_a_mode():
    # The two files cannot drift: a choice settings.py accepts that this
    # module cannot translate would open every file in the fallback mode.
    from xedown import settings

    for choice in settings.by_name(settings.DEFAULT_MODE).choices:
        assert mode_from_setting(choice) is not None
