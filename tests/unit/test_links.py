import os

import pytest
from xedown.links import (
    LinkAction,
    classify_link,
    is_dangerous_path,
    is_supported_image,
    resolve_to_uri,
)


@pytest.fixture
def base(tmp_path):
    (tmp_path / "other.md").write_text("# other")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "run.sh").write_text("#!/bin/sh\n")
    (tmp_path / "app.desktop").write_text("[Desktop Entry]\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.md").write_text("# deep")
    return str(tmp_path)


@pytest.mark.parametrize(
    "uri", ["https://example.com", "http://example.com/a?b=c", "mailto:a@b.c"]
)
def test_remote_links_open_in_the_browser(uri, base):
    decision = classify_link(uri, base)
    assert decision.action is LinkAction.EXTERNAL_BROWSER
    assert decision.target == uri


def test_anchors_are_handled_in_page(base):
    decision = classify_link("#section-one", base)
    assert decision.action is LinkAction.IN_PAGE_ANCHOR
    assert decision.target == "section-one"


def test_relative_markdown_opens_in_xed(base):
    decision = classify_link("other.md", base)
    assert decision.action is LinkAction.OPEN_IN_XED
    assert decision.target == "file://" + os.path.join(base, "other.md")


def test_nested_relative_markdown_is_normalized(base):
    decision = classify_link("./sub/../sub/deep.md", base)
    assert decision.action is LinkAction.OPEN_IN_XED
    assert decision.target == "file://" + os.path.join(base, "sub", "deep.md")
    assert "/../" not in decision.target


def test_ordinary_local_file_uses_the_desktop_handler(base):
    decision = classify_link("notes.txt", base)
    assert decision.action is LinkAction.DESKTOP_HANDLER


@pytest.mark.parametrize("name", ["run.sh", "app.desktop"])
def test_dangerous_local_files_require_confirmation(name, base):
    decision = classify_link(name, base)
    assert decision.action is LinkAction.CONFIRM_THEN_DESKTOP
    assert decision.reason


def test_missing_local_file_is_refused_with_a_reason(base):
    decision = classify_link("nope.md", base)
    assert decision.action is LinkAction.REFUSE
    assert "nope.md" in decision.reason


def test_relative_link_without_a_base_directory_is_refused():
    decision = classify_link("other.md", None)
    assert decision.action is LinkAction.REFUSE
    assert "unsaved" in decision.reason.lower() or "not been saved" in decision.reason


def test_unknown_schemes_are_refused(base):
    for uri in ("javascript:alert(1)", "vbscript:x", "data:text/html,x"):
        assert classify_link(uri, base).action is LinkAction.REFUSE


def test_resolve_to_uri_normalizes_and_percent_encodes_spaces(base):
    uri = resolve_to_uri("my notes.md", base)
    assert uri.startswith("file://")
    assert " " not in uri
    assert "%20" in uri


def test_resolve_to_uri_returns_none_without_a_base():
    assert resolve_to_uri("a.png", None) is None


def test_resolve_to_uri_passes_absolute_uris_through(base):
    assert (
        resolve_to_uri("https://example.com/a.png", base) == "https://example.com/a.png"
    )


def test_resolve_to_uri_percent_encodes_a_file_uri_containing_a_space(base):
    target = os.path.join(base, "my notes.md")
    with open(target, "w") as f:
        f.write("# hi")
    uri = resolve_to_uri("file://" + target, base)
    assert uri.startswith("file://")
    assert " " not in uri
    assert "%20" in uri


def test_resolve_to_uri_and_classify_link_agree_on_a_file_uri(base):
    target = os.path.join(base, "my notes.md")
    with open(target, "w") as f:
        f.write("# hi")
    reference = "file://" + target
    assert resolve_to_uri(reference, base) == classify_link(reference, base).target


@pytest.mark.parametrize(
    "name", ["a.png", "b.JPG", "c.jpeg", "d.gif", "e.webp", "f.svg", "g.bmp"]
)
def test_supported_image_suffixes(name):
    assert is_supported_image(name) is True


@pytest.mark.parametrize("name", ["a.txt", "a.md", "a.exe", "a"])
def test_unsupported_image_suffixes(name):
    assert is_supported_image(name) is False


@pytest.mark.parametrize(
    "name", ["x.sh", "x.desktop", "x.exe", "x.py", "x.appimage", "X.SH", "x.bat"]
)
def test_dangerous_suffixes(name):
    assert is_dangerous_path(name) is True


@pytest.mark.parametrize("name", ["x.txt", "x.md", "x.png", "x.pdf"])
def test_safe_suffixes(name):
    assert is_dangerous_path(name) is False


def test_executable_bit_makes_a_plain_file_dangerous(tmp_path):
    target = tmp_path / "tool"
    target.write_text("#!/bin/sh\n")
    target.chmod(0o755)
    decision = classify_link("tool", str(tmp_path))
    assert decision.action is LinkAction.CONFIRM_THEN_DESKTOP


# --- Additional adversarial cases beyond the brief's suite ---


def test_absolute_reference_resolves_even_without_a_base_directory(tmp_path):
    # An absolute path (or a file:// URI, which is also absolute) is
    # self-contained: resolving it never needed the document's directory,
    # so an unsaved document must not block it the way a *relative*
    # reference correctly is blocked.
    target = tmp_path / "standalone.txt"
    target.write_text("hi")
    decision = classify_link(str(target), None)
    assert decision.action is LinkAction.DESKTOP_HANDLER
    assert decision.target == "file://" + str(target)


def test_absolute_file_uri_resolves_even_without_a_base_directory(tmp_path):
    target = tmp_path / "standalone.md"
    target.write_text("# hi")
    decision = classify_link("file://" + str(target), None)
    assert decision.action is LinkAction.OPEN_IN_XED


def test_malformed_percent_encoding_does_not_crash(base):
    # "%00" decodes to an embedded NUL byte, which the os.path functions
    # reject with ValueError. classify_link must fail closed, not raise.
    decision = classify_link("a%00b.md", base)
    assert decision.action is LinkAction.REFUSE

    assert resolve_to_uri("a%00b.md", base) is None


def test_symlink_disguised_as_markdown_is_classified_by_its_real_target(base):
    # A symlink can be named to look harmless (or, as here, to look like a
    # safe markdown file) while pointing at something dangerous. The suffix
    # and executable-bit checks must apply to the resolved real path, not
    # the name used in the link text.
    link_path = os.path.join(base, "sneaky.md")
    os.symlink(os.path.join(base, "run.sh"), link_path)
    decision = classify_link("sneaky.md", base)
    assert decision.action is LinkAction.CONFIRM_THEN_DESKTOP


def test_symlink_loop_is_refused_not_a_crash(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    os.symlink(b, a)
    os.symlink(a, b)
    decision = classify_link("a", str(tmp_path))
    assert decision.action is LinkAction.REFUSE


def test_malformed_scheme_does_not_crash(base):
    # An unbalanced IPv6-literal bracket in the authority makes
    # `urllib.parse.urlparse` raise ValueError. Both entry points parse a
    # scheme from unvalidated document content and must fail closed rather
    # than propagate, the same way malformed percent-encoding already does
    # above.
    decision = classify_link("http://[bad", base)
    assert decision.action is LinkAction.REFUSE

    assert resolve_to_uri("http://[bad", base) is None
