"""The heading-anchor replacement: identical output, linear cost.

`toc.unique` is O(n^2) in duplicate slugs -- for the nth duplicate it
restarts its `_1, _2, ...` probe from the beginning. xedown replaces it
with a memoised walk that cannot skip an unoccupied value, so the answer
is unchanged and the cost is linear.

The vendored file is never edited; these tests exist partly to prove the
replacement still matches it after a re-vendor.
"""

import pytest
from xedown import mdext, vendoring


@pytest.fixture(scope="module")
def toc():
    markdown_module = vendoring.import_markdown()
    import importlib

    return importlib.import_module(f"{markdown_module.__name__}.extensions.toc")


def _reference(candidates, toc_module):
    """What the vendored function produces, in order."""
    used = set()
    return [toc_module.unique(c, used) for c in candidates]


def _replacement(candidates):
    used, memo = set(), {}
    return [mdext.unique_id(c, used, memo) for c in candidates]


CASES = {
    "no collisions": ["alpha", "beta", "gamma"],
    "plain duplicates": ["usage"] * 8,
    "changelog shape": ["fixed", "added", "fixed", "changed", "added", "fixed"],
    # The nasty one: a heading literally named `x_1` colliding with the
    # bumped form of `x`.
    "explicit numeric suffix": ["x", "x", "x_1", "x", "x_1", "x_2"],
    # The vendored loop treats a falsy id as a collision: `not id`.
    "empty slugs": ["", "", "", "alpha", ""],
    "unicode": ["مقدمة", "مقدمة", "مقدمة", "введение", "введение"],
    "suffix lookalikes": ["a_0", "a_0", "a", "a_00", "a_0"],
    "interleaved bases": ["a", "b", "a", "b", "a", "b", "a"],
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_output_is_identical_to_the_vendored_function(name, toc):
    candidates = CASES[name]
    assert _replacement(candidates) == _reference(candidates, toc)


def test_output_is_identical_with_ids_already_present(toc):
    # Explicit `{#id}` attributes seed `used` before any heading is seen.
    candidates = ["x", "x", "x", "y"]
    preset = {"x_1", "x_5", "y"}

    used_a = set(preset)
    expected = [toc.unique(c, used_a) for c in candidates]

    used_b, memo = set(preset), {}
    assert [mdext.unique_id(c, used_b, memo) for c in candidates] == expected


class _CountingSet(set):
    """Counts membership tests, which is what the vendored loop burns."""

    probes = 0

    def __contains__(self, value):
        self.probes += 1
        return super().__contains__(value)


def _probe_count(n):
    used, memo = _CountingSet(), {}
    used.probes = 0
    for _ in range(n):
        mdext.unique_id("usage", used, memo)
    return used.probes


def test_duplicate_resolution_is_linear_not_quadratic():
    """The permanent guard. An operation count, deliberately not a clock.

    A wall-clock threshold flakes on a shared CI runner and gets deleted.
    This counts membership probes: the vendored loop needs ~n^2/2 of them
    for n duplicates, the replacement a small constant multiple of n.
    """
    small, large = _probe_count(100), _probe_count(1600)
    # 16x the input for at most 32x the work: comfortably linear, and far
    # under the 256x a quadratic implementation would need.
    assert large <= small * 32, f"{small} probes at n=100, {large} at n=1600"
    assert large < 1600 * 4


def test_the_vendored_function_still_behaves_as_characterised(toc):
    """Pin the vendored algorithm, so a re-vendor that changes it is loud.

    `unique_id` is written to match this exact behaviour. If a future
    Python-Markdown changes it, this fails here -- with a clear reason --
    rather than leaving a replacement that silently no longer matches.
    """
    used = set()
    assert toc.unique("x", used) == "x"
    assert toc.unique("x", used) == "x_1"
    assert toc.unique("x", used) == "x_2"
    assert toc.unique("", used) == "_1"
    assert toc.unique("x_1", used) == "x_3"
    assert toc.IDCOUNT_RE.pattern == r"^(.*)_([0-9]+)$"


def test_the_extension_is_registered_over_the_vendored_treeprocessor():
    """The wrap only works if `toc` really is registered before xedown's."""
    from xedown import renderer

    converter = renderer._build_converter()
    assert "toc" in converter.treeprocessors
    processor = converter.treeprocessors["toc"]
    assert getattr(processor.run, "_xedown_fast_toc", False), (
        "xedown's fast heading-anchor wrap is not installed on the toc "
        "treeprocessor -- check extension ordering in make_extensions"
    )


def test_a_document_of_duplicate_headings_gets_the_expected_anchors():
    """End to end, through the real pipeline."""
    from xedown import renderer

    html = renderer.render_fragment("## Fixed\n\n## Fixed\n\n## Fixed\n")
    assert 'id="fixed"' in html
    assert 'id="fixed_1"' in html
    assert 'id="fixed_2"' in html
