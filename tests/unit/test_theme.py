import pytest
from xedown.theme import prefers_dark


def test_explicit_dark_preference_wins():
    assert prefers_dark("Adwaita", True) is True


@pytest.mark.parametrize(
    "name", ["Adwaita-dark", "Mint-Y-Dark", "Yaru-dark", "ARC-DARK", "Breeze Dark"]
)
def test_dark_theme_names_are_detected(name):
    assert prefers_dark(name, False) is True


@pytest.mark.parametrize("name", ["Adwaita", "Mint-Y", "Yaru", "Breeze", None, ""])
def test_light_theme_names_are_detected(name):
    assert prefers_dark(name, False) is False


def test_darker_is_not_mistaken_for_dark_suffix_matching():
    # "Darkly" and similar still contain "dark"; treat them as dark rather than
    # inventing a fragile rule. This documents the intended behaviour.
    assert prefers_dark("Darkly", False) is True
