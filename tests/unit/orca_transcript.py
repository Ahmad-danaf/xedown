"""Orca's speech log, sliced by what the probe was doing at the time.

Pure logic -- no GTK, no `gi`. That is what lets CI test the slicing without
a display, a nested X server or a screen reader, and it is why this module
takes text rather than file handles.

An utterance on its own proves nothing: "Orca said 'Preview'" is only
evidence if it is known which action produced it. The probe writes a marker
per action; every utterance belongs to the most recent marker before it.
"""

import re
import sys

# Orca writes `HH:MM:SS.ffffff - SPEECH OUTPUT: 'text' {voice dict}`. The
# text is captured to end of line rather than to a closing quote: an
# utterance may itself contain an apostrophe, and Orca does not escape it.
_UTTERANCE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}\.\d+) - SPEECH OUTPUT: '(.*)$")
# The voice dict Orca appends after the closing quote. Optional: some call
# sites log the text alone.
_TRAILING_VOICE = re.compile(r"'\s*\{.*\}\s*$")
_MARKER = re.compile(r"^(\d{2}):(\d{2}):(\d{2}\.\d+)\s+(\S+)\s*$")


class EmptyTranscript(Exception):
    """No speech at all was captured.

    Raised rather than returning empty slices: a transcript with nothing in
    it means the capture failed, and reporting "no utterance matched" for
    every row would look like a set of real findings instead of a broken
    instrument.
    """


class AmbiguousTimeline(Exception):
    """A transcript's timestamps step backwards, preventing safe attribution.

    This can indicate a genuine midnight crossing, or corrupted/out-of-order
    input. The module refuses both cases rather than silently losing data:
    a component that exists to make silence trustworthy must never
    manufacture silence.
    """


def _seconds(hours, minutes, seconds):
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_utterances(text):
    """Every `SPEECH OUTPUT` line, as `(seconds_since_midnight, spoken)`."""
    found = []
    for line in text.splitlines():
        match = _UTTERANCE.match(line)
        if match is None:
            continue
        hours, minutes, seconds, rest = match.groups()
        spoken = _TRAILING_VOICE.sub("", rest)
        spoken = spoken.removesuffix("'")
        found.append((_seconds(hours, minutes, seconds), spoken))
    return found


def parse_markers(text):
    """Every marker the probe wrote, as `(seconds_since_midnight, name)`."""
    found = []
    for line in text.splitlines():
        match = _MARKER.match(line)
        if match is None:
            continue
        hours, minutes, seconds, name = match.groups()
        found.append((_seconds(hours, minutes, seconds), name))
    return found


def slice_by_marker(utterances, markers):
    """Marker name -> what was spoken between it and the next marker.

    Utterances before the first marker are dropped: Orca's own startup
    announcement and the window appearing are not evidence about any row.

    Raises AmbiguousTimeline if either the marker or utterance timestamps
    step backwards. This catches genuine midnight crossings, corrupted input,
    and out-of-order logs — all cases where silent data loss would be worse
    than a loud failure.
    """
    if not utterances:
        raise EmptyTranscript("no SPEECH OUTPUT lines were captured")
    if not markers:
        return {}

    marker_times = [t for t, _ in markers]
    utterance_times = [t for t, _ in utterances]

    # Check for backwards steps in markers (catches midnight, corruption, etc.)
    for i in range(1, len(marker_times)):
        if marker_times[i] < marker_times[i - 1]:
            raise AmbiguousTimeline(
                f"marker times step backwards: {marker_times[i - 1]} -> {marker_times[i]}"
            )

    # Check for backwards steps in utterances
    for i in range(1, len(utterance_times)):
        if utterance_times[i] < utterance_times[i - 1]:
            raise AmbiguousTimeline(
                f"utterance times step backwards: {utterance_times[i - 1]} -> {utterance_times[i]}"
            )

    # Both lists are now guaranteed monotonic; slice safely
    sliced = {name: [] for _, name in markers}

    for utt_time, utt_text in utterances:
        # Find the most recent marker that precedes this utterance
        best_marker_idx = -1
        for marker_idx, marker_time in enumerate(marker_times):
            if marker_time <= utt_time:
                best_marker_idx = marker_idx
            else:
                break  # Monotonic, so we can stop early

        if best_marker_idx >= 0:
            sliced[markers[best_marker_idx][1]].append(utt_text)

    return sliced


def missing(spoken, expected):
    """Which `expected` strings nothing in `spoken` contains."""
    lowered = [text.lower() for text in spoken]
    return [
        want for want in expected if not any(want.lower() in got for got in lowered)
    ]


class Exact(list):
    """A `rows` entry that `spoken` must equal, not merely contain.

    A plain list keeps meaning substring containment (`missing`'s rule,
    unchanged): every string in it has to appear *somewhere* in what Orca
    said, case-insensitively, and extra utterances alongside it are fine.
    That is deliberately loose for rows where several controls each speak in
    turn (`row-99-search-bar-tab`) -- but it is too loose for a row measured
    to produce exactly one utterance, word for word: a substring check on
    `["Preview"]` is also satisfied by "Preview toggle button pressed.",
    which is precisely the misattributed utterance that fooled three review
    rounds earlier in this project before it was traced to a different,
    unmarked action. Wrapping a row's expected list in `Exact` closes that
    hole at the gate itself: `spoken` must equal `list(expected)` --
    same utterances, same order, nothing missing and nothing extra.
    """


def evaluate_rows(sliced, rows, silent_rows):
    """Check a sliced transcript against two expectation tables.

    `rows` maps marker name -> a list of substrings that must all appear,
    case-insensitively, somewhere in what was spoken during that marker's
    window. An empty or missing slice FAILs there: silence is a finding, not
    a pass -- a11y.check_tree's rule. Wrap the list in `Exact` (above) to
    require `spoken` to equal it exactly instead of merely contain it --
    for a row measured to produce one utterance and no other.

    `silent_rows` is an iterable of marker names that must have produced NO
    speech at all. A marker with any utterance FAILs there -- that would be
    news (something changed) worth surfacing loudly, not something to
    silently absorb.

    Both tables FAIL on a *missing* marker (the key absent from `sliced`
    entirely), because that means the probe never reached the action, in
    either direction: an assertion that found nothing is not a pass. This is
    the one place the two tables agree; on an *empty but present* slice they
    deliberately disagree -- that is `rows` vs. `silent_rows`'s whole reason
    to exist as two tables rather than one with a sign bit.

    Returns one "PASS <row> - ..." or "FAIL <row> - ..." line per row, in
    the order `rows` then `silent_rows` were given -- `scripts/run-orca-
    tests.sh` prints these directly and fails the run if any starts with
    "FAIL". Kept here, not inline in that script, so the decision that
    publishes an accessibility finding has unit test coverage independent of
    a live Orca session.
    """
    lines = []
    for row, expected in rows.items():
        spoken = sliced.get(row)
        if spoken is None:
            lines.append(f"FAIL {row} - no such marker in the transcript")
            continue
        if not spoken:
            lines.append(f"FAIL {row} - Orca said nothing at all")
            continue
        if isinstance(expected, Exact):
            wanted = list(expected)
            if spoken == wanted:
                lines.append(f"PASS {row} - exactly {wanted!r}")
            else:
                lines.append(
                    f"FAIL {row} - expected exactly {wanted!r}, Orca said {spoken!r}"
                )
            continue
        absent = missing(spoken, expected)
        if absent:
            lines.append(f"FAIL {row} - never said: {absent} (said: {spoken})")
        else:
            lines.append(f"PASS {row} - {expected}")

    for row in silent_rows:
        spoken = sliced.get(row)
        if spoken is None:
            lines.append(f"FAIL {row} - no such marker in the transcript")
            continue
        if spoken:
            lines.append(f"FAIL {row} - Orca spoke, expected silence: {spoken}")
        else:
            lines.append(f"PASS {row} - silent, as measured")

    return lines


def _main(argv):
    """`python -m orca_transcript <orca.log> <markers>`.

    The harness shells out to this rather than re-implementing the slicing
    in bash, so there is one parser with one set of tests behind it.
    """
    import json

    if len(argv) < 3:
        sys.stderr.write("usage: orca_transcript <orca-log> <marker-file>\n")
        return 2
    with open(argv[1], encoding="utf-8", errors="replace") as handle:
        log = handle.read()
    with open(argv[2], encoding="utf-8") as handle:
        marks = handle.read()
    try:
        sliced = slice_by_marker(parse_utterances(log), parse_markers(marks))
    except (EmptyTranscript, AmbiguousTimeline) as error:
        sys.stderr.write(f"ERROR: {error.__class__.__name__}: {error}\n")
        return 1
    json.dump(sliced, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
