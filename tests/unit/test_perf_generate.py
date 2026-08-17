"""The perf harness's generator is pure, so it is tested where tests run."""

import pytest

from tests.perf import generate


def test_every_shape_is_buildable():
    for shape in generate.SHAPES:
        assert generate.build(shape, 1000), f"{shape} produced nothing"


def test_output_is_deterministic():
    # A benchmark whose input differs per run cannot detect a regression.
    for shape in generate.SHAPES:
        assert generate.build(shape, 5000) == generate.build(shape, 5000)


def test_size_is_close_to_the_target():
    for shape in generate.SHAPES:
        text = generate.build(shape, 20_000)
        assert (
            0.8 * 20_000 <= len(text) <= 1.25 * 20_000
        ), f"{shape}: asked for 20000 chars, got {len(text)}"


def test_unique_and_duplicate_headings_are_different_shapes():
    # The whole point of the pair: toc.unique's cost depends on collisions,
    # so a generator that made them identical would hide the cliff.
    uniq = generate.build("headings-unique", 20_000)
    dupe = generate.build("headings-duplicate", 20_000)
    assert uniq != dupe
    assert len(set(uniq.splitlines())) > len(set(dupe.splitlines()))


def test_tables_shape_emits_a_single_header_row():
    # The whole shape must be one table, not thousands of one-row tables.
    text = generate.build("tables", 20_000)
    assert text.count("|---|---|---|---|") == 1


def test_unknown_shape_is_an_error():
    with pytest.raises(KeyError):
        generate.build("no-such-shape", 100)
