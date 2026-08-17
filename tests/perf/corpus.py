"""The same measurements over the real-README corpus.

Reuses `tests/compat/corpus/`, which `scripts/fetch-corpus.sh` reproduces
from MANIFEST.json's pinned SHAs. Nothing here fetches anything: an absent
corpus is a skip with an instruction, not an error and not a download.

The images shape is the one place synthetic measurement misleads --
`images.classify_image` does a `stat` per reference, and a synthetic
document points at files that are not there. Corpus documents point at
files that are also not there, so both undercount equally; the honest
number for images comes from `--images-on-disk`, which run_bench builds a
real directory for.
"""

import pathlib

from . import measure

CORPUS_DIR = pathlib.Path(__file__).resolve().parent.parent / "compat" / "corpus"


def available():
    return CORPUS_DIR.is_dir() and any(CORPUS_DIR.glob("*.md"))


def read(name):
    """One named corpus document's text, or None if it is not there.

    For the measurements that name a specific document rather than
    sweeping the whole corpus -- the memory table's two real-README rows.
    Absent is None, not an error, for the same reason `available()`
    exists: nothing here fetches anything.
    """
    path = CORPUS_DIR / name
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def measure_corpus(repeat=1):
    """Every corpus document, slowest first. Empty if the corpus is absent."""
    if not available():
        return []
    rows = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append((path.name, measure.time_layers(text, repeat=repeat)))
    rows.sort(key=lambda row: row[1].fragment_ms, reverse=True)
    return rows
