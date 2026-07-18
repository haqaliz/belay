"""Phase-0 batch runner: walk traces, verify each turn, classify the instance disposition.

`run_batch` is the driver Task 1's `RunLedger` and Task 2's report exist to be filled and
rendered by: for each trace file in a directory, verify every `tools/call` turn, ingest the
FAILing ones into the corpus, and fold the outcome into one `InstanceRecord`.

Every test here injects a FAKE verifier and a FAKE ingester (never `verify_turn`/`add_case`
themselves, never Seatbelt) — capture, correlation and `tool_calls` are the only real
machinery exercised, and those are pure and cross-platform. The fake verifier is keyed by
the trace's stem (read back off `manifest_dir`'s name, which `default_manifest_dir_for`
derives deterministically from the trace path), so each written trace can be given its own
canned verdict script without depending on capture order or randomness.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.phase0.ledger import Disposition
from belay.phase0.runner import run_batch
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-07-18T00:00:00+00:00"


# --- synthetic trace + canned-verdict apparatus ---------------------------------------


def _call_frame(call_id: int, tool: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    ).encode()


def _reply_frame(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ).encode()


def _write_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """Write one `trace-*.jsonl` of `n_calls` `tools/call` turns for `tool`, via the real writer."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            writer.observer("c2s")(_call_frame(call_id, tool), False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    return writer.path


def _verdict(n: int, status: Status, *, cause: str | None = None) -> TurnVerdict:
    """A canned `TurnVerdict`: UNVERIFIED carries a cause, everything else one sub-verdict."""
    if status is Status.UNVERIFIED:
        return TurnVerdict(
            turn_index=n, tool_name="t", status=status, sub_verdicts=[], cause=cause or "unknown"
        )
    return TurnVerdict(
        turn_index=n,
        tool_name="t",
        status=status,
        sub_verdicts=[Verdict("A2", "replay", status, None, None, "canned")],
        cause=None,
    )


def _stem_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier keyed by the trace's stem, read back off `manifest_dir`'s name.

    `default_manifest_dir_for` names the manifest dir `<stem>.manifests`; this fake reverses
    that convention rather than hard-coding a second one, so it stays true to what the real
    seam actually passes through.
    """

    def verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _noop_ingester(corpus_dir, **kwargs) -> Path:
    return Path(corpus_dir) / "unused-case"


# --- (1) four traces, four dispositions, disciplined denominator -----------------------


def test_four_traces_four_dispositions_and_violation_denominator(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"

    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    unverifiable_path = _write_trace(trace_dir, "unverified_tool", 1)
    corrupt_path = trace_dir / "trace-corrupt-broken.jsonl"
    corrupt_path.write_text("not json at all\n", encoding="utf-8")

    canned = {
        fail_path.stem: [_verdict(0, Status.FAIL)],
        clean_path.stem: [_verdict(0, Status.PASS)],
        unverifiable_path.stem: [_verdict(0, Status.UNVERIFIED, cause="timeout")],
    }

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=_noop_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert len(ledger.instances) == 4
    assert by_id[fail_path.stem].disposition is Disposition.VERIFIED_FLAGGED
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN
    assert by_id[unverifiable_path.stem].disposition is Disposition.NO_VERIFIABLE_TURNS
    assert by_id[corrupt_path.stem].disposition is Disposition.ERRORED
    assert by_id[corrupt_path.stem].error is not None
    # ERRORED carries no counts.
    assert by_id[corrupt_path.stem].turn_status_counts == {}
    assert by_id[corrupt_path.stem].flagged_turns == []

    # Only the two VERIFIED_* instances count toward the violation denominator.
    assert ledger.violation_denominator() == 2
    assert ledger.violating_instances() == 1


# --- (2) a FAIL turn whose fake ingester succeeds ---------------------------------------


def test_flagged_turn_ingest_success_is_flagged_addable_and_ingester_called_correctly(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}

    calls: list[dict] = []

    def fake_ingester(corpus_dir_arg, **kwargs) -> Path:
        calls.append(kwargs)
        return Path(corpus_dir_arg) / "case-1"

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=fake_ingester,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.flagged_turns == [0]
    assert inst.flagged_addable == [0]
    assert inst.flagged_unaddable == []

    assert len(calls) == 1
    call = calls[0]
    assert call["human_label"] == "pending"
    assert call["target_turn_index"] == 0
    assert call["source_trace_id"] == fail_path.stem
    assert call["captured_at"] == CAPTURED_AT
    assert call["verdict"].status is Status.FAIL


# --- (3) a FAIL turn whose fake ingester raises ValueError ------------------------------


def test_flagged_turn_ingest_value_error_stays_flagged_and_unaddable_batch_continues(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    canned = {
        fail_path.stem: [_verdict(0, Status.FAIL)],
        clean_path.stem: [_verdict(0, Status.PASS)],
    }

    def raising_ingester(corpus_dir_arg, **kwargs) -> Path:
        raise ValueError("no restorable pre-state")

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=raising_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    flagged = by_id[fail_path.stem]
    assert flagged.disposition is Disposition.VERIFIED_FLAGGED
    assert flagged.flagged_turns == [0]
    assert flagged.flagged_addable == []
    assert flagged.flagged_unaddable == [{"turn": 0, "cause": "no restorable pre-state"}]

    # Still a violation, even though it could not be ingested as a corpus case.
    assert ledger.violating_instances() == 1
    assert ledger.violation_denominator() == 2

    # The batch continued: the other trace was still processed correctly.
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN


# --- (4) a corrupt trace file never aborts the batch ------------------------------------


def test_corrupt_trace_is_errored_other_traces_still_processed(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    corrupt_path = trace_dir / "trace-corrupt-9999.jsonl"
    corrupt_path.write_text("{not valid json\n", encoding="utf-8")

    canned = {clean_path.stem: [_verdict(0, Status.PASS)]}

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=_noop_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert by_id[corrupt_path.stem].disposition is Disposition.ERRORED
    assert isinstance(by_id[corrupt_path.stem].error, str)
    assert by_id[corrupt_path.stem].error
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN


# --- (5) one PASS + several UNVERIFIED is VERIFIED_CLEAN, causes tallied ---------------


def test_one_pass_and_several_unverified_is_clean_with_causes_tallied(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    path = _write_trace(trace_dir, "mixed_tool", 3)
    canned = {
        path.stem: [
            _verdict(0, Status.PASS),
            _verdict(1, Status.UNVERIFIED, cause="timeout"),
            _verdict(2, Status.UNVERIFIED, cause="timeout"),
        ]
    }

    def failing_ingester(corpus_dir_arg, **kwargs) -> Path:
        raise AssertionError("no FAIL turn exists; ingester must not be called")

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=failing_ingester,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.turn_status_counts == {"PASS": 1, "UNVERIFIED": 2}
    assert inst.unverified_causes == {"timeout": 2}
    assert inst.flagged_turns == []


# --- (6) captured_at passed through verbatim; the runner reads no clock ----------------


def test_captured_at_passed_through_verbatim(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}

    seen: list[str] = []

    def fake_ingester(corpus_dir_arg, **kwargs) -> Path:
        seen.append(kwargs["captured_at"])
        return Path(corpus_dir_arg) / "case"

    custom_captured_at = "1999-01-01T00:00:00+00:00"
    run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=custom_captured_at,
        verifier=_stem_verifier(canned),
        ingester=fake_ingester,
    )

    # The exact string passed in, byte for byte -- never re-derived, never a clock read.
    assert seen == [custom_captured_at]
