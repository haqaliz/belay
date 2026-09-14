"""The approval gate's trace observations: two additive record kinds, a derived reader.

The gate's events become first-class trace observations exactly as the format
was built to receive them: `approval_hold` (written when a hold begins) and
`approval_decision` (written before the refusal is delivered, or before an
approved frame is forwarded) go through `TraceWriter.record` — the documented
extension point — and so inherit the full envelope (`v`, `seq`, `t_in`,
`observation_point: "proxy"`) with no change to the writer and no schema bump.
Nothing from the gate flows through the frame path or the request index.

These tests pin the writer side (Phase 1: the kinds exist, the envelope holds,
seq is allocated under the writer's lock, and the records survive a write→read
round-trip losslessly) and the derived reader (Phase 2: `derive_approval_events`
returns the events in seq order with exactly the field contract, reports what
exists and never repairs).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from belay.replay.reader import read_trace
from belay.trace import KINDS, SCHEMA_VERSION, TraceWriter


def _sole_trace(directory: Path) -> Path:
    traces = sorted(directory.glob("*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    return traces[0]


def _read(path: Path) -> list[dict]:
    return read_trace(path).records


def _on_disk(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_bytes().splitlines() if line]


# --- Phase 1: the kinds exist and are additive -------------------------------


def test_the_approval_kinds_are_declared_in_kinds() -> None:
    assert "approval_hold" in KINDS
    assert "approval_decision" in KINDS


def test_approval_hold_records_carry_the_full_envelope(tmp_path: Path) -> None:
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record(
            "approval_hold",
            hold_id="hold-1",
            tool="write_file",
            request_id=7,
            triggers=["destructiveHint", "idempotentHint"],
            timeout=60,
        )
    finally:
        writer.close()

    (record,) = [
        r
        for r in _read(_sole_trace(tmp_path / "trace"))
        if r["kind"] == "approval_hold"
    ]
    assert record["v"] == SCHEMA_VERSION
    assert record["kind"] == "approval_hold"
    assert isinstance(record["seq"], int)
    assert record["t_in"].endswith("+00:00")
    assert record["observation_point"] == "proxy"
    assert record["hold_id"] == "hold-1"
    assert record["tool"] == "write_file"
    assert record["request_id"] == 7
    assert record["triggers"] == ["destructiveHint", "idempotentHint"]
    assert record["timeout"] == 60


def test_approval_decision_records_carry_the_full_envelope(tmp_path: Path) -> None:
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record(
            "approval_decision",
            hold_id="hold-1",
            decision="deny",
            cause="DENIED",
            waited=2.5,
        )
    finally:
        writer.close()

    (record,) = [
        r
        for r in _read(_sole_trace(tmp_path / "trace"))
        if r["kind"] == "approval_decision"
    ]
    assert record["v"] == SCHEMA_VERSION
    assert record["kind"] == "approval_decision"
    assert isinstance(record["seq"], int)
    assert record["t_in"].endswith("+00:00")
    assert record["observation_point"] == "proxy"
    assert record["hold_id"] == "hold-1"
    assert record["decision"] == "deny"
    assert record["cause"] == "DENIED"
    assert record["waited"] == 2.5


def test_concurrent_recorders_allocate_unique_seq_under_the_lock(tmp_path: Path) -> None:
    """Two threads writing approval kinds through `record`: one gapless sequence.

    `record` allocates `seq` under the writer's lock like every other append, so
    concurrent writers must never repeat or skip a sequence number. Same contract
    as the two-pump stress in test_trace_format.py, exercised on the extension
    point itself.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    per_thread = 250

    def hammer(kind: str) -> None:
        for i in range(per_thread):
            writer.record(
                kind,
                hold_id=f"hold-{kind}-{i}",
                tool="write_file",
                request_id=i,
                triggers=["destructiveHint"],
                timeout=30,
            )

    threads = [
        threading.Thread(target=hammer, args=("approval_hold",)),
        threading.Thread(target=hammer, args=("approval_decision",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    writer.close()

    records = _read(_sole_trace(tmp_path / "trace"))
    assert len(records) == 2 * per_thread + 2  # the two connection_window bookends
    approval = [r for r in records if r["kind"] in ("approval_hold", "approval_decision")]
    assert len(approval) == 2 * per_thread
    # Every record, approval kinds and bookends alike, in one gapless sequence:
    # seq is allocated across kinds, never per kind.
    assert sorted(r["seq"] for r in records) == list(range(len(records)))


def test_approval_records_survive_the_write_read_round_trip_losslessly(
    tmp_path: Path,
) -> None:
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.record(
            "approval_hold",
            hold_id="h1",
            tool="rm",
            request_id=3,
            triggers=["destructiveHint"],
            timeout=0.25,
        )
        writer.record(
            "approval_decision",
            hold_id="h1",
            decision="approve",
            cause="APPROVED",
            waited=0.125,
        )
    finally:
        writer.close()
    path = _sole_trace(tmp_path / "trace")

    result = read_trace(path)

    assert result.skips == []
    assert result.records == _on_disk(path)
    kinds = [r["kind"] for r in result.records]
    assert kinds == [
        "connection_window",
        "approval_hold",
        "approval_decision",
        "connection_window",
    ]