"""Turn a stylesheet into `{selector: {property: value}}`.

Used by the v0.1 parity test and the token-contract tests. Grouped selectors
are split, so `pre, code { ... }` contributes to both `pre` and `code` — that
is what lets the base sheet and a theme sheet each own part of one v0.1 rule
and still compare equal to it. At-rule preludes are folded into the key, so
the `.xedown-document` inside `@media (max-width: 40rem)` never merges with
the top-level one.

This is not a CSS parser in any general sense. It handles exactly the subset
this repository writes: no strings containing braces, no semicolons inside
values, no at-rules nested more than one level deep.
"""

import re


def _normalise(text):
    return " ".join(text.split())


def _split_selector_list(prelude):
    """Split a selector group on top-level commas only.

    A bare `prelude.split(",")` breaks on `:is(a, b, c)` -- introduced by
    preview.css's `[align] :is(p, h1, ...)` rule -- by treating the commas
    inside the functional pseudo-class as if they separated whole selectors,
    scattering `h1`, `h2`, etc. out as spurious top-level keys. Depth-tracked
    so a comma inside any parenthesised argument list (`:is()`, `:not()`, a
    future `:where()`) stays part of the one selector it belongs to.
    """
    parts = []
    buffer = ""
    depth = 0
    for char in prelude:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append(buffer)
            buffer = ""
        else:
            buffer += char
    parts.append(buffer)
    return parts


def declarations(css, prefix=""):
    """`(map, duplicates)` for `css`.

    `duplicates` lists every `(selector, property)` declared more than once,
    which is how the parity test proves the base sheet and a theme sheet are
    disjoint rather than merely additive.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    out = {}
    duplicates = []
    buffer = ""
    index = 0
    while index < len(css):
        if css[index] != "{":
            buffer += css[index]
            index += 1
            continue

        prelude = _normalise(buffer)
        buffer = ""
        depth = 1
        start = index + 1
        index += 1
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        block = css[start : index - 1]

        if prelude.startswith("@"):
            nested, nested_duplicates = declarations(block, f"{prefix}{prelude} ")
            for key, value in nested.items():
                target = out.setdefault(key, {})
                for name, declared in value.items():
                    if name in target:
                        duplicates.append((key, name))
                    target[name] = declared
            duplicates.extend(nested_duplicates)
            continue

        for selector in _split_selector_list(prelude):
            selector = _normalise(selector)
            if not selector:
                continue
            key = prefix + selector
            target = out.setdefault(key, {})
            for declaration in block.split(";"):
                if ":" not in declaration:
                    continue
                name, _, value = declaration.partition(":")
                name = _normalise(name)
                if name in target:
                    duplicates.append((key, name))
                target[name] = _normalise(value)
    return out, duplicates
