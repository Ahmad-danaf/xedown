"""Run the differential over the corpus and print clustered findings.

Usage:  .venv/bin/python tests/compat/run_audit.py [--kind parser|allowlist]
"""

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TESTS_DIR = HERE.parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from compat import differential


def documents():
    corpus = HERE / "corpus"
    manifest = corpus / "MANIFEST.json"
    if manifest.exists():
        for entry in json.loads(manifest.read_text(encoding="utf-8")):
            path = corpus / f"{entry['name']}.md"
            if path.exists():
                yield path
    yield from sorted((HERE / "synthetic").glob("*.md"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=[differential.PARSER, differential.ALLOWLIST])
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()

    everything = []
    for path in documents():
        text = path.read_text(encoding="utf-8", errors="replace")
        result = differential.compare_document(text, str(path.parent), path.name)
        everything.extend(result.divergences)
        print(
            f"  audited {path.name}: {len(result.divergences)} divergences",
            file=sys.stderr,
        )

    if args.kind:
        everything = [d for d in everything if d.kind == args.kind]

    clusters = differential.cluster(everything)
    print(f"\n{len(everything)} divergences in {len(clusters)} clusters\n")
    for index, item in enumerate(clusters[: args.top], 1):
        print(f"--- {index}. [{item.kind}] x{item.count}")
        print(
            f"    signature: {item.signature[1]} {item.signature[2]!r} "
            f"-> {item.signature[3]!r}"
        )
        example = item.examples[0]
        print(f"    cmark : {example.left[:200]!r}")
        print(f"    xedown: {example.right[:200]!r}\n")


if __name__ == "__main__":
    main()
