import shutil
import subprocess

import pytest
from xedown import vendoring


@pytest.fixture
def preview_js():
    return vendoring.read_resource("preview.js")


@pytest.fixture
def preview_css():
    return vendoring.read_resource("preview.css")


def test_stylesheet_defines_both_themes(preview_css):
    assert "--xedown-bg" in preview_css
    assert "body.dark" in preview_css or ".dark" in preview_css


def test_stylesheet_caps_the_document_width(preview_css):
    assert "max-width" in preview_css


def test_stylesheet_lets_wide_content_scroll_itself(preview_css):
    assert "overflow-x" in preview_css


def test_stylesheet_defines_focus_visible_style(preview_css):
    # Rendered documents contain links; a keyboard user must be able to see
    # where focus is. This must not be suppressed anywhere in the sheet.
    assert ":focus-visible" in preview_css
    assert "outline: none" not in preview_css
    assert "outline:none" not in preview_css


def test_resources_reference_nothing_remote(preview_css, preview_js):
    for text in (preview_css, preview_js):
        assert "http://" not in text
        assert "https://" not in text
        assert "//cdn" not in text


def test_script_exposes_the_host_interface(preview_js):
    for symbol in (
        "replaceBody",
        "setScroll",
        "getScroll",
        "scrollToAnchor",
        "window.xedown",
    ):
        assert symbol in preview_js


def test_script_guards_unknown_highlight_languages(preview_js):
    # The bundle throws "Unknown language" for anything unregistered, so the
    # call must be guarded and fall back to an unhighlighted block.
    assert "getLanguage" in preview_js
    assert "try" in preview_js


def test_script_installs_image_error_handlers(preview_js):
    assert "error" in preview_js
    assert "img" in preview_js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_script_is_syntactically_valid():
    path = vendoring.RESOURCES_DIR / "preview.js"
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
