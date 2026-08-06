import json
import pathlib

import pytest
from xedown import settings

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PREVIEW_CSS = ROOT / "plugin" / "xedown" / "resources" / "preview.css"
CONTROLLER = ROOT / "plugin" / "xedown" / "controller.py"


def test_every_setting_has_the_documented_default():
    assert settings.defaults() == {
        "default_mode": "preview",
        "remember_mode_per_file": True,
        "preview_theme": "github",
        "custom_stylesheet": None,
        "content_width_rem": 46.0,
        "text_size_px": 16.0,
        "auto_refresh": True,
        "refresh_delay_ms": 250,
        "remote_images": "placeholder",
        "code_copy_buttons": True,
        "text_direction": "auto",
        "watch_external_changes": True,
    }


def test_defaults_are_a_fresh_copy_each_time():
    first = settings.defaults()
    first["preview_theme"] = "cursor"
    assert settings.defaults()["preview_theme"] == "github"


def test_an_unknown_setting_name_is_a_programming_error():
    with pytest.raises(KeyError):
        settings.by_name("prevew_theme")


def test_content_width_default_still_matches_the_live_stylesheet():
    css = PREVIEW_CSS.read_text(encoding="utf-8")
    expected = settings.defaults()["content_width_rem"]
    assert f"max-width: {expected:g}rem;" in css, (
        "the default must stay today's value; if preview.css changed "
        "deliberately, change the default with it"
    )


def test_text_size_default_still_matches_the_live_stylesheet():
    css = PREVIEW_CSS.read_text(encoding="utf-8")
    expected = settings.defaults()["text_size_px"]
    assert f"font-size: {expected:g}px;" in css


def test_refresh_delay_default_still_matches_the_live_constant():
    source = CONTROLLER.read_text(encoding="utf-8")
    expected = settings.defaults()["refresh_delay_ms"]
    assert f"REFRESH_DELAY_MS = {expected}" in source


@pytest.mark.parametrize(
    "name,given,expected",
    [
        ("preview_theme", "GitHub", "github"),
        ("preview_theme", "  minimal  ", "minimal"),
        ("default_mode", "MARKDOWN", "markdown"),
        ("text_direction", "RTL", "rtl"),
        ("remote_images", "Hidden", "hidden"),
    ],
)
def test_choices_are_matched_ignoring_case_and_space(name, given, expected):
    assert settings.by_name(name).coerce(given) == (expected, True)


@pytest.mark.parametrize(
    "given", ["cursorish", "", "   ", 3, None, True, ["github"], {"t": "github"}]
)
def test_an_unusable_choice_falls_back_to_the_default(given):
    assert settings.by_name("preview_theme").coerce(given) == ("github", False)


@pytest.mark.parametrize("given", [True, False])
def test_real_booleans_are_accepted(given):
    assert settings.by_name("auto_refresh").coerce(given) == (given, True)


@pytest.mark.parametrize("given", ["true", "false", "on", "yes", 1, 0, None])
def test_boolean_lookalikes_are_refused(given):
    assert settings.by_name("auto_refresh").coerce(given) == (True, False)


@pytest.mark.parametrize(
    "given,expected",
    [
        (30, 30.0),
        (46, 46.0),
        (100, 100.0),
        (46.5, 46.5),
        (29.9, 30.0),
        (1, 30.0),
        (-500, 30.0),
        (100.1, 100.0),
        (10_000, 100.0),
    ],
)
def test_a_number_is_clamped_into_range_rather_than_rejected(given, expected):
    assert settings.by_name("content_width_rem").coerce(given) == (expected, True)


@pytest.mark.parametrize(
    "given,expected", [(11, 11.0), (2, 11.0), (28, 28.0), (99, 28.0)]
)
def test_text_size_is_clamped_into_range(given, expected):
    assert settings.by_name("text_size_px").coerce(given) == (expected, True)


@pytest.mark.parametrize(
    "given,expected", [(50, 50), (250, 250), (2000, 2000), (0, 50), (99999, 2000)]
)
def test_refresh_delay_is_clamped_into_range(given, expected):
    assert settings.by_name("refresh_delay_ms").coerce(given) == (expected, True)


def test_refresh_delay_is_rounded_to_a_whole_millisecond():
    value, ok = settings.by_name("refresh_delay_ms").coerce(300.6)
    assert (value, ok) == (301, True)
    assert isinstance(value, int)


@pytest.mark.parametrize("given", [True, False])
def test_a_boolean_is_not_a_number(given):
    # isinstance(True, int) is true in Python, so a stored `true` would
    # otherwise become 1 and clamp to the minimum width.
    assert settings.by_name("content_width_rem").coerce(given) == (46.0, False)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_the_json_float_literals_are_refused(literal):
    # json.loads accepts all three by default; none of them can be clamped.
    setting = settings.by_name("content_width_rem")
    assert setting.coerce(json.loads(literal)) == (46.0, False)


@pytest.mark.parametrize("given", ["46", None, [46], {"rem": 46}])
def test_a_non_number_falls_back_to_the_default(given):
    assert settings.by_name("content_width_rem").coerce(given) == (46.0, False)


@pytest.mark.parametrize(
    "name,given,expected",
    [
        ("content_width_rem", 10**400, 100.0),
        ("content_width_rem", -(10**400), 30.0),
        ("refresh_delay_ms", 10**400, 2000),
        ("text_size_px", -(10**400), 11.0),
    ],
)
def test_an_enormous_integer_is_clamped_rather_than_crashing(name, given, expected):
    # JSON integers are unbounded, so a hand-edited file can hold one too
    # large to convert to a C double. `math.isnan`/`isinf` raise
    # OverflowError on those, which would turn a bad setting into a crash --
    # the one thing this module exists to prevent.
    assert settings.by_name(name).coerce(given) == (expected, True)


@pytest.mark.parametrize(
    "given,expected",
    [
        ("/home/me/style.css", "/home/me/style.css"),
        ("  /home/me/style.css  ", "/home/me/style.css"),
        ("~/style.css", "~/style.css"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_a_stylesheet_path_is_kept_exactly_as_written(given, expected):
    assert settings.by_name("custom_stylesheet").coerce(given) == (expected, True)


@pytest.mark.parametrize("given", [42, True, ["/a"], {"path": "/a"}])
def test_a_non_string_stylesheet_value_is_refused(given):
    assert settings.by_name("custom_stylesheet").coerce(given) == (None, False)


def _store(tmp_path, text=None):
    """A Settings over tmp_path/settings.json, optionally pre-seeded."""
    path = tmp_path / "settings.json"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return settings.Settings(path)


def test_a_missing_file_gives_defaults_and_creates_nothing(tmp_path):
    store = _store(tmp_path)
    assert store.get("preview_theme") == "github"
    assert not (tmp_path / "settings.json").exists()


def test_a_stored_value_is_used(tmp_path):
    store = _store(tmp_path, '{"preview_theme": "cursor"}')
    assert store.get("preview_theme") == "cursor"


def test_the_store_reads_the_file_only_once(tmp_path):
    store = _store(tmp_path, '{"preview_theme": "cursor"}')
    (tmp_path / "settings.json").write_text(
        '{"preview_theme": "minimal"}', encoding="utf-8"
    )
    assert store.get("preview_theme") == "cursor"


def test_getting_an_unknown_setting_raises(tmp_path):
    with pytest.raises(KeyError):
        _store(tmp_path).get("who_knows")


@pytest.mark.parametrize("text", ["", "\n", "   \n  \t\n"])
def test_a_blank_file_is_not_treated_as_corruption(tmp_path, text):
    # Nothing in it to preserve, and this is exactly what a truncated write
    # or a `: > settings.json` leaves behind.
    store = _store(tmp_path, text)
    assert store.get("preview_theme") == "github"
    assert not (tmp_path / "settings.json.corrupt").exists()


@pytest.mark.parametrize(
    "text", ['{"preview_theme": "cursor"', "not json at all", '{"a": }', "{"]
)
def test_unparseable_json_is_quarantined(tmp_path, text):
    store = _store(tmp_path, text)
    assert store.get("preview_theme") == "github"
    assert (tmp_path / "settings.json.corrupt").read_text(encoding="utf-8") == text
    assert not (tmp_path / "settings.json").exists()


@pytest.mark.parametrize("text", ["[]", '"github"', "42", "null", "true"])
def test_json_that_is_not_an_object_is_quarantined(tmp_path, text):
    store = _store(tmp_path, text)
    assert store.get("preview_theme") == "github"
    assert (tmp_path / "settings.json.corrupt").read_text(encoding="utf-8") == text


def test_an_unreadable_store_falls_back_to_defaults(tmp_path):
    # A directory where the file belongs. Chosen over chmod because it fails
    # for root too, so the test cannot pass by accident on a runner that
    # happens to be root.
    path = tmp_path / "settings.json"
    path.mkdir()
    assert settings.Settings(path).get("preview_theme") == "github"


def test_a_file_of_invalid_utf8_bytes_is_quarantined(tmp_path):
    # A write truncated mid-multibyte-character. `read_text` raises
    # UnicodeDecodeError -- a ValueError, not an OSError -- so a handler that
    # names only OSError lets it escape. Worse, the escape happens before the
    # quarantine, so the same file would break every later launch too.
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"preview_theme": "curs\xff\xfe')
    store = settings.Settings(path)
    assert store.get("preview_theme") == "github"
    assert (tmp_path / "settings.json.corrupt").exists()


def test_deeply_nested_json_is_quarantined(tmp_path):
    # json.loads raises RecursionError -- a RuntimeError, not a ValueError.
    path = tmp_path / "settings.json"
    path.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")
    store = settings.Settings(path)
    assert store.get("preview_theme") == "github"
    assert (tmp_path / "settings.json.corrupt").exists()


def test_the_quarantine_message_names_both_paths(tmp_path, capsys):
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    settings.Settings(path)
    message = capsys.readouterr().err
    assert str(path) in message
    assert str(path) + ".corrupt" in message


def test_a_second_corruption_replaces_the_first_preserved_copy(tmp_path):
    # A deliberate tradeoff, pinned here so changing it is a decision rather
    # than an accident: a fixed name keeps the config directory from growing
    # without bound and gives the preferences window a path it can always
    # quote.
    path = tmp_path / "settings.json"
    path.write_text("first broken copy", encoding="utf-8")
    settings.Settings(path)
    path.write_text("second broken copy", encoding="utf-8")
    settings.Settings(path)
    preserved = tmp_path / "settings.json.corrupt"
    assert preserved.read_text(encoding="utf-8") == "second broken copy"


def test_unknown_keys_are_ignored_without_quarantine(tmp_path):
    store = _store(tmp_path, '{"preview_theme": "cursor", "who_knows": 1}')
    assert store.get("preview_theme") == "cursor"
    assert not (tmp_path / "settings.json.corrupt").exists()


def test_a_wrong_typed_value_defaults_without_touching_its_neighbours(tmp_path):
    store = _store(tmp_path, '{"auto_refresh": "yes", "preview_theme": "minimal"}')
    assert store.get("auto_refresh") is True
    assert store.get("preview_theme") == "minimal"


def test_an_out_of_range_value_is_clamped_on_load(tmp_path):
    store = _store(tmp_path, '{"content_width_rem": 5000, "text_size_px": 2}')
    assert store.get("content_width_rem") == 100.0
    assert store.get("text_size_px") == 11.0


def test_a_mis_cased_choice_is_accepted_on_load(tmp_path):
    store = _store(tmp_path, '{"preview_theme": "GitHub"}')
    assert store.get("preview_theme") == "github"


def test_a_hand_edited_disaster_still_loads(tmp_path):
    # Every failure mode at once: wrong types, out of range, a misspelled
    # key, a mis-cased choice. None of it may stop the plugin loading.
    broken = {
        "default_mode": "Markdown",
        "auto_refresh": "no",
        "content_width_rem": "wide",
        "text_size_px": 9999,
        "refresh_dely_ms": 10,
        "custom_stylesheet": 42,
    }
    store = _store(tmp_path, json.dumps(broken))
    assert store.get("default_mode") == "markdown"
    assert store.get("auto_refresh") is True
    assert store.get("content_width_rem") == 46.0
    assert store.get("text_size_px") == 28.0
    assert store.get("refresh_delay_ms") == 250
    assert store.get("custom_stylesheet") is None


def test_a_value_survives_a_restart(tmp_path):
    path = tmp_path / "settings.json"
    settings.Settings(path).set("preview_theme", "cursor")
    assert settings.Settings(path).get("preview_theme") == "cursor"


def test_set_reports_whether_anything_changed(tmp_path):
    store = _store(tmp_path)
    assert store.set("preview_theme", "cursor") is True
    assert store.set("preview_theme", "cursor") is False


def test_a_no_op_set_does_not_write(tmp_path):
    store = _store(tmp_path)
    path = tmp_path / "settings.json"
    path.write_text("SENTINEL: not valid JSON", encoding="utf-8")
    assert store.set("preview_theme", "github") is False
    assert path.read_text(encoding="utf-8") == "SENTINEL: not valid JSON"


def test_an_out_of_range_value_is_clamped_on_the_way_in(tmp_path):
    store = _store(tmp_path)
    assert store.set("content_width_rem", 9999) is True
    assert store.get("content_width_rem") == 100.0


def test_an_unusable_value_from_our_own_code_raises(tmp_path):
    # Bad data from the user's file is forgiven; bad data from a caller is a
    # bug, and swallowing it would let a broken preferences window look like
    # a working save.
    with pytest.raises(ValueError):
        _store(tmp_path).set("auto_refresh", "yes")


def test_an_unknown_name_raises_on_write_too(tmp_path):
    with pytest.raises(KeyError):
        _store(tmp_path).set("prevew_theme", "cursor")


def test_a_rejected_set_many_changes_nothing_at_all(tmp_path):
    # Everything is validated before anything is applied, so a bad value
    # late in the mapping cannot leave a half-applied change behind.
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.set_many({"preview_theme": "cursor", "auto_refresh": "yes"})
    assert store.get("preview_theme") == "github"
    assert not (tmp_path / "settings.json").exists()


def test_set_many_reports_only_what_moved(tmp_path):
    store = _store(tmp_path)
    changed = store.set_many({"preview_theme": "cursor", "auto_refresh": True})
    assert changed == frozenset({"preview_theme"})


def test_reset_restores_every_default(tmp_path):
    store = _store(tmp_path)
    store.set_many({"preview_theme": "cursor", "text_size_px": 22})
    assert store.reset() == frozenset({"preview_theme", "text_size_px"})
    assert store.get("preview_theme") == "github"
    assert store.get("text_size_px") == 16.0


def test_reset_survives_a_restart(tmp_path):
    path = tmp_path / "settings.json"
    store = settings.Settings(path)
    store.set("preview_theme", "cursor")
    store.reset()
    assert settings.Settings(path).get("preview_theme") == "github"


def test_the_file_is_readable_json(tmp_path):
    store = _store(tmp_path)
    store.set("preview_theme", "cursor")
    text = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert json.loads(text)["preview_theme"] == "cursor"
    assert text.endswith("\n")


def test_a_key_this_version_does_not_know_survives_a_write(tmp_path):
    # A newer xedown's setting after a downgrade, or a note the user added.
    path = tmp_path / "settings.json"
    path.write_text('{"who_knows": "keep me"}', encoding="utf-8")
    settings.Settings(path).set("preview_theme", "cursor")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["who_knows"] == "keep me"
    assert stored["preview_theme"] == "cursor"


def test_a_second_process_does_not_clobber_the_first(tmp_path):
    # Two xed processes, which `xed --standalone` allows. Neither may undo
    # the other's saved settings.
    path = tmp_path / "settings.json"
    first = settings.Settings(path)
    second = settings.Settings(path)
    first.set("preview_theme", "cursor")
    second.set("text_size_px", 22)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["preview_theme"] == "cursor"
    assert stored["text_size_px"] == 22


def test_a_write_survives_the_file_being_replaced_underneath(tmp_path):
    # Another process, or the user, replaced the store between load and save.
    # Re-reading it for the merge must not become the thing that fails --
    # the same untrusted-content problem `_load` has, in the write path.
    store = _store(tmp_path)
    path = tmp_path / "settings.json"
    path.write_text("[" * 20_000 + "]" * 20_000, encoding="utf-8")
    assert store.set("preview_theme", "cursor") is True
    assert store.get("preview_theme") == "cursor"
    assert json.loads(path.read_text(encoding="utf-8")) == {"preview_theme": "cursor"}


def test_a_failed_write_keeps_the_value_and_records_why(tmp_path):
    # A directory sitting exactly where the temp file must go. Chosen over
    # chmod because it fails for root too. This deliberately couples the
    # test to the temp file's name: that name is part of how the atomic
    # write works, and pinning it is cheaper than an unreliable test.
    (tmp_path / "settings.json.tmp").mkdir()
    store = _store(tmp_path)
    assert store.set("preview_theme", "cursor") is True
    assert store.get("preview_theme") == "cursor"
    assert store.write_error is not None


def test_a_later_successful_write_clears_the_error(tmp_path):
    blocker = tmp_path / "settings.json.tmp"
    blocker.mkdir()
    store = _store(tmp_path)
    store.set("preview_theme", "cursor")
    assert store.write_error is not None
    blocker.rmdir()
    store.set("preview_theme", "minimal")
    assert store.write_error is None


def test_the_config_directory_is_created_on_first_write(tmp_path):
    path = tmp_path / "nested" / "deeper" / "settings.json"
    settings.Settings(path).set("preview_theme", "cursor")
    assert path.exists()


def test_a_write_after_a_quarantine_starts_clean(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    store = settings.Settings(path)
    store.set("preview_theme", "cursor")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {"preview_theme": "cursor"}


def test_a_listener_is_told_what_changed(tmp_path):
    store = _store(tmp_path)
    seen = []
    store.connect(seen.append)
    store.set("preview_theme", "cursor")
    assert seen == [frozenset({"preview_theme"})]


def test_set_many_notifies_once(tmp_path):
    store = _store(tmp_path)
    seen = []
    store.connect(seen.append)
    store.set_many({"preview_theme": "cursor", "text_size_px": 22})
    assert seen == [frozenset({"preview_theme", "text_size_px"})]


def test_a_no_op_set_notifies_nobody(tmp_path):
    store = _store(tmp_path)
    seen = []
    store.connect(seen.append)
    store.set("preview_theme", "github")
    assert seen == []


def test_every_listener_hears_about_a_change(tmp_path):
    store = _store(tmp_path)
    first, second = [], []
    store.connect(first.append)
    store.connect(second.append)
    store.set("preview_theme", "cursor")
    assert first == second == [frozenset({"preview_theme"})]


def test_disconnect_stops_delivery(tmp_path):
    store = _store(tmp_path)
    seen = []
    token = store.connect(seen.append)
    store.disconnect(token)
    store.set("preview_theme", "cursor")
    assert seen == []


def test_disconnecting_twice_is_harmless(tmp_path):
    store = _store(tmp_path)
    seen = []
    token = store.connect(seen.append)
    store.disconnect(token)
    store.disconnect(token)
    store.set("preview_theme", "cursor")
    assert seen == []


def test_a_listener_sees_the_new_value(tmp_path):
    store = _store(tmp_path)
    seen = []
    store.connect(lambda changed: seen.append(store.get("preview_theme")))
    store.set("preview_theme", "cursor")
    assert seen == ["cursor"]


def test_a_listener_that_raises_does_not_stop_the_others(tmp_path):
    store = _store(tmp_path)
    seen = []

    def explode(changed):
        raise RuntimeError("this listener is broken")

    store.connect(explode)
    store.connect(seen.append)
    store.set("preview_theme", "cursor")
    assert seen == [frozenset({"preview_theme"})]


def test_a_listener_that_raises_does_not_fail_the_write(tmp_path):
    path = tmp_path / "settings.json"
    store = settings.Settings(path)

    def explode(changed):
        raise RuntimeError("this listener is broken")

    store.connect(explode)
    store.set("preview_theme", "cursor")
    assert settings.Settings(path).get("preview_theme") == "cursor"


def test_a_listener_may_disconnect_another_mid_broadcast(tmp_path):
    # A controller torn down in response to something must not then be
    # called by the broadcast it was already part of.
    store = _store(tmp_path)
    calls = []
    tokens = {}

    def first(changed):
        calls.append("first")
        store.disconnect(tokens["second"])

    tokens["first"] = store.connect(first)
    tokens["second"] = store.connect(lambda changed: calls.append("second"))
    store.set("preview_theme", "cursor")
    assert calls == ["first"]


def test_a_listener_still_runs_when_the_write_failed(tmp_path):
    # The change is live for the session either way; a listener that skipped
    # its work here would leave the preview disagreeing with the setting the
    # user just chose.
    (tmp_path / "settings.json.tmp").mkdir()
    store = _store(tmp_path)
    seen = []
    store.connect(seen.append)
    store.set("preview_theme", "cursor")
    assert seen == [frozenset({"preview_theme"})]


def test_the_environment_override_wins(monkeypatch, tmp_path):
    # The live harnesses set this so a test run cannot rewrite -- or
    # quarantine -- the developer's own settings file.
    monkeypatch.setenv("XEDOWN_CONFIG_DIR", str(tmp_path / "scratch"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert settings.default_config_dir() == tmp_path / "scratch"


def test_xdg_config_home_is_honoured(monkeypatch, tmp_path):
    monkeypatch.delenv("XEDOWN_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert settings.default_config_dir() == tmp_path / "xdg" / "xedown"


def test_the_fallback_is_dot_config(monkeypatch):
    monkeypatch.delenv("XEDOWN_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/somebody")
    expected = pathlib.Path("/home/somebody/.config/xedown")
    assert settings.default_config_dir() == expected


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_override_is_ignored(monkeypatch, blank):
    # The XDG spec says an unset *or empty* value falls back to $HOME/.config.
    monkeypatch.setenv("XEDOWN_CONFIG_DIR", blank)
    monkeypatch.setenv("XDG_CONFIG_HOME", blank)
    monkeypatch.setenv("HOME", "/home/somebody")
    expected = pathlib.Path("/home/somebody/.config/xedown")
    assert settings.default_config_dir() == expected


def test_the_store_file_is_named_settings_json(monkeypatch, tmp_path):
    monkeypatch.setenv("XEDOWN_CONFIG_DIR", str(tmp_path))
    assert settings.default_path() == tmp_path / "settings.json"


def test_every_caller_shares_one_store(monkeypatch, tmp_path):
    # monkeypatch.setattr restores the singleton afterwards, so this test
    # cannot leak a store built against tmp_path into another test.
    monkeypatch.setenv("XEDOWN_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "_INSTANCE", None)
    store = settings.get_settings()
    assert settings.get_settings() is store
    assert store.path == tmp_path / "settings.json"
