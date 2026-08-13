"""Three renders, two diffs. See the design doc, section 8.

    cmark_raw       cmark-gfm, UNSAFE          what GitHub does
    cmark_sanitized sanitize(cmark_raw)        xedown's allowlist applied
                                               to GitHub's parse
    xedown_out      renderer.render_fragment   what xedown does

Diff A -- cmark_sanitized vs xedown_out -- is parser divergence alone,
because the same sanitizer ran on both sides and cancels out.

Diff B -- cmark_raw vs cmark_sanitized -- is exactly what xedown's
allowlist removes from a document GitHub renders in full.

Collapsing these into one diff would make every <details> in the corpus
look like a parser bug and bury the real parser findings under it.

UNSAFE is required on the cmark side: without it cmark escapes raw HTML,
and mixed HTML-and-Markdown -- one of the cases this audit exists to test
-- becomes uncomparable. Rendering unsafe and then sanitizing gives the
oracle the same shape as the pipeline it measures; it does not make the
oracle less safe, because nothing here is ever shown to a user.
"""

import collections
import difflib
import pathlib
import sys

import cmarkgfm
from cmarkgfm.cmark import Options as cmark_options

TESTS_DIR = pathlib.Path(__file__).resolve().parent.parent
PLUGIN_DIR = TESTS_DIR.parent / "plugin"
for _path in (str(TESTS_DIR), str(PLUGIN_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from xedown import renderer, sanitizer

from compat import normalise

PARSER = "parser"
ALLOWLIST = "allowlist"

ThreeRenders = collections.namedtuple(
    "ThreeRenders", "cmark_raw cmark_sanitized xedown_out"
)
Divergence = collections.namedtuple("Divergence", "kind signature left right")
DocumentResult = collections.namedtuple("DocumentResult", "name divergences")
Cluster = collections.namedtuple("Cluster", "kind signature count examples")

_CMARK_OPTIONS = cmark_options.CMARK_OPT_UNSAFE


def render_three_ways(text, base_dir):
    cmark_raw = cmarkgfm.github_flavored_markdown_to_html(text, options=_CMARK_OPTIONS)
    cmark_sanitized = sanitizer.sanitize(cmark_raw)
    xedown_out = renderer.render_fragment(text, base_dir=base_dir)
    return ThreeRenders(cmark_raw, cmark_sanitized, xedown_out)


def _opcodes(left, right):
    """Line-oriented differences between two canonical forms.

    Canonical HTML is one long line, so it is split on tag boundaries
    first: a per-character diff produces signatures too fine to cluster.
    """
    left_lines = left.replace("><", ">\n<").splitlines()
    right_lines = right.replace("><", ">\n<").splitlines()
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        yield tag, "\n".join(left_lines[i1:i2]), "\n".join(right_lines[j1:j2])


def _signature(kind, operation, left, right):
    """A stable key for clustering: what changed, not which document.

    Thirty instances of one root cause must arrive as one finding with a
    count, not thirty findings.
    """

    def shape(fragment):
        return " ".join(
            part.split()[0].lstrip("<").rstrip(">")
            for part in fragment.splitlines()
            if part.startswith("<")
        )[:120]

    return (kind, operation, shape(left), shape(right))


def compare_document(text, base_dir, name="<memory>"):
    renders = render_three_ways(text, base_dir)
    divergences = []

    for kind, left_html, right_html in (
        (PARSER, renders.cmark_sanitized, renders.xedown_out),
        (ALLOWLIST, renders.cmark_raw, renders.cmark_sanitized),
    ):
        left = normalise.canonicalise(left_html, base_dir=base_dir)
        right = normalise.canonicalise(right_html, base_dir=base_dir)
        for operation, left_part, right_part in _opcodes(left, right):
            divergences.append(
                Divergence(
                    kind=kind,
                    signature=_signature(kind, operation, left_part, right_part),
                    left=left_part[:400],
                    right=right_part[:400],
                )
            )
    return DocumentResult(name=name, divergences=divergences)


def cluster(divergences):
    grouped = collections.OrderedDict()
    for divergence in divergences:
        grouped.setdefault(divergence.signature, []).append(divergence)
    clusters = [
        Cluster(
            kind=members[0].kind,
            signature=signature,
            count=len(members),
            examples=members[:3],
        )
        for signature, members in grouped.items()
    ]
    clusters.sort(key=lambda item: item.count, reverse=True)
    return clusters
