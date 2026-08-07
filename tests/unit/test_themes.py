import pathlib
import re

import pytest
from xedown import renderer, settings, stylesheets, themes, vendoring

from .cssparse import declarations

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "fixtures"

# Exactly v0.1's eleven. Every theme declares all of them in both
# appearances, because the contrast gate looks them up by name.
REQUIRED_COLOUR_TOKENS = (
    "--xedown-bg",
    "--xedown-fg",
    "--xedown-muted",
    "--xedown-border",
    "--xedown-quote-border",
    "--xedown-code-bg",
    "--xedown-link",
    "--xedown-focus-ring",
    "--xedown-error-bg",
    "--xedown-error-fg",
    "--xedown-error-border",
)

REQUIRED_SCALE_TOKENS = ("--xedown-measure-scale", "--xedown-text-scale")

SYNTAX_TOKENS = (
    "--xedown-syn-comment",
    "--xedown-syn-keyword",
    "--xedown-syn-string",
    "--xedown-syn-number",
    "--xedown-syn-function",
    "--xedown-syn-type",
    "--xedown-syn-variable",
    "--xedown-syn-meta",
    "--xedown-syn-addition-fg",
    "--xedown-syn-addition-bg",
    "--xedown-syn-deletion-fg",
    "--xedown-syn-deletion-bg",
)

COLOUR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")


def theme_ids():
    return [theme.identifier for theme in themes.THEMES]


@pytest.fixture(params=[t.identifier for t in themes.THEMES])
def theme(request):
    return themes.resolve(request.param)


def _palette_blocks(theme):
    parsed, _ = declarations(vendoring.read_resource(theme.stylesheet))
    return parsed.get(":root", {}), parsed.get("body.dark", {})


def test_the_default_theme_is_registered():
    assert themes.DEFAULT_THEME in theme_ids()


def test_every_theme_has_a_label_and_a_summary(theme):
    assert theme.label.strip()
    assert theme.summary.strip()


@pytest.mark.parametrize(
    "given", ["nope", "", "   ", None, 3, ["repository"], "github", "cursor"]
)
def test_an_unusable_identifier_falls_back_to_the_default(given):
    # Never an exception and never an unstyled page: an identifier this
    # version does not know -- including the two brief 1 briefly registered
    # -- resolves to the default instead.
    assert themes.resolve(given).identifier == themes.DEFAULT_THEME


def test_a_known_identifier_resolves_regardless_of_case_and_space():
    assert themes.resolve("  RePoSiToRy ").identifier == "repository"


def test_base_and_theme_never_declare_the_same_property_twice(theme):
    # test_v01_parity.py checks this disjointness for `repository` alone,
    # because there it is what turns a v0.1 comparison into an equality. But
    # the base sheet's own invariants -- overflow containment, bidi
    # correctness, the focus ring -- are only guaranteed for the *other*
    # three themes too if nothing in a theme's stylesheet can silently
    # redeclare a selector/property the base sheet already owns and win by
    # source order. Without this test, a future theme adding e.g.
    # `pre { overflow-x: visible }` would quietly defeat a guarantee the
    # base sheet exists to provide, and every other test would still be
    # green.
    #
    # Each stylesheet is parsed on its own rather than reusing the
    # concatenate-then-look-at-`duplicates` trick test_v01_parity.py uses:
    # `document` legitimately restates h5/h6 font-weight and colour over the
    # shared `h1..h6` rule (ordinary same-specificity CSS cascade, later in
    # source order, touching properties the base sheet never declares for
    # headings), and that self-contained pattern would otherwise register as
    # a false "duplicate". What must never happen is the *base* and the
    # *theme* both claiming the same selector/property -- so this compares
    # each file's own effective declarations instead.
    base, _ = declarations(vendoring.read_resource(stylesheets.BASE_STYLESHEET))
    theme_rules, _ = declarations(vendoring.read_resource(theme.stylesheet))
    collisions = [
        (selector, prop)
        for selector, props in theme_rules.items()
        for prop in props
        if prop in base.get(selector, {})
    ]
    assert collisions == []


def test_every_theme_declares_the_required_colour_tokens_in_both_appearances(theme):
    light, dark = _palette_blocks(theme)
    for token in REQUIRED_COLOUR_TOKENS:
        assert token in light, f"{theme.identifier} :root is missing {token}"
        assert token in dark, f"{theme.identifier} body.dark is missing {token}"


def test_every_theme_declares_the_scale_tokens_on_root(theme):
    # On :root specifically: the root font size multiplies by the text
    # scale, and a value set on `body` would never reach it.
    light, _ = _palette_blocks(theme)
    for token in REQUIRED_SCALE_TOKENS:
        assert token in light, f"{theme.identifier} :root is missing {token}"


def test_a_theme_using_the_shared_syntax_sheet_declares_every_syntax_token(theme):
    if theme.syntax_stylesheet(False) != themes.SHARED_SYNTAX_STYLESHEET:
        pytest.skip(f"{theme.identifier} uses a vendored syntax stylesheet")
    light, dark = _palette_blocks(theme)
    for token in SYNTAX_TOKENS:
        assert token in light, f"{theme.identifier} :root is missing {token}"
        assert token in dark, f"{theme.identifier} body.dark is missing {token}"


def test_no_theme_declares_a_colour_outside_its_palette_blocks(theme):
    # The contrast gate reads the two palette blocks. A colour written
    # anywhere else is a colour nothing checks.
    parsed, _ = declarations(vendoring.read_resource(theme.stylesheet))
    for selector, props in parsed.items():
        if selector in (":root", "body.dark"):
            continue
        for name, value in props.items():
            assert not COLOUR_LITERAL.search(value), (
                f"{theme.identifier}: {selector} {{ {name}: {value} }} is a "
                f"colour outside the palette blocks"
            )


@pytest.mark.parametrize("name", ["showcase.md", "edge-cases.md"])
@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_every_fixture_renders_in_every_theme(name, dark, theme):
    page = renderer.render_document(
        (FIXTURES / name).read_text(encoding="utf-8"),
        base_dir=str(FIXTURES),
        dark=dark,
        theme=theme.identifier,
        nonce="n",
    )
    assert f'xedown-theme-{theme.identifier}"' in page
    assert f'id="{renderer.CONTENT_ELEMENT_ID}"' in page
    assert "Cannot render this document" not in page
    assert "Installation incomplete" not in page


def test_the_registry_holds_exactly_the_four_built_in_themes():
    assert sorted(theme_ids()) == ["document", "focused", "minimal", "repository"]


def test_the_settings_choices_are_exactly_the_registered_themes():
    # Two lists that must never drift: a setting offering a theme that does
    # not exist would silently fall back, and a theme missing from the
    # setting would be unreachable.
    choices = settings.by_name(settings.PREVIEW_THEME).choices
    assert sorted(choices) == sorted(theme_ids())
    assert settings.by_name(settings.PREVIEW_THEME).default == themes.DEFAULT_THEME
