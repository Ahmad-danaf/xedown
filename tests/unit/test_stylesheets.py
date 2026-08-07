import pytest
from xedown import stylesheets, themes, vendoring


@pytest.fixture(params=[t.identifier for t in themes.THEMES])
def theme(request):
    return themes.resolve(request.param)


def test_assemble_reports_the_theme_it_actually_used(theme):
    _, effective = stylesheets.assemble_css(theme.identifier)
    assert effective == theme.identifier


def test_assemble_falls_back_when_a_theme_sheet_cannot_be_read(monkeypatch):
    broken = [t for t in themes.THEMES if t.identifier != themes.DEFAULT_THEME]
    if not broken:
        pytest.skip("only the default theme is registered yet")
    target = broken[0]
    real = vendoring.read_resource

    def refuse(name):
        if name == target.stylesheet:
            raise vendoring.VendorError("no such file")
        return real(name)

    monkeypatch.setattr(vendoring, "read_resource", refuse)
    css, effective = stylesheets.assemble_css(target.identifier)
    assert effective == themes.DEFAULT_THEME
    assert "--xedown-bg" in css


def test_assemble_raises_when_the_default_itself_cannot_be_read(monkeypatch):
    # Nothing is left to fall back to, so this must reach render_document's
    # VendorError handler and become the "Installation incomplete" page
    # rather than a silently unstyled preview.
    default = themes.resolve(themes.DEFAULT_THEME)
    real = vendoring.read_resource

    def refuse(name):
        if name == default.stylesheet:
            raise vendoring.VendorError("no such file")
        return real(name)

    monkeypatch.setattr(vendoring, "read_resource", refuse)
    with pytest.raises(vendoring.VendorError):
        stylesheets.assemble_css(themes.DEFAULT_THEME)


def test_the_stylesheet_is_assembled_in_emission_order(theme):
    # Order is load-bearing, not cosmetic: preview.css's `pre code.hljs`
    # override beats the highlight stylesheet by SOURCE ORDER, not by
    # specificity, so a reversed assembly silently breaks every highlighted
    # code block while leaving the page otherwise intact.
    #
    # Asserted as an exact composition on purpose. An earlier version of
    # this test compared substring positions and passed under either order,
    # because the base sheet's own comment mentions `hljs` before the
    # override rule appears -- a test that cannot fail for the bug it names.
    css, _ = stylesheets.assemble_css(theme.identifier)
    assert css == "\n".join(
        (
            vendoring.read_resource(theme.syntax_stylesheet(False)),
            vendoring.read_resource(stylesheets.BASE_STYLESHEET),
            vendoring.read_resource(theme.stylesheet),
        )
    )
