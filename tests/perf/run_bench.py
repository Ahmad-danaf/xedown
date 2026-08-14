"""Measure the render pipeline. Run on demand; never part of the unit run.

    .venv/bin/python -m tests.perf.run_bench --shapes
    .venv/bin/python -m tests.perf.run_bench --sizes
    .venv/bin/python -m tests.perf.run_bench --corpus
    .venv/bin/python -m tests.perf.run_bench --all --json out.json

Wall-clock assertions do not belong in CI -- they flake on a shared
runner and get deleted within a month. The permanent guard against the
one cliff this pass found is an operation count, in
`tests/unit/test_toc_unique.py`. This is the tool a human runs when they
want the curve.
"""

import argparse
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "plugin"))

from tests.perf import corpus, generate, measure

_HEAD = f"{'shape':<20}{'chars':>10}{'parse':>10}{'sanitize':>10}{'fragment':>10}{'document':>10}"


def _row(label, timing):
    return (
        f"{label:<20}{timing.chars:>10}{timing.parse_ms:>9.0f}m"
        f"{timing.sanitize_ms:>9.0f}m{timing.fragment_ms:>9.0f}m"
        f"{timing.document_ms:>9.0f}m"
    )


def _shapes(records, repeat):
    print("\n=== shape sensitivity at 100k characters ===")
    print(_HEAD)
    for shape in generate.SHAPES:
        timing = measure.time_layers(generate.build(shape, 100_000), repeat=repeat)
        print(_row(shape, timing))
        records.append({"kind": "shape", "shape": shape, **timing._asdict()})


def _sizes(records, repeat):
    print("\n=== size scaling ===")
    print(_HEAD)
    for shape in ("prose", "tables"):
        for size in generate.SIZES:
            timing = measure.time_layers(generate.build(shape, size), repeat=repeat)
            print(_row(f"{shape} {size // 1000}k", timing))
            records.append(
                {"kind": "size", "shape": shape, "target": size, **timing._asdict()}
            )


def _images_on_disk(records, repeat):
    """The honest images number: references that resolve to real files.

    `images.classify_image` stats every reference. A synthetic document
    pointing at nothing measures the missing-file path, which is not what
    a reader with an illustrated README pays.
    """
    print("\n=== images, resolving to real files on disk ===")
    print(_HEAD)
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        (base / "img").mkdir()
        text = generate.build("images", 100_000)
        count = text.count("![")
        for i in range(count):
            (base / "img" / f"figure-{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        timing = measure.time_layers(text, base_dir=str(base), repeat=repeat)
        print(_row(f"images ({count} files)", timing))
        records.append({"kind": "images-on-disk", "files": count, **timing._asdict()})


def _corpus(records, repeat):
    print("\n=== real corpus ===")
    if not corpus.available():
        print("  corpus absent - run scripts/fetch-corpus.sh to populate it")
        return
    print(_HEAD)
    rows = corpus.measure_corpus(repeat=repeat)
    for name, timing in rows:
        print(_row(name[:19], timing))
        records.append({"kind": "corpus", "document": name, **timing._asdict()})
    total = sum(t.fragment_ms for _, t in rows)
    print(f"\n  {len(rows)} documents, {total / 1000:.1f}s total")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shapes", action="store_true")
    parser.add_argument("--sizes", action="store_true")
    parser.add_argument("--images-on-disk", action="store_true")
    parser.add_argument("--corpus", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    selected = any(
        (args.shapes, args.sizes, args.images_on_disk, args.corpus, args.all)
    )
    if not selected:
        parser.error(
            "choose at least one of --shapes --sizes --images-on-disk " "--corpus --all"
        )

    records = []
    if args.shapes or args.all:
        _shapes(records, args.repeat)
    if args.sizes or args.all:
        _sizes(records, args.repeat)
    if args.images_on_disk or args.all:
        _images_on_disk(records, args.repeat)
    if args.corpus or args.all:
        _corpus(records, args.repeat)

    if args.json is not None:
        args.json.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
