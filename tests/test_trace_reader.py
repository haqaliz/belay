"""The trace reader: read a trace file back into records, honouring C1's contract.

`belay.trace` is writer-only. Before C3 can replay a recorded turn it must read the
trace back — and the one rule that makes that safe is the unknown-kind rule C1 wrote
into the format (trace.py:48-52, docs/technical/TRACE_FORMAT.md): a record whose
`kind` is unknown, or whose `v` is higher than this reader understands, must be
SKIPPED and the skip RECORDED. Never dropped silently (that hides data — the exact
false-completeness this project exists to catch), never fatal (an old reader must
survive a new writer).

These tests are written against the real writer where they can be, so the reader is
tested against the format as WRITTEN, not against a fabricated envelope. The two
cases the current writer cannot produce — a higher `v`, and a genuinely broken line
— are hand-crafted onto a real trace file, which is exactly how a future writer or a
damaged disk would present them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.index import derive_correlation
from belay.replay.reader import ReadResult, Skip, TraceCorrupt, read_trace
from belay.trace import KINDS, SCHEMA_VERSION, TraceWriter


def _sole_trace(directory: Path) -> Path:
    traces = sorted(directory.glob("*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    return traces[0]


def _write_real_trace(tmp_path: Path, frames: list[tuple[str, bytes]]) -> Path:
    """Record `frames` through the REAL writer and return the trace file's path.

    Each frame is `(direction, raw_bytes)`. Going through `TraceWriter` means the
    reader is exercised against bytes the writer actually emits — a hand-built
    envelope would only ever test the reader against the test's idea of the format.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for direction, raw in frames:
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return _sole_trace(tmp_path / "trace")


# A conforming request, so the round-trip has a real frame to carry.
_INIT = (
    b'{"jsonrpc":"2.0","id":1,"method":"initialize",'
    b'"params":{"protocolVersion":"2025-11-25"}}'
)


def test_normal_trace_round_trips_with_zero_skips(tmp_path: Path) -> None:
    """A real trace reads back to exactly its records, and skips nothing.

    The writer brackets the frames with `connection_window` open/close and stamps
    every record `v == SCHEMA_VERSION` with a known `kind`, so a reader that honours
    the current schema must return all of them and skip none.
    """
    path = _write_real_trace(tmp_path, [("c2s", _INIT)])

    result = read_trace(path)

    assert isinstance(result, ReadResult)
    assert result.skips == []
    # Every record the writer wrote comes back, in order, byte-for-byte equal.
    on_disk = [json.loads(line) for line in path.read_bytes().splitlines() if line]
    assert result.records == on_disk
    # And it really did read the frame, not just the window bookends.
    kinds = [r["kind"] for r in result.records]
    assert kinds == ["connection_window", "frame", "connection_window"]


def test_unknown_kind_is_skipped_and_recorded(tmp_path: Path) -> None:
    """An unknown `kind` -> in `skips`, naming the kind, and NOT in `records`.

    `nondeterminism` is a kind C3 itself will append later; it is valid `v == 1`
    data this reader does not yet understand. The writer's own `record()` produces
    it as a genuine record, so this is the real forward-compat case, not a mock.

    A naive reader fails this test twice over: it either includes the unknown record
    in `records` (claiming it understood it) or drops it with no `skips` entry
    (hiding that anything was there). Both are the false-completeness the rule bans.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record("nondeterminism", detail="a kind this reader does not know")
    finally:
        writer.close()
    path = _sole_trace(tmp_path / "trace")

    result = read_trace(path)

    assert all(r["kind"] != "nondeterminism" for r in result.records)
    unknown = [s for s in result.skips if s.kind == "nondeterminism"]
    assert len(unknown) == 1, f"the unknown kind must be recorded once, got {result.skips!r}"
    assert "nondeterminism" in unknown[0].reason


def test_higher_version_is_skipped_and_recorded(tmp_path: Path) -> None:
    """A record with `v` higher than understood -> skipped, naming the version.

    The current writer only ever stamps `v == SCHEMA_VERSION`, so a future version
    is appended by hand onto a real trace — exactly how a newer writer would present
    it to this older reader. The reader must survive it and say what it saw.
    """
    path = _write_real_trace(tmp_path, [("c2s", _INIT)])
    future = {
        "v": SCHEMA_VERSION + 1,
        "kind": "frame",  # a KNOWN kind: it is the VERSION that is unreadable
        "seq": 999,
        "t_in": "2026-07-16T00:00:00+00:00",
        "observation_point": "proxy",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(future) + "\n")

    result = read_trace(path)

    assert all(r.get("seq") != 999 for r in result.records)
    versioned = [s for s in result.skips if s.seq == 999]
    assert len(versioned) == 1, f"the higher-version record must be recorded, got {result.skips!r}"
    assert str(SCHEMA_VERSION + 1) in versioned[0].reason


def test_corrupt_line_raises_and_is_not_a_skip(tmp_path: Path) -> None:
    """A line that is not valid JSON -> raises. A skip means the opposite.

    A skip is "I read a valid record and do not understand it". A broken line is
    "this is not a trace" — a different failure, and it must not be laundered into a
    skip, which would let a corrupted file read back as a merely-incomplete one.
    """
    trace_dir = tmp_path / "trace"
    path = _write_real_trace(tmp_path, [("c2s", _INIT)])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{this is not json at all\n")

    with pytest.raises(TraceCorrupt) as excinfo:
        read_trace(path)
    # It is NOT the graceful skip path: nothing about this is a Skip.
    assert not isinstance(excinfo.value, Skip)
    del trace_dir


def test_the_skip_is_observable(tmp_path: Path) -> None:
    """A caller can see exactly what was skipped and why. A silent drop fails here.

    This is the whole point of "recorded": every field a downstream reader needs to
    know a record was dropped, and why, is on the `Skip`. If the reader dropped the
    record with no observable trace, `skips` would be empty and this fails.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record("nondeterminism", detail="unknown to this reader")
    finally:
        writer.close()
    path = _sole_trace(tmp_path / "trace")

    result = read_trace(path)

    assert len(result.skips) == 1
    skip = result.skips[0]
    assert skip.kind == "nondeterminism"
    assert skip.seq is not None  # the writer stamped a seq; the skip preserves it
    assert isinstance(skip.reason, str) and skip.reason  # a non-empty why


def test_read_records_feed_correlation_unchanged(tmp_path: Path) -> None:
    """The reader produces records; correlation stays in `index.py`.

    Proves the reuse contract: the records `read_trace` returns are the exact input
    `derive_correlation` already consumes, so the reader does not reimplement — or
    perturb — the correlation it feeds.
    """
    path = _write_real_trace(tmp_path, [("c2s", _INIT)])

    result = read_trace(path)
    on_disk = [json.loads(line) for line in path.read_bytes().splitlines() if line]

    assert derive_correlation(result.records) == derive_correlation(on_disk)


def test_reader_understands_every_current_kind(tmp_path: Path) -> None:
    """Every kind the writer declares is a kind the reader keeps, not skips.

    A drift where the writer adds a kind to `KINDS` but the reader still skips it
    would silently discard live data. Pinning the reader's understanding to the
    writer's `KINDS` is what stops that.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for kind in KINDS:
            if kind == "frame":
                writer.observer("c2s")(_INIT, False)
            else:
                writer.record(kind, note="present")
    finally:
        writer.close()
    path = _sole_trace(tmp_path / "trace")

    result = read_trace(path)

    assert result.skips == []
    assert {r["kind"] for r in result.records} >= set(KINDS)
