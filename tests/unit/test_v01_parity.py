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
    # v0.1 asked the browser to tint a native checkbox. v0.2 draws the
    # control instead, so the same token now fills the box directly. Same
    # accent, same theme, applied by us.
    ('li.task-list-item > input[type="checkbox"]', "accent-color"): (
        ('li.task-list-item > input[type="checkbox"]:checked', "background"),
        "var(--xedown-link)",
    ),
    # v0.1 capped every table at the container width, which meant a wide
    # table was compressed instead of scrolling inside its own wrapper.
    ("table", "width"): (("table", "width"), "auto"),
    # Brief 7: the list indent is start-relative, so bullets and their
    # indentation move to the right side of a right-to-left document. Every
    # substitution below is computed-identical for a left-to-right one --
    # which is what keeps "repository renders identically to 0.1.0" true.
    ("ul", "padding-left"): (("ul", "padding-inline-start"), "1.7em"),
    ("ol", "padding-left"): (("ol", "padding-inline-start"), "1.7em"),
    ("ul.task-list", "padding-left"): (
        ("ul.task-list", "padding-inline-start"),
        "1.2em",
    ),
    # Brief 7: v0.1's four-value shorthand said left and right separately,
    # which is the one shorthand form that cannot mirror. Split into a
    # symmetric block-axis pair plus a logical inline start.
    ("blockquote", "padding"): (("blockquote", "padding"), ".1em 0"),
    # Brief 7: the quote bar moves to the right side of a right-to-left
    # document.
    ("blockquote", "border-left"): (
        ("blockquote", "border-inline-start"),
        ".25em solid var(--xedown-quote-border)",
    ),
}

# Selectors v0.2 introduces that v0.1 never had.
#
# Admissible only when the selector cannot match anything a page v0.1 could
# have produced. That constraint is what keeps this from being a hole in the
# guard: a rule matching no element in an existing document cannot move an
# upgrading user's preview, which is the one thing this test exists to
# protect. Anything that could match existing markup is a change to v0.1's
# design and belongs in SUBSTITUTIONS, with its v0.1 counterpart named.
ADDITIONS = {
    # Emitted only when the user has set a custom stylesheet that could not
    # be used — and v0.1 had no such setting, so no v0.1 page contains one.
    ".xedown-notice",
    # v0.1 never set these classes on a table's wrapper, so a rule that only
    # matches their combination cannot match anything a v0.1 page produced.
    ".xedown-table-scroll.xedown-more-left",
    ".xedown-table-scroll.xedown-more-right",
    ".xedown-table-scroll.xedown-more-left.xedown-more-right",
    # Emitted only in alt-only mode, which v0.1 had no setting for.
    ".xedown-image-alt",
    ".xedown-code-block",
    ".xedown-copy",
    ".xedown-code-block:hover > .xedown-copy",
    ".xedown-copy:focus-visible",
    "@media (hover: none) .xedown-copy",
    # v0.1 emitted no `dir` attribute anywhere, so a rule scoped to
    # .xedown-document[dir="rtl"] cannot match anything a v0.1 page produced.
    '.xedown-document[dir="rtl"] .footnote a[href^="#fnref"]',
}

# Declarations v0.1 shipped that v0.2 deliberately DROPS, with no v0.2
# counterpart to put in SUBSTITUTIONS. Same doctrine as the two tables below:
# an entry here changes an upgrading user's preview, so it is a decision
# someone approved and the reason lives beside it.
#
# This table is the narrowest of the four, and should stay that way: a
# removal is the one kind of change that leaves nothing behind to compare, so
# nothing but the reason written here records that it was intended.
DELIBERATE_REMOVALS = {
    ("li", "unicode-bidi"): (
        "brief 7: under `plaintext` WebKit positions a list marker from the "
        "item's own content-derived direction rather than the list's. In a "
        "right-to-left document an item beginning with a bidi isolate -- "
        "which `a { unicode-bidi: plaintext }` makes every link -- paints its "
        "bullet over the text or drops it, and an item resolving the other "
        "way puts its bullet on the far side from its siblings. A marker is "
        "layout, and layout follows the document. `li { text-align: start }` "
        "is kept and now follows `direction`."
    ),
}

# Selectors v0.2 introduces that CAN match markup a v0.1 page contained --
# so each one does change an upgrading user's preview, on purpose.
#
# This is the escape hatch ADDITIONS deliberately refuses to be, and it is
# narrow for the same reason: an entry here is a design decision that
# someone approved, and the reason has to be written down beside it. What
# this guard exists to prevent is a preview moving *silently*, not a preview
# moving at all.
DELIBERATE_SELECTORS = {
    'li.task-list-item > input[type="checkbox"]:checked': (
        "brief 5: a drawn checkbox fills the box itself"
    ),
    'li.task-list-item > input[type="checkbox"]:checked::after': (
        "brief 5: the tick inside a drawn checkbox"
    ),
    "img:not([width]):not([height])": (
        "brief 5: very tall images are capped to the window"
    ),
}

# Properties v0.2 adds to a selector v0.1 already declared. Same doctrine as
# DELIBERATE_SELECTORS, at declaration rather than selector granularity.
DELIBERATE_DECLARATIONS = {
    ('li.task-list-item > input[type="checkbox"]', "position"): (
        "brief 5: the tick is positioned against the box"
    ),
    ('li.task-list-item > input[type="checkbox"]', "-webkit-appearance"): (
        "brief 5: drawn, not native"
    ),
    ('li.task-list-item > input[type="checkbox"]', "appearance"): (
        "brief 5: drawn, not native"
    ),
    ('li.task-list-item > input[type="checkbox"]', "background"): (
        "brief 5: the box's own surface"
    ),
    ('li.task-list-item > input[type="checkbox"]', "border"): (
        "brief 5: the box's own outline"
    ),
    ('li.task-list-item > input[type="checkbox"]', "border-radius"): (
        "brief 5: the box's own corners"
    ),
    ('li.task-list-item > input[type="checkbox"]', "opacity"): (
        "brief 5: a read-only control must not be dimmed like a disabled one"
    ),
    ('li.task-list-item > input[type="checkbox"]', "cursor"): (
        "brief 5: read-only, not unavailable"
    ),
    ("table", "min-width"): (
        "brief 5: a narrow table still fills the column while a wide one overflows"
    ),
    ("th", "min-width"): ("brief 5: a floor under column width"),
    ("td", "min-width"): ("brief 5: a floor under column width"),
    ("blockquote", "padding-inline-start"): (
        "brief 7: the quote's indent, split out of v0.1's four-value padding"
    ),
    ("a", "unicode-bidi"): (
        "brief 7: a link's text is its own bidi run, so a URL used as link "
        "text stops dragging the sentence's neutrals around"
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

    for selector, name in DELIBERATE_REMOVALS:
        # Dropped from v0.1's side before the comparison below, so the
        # removal is recorded rather than merely tolerated. Asserting it was
        # there in v0.1 is what keeps a stale entry from silently exempting
        # a property that no longer needs exempting.
        assert name in v01.get(selector, {}), (
            f"{selector} {{ {name} }} is in DELIBERATE_REMOVALS but v0.1 "
            "never declared it"
        )
        del v01[selector][name]
        assert name not in shipped.get(selector, {}), (
            f"{selector} {{ {name} }} is in DELIBERATE_REMOVALS but the "
            "shipped stylesheet still declares it"
        )

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
        if selector in ADDITIONS or selector in DELIBERATE_SELECTORS:
            continue
        for name, value in props.items():
            if name.startswith("--"):
                continue
            if (selector, name) in DELIBERATE_DECLARATIONS:
                continue
            assert (
                v01.get(selector, {}).get(name) == value
            ), f"{selector} {{ {name}: {value} }} is not in v0.1"


def test_every_addition_is_absent_from_v01():
    # An entry here that v0.1 also declared would silently stop comparing a
    # selector that does need comparing.
    v01, _ = declarations(V01.read_text(encoding="utf-8"))
    for selector in ADDITIONS:
        assert selector not in v01, f"{selector} exists in v0.1; it is not an addition"


def test_every_addition_is_actually_shipped():
    # A stale entry would leave the guard permanently relaxed for a selector
    # nothing declares any more.
    shipped, _ = _shipped()
    for selector in ADDITIONS:
        assert (
            selector in shipped
        ), f"{selector} is in ADDITIONS but nothing declares it"


def test_every_deliberate_selector_is_actually_shipped():
    shipped, _ = _shipped()
    for selector in DELIBERATE_SELECTORS:
        assert (
            selector in shipped
        ), f"{selector} is in DELIBERATE_SELECTORS but nothing declares it"


def test_every_deliberate_selector_is_absent_from_v01():
    # Same reason as ADDITIONS: an entry v0.1 also declared would exempt a
    # whole existing selector, which is exactly what DELIBERATE_DECLARATIONS
    # exists to make impossible one property at a time.
    v01, _ = declarations(V01.read_text(encoding="utf-8"))
    for selector in DELIBERATE_SELECTORS:
        assert (
            selector not in v01
        ), f"{selector} exists in v0.1; use DELIBERATE_DECLARATIONS"


def test_every_deliberate_declaration_is_actually_shipped():
    shipped, _ = _shipped()
    for selector, name in DELIBERATE_DECLARATIONS:
        assert name in shipped.get(selector, {}), (
            f"{selector} {{ {name} }} is in DELIBERATE_DECLARATIONS "
            "but nothing declares it"
        )
