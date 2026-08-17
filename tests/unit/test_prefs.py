import pytest
from xedown import a11y, prefs, settings, themes


def test_every_setting_appears_exactly_once():
    named = [row.setting for row in prefs.rows()]
    assert sorted(named) == sorted(setting.name for setting in settings.SETTINGS)
    assert len(named) == len(set(named))


def test_no_row_names_a_setting_that_does_not_exist():
    for row in prefs.rows():
        # Raises KeyError for an unknown name, which is the assertion.
        settings.by_name(row.setting)


def test_the_groups_are_the_four_the_brief_asked_for():
    assert [group.title for group in prefs.GROUPS] == [
        "How files open",
        "How the preview looks",
        "How it refreshes",
        "Images and changes made outside xed",
    ]


def test_every_row_takes_its_label_from_the_accessibility_standard():
    for row in prefs.rows():
        assert row.label == a11y.NAMES[row.key]
        assert row.label.strip()


def test_every_settings_window_name_is_used_by_exactly_one_control():
    declared = {row.key for row in prefs.rows()} | set(prefs.EXTRA_KEYS)
    in_standard = {key for key in a11y.NAMES if key.startswith("prefs_")}
    assert declared == in_standard
    assert len(prefs.rows()) + len(prefs.EXTRA_KEYS) == len(in_standard)


def test_every_settings_window_name_can_be_read_aloud():
    for key in a11y.NAMES:
        if key.startswith("prefs_"):
            # The same rule brief 13 applies to every other control.
            assert not a11y.check_node(
                a11y.node(key=key, name=a11y.NAMES[key], role="push button")
            )


def test_number_rows_take_their_bounds_from_the_validator():
    for row in prefs.rows():
        if row.kind != prefs.NUMBER:
            continue
        setting = settings.by_name(row.setting)
        assert prefs.bounds(row) == (
            setting.minimum,
            setting.maximum,
            setting.integer,
        )
        assert row.step > 0
        assert row.page_step >= row.step
        assert row.unit


def test_choice_rows_offer_exactly_the_values_the_validator_accepts():
    for row in prefs.rows():
        if row.kind != prefs.CHOICE:
            continue
        setting = settings.by_name(row.setting)
        assert [value for value, _ in row.choices] == list(setting.choices)
        for _, display in row.choices:
            assert display.strip()


def test_the_theme_row_is_built_from_the_theme_registry():
    row = next(r for r in prefs.rows() if r.setting == settings.PREVIEW_THEME)
    assert row.choices == tuple(
        (theme.identifier, theme.label) for theme in themes.THEMES
    )


def test_the_theme_row_explains_itself_from_the_registry():
    for theme in themes.THEMES:
        assert (
            prefs.choice_help(settings.PREVIEW_THEME, theme.identifier) == theme.summary
        )


def test_no_other_setting_has_value_dependent_help():
    assert prefs.choice_help(settings.TEXT_DIRECTION, "rtl") is None


def test_enabled_by_names_a_real_boolean_setting():
    for row in prefs.rows():
        if row.enabled_by is None:
            continue
        assert isinstance(settings.by_name(row.enabled_by), settings.BoolSetting)


def test_the_refresh_delay_depends_on_auto_refresh():
    row = next(r for r in prefs.rows() if r.setting == settings.REFRESH_DELAY_MS)
    assert row.enabled_by == settings.AUTO_REFRESH


@pytest.mark.parametrize("row", prefs.rows(), ids=lambda row: row.setting)
def test_every_row_has_a_known_control_kind(row):
    assert row.kind in (prefs.SWITCH, prefs.CHOICE, prefs.NUMBER, prefs.PATH)


def rows_by_setting():
    return {row.setting: row for row in prefs.rows()}


def test_the_fetch_policy_has_a_row():
    row = rows_by_setting()[settings.REMOTE_IMAGES]
    assert row.kind == prefs.CHOICE
    assert [value for value, _label in row.choices] == ["never", "https"]


def test_the_help_text_names_the_disclosure_in_plain_words():
    row = rows_by_setting()[settings.REMOTE_IMAGES]
    assert "IP address" in row.help_text
    assert "http://" in row.help_text


def test_the_fallback_row_no_longer_claims_nothing_is_fetched():
    row = rows_by_setting()[settings.IMAGE_FALLBACK]
    assert "never fetches" not in (row.help_text or "")


def test_both_image_rows_have_accessible_names():
    assert a11y.NAMES["prefs_remote_images"]
    assert a11y.NAMES["prefs_image_fallback"]


def test_every_row_setting_exists_in_the_settings_module():
    for row in prefs.rows():
        settings.by_name(row.setting)
