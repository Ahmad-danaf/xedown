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
