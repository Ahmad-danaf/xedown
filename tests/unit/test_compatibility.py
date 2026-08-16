"""Pins the published compatibility claim to the matrix the installer uses.

The matrix lives in two places on purpose. `preflight.py` needs it as data;
`docs/compatibility.md` is the copy a reader actually meets, and neither can
be replaced by a pointer to the other. What makes a duplicate safe is a test
that fails when the copies disagree -- the same technique
`test_shutdown_allowlist.py` uses for the allowlist line duplicated across
both harness scripts, and `test_release_manifest.py` for the REQUIRED array.

The table is read out of the document rather than restated here. Restating
it would produce a test that passes happily while the published claim drifts.
"""

import pathlib
import re

from xedown import preflight

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC = ROOT / "docs" / "compatibility.md"
INDEX = ROOT / "docs" / "index.md"


def supported_rows():
    """`{component: [token, ...]}` from the Supported table's second column."""
    text = DOC.read_text(encoding="utf-8")
    section = re.search(r"^## Supported\b(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section is not None, "no '## Supported' section in docs/compatibility.md"
    rows = {}
    for line in section.group(1).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("- ") or not cells[0]:
            continue
        tokens = re.findall(r"`([^`]+)`", cells[1])
        if tokens:
            rows[cells[0]] = tokens
    assert rows, "the Supported table parsed as empty; its shape has drifted"
    return rows


def test_every_component_in_the_matrix_has_a_published_row():
    rows = supported_rows()
    for component in (
        "Linux Mint",
        "xed",
        "Python",
        "WebKit2GTK",
        "GTK",
        "Display server",
    ):
        assert component in rows, f"no published row for {component}"


def test_the_published_xed_series_is_the_tested_one():
    (token,) = supported_rows()["xed"]
    assert token == f"{preflight.TESTED_XED[0]}.{preflight.TESTED_XED[1]}.x"


def test_the_published_python_versions_are_the_tested_ones():
    tokens = supported_rows()["Python"]
    published = tuple(preflight.parse_python_version(t)[:2] for t in tokens)
    assert published == preflight.TESTED_PYTHON


def test_the_published_webkit_and_gtk_versions_are_the_required_ones():
    rows = supported_rows()
    assert rows["WebKit2GTK"] == [preflight.REQUIRED_WEBKIT_GI]
    assert rows["GTK"] == [preflight.REQUIRED_GTK_GI]


def test_the_published_distro_is_the_tested_one():
    (token,) = supported_rows()["Linux Mint"]
    assert token == f"{preflight.TESTED_DISTRO_MAJOR}.x"


def test_the_published_display_server_is_the_tested_one():
    (token,) = supported_rows()["Display server"]
    assert token == preflight.TESTED_SESSION_TYPE


def test_the_known_negative_is_stated():
    # WebKit2GTK 4.1 is pinned in code, so 4.0-only systems cannot work at
    # all. A known negative is more useful to a reader than silence, and
    # this is the one xedown knows.
    text = DOC.read_text(encoding="utf-8")
    assert "4.0" in text


def test_the_may_work_sentence_exists():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "may work" in text
    assert "not officially tested" in text


def test_the_document_is_linked_from_the_docs_index():
    assert "](compatibility.md)" in INDEX.read_text(encoding="utf-8")
