import json

import pytest
from xedown import modestore
from xedown.document_state import Mode


@pytest.fixture
def path(tmp_path):
    return tmp_path / "modes.json"


def test_a_remembered_mode_survives_a_reload(path):
    modestore.ModeStore(path).remember("/notes/a.md", Mode.SOURCE)
    assert modestore.ModeStore(path).get("/notes/a.md") is Mode.SOURCE


def test_an_unknown_path_is_not_remembered(path):
    assert modestore.ModeStore(path).get("/notes/never-seen.md") is None


def test_a_document_with_no_path_is_never_stored(path):
    store = modestore.ModeStore(path)
    store.remember(None, Mode.SOURCE)
    store.remember("", Mode.SOURCE)
    assert store.get(None) is None
    assert not path.exists()


def test_the_file_uses_the_user_facing_spelling(path):
    modestore.ModeStore(path).remember("/notes/a.md", Mode.SOURCE)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == modestore.VERSION
    assert stored["modes"] == [["/notes/a.md", "markdown"]]


def test_the_newest_entry_comes_first(path):
    store = modestore.ModeStore(path)
    store.remember("/a.md", Mode.SOURCE)
    store.remember("/b.md", Mode.PREVIEW)
    store.remember("/a.md", Mode.PREVIEW)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert [row[0] for row in stored["modes"]] == ["/a.md", "/b.md"]
    assert store.get("/a.md") is Mode.PREVIEW


def test_the_store_is_bounded_and_drops_from_the_end(path):
    store = modestore.ModeStore(path)
    for index in range(modestore.MAX_ENTRIES + 10):
        store.remember(f"/f{index}.md", Mode.SOURCE)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored["modes"]) == modestore.MAX_ENTRIES
    # The ten oldest are gone; the newest is still there.
    assert store.get("/f0.md") is None
    assert store.get(f"/f{modestore.MAX_ENTRIES + 9}.md") is Mode.SOURCE


def test_a_write_keeps_entries_another_process_added(path):
    first = modestore.ModeStore(path)
    first.remember("/a.md", Mode.SOURCE)
    second = modestore.ModeStore(path)
    second.remember("/b.md", Mode.PREVIEW)
    # `first` never saw /b.md, and must not erase it when it writes again.
    first.remember("/c.md", Mode.SOURCE)
    assert modestore.ModeStore(path).get("/b.md") is Mode.PREVIEW


def test_this_process_wins_a_conflicting_path(path):
    first = modestore.ModeStore(path)
    first.remember("/a.md", Mode.SOURCE)
    modestore.ModeStore(path).remember("/a.md", Mode.PREVIEW)
    first.remember("/a.md", Mode.SOURCE)
    assert modestore.ModeStore(path).get("/a.md") is Mode.SOURCE


def test_rename_moves_an_entry_and_leaves_nothing_behind(path):
    store = modestore.ModeStore(path)
    store.remember("/old.md", Mode.SOURCE)
    store.rename("/old.md", "/new.md")
    assert store.get("/old.md") is None
    assert store.get("/new.md") is Mode.SOURCE
    assert modestore.ModeStore(path).get("/old.md") is None


def test_renaming_something_never_remembered_changes_nothing(path):
    store = modestore.ModeStore(path)
    store.remember("/a.md", Mode.SOURCE)
    store.rename("/never.md", "/other.md")
    assert store.get("/other.md") is None
    assert store.get("/a.md") is Mode.SOURCE


def test_forget_removes_one_entry(path):
    store = modestore.ModeStore(path)
    store.remember("/a.md", Mode.SOURCE)
    store.forget("/a.md")
    assert modestore.ModeStore(path).get("/a.md") is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "{",
        "[]",
        '{"version": 99, "modes": [["/a.md", "markdown"]]}',
        '{"version": 1, "modes": "not a list"}',
        "\xff\xfe not utf-8 at all",
    ],
)
def test_an_unusable_store_loads_empty_and_silently(path, text, capsys):
    path.write_text(text, encoding="utf-8", errors="ignore")
    store = modestore.ModeStore(path)
    assert store.get("/a.md") is None
    # Derived state, not the user's own file: no quarantine copy, and no
    # noise. The brief requires falling back without interrupting the user.
    assert not path.with_name(path.name + ".corrupt").exists()
    assert capsys.readouterr().err == ""


def test_a_malformed_entry_is_skipped_while_its_neighbours_survive(path):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "modes": [
                    ["/good.md", "preview"],
                    ["/bad.md", "sideways"],
                    "not a row",
                    ["/only-one-element.md"],
                    [17, "preview"],
                    ["/also-good.md", "markdown"],
                ],
            }
        ),
        encoding="utf-8",
    )
    store = modestore.ModeStore(path)
    assert store.get("/good.md") is Mode.PREVIEW
    assert store.get("/also-good.md") is Mode.SOURCE
    assert store.get("/bad.md") is None


def test_a_write_that_cannot_land_keeps_the_value_for_the_session(tmp_path):
    unwritable = tmp_path / "ro"
    unwritable.mkdir()
    unwritable.chmod(0o500)
    try:
        store = modestore.ModeStore(unwritable / "modes.json")
        store.remember("/a.md", Mode.SOURCE)
        assert store.get("/a.md") is Mode.SOURCE
    finally:
        unwritable.chmod(0o700)


def test_a_write_leaves_no_temporary_file_behind(path):
    modestore.ModeStore(path).remember("/a.md", Mode.SOURCE)
    assert not path.with_name(path.name + ".tmp").exists()


def test_the_store_lives_beside_settings_json(monkeypatch, tmp_path):
    monkeypatch.setenv("XEDOWN_CONFIG_DIR", str(tmp_path))
    assert modestore.default_path() == tmp_path / modestore.STORE_NAME
