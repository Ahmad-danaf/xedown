import json
import pathlib

import pytest
from xedown import shortcuts


def test_the_four_actions_exist_with_the_designed_accelerators():
    assert {action.name: action.accelerator for action in shortcuts.ACTIONS} == {
        shortcuts.TOGGLE: "<Ctrl><Shift>M",
        shortcuts.PREVIEW_MODE: "<Ctrl><Shift>1",
        shortcuts.MARKDOWN_MODE: "<Ctrl><Shift>2",
        shortcuts.REFRESH: "<Ctrl><Shift>R",
    }


def test_the_toggle_keeps_its_v01_identity():
    # v0.1 shipped this name, label and accelerator. An upgrading user's
    # muscle memory and menu entry must not move.
    toggle = next(a for a in shortcuts.ACTIONS if a.name == shortcuts.TOGGLE)
    assert toggle.name == "XedownToggleAction"
    assert toggle.label == "Toggle Markdown _Preview"
    assert toggle.accelerator == "<Ctrl><Shift>M"


def test_no_action_reuses_a_name_an_accelerator_or_a_label():
    for field in ("name", "accelerator", "label"):
        values = [getattr(action, field) for action in shortcuts.ACTIONS]
        assert len(set(values)) == len(values)


def test_every_action_has_a_tooltip_and_a_mnemonic():
    for action in shortcuts.ACTIONS:
        assert action.tooltip
        assert "_" in action.label


def test_ctrl_r_is_never_proposed():
    # xed 3.8.9 binds it to Toggle Word Wrap.
    taken = shortcuts.parse_accelerator("<Control>R")
    assert all(
        shortcuts.parse_accelerator(a.accelerator) != taken for a in shortcuts.ACTIONS
    )


@pytest.mark.parametrize(
    "first,second",
    [
        ("<Primary>A", "<Control>a"),
        ("<ctrl>A", "<Control>A"),
        ("<Shift><Control>G", "<Control><Shift>g"),
        ("<ctrl><shift>a", "<Ctrl><Shift>A"),
    ],
)
def test_the_same_accelerator_spelt_differently_compares_equal(first, second):
    assert shortcuts.parse_accelerator(first) == shortcuts.parse_accelerator(second)


@pytest.mark.parametrize(
    "first,second",
    [
        ("<Control>slash", "<Control>s"),
        ("<Control>question", "<Control>q"),
        ("<Control>Page_Up", "<Control>Page_Down"),
        ("<Control>1", "<Control><Shift>1"),
    ],
)
def test_different_accelerators_stay_different(first, second):
    assert shortcuts.parse_accelerator(first) != shortcuts.parse_accelerator(second)


def test_handled_keys_is_exactly_what_route_key_answers_for():
    assert shortcuts.HANDLED_KEYS == frozenset(
        shortcuts.COPY_KEYS + shortcuts.SELECT_ALL_KEYS
    )


def _route(**overrides):
    call = {
        "key_name": "c",
        "control_only": True,
        "focus_is_editable": False,
        "previewing": True,
    }
    call.update(overrides)
    key_name = call.pop("key_name")
    return shortcuts.route_key(key_name, **call)


def test_ctrl_c_in_the_preview_is_a_copy():
    assert _route(key_name="c") is shortcuts.KeyAction.COPY


def test_ctrl_insert_is_copys_legacy_alias():
    assert _route(key_name="insert") is shortcuts.KeyAction.COPY


def test_ctrl_a_in_the_preview_is_a_select_all():
    assert _route(key_name="a") is shortcuts.KeyAction.SELECT_ALL


def test_another_modifier_is_never_ours():
    # <Ctrl><Shift>A is a bundled xed plugin's "increment number at cursor".
    assert _route(key_name="a", control_only=False) is None


def test_another_key_is_never_ours():
    assert _route(key_name="v") is None
    assert _route(key_name="z") is None


def test_a_key_meant_for_something_the_user_types_into_is_left_alone():
    # xed's find bar, the file browser's rename entry, any dialog entry.
    assert _route(key_name="c", focus_is_editable=True) is None
    assert _route(key_name="a", focus_is_editable=True) is None


def test_nothing_is_taken_while_the_source_is_the_visible_surface():
    assert _route(key_name="c", previewing=False) is None
    assert _route(key_name="a", previewing=False) is None


def test_every_handled_key_is_already_lowercase():
    # The caller (the GTK layer) lowercases key names before passing to
    # route_key, so this function assumes all entries in HANDLED_KEYS are
    # already lowercase. This test ensures that a later contributor who adds
    # a capitalised key to COPY_KEYS or SELECT_ALL_KEYS will see the contract
    # broken loudly rather than silently.
    for key in shortcuts.HANDLED_KEYS:
        assert key == key.lower(), f"Key {key!r} is not lowercase"


def test_capitalized_insert_does_not_match_because_the_caller_lowercases():
    # GDK returns Gdk.keyval_name(Gdk.KEY_Insert) as "Insert" (capitalised).
    # The GTK layer is responsible for lowercasing (via Gdk.keyval_to_lower)
    # before calling route_key. This test exists to pin that contract: if
    # someone removes the `.lower()` call in the GTK layer and expects this
    # function to handle capitalised key names, they will see this test fail
    # and understand the intent.
    assert _route(key_name="Insert") is None


FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "fixtures"
    / "xed-accelerators.json"
)


def _xed():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_extract_is_substantial_enough_to_prove_anything():
    # An empty or near-empty fixture would make the clash test below pass
    # while checking nothing at all.
    xed = _xed()
    assert xed["xed_version"]
    assert len(xed["accelerators"]) >= 20


def test_the_extract_contains_the_accelerator_the_brief_names():
    # Ctrl+R is xed's Toggle Word Wrap. If it is missing from the extract,
    # the extract is not reading what it thinks it is reading.
    taken = {shortcuts.parse_accelerator(a) for a in _xed()["accelerators"]}
    assert shortcuts.parse_accelerator("<Control>R") in taken


def test_no_xedown_accelerator_collides_with_one_of_xeds():
    taken = {shortcuts.parse_accelerator(a) for a in _xed()["accelerators"]}
    for action in shortcuts.ACTIONS:
        assert (
            shortcuts.parse_accelerator(action.accelerator) not in taken
        ), f"{action.accelerator} ({action.name}) is already xed's"
