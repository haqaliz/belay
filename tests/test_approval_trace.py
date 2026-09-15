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
round-trip losslessly), the derived reader (Phase 2: `derive_approval_events`
returns the events in seq order with exactly the field contract, reports what
exists and never repairs), and the e2e traces the real gate writes (Phase 3:
hold-then-decision ordering in a subprocess-level deny/approve/timeout run,
never a frame for a suppressed request or its refusal, a clean correlation
index, and the old-reader round trip that skips the kinds by name).
"""

from __future__ import annotations

import base64
import json
import threading
from pathlib import Path

from belay.approval.reader import APPROVAL_KINDS, derive_approval_events
from belay.index import derive_correlation
from belay.replay.reader import read_trace
from belay.trace import KINDS, SCHEMA_VERSION, TraceWriter
from test_approval_proxy import (
    approval_env,
    run_proxy_phased,
    server_cmd,
    write_decision,
)


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


# --- Phase 2: the derived reader ---------------------------------------------


def _hold(seq: int, **extra: object) -> dict:
    return {
        "kind": "approval_hold",
        "seq": seq,
        "hold_id": "h1",
        "tool": "rm",
        "request_id": 7,
        "triggers": ["destructiveHint"],
        "timeout": 60,
        **extra,
    }


def _decision(seq: int, **extra: object) -> dict:
    return {
        "kind": "approval_decision",
        "seq": seq,
        "hold_id": "h1",
        "decision": "deny",
        "cause": "DENIED",
        "waited": 2.5,
        **extra,
    }


def test_events_come_back_in_seq_order_with_exactly_the_field_contract() -> None:
    records = [
        _hold(1),
        _decision(3),
    ]

    events = derive_approval_events(records)

    assert events == [
        {
            "kind": "approval_hold",
            "seq": 1,
            "hold_id": "h1",
            "tool": "rm",
            "request_id": 7,
            "triggers": ["destructiveHint"],
            "timeout": 60,
        },
        {
            "kind": "approval_decision",
            "seq": 3,
            "hold_id": "h1",
            "decision": "deny",
            "cause": "DENIED",
            "waited": 2.5,
        },
    ]


def test_events_are_sorted_by_seq_even_when_records_are_not() -> None:
    records = [_decision(5), _hold(2), _decision(4)]

    events = derive_approval_events(records)

    assert [e["seq"] for e in events] == [2, 4, 5]


def test_no_approval_records_yields_an_empty_list() -> None:
    assert derive_approval_events([]) == []
    assert derive_approval_events([{"kind": "frame", "seq": 0}]) == []


def test_mixed_traces_return_only_the_approval_events_fields_untouched() -> None:
    records = [
        {"kind": "connection_window", "seq": 0, "phase": "open"},
        _hold(1),
        {"kind": "frame", "seq": 2, "dir": "c2s", "raw": "e30="},
        {"kind": "annotation_snapshot", "seq": 3, "source_seq": 2},
        _decision(4, cause="APPROVAL_TIMEOUT", waited=60.0),
        {"kind": "connection_window", "seq": 5, "phase": "close"},
    ]

    events = derive_approval_events(records)

    assert [e["kind"] for e in events] == ["approval_hold", "approval_decision"]
    # The decision's fields pass through as recorded — a non-default cause and a
    # fractional wait are the trace's own statement, never repaired or re-derived.
    assert events[1]["cause"] == "APPROVAL_TIMEOUT"
    assert events[1]["waited"] == 60.0


def test_a_hold_without_a_decision_yields_the_hold_event_and_nothing_else() -> None:
    """A trace cut mid-hold (shutdown): the reader reports what exists, never repairs.

    Fabricating a decision for the hold would assert an outcome that was never
    observed; the absence of a decision is the trace's own statement.
    """
    events = derive_approval_events([_hold(1)])

    assert len(events) == 1
    assert events[0]["kind"] == "approval_hold"


def test_a_decision_without_a_preceding_hold_is_reported_as_is() -> None:
    """The reader reports, never repairs: a missing hold is the trace's statement."""
    events = derive_approval_events([_decision(2)])

    assert len(events) == 1
    assert events[0]["kind"] == "approval_decision"


def test_unknown_approval_adjacent_kinds_are_skipped_never_fatal() -> None:
    """The closed-kind check: only the two declared kinds are events.

    A future approval-adjacent kind (`approval_*`) is not an event this reader
    understands; it is skipped, never raised over, never silently turned into a
    hold or decision — and never invented into one.
    """
    records = [
        _hold(1),
        {"kind": "approval_future", "seq": 2, "note": "from a newer writer"},
        _decision(3),
    ]

    events = derive_approval_events(records)

    assert [e["kind"] for e in events] == ["approval_hold", "approval_decision"]


# --- Phase 3: the real gate's traces (subprocess-level e2e) -------------------


def _e2e_deny_trace(tmp_path: Path) -> Path:
    """One real deny run through the proxy; return the captured trace's path.

    Reuses the scripted-server pattern from `test_approval_proxy.py` (phase 4 of
    aspect 3): the deny decision for hold `0-blast` is pre-written, the client
    handshakes, lists tools, then calls the destructive tool, and the gate
    suppresses the call and delivers the refusal.
    """
    approval_dir = tmp_path / "approval"
    write_decision(approval_dir, "0-blast", "deny", reason="not now")
    server, log = server_cmd(tmp_path)
    env = approval_env(tmp_path / "trace", approval_dir)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0
    return _sole_trace(tmp_path / "trace")


def _decoded_frames(records: list[dict]) -> list[tuple[dict, bytes]]:
    """Every frame record with its decoded bytes — what actually crossed the wire."""
    return [
        (record, base64.b64decode(record["raw"]))
        for record in records
        if record["kind"] == "frame"
    ]


def test_e2e_deny_run_records_hold_then_decision_and_never_a_frame_for_the_gate(
    tmp_path: Path,
) -> None:
    """The e2e deny trace: `approval_hold` then `approval_decision` (deny, named
    cause), no `frame` record for the suppressed request or the refusal, and a
    correlation index the gate's events leave clean.

    The refusal is the gate's own channel, never the wire — so the trace's
    frames are exactly the handshake and the `tools/list` pair, and
    `derive_correlation` reports no `response-without-request` and no
    `unanswered`: nothing from the gate flows through the correlation machinery.
    """
    path = _e2e_deny_trace(tmp_path)
    records = _read(path)

    hold = next(r for r in records if r["kind"] == "approval_hold")
    decision = next(r for r in records if r["kind"] == "approval_decision")
    assert decision["seq"] > hold["seq"], "the hold is recorded before its decision"
    assert decision["cause"] == "DENIED"
    assert decision["decision"] == "deny"

    frames = _decoded_frames(records)
    assert len(frames) == 5, (
        "the trace holds exactly the initialize pair, the initialized "
        f"notification and the tools/list pair — got {len(frames)} frames"
    )
    assert not any(b'"method":"tools/call"' in raw for _, raw in frames), (
        "the suppressed request must never become a frame record"
    )
    assert not any(b'"code": -32000' in raw for _, raw in frames), (
        "the refusal travels on the gate's own channel, never as a frame"
    )

    index = derive_correlation(records)
    assert not any(e["status"] == "response-without-request" for e in index)
    assert not any(e["status"] == "unanswered" for e in index)


def test_e2e_approve_run_records_the_decision_before_the_forwarded_call(
    tmp_path: Path,
) -> None:
    """M7 ordering, pinned as a SEQUENCE assertion over the records: the approve
    decision is recorded before the approved frame is forwarded — the decision's
    `seq` precedes the call's own frame records, never a timing assertion."""
    approval_dir = tmp_path / "approval"
    write_decision(approval_dir, "0-blast", "approve", reason="go")
    server, log = server_cmd(tmp_path)
    env = approval_env(tmp_path / "trace", approval_dir)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0

    records = _read(_sole_trace(tmp_path / "trace"))
    approval = [r for r in records if r["kind"] in ("approval_hold", "approval_decision")]
    hold_seq = next(r["seq"] for r in approval if r["kind"] == "approval_hold")
    decision = next(r for r in approval if r["kind"] == "approval_decision")
    assert decision["cause"] == "APPROVED"
    assert decision["decision"] == "approve"

    frames = _decoded_frames(records)
    call_seq = next(
        record["seq"]
        for record, raw in frames
        if b'"method":"tools/call"' in raw
    )
    reply_seq = next(
        record["seq"]
        for record, raw in frames
        if b'"id": 3' in raw and b'"result"' in raw
    )
    # hold, then the decision, then the call crosses, then its reply returns:
    # the decision record is written BEFORE the approved frame is forwarded.
    assert hold_seq < decision["seq"] < call_seq < reply_seq


def test_e2e_timeout_run_records_an_APPROVAL_TIMEOUT_decision(tmp_path: Path) -> None:
    """A short `BELAY_APPROVAL_TIMEOUT` with no decision file: the hold times
    out fail-closed — the call never crosses, and the decision record names
    `APPROVAL_TIMEOUT` with no human decision."""
    server, log = server_cmd(tmp_path)
    env = approval_env(tmp_path / "trace", tmp_path / "approval", timeout=0.4)

    outcome = run_proxy_phased(server, env)
    assert outcome["returncode"] == 0
    assert outcome["elapsed"] < 15.0

    records = _read(_sole_trace(tmp_path / "trace"))
    decision = next(r for r in records if r["kind"] == "approval_decision")
    assert decision["cause"] == "APPROVAL_TIMEOUT"
    assert decision["decision"] is None, "a timeout carries no human decision"

    frames = _decoded_frames(records)
    assert not any(b'"method":"tools/call"' in raw for _, raw in frames), (
        "a timed-out call is suppressed, never forwarded"
    )


def test_old_reader_round_trip_keeps_every_frame_and_skips_the_approval_kinds(
    tmp_path: Path, monkeypatch
) -> None:
    """An OLD reader — schema-v1 KINDS without the approval kinds — survives the
    e2e deny trace: every frame is intact and byte-identical, and the two
    approval kinds are SKIPPED with their kind named in the skip's reason, never
    an error and never a silent drop.

    The current reader knows the kinds (they are in `belay.trace.KINDS`), so the
    old reader is simulated by pinning its `KINDS` to the pre-approval set — the
    exact list any reader written before the kinds shipped would hold.
    """
    path = _e2e_deny_trace(tmp_path)
    on_disk = _on_disk(path)

    old_kinds = tuple(k for k in KINDS if k not in APPROVAL_KINDS)
    monkeypatch.setattr("belay.replay.reader.KINDS", old_kinds)

    result = read_trace(path)

    assert result.records == [r for r in on_disk if r["kind"] not in APPROVAL_KINDS], (
        "every understood record — frames included — is intact and byte-identical"
    )
    assert [s.kind for s in result.skips] == ["approval_hold", "approval_decision"]
    assert all("unknown kind" in s.reason for s in result.skips), [
        s.reason for s in result.skips
    ]