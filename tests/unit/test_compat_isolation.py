"""cmarkgfm is an audit oracle and must never become a runtime dependency.

The plugin ships as a tarball extracted into ~/.local/share/xed/plugins
with no pip step, so an import of anything not vendored is a broken
install for every user. This is the test that notices.
"""

import pathlib

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "plugin"


def test_no_plugin_module_imports_cmarkgfm():
    offenders = [
        path.relative_to(PLUGIN_DIR)
        for path in PLUGIN_DIR.rglob("*.py")
        if "cmarkgfm" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"cmarkgfm must stay out of plugin/: {offenders}"


def test_cmarkgfm_is_not_in_dev_requirements():
    # requirements-dev.txt is what CI installs, on three Python versions.
    # The audit oracle belongs in requirements-audit.txt so CI never pays
    # for a wheel it does not use.
    root = PLUGIN_DIR.parent
    dev = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "cmarkgfm" not in dev
    audit = (root / "requirements-audit.txt").read_text(encoding="utf-8")
    assert "cmarkgfm" in audit
