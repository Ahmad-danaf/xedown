import subprocess
import sys
import textwrap

from xedown import vendoring


def test_vendor_directory_contains_the_pinned_dependencies():
    assert (vendoring.VENDOR_DIR / "markdown" / "__init__.py").is_file()
    assert (vendoring.VENDOR_DIR / "highlight.min.js").is_file()
    assert (vendoring.VENDOR_DIR / "licenses" / "python-markdown-LICENSE.md").is_file()
    assert (vendoring.VENDOR_DIR / "licenses" / "highlight.js-LICENSE").is_file()


def test_extension_names_are_fully_qualified():
    # Short names such as "tables" resolve via entry-point metadata that
    # vendoring drops. They work with system Markdown installed and fail on a
    # clean install, so every name must be fully qualified.
    assert vendoring.MARKDOWN_EXTENSIONS
    for name in vendoring.MARKDOWN_EXTENSIONS:
        assert name.startswith("markdown.extensions."), name


def test_import_markdown_returns_the_vendored_copy():
    md = vendoring.import_markdown()
    assert md.__version__ == "3.7"
    assert str(vendoring.VENDOR_DIR) in md.__file__


def test_renders_with_pinned_extensions_when_no_system_markdown_exists():
    # Runs in a subprocess with system package dirs removed from sys.path.
    script = textwrap.dedent("""
        import sys
        sys.path = [p for p in sys.path
                    if "dist-packages" not in p and "site-packages" not in p]
        sys.path.insert(0, %r)
        try:
            import markdown
        except ImportError:
            pass
        else:
            raise SystemExit("system markdown leaked into the isolated run")
        from xedown import vendoring
        md = vendoring.import_markdown()
        html = md.markdown(
            "| a |\\n|---|\\n| 1 |\\n\\n```python\\nx=1\\n```",
            extensions=list(vendoring.MARKDOWN_EXTENSIONS),
        )
        assert "<table>" in html, html
        assert 'class="language-python"' in html, html
        print("OK")
        """) % str(vendoring.PLUGIN_DIR)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_read_resource_returns_text_and_rejects_traversal():
    assert "hljs" in vendoring.read_resource("highlight-light.css")
    try:
        vendoring.read_resource("../vendor/highlight.min.js")
    except vendoring.VendorError:
        pass
    else:
        raise AssertionError("path traversal was not rejected")
