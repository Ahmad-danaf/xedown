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
                out.setdefault(key, {}).update(value)
            duplicates.extend(nested_duplicates)
            continue

        for selector in prelude.split(","):
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
