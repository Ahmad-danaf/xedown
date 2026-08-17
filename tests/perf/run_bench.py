"""Measure the render pipeline. Run on demand; never part of the unit run.

    .venv/bin/python -m tests.perf.run_bench --shapes
    .venv/bin/python -m tests.perf.run_bench --sizes
    .venv/bin/python -m tests.perf.run_bench --corpus
    .venv/bin/python -m tests.perf.run_bench --memory
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


# Decimal, not 1024 * 1024, and the one place in the tree that differs:
# `perflimits.describe_bytes` deliberately calls a mebibyte "MB" because
# that is what a file manager shows the reader. Nothing here is shown to a
# reader -- it is a published measurement, so it uses the unit the symbol
# actually means, and `docs/performance.md` says so above the table.
_MB = 1_000_000

_MEMORY_HEAD = (
    f"{'case':<24}{'chars':>10}{'peak':>12}{'above floor':>14}{'x chars':>10}"
)


def _memory(records):
    """Peak allocation during a full render, by `tracemalloc`.

    A separate pass rather than a fifth column on the timing tables,
    because it cannot share their runs: tracing every allocation costs
    several times the render itself, so a time taken under it measures
    the tracer. `--repeat` does not apply here either -- peak allocation
    is deterministic where wall clock is not.

    The first case is an empty document, which is the fixed floor every
    other row is quoted against: the self-contained page inlines its CSS,
    its JavaScript and the highlight.js bundle whatever the document
    says, and `read_vendor_file` re-reads that bundle on every render, so
    the floor is a real per-render cost rather than a one-off. The two
    corpus rows are skipped, with the same instruction the corpus pass
    prints, when the corpus is absent -- the four synthetic rows still
    run.

    One render is discarded before any of them, and it has to be. The
    *first* render in a process also pays Python-Markdown's lazy import
    of its extension modules and every regex they compile, which is
    around 4 MB that no later render pays again -- measured: an empty
    document peaks at 4.9 MB cold and 0.74 MB warm -- both in the decimal
    MB this table prints, so they read against it directly. Leaving that in
    would put the whole table's floor six times too high and turn every
    "above the floor" figure into nonsense.
    """
    print("\n=== peak memory during render_document (tracemalloc) ===")
    print(_MEMORY_HEAD)
    measure.peak_render_bytes("warm up the interpreter, discard the result")
    biggest = generate.SIZES[-1]
    cases = [
        ("empty document", ""),
        ("prose", generate.build("prose", biggest)),
    ]
    if corpus.available():
        for name in ("public-apis.md", "awesome-go.md"):
            text = corpus.read(name)
            if text is None:
                # Said out loud, not dropped. A corpus that is present but
                # missing one document is a fetch that half worked, and a
                # table quietly one row short is worse than a corpus that
                # is plainly absent -- that case at least announces itself.
                print(f"  {name} not in the corpus - that row skipped")
                continue
            cases.append((f"{name[:-3]} (corpus)", text))
    else:
        print("  corpus rows skipped - run scripts/fetch-corpus.sh to populate it")
    cases += [
        ("tables", generate.build("tables", biggest)),
        ("headings, repeated", generate.build("headings-duplicate", biggest)),
    ]

    floor = None
    for label, text in cases:
        peak = measure.peak_render_bytes(text)
        if floor is None:
            floor = peak
        above = peak - floor
        ratio = f"{above / len(text):.0f}x" if text else "-"
        # `or 0.0` is the negative-zero guard, not a default: a row landing
        # a few bytes under the floor rounds to -0.0, which is falsy, and
        # "-0.0 MB" reads as a measurement error rather than as "at the
        # floor". A deficit large enough to round to -0.1 is truthy and
        # still prints, because that one would be worth seeing.
        above_mb = f"{round(above / _MB, 1) or 0.0:.1f} MB" if text else "-"
        print(
            f"{label:<24}{len(text):>10}{peak / _MB:>10.2f}MB"
            f"{above_mb:>14}{ratio:>10}"
        )
        records.append(
            {
                "kind": "memory",
                "case": label,
                "chars": len(text),
                "peak_bytes": peak,
                "above_floor_bytes": above,
            }
        )


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
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=pathlib.Path, default=None)
    args = parser.parse_args(argv)

    selected = any(
        (
            args.shapes,
            args.sizes,
            args.images_on_disk,
            args.corpus,
            args.memory,
            args.all,
        )
    )
    if not selected:
        parser.error(
            "choose at least one of --shapes --sizes --images-on-disk "
            "--corpus --memory --all"
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
    # Last, and outside `--repeat`: see `_memory`. Included in `--all` so
    # that "run_bench reproduces every table" stays true of one command.
    if args.memory or args.all:
        _memory(records)

    if args.json is not None:
        args.json.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
