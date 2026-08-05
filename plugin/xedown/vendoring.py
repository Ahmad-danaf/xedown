"""Loads vendored third-party code. Our code — `vendor/` holds only theirs."""

import importlib
import pathlib
import sys

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent
PLUGIN_DIR = PACKAGE_DIR.parent
VENDOR_DIR = PACKAGE_DIR / "vendor"
RESOURCES_DIR = PACKAGE_DIR / "resources"

# Fully-qualified names are mandatory. Short names ("tables") resolve through
# entry-point metadata that vendoring drops, so they succeed on a machine with
# system Markdown installed and fail on a clean install.
MARKDOWN_EXTENSIONS = (
    "markdown.extensions.tables",
    "markdown.extensions.fenced_code",
    "markdown.extensions.footnotes",
    "markdown.extensions.toc",
    "markdown.extensions.sane_lists",
    "markdown.extensions.attr_list",
)


class VendorError(RuntimeError):
    """A bundled dependency or resource is missing or unreadable."""


def _ensure_vendor_on_path():
    path = str(VENDOR_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


def import_markdown():
    """Return the vendored Markdown module, preferring it over any system copy."""
    _ensure_vendor_on_path()
    module = sys.modules.get("markdown")
    if module is not None and str(VENDOR_DIR) in getattr(module, "__file__", ""):
        return module
    for name in [n for n in sys.modules if n == "markdown" or n.startswith("markdown.")]:
        del sys.modules[name]
    try:
        module = importlib.import_module("markdown")
    except ImportError as exc:
        raise VendorError(
            f"the bundled Markdown library is missing from {VENDOR_DIR}; this "
            "release is incomplete"
        ) from exc
    if str(VENDOR_DIR) not in getattr(module, "__file__", ""):
        raise VendorError("a non-bundled Markdown library was imported instead")
    return module


def read_resource(name):
    """Read a file from resources/, refusing anything outside that directory."""
    target = (RESOURCES_DIR / name).resolve()
    if not target.is_relative_to(RESOURCES_DIR.resolve()):
        raise VendorError(f"refusing to read outside the resources directory: {name}")
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise VendorError(f"cannot read bundled resource {name}: {exc}") from exc


def read_vendor_file(name):
    """Read a file from vendor/, refusing anything outside that directory."""
    target = (VENDOR_DIR / name).resolve()
    if not target.is_relative_to(VENDOR_DIR.resolve()):
        raise VendorError(f"refusing to read outside the vendor directory: {name}")
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise VendorError(f"cannot read bundled file {name}: {exc}") from exc
