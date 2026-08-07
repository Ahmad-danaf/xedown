import os

import pytest
from xedown import errors, settings, stylesheets, themes, vendoring


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


# --- the user's own stylesheet -----------------------------------------------


def write(tmp_path, text, name="mine.css"):
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return target


def test_an_unset_stylesheet_is_no_stylesheet_and_no_problem():
    for value in (None, "", "   "):
        loaded = stylesheets.load_user_stylesheet(value)
        assert loaded.css == ""
        assert loaded.problem is None
        assert loaded.path is None


def test_a_readable_stylesheet_is_returned_verbatim(tmp_path):
    target = write(tmp_path, "body { color: red; }\n")
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.css == "body { color: red; }\n"
    assert loaded.problem is None
    assert loaded.path == str(target)


def test_a_missing_file_reports_where_it_looked(tmp_path):
    target = tmp_path / "gone.css"
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.problem == errors.STYLESHEET_NOT_FOUND
    assert loaded.path == str(target)
    assert loaded.css == ""


def test_a_directory_is_not_a_file(tmp_path):
    loaded = stylesheets.load_user_stylesheet(str(tmp_path))
    assert loaded.problem == errors.STYLESHEET_NOT_A_FILE


def test_a_fifo_is_refused_without_ever_being_opened(tmp_path):
    # The whole value of this test is that it TERMINATES. Opening a FIFO
    # blocks on read() until something writes to the other end, and this
    # loader runs on the GTK main thread -- so getting this wrong hangs the
    # entire editor, not merely the preview. A size check does not help:
    # a FIFO reports st_size == 0, which would read as "empty".
    target = tmp_path / "pipe.css"
    os.mkfifo(target)
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.problem == errors.STYLESHEET_NOT_A_FILE


def test_an_unreadable_file_reports_why(tmp_path):
    target = write(tmp_path, "body { color: red; }")
    target.chmod(0o000)
    try:
        loaded = stylesheets.load_user_stylesheet(str(target))
    finally:
        target.chmod(0o644)
    assert loaded.problem == errors.STYLESHEET_UNREADABLE
    assert loaded.detail


def test_a_file_that_is_not_utf8_is_refused(tmp_path):
    target = tmp_path / "binary.css"
    target.write_bytes(b"body { color: \xff\xfe; }")
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.problem == errors.STYLESHEET_NOT_UTF8


def test_an_empty_or_whitespace_only_file_is_refused(tmp_path):
    for text in ("", "\n\n   \t\n"):
        target = write(tmp_path, text)
        assert stylesheets.load_user_stylesheet(str(target)).problem == (
            errors.STYLESHEET_EMPTY
        )


def test_a_file_at_exactly_the_cap_is_accepted(tmp_path):
    body = "a" * (stylesheets.MAX_STYLESHEET_BYTES - len("/**/"))
    target = write(tmp_path, f"/*{body}*/")
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.problem is None
    assert len(loaded.css.encode("utf-8")) == stylesheets.MAX_STYLESHEET_BYTES


def test_a_file_one_byte_over_the_cap_is_refused(tmp_path):
    body = "a" * (stylesheets.MAX_STYLESHEET_BYTES - len("/**/") + 1)
    target = write(tmp_path, f"/*{body}*/")
    assert stylesheets.load_user_stylesheet(str(target)).problem == (
        errors.STYLESHEET_TOO_LARGE
    )


@pytest.mark.parametrize(
    "text",
    [
        "body { color: red; }</style><script>alert(1)</script>",
        "/* </STYLE> */ body { color: red; }",
        'a::after { content: "</style >"; }',
    ],
)
def test_a_stylesheet_that_could_close_the_style_element_is_refused(tmp_path, text):
    # Refused rather than rewritten: the assembled CSS is interpolated raw
    # between <style> and </style>, and no single substitution is correct
    # inside a comment, inside a string and in ordinary CSS at once. Matched
    # case-insensitively, because the HTML tokenizer is.
    target = write(tmp_path, text)
    loaded = stylesheets.load_user_stylesheet(str(target))
    assert loaded.problem == errors.STYLESHEET_UNSAFE
    assert loaded.css == ""


def test_a_tilde_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    write(tmp_path, "body { color: red; }", name="home.css")
    loaded = stylesheets.load_user_stylesheet("~/home.css")
    assert loaded.problem is None
    assert loaded.path == str(tmp_path / "home.css")


def test_a_relative_path_resolves_against_the_config_directory(tmp_path):
    write(tmp_path, "body { color: red; }", name="rel.css")
    loaded = stylesheets.load_user_stylesheet("rel.css", config_dir=tmp_path)
    assert loaded.problem is None
    assert loaded.path == str(tmp_path / "rel.css")


def test_a_dollar_sign_is_a_dollar_sign_not_a_variable(tmp_path, monkeypatch):
    # Expanding environment variables would make one stored setting mean
    # different things depending on how xed was launched.
    monkeypatch.setenv("XEDOWN_TEST_DIR", str(tmp_path))
    loaded = stylesheets.load_user_stylesheet(
        "$XEDOWN_TEST_DIR/x.css", config_dir=tmp_path
    )
    assert loaded.problem == errors.STYLESHEET_NOT_FOUND
    assert "$XEDOWN_TEST_DIR" in loaded.path


def test_every_problem_has_a_phrase():
    problems = [
        errors.STYLESHEET_NOT_FOUND,
        errors.STYLESHEET_NOT_A_FILE,
        errors.STYLESHEET_UNREADABLE,
        errors.STYLESHEET_NOT_UTF8,
        errors.STYLESHEET_EMPTY,
        errors.STYLESHEET_TOO_LARGE,
        errors.STYLESHEET_UNSAFE,
    ]
    assert len(set(problems)) == len(problems)
    for problem in problems:
        assert errors.stylesheet_problem_phrase(problem).strip()


def test_the_size_phrase_names_the_actual_cap():
    # The cap is a constant in stylesheets.py and a number in a sentence in
    # errors.py. Nothing but this test keeps the two from drifting.
    kib = stylesheets.MAX_STYLESHEET_BYTES // 1024
    assert f"{kib} KiB" in errors.stylesheet_problem_phrase(errors.STYLESHEET_TOO_LARGE)


# --- the style a page is rendered with ---------------------------------------


def test_a_default_style_reproduces_the_base_stylesheet_values():
    # The v0.1 appearance, restated. preview.css declares the same two values
    # as its own defaults, so an untouched install renders identically.
    css = stylesheets.metrics_css(stylesheets.PreviewStyle())
    assert "--xedown-content-width: 46rem;" in css
    assert "--xedown-text-size: 16px;" in css


def test_the_metrics_block_is_a_root_rule():
    # On :root specifically. `rem` resolves against the root element, so a
    # width set anywhere else would drift away from the text size.
    css = stylesheets.metrics_css(stylesheets.PreviewStyle())
    assert css.strip().startswith(":root {")


def test_whole_numbers_are_not_written_with_a_trailing_zero():
    css = stylesheets.metrics_css(
        stylesheets.PreviewStyle(content_width_rem=62.0, text_size_px=18.0)
    )
    assert "62rem" in css and "62.0rem" not in css
    assert "18px" in css and "18.0px" not in css


def test_a_fractional_value_survives():
    css = stylesheets.metrics_css(stylesheets.PreviewStyle(text_size_px=17.5))
    assert "17.5px" in css


@pytest.mark.parametrize(
    ("width", "expected"),
    [(5, 30.0), (5000, 100.0), ("wide", 46.0), (None, 46.0), (True, 46.0)],
)
def test_an_out_of_range_or_nonsense_width_is_brought_into_range(width, expected):
    # render_document is called directly by the scripts and the tests, not
    # only through the settings store, so a bad argument must still produce a
    # sane page -- the precedent themes.resolve set.
    assert stylesheets.PreviewStyle(content_width_rem=width).content_width_rem == (
        expected
    )


def test_from_settings_reads_all_three_keys(tmp_path):
    store = settings.Settings(tmp_path / "settings.json")
    store.set_many(
        {
            settings.PREVIEW_THEME: "minimal",
            settings.CONTENT_WIDTH_REM: 72,
            settings.TEXT_SIZE_PX: 20,
        }
    )
    user = stylesheets.UserStylesheet(css="body {}", path="/x.css")
    style = stylesheets.PreviewStyle.from_settings(store, user=user)
    assert style.theme == "minimal"
    assert style.content_width_rem == 72.0
    assert style.text_size_px == 20.0
    assert style.user is user


def test_assemble_puts_the_layers_in_order():
    user = stylesheets.UserStylesheet(css="/*USER*/", path="/x.css")
    style = stylesheets.PreviewStyle(theme="repository", user=user)
    css, effective = stylesheets.assemble(style)
    assert effective == "repository"

    # Asserted as an exact composition, not by comparing substring positions.
    # The base sheet declares --xedown-content-width itself, so a positional
    # check would find the base sheet's occurrence rather than the metrics
    # block and pass under either order -- the same trap test_themes.py
    # records having fallen into once already.
    theme_css, _ = stylesheets.assemble_css("repository")
    assert css == theme_css + "\n" + stylesheets.metrics_css(style) + "\n/*USER*/"


def test_assemble_emits_no_layer_for_an_unset_user_stylesheet():
    style = stylesheets.PreviewStyle()
    css, _ = stylesheets.assemble(style)
    theme_css, _ = stylesheets.assemble_css(themes.DEFAULT_THEME)
    assert css == theme_css + "\n" + stylesheets.metrics_css(style)


def test_assemble_with_no_style_at_all_still_works():
    css, effective = stylesheets.assemble()
    assert effective == themes.DEFAULT_THEME
    assert "--xedown-bg" in css


# --- the file watcher ---------------------------------------------------------


def test_the_watcher_module_imports_without_a_desktop():
    # It talks to Gio, but lazily, inside its methods -- the same shape
    # appearance.AppearanceWatcher uses for Gtk. A module-level `gi` import
    # here would put it out of reach of every unit test in this file and
    # break the import in CI, where no typelibs exist.
    from xedown import stylewatcher

    assert stylewatcher.DEBOUNCE_MS > 0
    assert stylewatcher.get_watcher() is stylewatcher.get_watcher()
    assert stylewatcher.get_watcher().current().problem is None
