"""Pin what `docs/compatibility.md` publishes to the constants behind it.

Two different claims live in that document, and both are duplicated from
`preflight.py` on purpose -- `preflight.py` needs them as data, and the
document is the copy a reader actually meets, so neither can be replaced by
a pointer to the other:

- the *support* claim: the exact live-verified stack, held against the
  `LIVE_*` constants and the required GI API versions;
- the *installer* claim: the broader series-level matrix the preflight
  judges a machine against, held against `MIN_PYTHON`, `TESTED_PYTHON`,
  `TESTED_XED` and `TESTED_DISTRO_MAJOR`.

What makes a duplicate safe is a test that fails when the copies disagree --
the same technique `test_shutdown_allowlist.py` uses for the allowlist line
duplicated across both harness scripts. Both claims are read out of the
document rather than restated here; restating one would produce a test that
passes happily while the published claim drifts.
"""

import pathlib
import re

from xedown import preflight

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DOC = ROOT / "docs" / "compatibility.md"
INDEX = ROOT / "docs" / "index.md"


def dotted(version):
    return ".".join(str(part) for part in version)


def section(title):
    """The body of `## <title>`, up to the next heading or the end."""
    text = DOC.read_text(encoding="utf-8")
    found = re.search(
        rf"^## {re.escape(title)}\b(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert found is not None, f"no '## {title}' section in docs/compatibility.md"
    body = found.group(1)
    assert body.strip(), f"the '{title}' section is empty; its shape has drifted"
    return body


def supported_rows():
    """`{component: [token, ...]}` from the supported table's second column."""
    rows = {}
    for line in section("Officially supported runtime").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("- ") or not cells[0]:
            continue
        tokens = re.findall(r"`([^`]+)`", cells[1])
        if tokens:
            rows[cells[0]] = tokens
    assert rows, "the supported table parsed as empty; its shape has drifted"
    return rows


def test_every_live_component_has_a_published_row():
    assert set(supported_rows()) == {
        "Linux Mint",
        "xed",
        "Python",
        "GTK",
        "WebKitGTK",
        "Display server",
    }


def test_exact_live_versions_are_published():
    rows = supported_rows()
    assert rows["Linux Mint"] == [preflight.LIVE_DISTRO_VERSION]
    assert rows["xed"] == [preflight.LIVE_XED_VERSION]
    assert rows["Python"] == [preflight.LIVE_PYTHON_VERSION]
    assert rows["GTK"] == [
        preflight.LIVE_GTK_VERSION,
        preflight.REQUIRED_GTK_GI,
    ]
    assert rows["WebKitGTK"] == [
        preflight.LIVE_WEBKIT_VERSION,
        preflight.REQUIRED_WEBKIT_GI,
    ]
    assert rows["Display server"] == [preflight.TESTED_SESSION_TYPE.upper()]


def test_ci_only_python_versions_are_not_called_live_supported():
    body = section("CI unit-tested only")
    # Every tested series except the one the live machine ran: those are the
    # interpreters with unit evidence and no evidence inside xed.
    for version in preflight.TESTED_PYTHON[:-1]:
        assert f"`{dotted(version)}`" in body, (
            f"Python {dotted(version)} is in TESTED_PYTHON but the "
            "CI-only section does not name it"
        )


def test_the_installer_refusal_and_warning_thresholds_are_published():
    """The preflight's series-level matrix, as the installer section states it.

    These are the numbers a reader uses to predict what `install.sh` will do
    on their machine, and each one is a constant in `preflight.py`. They are
    checked inside the installer section specifically: the same digits appear
    elsewhere in the document meaning something else -- `3.12` is also the
    live-verified patch series, `3.10` also the hard minimum -- so a
    whole-document search would pass on the wrong sentence.
    """
    body = section("What the installer checks")
    for token, constant in (
        (dotted(preflight.MIN_PYTHON), "MIN_PYTHON"),
        (dotted(preflight.TESTED_PYTHON[-1]), "TESTED_PYTHON's ceiling"),
        (dotted(preflight.TESTED_XED), "TESTED_XED"),
        (str(preflight.TESTED_DISTRO_MAJOR), "TESTED_DISTRO_MAJOR"),
    ):
        assert f"`{token}`" in body, (
            f"{constant} is {token}, which the installer section does not "
            "publish; the two copies have drifted"
        )


def test_the_hard_python_minimum_is_published_with_the_requirements():
    # Stated twice in the document because a reader checking requirements
    # and a reader predicting the installer are looking in different places.
    body = section("Hard requirements and known negatives")
    assert f"`{dotted(preflight.MIN_PYTHON)}`" in body


def test_the_required_gi_api_versions_are_published_as_requirements():
    body = section("Hard requirements and known negatives")
    assert f"`{preflight.REQUIRED_WEBKIT_GI}`" in body
    assert f"`{preflight.REQUIRED_GTK_GI}`" in body


def test_expected_versions_are_explicitly_unverified():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "expected to work" in text
    assert "unverified" in text


def test_webkit_40_is_a_known_negative():
    assert "4.0" in DOC.read_text(encoding="utf-8")


def test_document_is_linked_from_the_docs_index():
    assert "](compatibility.md)" in INDEX.read_text(encoding="utf-8")
