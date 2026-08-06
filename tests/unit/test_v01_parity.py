"""The `repository` theme is the stylesheet xedown 0.1.0 shipped.

"Visually identical to v0.1" is otherwise a claim nobody can check. This
compares the base sheet plus `themes/repository.css`, merged, against a frozen
copy of v0.1's `preview.css`, and permits exactly the deviations in
SUBSTITUTIONS.
"""

import pathlib

from xedown import vendoring

from .cssparse import declarations

V01 = pathlib.Path(__file__).resolve().parent.parent / "fixtures" / "v0.1-preview.css"

# (v0.1 selector, property) -> ((v0.2 selector, property), value)
SUBSTITUTIONS = {
    # v0.1 sized text on `body` while sizing the measure in `rem`, which
    # resolves against the *root* element -- so text size and content width
    # could never scale together, which brief 1 recorded for brief 4.
    # Declaring it on :root fixes that in advance and is computed-identical
    # here: the root default is 16px and repository's text scale is 1.
    ("body", "font-size"): (
        (":root", "font-size"),
        "calc(var(--xedown-text-size) * var(--xedown-text-scale))",
    ),
    # 46rem times a measure scale of 1. The indirection is what lets brief 4
    # move the width while each theme keeps its own proportions.
    (".xedown-document", "max-width"): (
        (".xedown-document", "max-width"),
        "calc(var(--xedown-content-width) * var(--xedown-measure-scale))",
    ),
}


def _shipped():
    """The declarations a `repository` preview actually receives."""
    return declarations(
        vendoring.read_resource("preview.css")
        + "\n"
        + vendoring.read_resource("themes/repository.css")
    )


def test_base_and_repository_never_declare_the_same_property_twice():
    # Disjointness is what makes the comparison below an equality rather than
    # a cascade simulation: if both layers set `pre { padding }`, the merged
    # map silently keeps one and the test would prove nothing.
    _, duplicates = _shipped()
    assert duplicates == []


def test_repository_is_the_v01_stylesheet():
    v01, v01_duplicates = declarations(V01.read_text(encoding="utf-8"))
    assert v01_duplicates == []
    shipped, _ = _shipped()

    for old, new in SUBSTITUTIONS.items():
        old_selector, old_property = old
        (new_selector, new_property), new_value = new
        assert old_property in v01.get(old_selector, {})
        del v01[old_selector][old_property]
        assert shipped.get(new_selector, {}).get(new_property) == new_value
        del shipped[new_selector][new_property]

    for selector, props in v01.items():
        for name, value in props.items():
            assert shipped.get(selector, {}).get(name) == value, (
                f"v0.1 declared {selector} {{ {name}: {value} }} and the "
                f"shipped stylesheet does not"
            )

    # A custom property nothing references changes nothing, and every
    # reference is itself a value compared above -- so v0.2's added tokens are
    # allowed while every real declaration must match.
    for selector, props in shipped.items():
        for name, value in props.items():
            if name.startswith("--"):
                continue
            assert (
                v01.get(selector, {}).get(name) == value
            ), f"{selector} {{ {name}: {value} }} is not in v0.1"
