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

# A run that starts before midnight and ends after it would otherwise slice
# backwards, silently attributing every later utterance to no marker at all.
_DAY = 86400.0


class EmptyTranscript(Exception):
    """No speech at all was captured.

    Raised rather than returning empty slices: a transcript with nothing in
    it means the capture failed, and reporting "no utterance matched" for
    every row would look like a set of real findings instead of a broken
    instrument.
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


def _unwrapped(stamps):
    """The same times, made monotonic by adding a day at each wrap."""
    out = []
    days = 0
    previous = None
    for stamp in stamps:
        if previous is not None and stamp < previous:
            days += 1
        out.append(stamp + days * _DAY)
        previous = stamp
    return out


def slice_by_marker(utterances, markers):
    """Marker name -> what was spoken between it and the next marker.

    Utterances before the first marker are dropped: Orca's own startup
    announcement and the window appearing are not evidence about any row.
    """
    if not utterances:
        raise EmptyTranscript("no SPEECH OUTPUT lines were captured")
    if not markers:
        return {}

    # Collect all events with metadata
    all_events = []
    for idx, (time, name) in enumerate(markers):
        all_events.append((time, "marker", idx, name))
    for idx, (time, text) in enumerate(utterances):
        all_events.append((time, "utterance", idx, text))

    # Sort by time to get chronological order
    sorted_events = sorted(all_events, key=lambda x: x[0])

    # Unwrap the times from the chronologically sorted sequence
    times_sorted = [t for t, _, _, _ in sorted_events]
    unwrapped_times_sorted = _unwrapped(times_sorted)

    # Process in chronological order
    utterance_markers = {}  # utterance_idx -> marker_name
    current_marker = None

    for (orig_time, event_type, idx, value), unwrapped_time in zip(
        sorted_events, unwrapped_times_sorted
    ):
        if event_type == "marker":
            current_marker = value
        else:  # utterance
            if current_marker is not None:
                utterance_markers[idx] = current_marker

    # Rebuild result in utterance order
    sliced = {name: [] for _, name in markers}
    for idx, (time, text) in enumerate(utterances):
        if idx in utterance_markers:
            sliced[utterance_markers[idx]].append(text)
    return sliced


def missing(spoken, expected):
    """Which `expected` strings nothing in `spoken` contains."""
    lowered = [text.lower() for text in spoken]
    return [
        want for want in expected if not any(want.lower() in got for got in lowered)
    ]


def _main(argv):
    """`python -m orca_transcript <orca.log> <markers> [--json]`.

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
    except EmptyTranscript as error:
        sys.stderr.write(f"EMPTY TRANSCRIPT: {error}\n")
        return 1
    json.dump(sliced, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
