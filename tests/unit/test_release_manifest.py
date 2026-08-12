"""Pins `scripts/build-release.sh`'s completeness gate to what the code needs.

`REQUIRED` is the promise that a built archive carries everything a clean
machine needs: no pip step, offline highlighting, both third-party licences.
It is hand-maintained, and brief 3's plan recorded the failure mode -- nothing
linked it to what the package actually imports, so a module added by any later
brief was simply never gated. By v0.2, 22 of the package's 27 modules were
missing from it.

The array is read out of the shell script rather than restated here, the same
way `test_shutdown_allowlist.py` reads its patterns: a copy would keep passing
while the real gate drifted.

The module set is computed by parsing the package with `ast`, never by
importing it. `controller.py`, `preview.py`, `modebar.py`, `prefswindow.py`
and `searchbar.py` import `gi` at module level, which does not exist in CI --
the same boundary that decides where logic lives in this codebase decides how
this test is allowed to look at it.
"""

import ast
import pathlib
import re

from xedown import stylesheets, themes

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BUILD_SCRIPT = ROOT / "scripts" / "build-release.sh"
PACKAGE = ROOT / "plugin" / "xedown"
PLUGIN_DESCRIPTOR = ROOT / "plugin" / "xedown.plugin"
README = ROOT / "README.md"
PROBE_DESCRIPTORS = tuple(sorted((ROOT / "tests" / "integration").glob("*.plugin")))

_MODULE_ENTRY = re.compile(r"xedown/[^/]+\.py$")


def required_paths():
    """The REQUIRED array, read out of the shell script itself."""
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^REQUIRED=\(\n(.*?)^\)$", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "REQUIRED array not found in build-release.sh"
    paths = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert paths, "REQUIRED array parsed as empty; the pattern has drifted"
    return paths


def _intra_package_imports(path):
    """Module names this file imports from its own package, at any depth.

    `ast.walk` rather than a scan of top-level statements: several modules
    import lazily inside a function or method (ThemeWatcher does it to keep
    `gi` out of import time), and a lazily imported module is exactly as
    required at runtime as an eagerly imported one.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module is None:  # from . import a, b
                names.update(alias.name for alias in node.names)
            else:  # from .module import name
                names.add(node.module.split(".")[0])
    return names


def imported_modules():
    """Every module reachable from `__init__.py` by intra-package import."""
    on_disk = {path.stem for path in PACKAGE.glob("*.py")}
    reached = {"__init__"}
    pending = ["__init__"]
    while pending:
        for name in _intra_package_imports(PACKAGE / f"{pending.pop()}.py") & on_disk:
            if name not in reached:
                reached.add(name)
                pending.append(name)
    return reached


def package_version():
    text = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "(.+)"$', text, re.MULTILINE)
    assert match is not None, "__version__ not found in plugin/xedown/__init__.py"
    return match.group(1)


def test_every_module_the_package_imports_is_gated():
    required = required_paths()
    missing = sorted(
        f"xedown/{name}.py"
        for name in imported_modules()
        if f"xedown/{name}.py" not in required
    )
    assert missing == [], (
        "these modules are imported by the package but are not in "
        f"build-release.sh's REQUIRED array: {missing}"
    )


def test_no_gated_module_has_been_deleted():
    # The other direction: a stale entry would keep gating a module that no
    # longer exists, and the build would fail for a reason nobody could act on.
    on_disk = {f"xedown/{path.name}" for path in PACKAGE.glob("*.py")}
    gated = {path for path in required_paths() if _MODULE_ENTRY.match(path)}
    assert (
        gated <= on_disk
    ), f"REQUIRED gates modules that do not exist: {gated - on_disk}"


def test_every_stylesheet_a_theme_names_is_gated():
    # Themes name their stylesheets by string, so a new theme's CSS file can
    # be shipped, referenced and never gated. `themes` and `stylesheets` are
    # both pure modules, so this reads the real values rather than a copy.
    required = required_paths()
    for theme in themes.THEMES:
        for name in (theme.stylesheet, theme.syntax_light, theme.syntax_dark):
            assert f"xedown/resources/{name}" in required, f"{name} is not gated"
    assert f"xedown/resources/{stylesheets.BASE_STYLESHEET}" in required


def test_the_plugin_descriptor_carries_the_package_version():
    # build-release.sh refuses to build when these disagree; this fails in CI
    # instead of at release time, when it is cheaper to notice.
    text = PLUGIN_DESCRIPTOR.read_text(encoding="utf-8")
    match = re.search(r"^Version=(.+)$", text, re.MULTILINE)
    assert match is not None, "Version= not found in plugin/xedown.plugin"
    assert match.group(1) == package_version()


def test_every_probe_descriptor_carries_the_package_version():
    for descriptor in PROBE_DESCRIPTORS:
        text = descriptor.read_text(encoding="utf-8")
        match = re.search(r"^Version=(.+)$", text, re.MULTILINE)
        assert match is not None, f"Version= not found in {descriptor.name}"
        assert match.group(1) == package_version(), descriptor.name


def test_the_readme_installs_the_version_it_documents():
    text = README.read_text(encoding="utf-8")
    named = set(re.findall(r"xedown-(\d+\.\d+\.\d+)\.tar\.gz", text))
    assert named == {package_version()}, (
        f"README names archive versions {sorted(named)}; "
        f"__version__ is {package_version()}"
    )
