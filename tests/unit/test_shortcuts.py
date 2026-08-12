import json
import pathlib

import pytest
from xedown import shortcuts


def test_every_action_exists_with_its_designed_accelerator():
    assert {action.name: action.accelerator for action in shortcuts.ACTIONS} == {
        shortcuts.TOGGLE: "<Ctrl><Shift>M",
        shortcuts.PREVIEW_MODE: "<Ctrl><Shift>1",
        shortcuts.MARKDOWN_MODE: "<Ctrl><Shift>2",
        shortcuts.REFRESH: "<Ctrl><Shift>R",
        # No accelerator on purpose -- see shortcuts.SETTINGS's Action entry.
        shortcuts.SETTINGS: None,
    }


def test_the_digit_actions_carry_a_shifted_symbol_alias():
    # <Ctrl><Shift>1 and <Ctrl><Shift>2 are what the menu shows and a user
    # presses, but on a layout where Shift+digit produces a symbol (US, UK,
    # most Latin QWERTY layouts) that is never what GTK actually receives --
    # see Action's docstring. The alias is the spelling that fires there.
    # Toggle and Refresh are letters, unaffected by the same translation, so
    # they carry none.
    assert {action.name: action.aliases for action in shortcuts.ACTIONS} == {
        shortcuts.TOGGLE: (),
        shortcuts.PREVIEW_MODE: ("<Ctrl><Shift>exclam",),
        shortcuts.MARKDOWN_MODE: ("<Ctrl><Shift>at",),
        shortcuts.REFRESH: (),
        shortcuts.SETTINGS: (),
    }


def test_the_toggle_keeps_its_v01_identity():
    # v0.1 shipped this name, label and accelerator. An upgrading user's
    # muscle memory and menu entry must not move.
    toggle = next(a for a in shortcuts.ACTIONS if a.name == shortcuts.TOGGLE)
    assert toggle.name == "XedownToggleAction"
    assert toggle.label == "Toggle Markdown _Preview"
    assert toggle.accelerator == "<Ctrl><Shift>M"


def test_no_action_reuses_a_name_an_accelerator_or_a_label():
    for field in ("name", "label"):
        values = [getattr(action, field) for action in shortcuts.ACTIONS]
        assert len(set(values)) == len(values)

    # Accelerators are checked separately because an action is allowed to
    # have none, and two actions having none is not a collision.
    bound = [a.accelerator for a in shortcuts.ACTIONS if a.accelerator is not None]
    assert len(set(bound)) == len(bound)

    # Primary and alias accelerators share one namespace: an alias that
    # collided with another action's primary (or another action's alias)
    # would be just as broken as two actions sharing a primary outright, and
    # nothing above would catch it since it only looks at `accelerator`.
    all_accelerators = [
        shortcuts.parse_accelerator(accel)
        for action in shortcuts.ACTIONS
        for accel in (action.accelerator, *action.aliases)
        if accel is not None
    ]
    assert len(set(all_accelerators)) == len(all_accelerators)


def test_every_action_has_a_tooltip_and_a_mnemonic():
    for action in shortcuts.ACTIONS:
        assert action.tooltip
        assert "_" in action.label


def test_the_settings_action_exists_and_binds_no_key():
    action = next(a for a in shortcuts.ACTIONS if a.name == shortcuts.SETTINGS)
    assert action.accelerator is None
    assert action.aliases == ()
    assert action.label == "Markdown Preview _Settings"


def test_settings_is_the_only_action_that_survives_a_non_markdown_file():
    relaxed = [a.name for a in shortcuts.ACTIONS if not a.requires_markdown]
    assert relaxed == [shortcuts.SETTINGS]


def test_every_other_action_still_requires_a_markdown_document():
    for action in shortcuts.ACTIONS:
        if action.name != shortcuts.SETTINGS:
            assert action.requires_markdown


def test_ctrl_r_is_never_proposed():
    # xed 3.8.9 binds it to Toggle Word Wrap.
    taken = shortcuts.parse_accelerator("<Control>R")
    assert all(
        shortcuts.parse_accelerator(a.accelerator) != taken
        for a in shortcuts.ACTIONS
        if a.accelerator is not None
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


def test_every_key_route_key_answers_for_is_in_handled_keys():
    # __init__.py's `_on_key_press` only ever calls `route_key` for a key
    # already in `HANDLED_KEYS` -- that short-circuit is what keeps every
    # other key press in the window from paying for a full route_key call,
    # but it also means a key route_key WOULD answer for, that HANDLED_KEYS
    # does not list, would never reach route_key at all: not merely
    # untested, silently unreachable. This drives route_key itself over a
    # broad keyspace under the one call shape that can make it answer
    # (control held, focus elsewhere, previewing) and checks the actual
    # containment property, rather than re-deriving HANDLED_KEYS from the
    # same two tuples it is built from -- which is true by construction and
    # cannot fail no matter how badly the two drift apart.
    keyspace = (
        [chr(c) for c in range(ord("a"), ord("z") + 1)]
        + [str(digit) for digit in range(10)]
        + [
            "insert",
            "delete",
            "tab",
            "space",
            "escape",
            "return",
            "home",
            "end",
            "page_up",
            "page_down",
            "up",
            "down",
            "left",
            "right",
        ]
        + [f"f{n}" for n in range(1, 13)]
    )
    for key_name in keyspace:
        action = shortcuts.route_key(
            key_name, control_only=True, focus_is_editable=False, previewing=True
        )
        if action is not None:
            assert key_name in shortcuts.HANDLED_KEYS, (
                f"route_key answers for {key_name!r} but HANDLED_KEYS omits "
                "it, so __init__.py's short-circuit would never let it reach "
                "route_key at all"
            )


def _route(**overrides):
    call = {
        "key_name": "c",
        "control_only": True,
        "focus_is_editable": False,
        "previewing": True,
        "focus_in_preview_search": False,
        "search_open": False,
        "no_modifier": False,
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


def test_ctrl_f_in_the_preview_opens_xedowns_own_find():
    assert _route(key_name="f") is shortcuts.KeyAction.FIND


def test_ctrl_f_over_the_source_is_xeds_own_find():
    assert _route(key_name="f", previewing=False) is None


def test_ctrl_f_inside_someone_elses_entry_is_theirs():
    # xed's find bar, the file browser's rename box, any dialog entry.
    assert _route(key_name="f", focus_is_editable=True) is None


def test_ctrl_f_inside_our_own_search_entry_is_still_ours():
    # Pressing it again re-selects the query so typing replaces it, rather
    # than opening xed's find over a preview it does not control.
    assert (
        _route(key_name="f", focus_is_editable=True, focus_in_preview_search=True)
        is shortcuts.KeyAction.FIND
    )


def test_copy_and_select_all_inside_our_search_entry_stay_the_entrys():
    # The entry is a GtkEditable, so the existing guard already defers to it;
    # this pins that adding the search flags did not change it.
    for key in ("c", "a", "insert"):
        assert (
            _route(key_name=key, focus_is_editable=True, focus_in_preview_search=True)
            is None
        )


def test_escape_closes_an_open_preview_search():
    assert (
        _route(
            key_name="escape", control_only=False, no_modifier=True, search_open=True
        )
        is shortcuts.KeyAction.CLOSE_SEARCH
    )


def test_escape_with_no_search_open_belongs_to_the_host():
    assert (
        _route(
            key_name="escape", control_only=False, no_modifier=True, search_open=False
        )
        is None
    )


def test_escape_over_the_source_belongs_to_the_host():
    assert (
        _route(
            key_name="escape",
            control_only=False,
            no_modifier=True,
            previewing=False,
            search_open=True,
        )
        is None
    )


def test_escape_in_someone_elses_entry_is_theirs():
    # xed's own find bar closes on Escape, and must keep doing so even while
    # xedown's bar happens to be open in the same tab.
    assert (
        _route(
            key_name="escape",
            control_only=False,
            no_modifier=True,
            search_open=True,
            focus_is_editable=True,
        )
        is None
    )


def test_escape_in_our_own_entry_closes_our_bar():
    assert (
        _route(
            key_name="escape",
            control_only=False,
            no_modifier=True,
            search_open=True,
            focus_is_editable=True,
            focus_in_preview_search=True,
        )
        is shortcuts.KeyAction.CLOSE_SEARCH
    )


def test_a_modified_escape_is_never_ours():
    assert (
        _route(
            key_name="escape", control_only=True, no_modifier=False, search_open=True
        )
        is None
    )


def test_the_unmodified_keyspace_is_exactly_escape():
    # __init__.py short-circuits on this set before looking at anything else,
    # so a key added here is a key xedown starts inspecting on every press.
    assert shortcuts.UNMODIFIED_KEYS == frozenset({"escape"})


def test_find_is_a_routed_key_not_an_accelerator():
    # Ctrl+F reaches the preview through the key hook, like copy. Registering
    # it as an accelerator would take it from xed in Markdown mode too, and
    # would put it in front of the clash fixture as a collision with xed's own
    # <control>F.
    assert "f" in shortcuts.HANDLED_KEYS
    assert all(
        action.accelerator is None or "F" not in action.accelerator
        for action in shortcuts.ACTIONS
    )


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
    # Covers aliases too, not just primaries: an alias that collided with
    # one of xed's own accelerators would be just as broken as a primary
    # doing so -- it is the spelling that actually fires on some layouts.
    taken = {shortcuts.parse_accelerator(a) for a in _xed()["accelerators"]}
    for action in shortcuts.ACTIONS:
        for accel in (action.accelerator, *action.aliases):
            if accel is None:
                continue
            assert (
                shortcuts.parse_accelerator(accel) not in taken
            ), f"{accel} ({action.name}) is already xed's"
