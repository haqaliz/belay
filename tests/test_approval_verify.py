"""`belay verify` reports the trace's approval events — the additive `approval` section.

Aspect `approval-gate/verify-report`: the gate's hold/decision records are
observations, never turns and never verdicts, and the verify surfaces report
them as such. The `--json` document gains one additive section —
`{"approval": {"holds": N, "decisions": {<CAUSE>: n, ...}}}` — present iff the
trace carries approval records (absent otherwise: **absent-never-zero**, never a
fabricated `0` and never an empty dict). The text surface gains one line that
travels with the coverage statement.

Fixtures are small traces written with the aspect-4 kinds via `TraceWriter`
directly — no subprocess, no replay, no sandbox: the section is derived from
the trace's records, so the builder is testable where it lives. The CLI-level
surfaces (the real `belay verify` over a captured run) are pinned in
`tests/test_verify_json.py` with the real roundtrip fixture.
"""

from __future__ import annotations

from pathlib import Path

from belay.approval.reader import derive_approval_events
from belay.replay.reader import read_trace
from belay.trace import TraceWriter
from belay.verify.json import VerifyReport, approval_record


def _approval_trace(tmp_path: Path, records: list[tuple[str, dict]]) -> list[dict]:
    """Write `records` (kind, fields) through the real writer; return them as read."""
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for kind, fields in records:
            writer.record(kind, **fields)
    finally:
        writer.close()
    traces = sorted((tmp_path / "trace").glob("*.jsonl"))
    assert len(traces) == 1, traces
    return read_trace(traces[0]).records


def _hold(
    hold_id: str = "h1",
    tool: str = "rm",
    request_id: int = 7,
    triggers: tuple[str, ...] = ("destructiveHint",),
    timeout: float = 300.0,
) -> tuple[str, dict]:
    return (
        "approval_hold",
        {
            "hold_id": hold_id,
            "tool": tool,
            "request_id": request_id,
            "triggers": list(triggers),
            "timeout": timeout,
        },
    )


def _decision(
    hold_id: str = "h1",
    decision: str = "deny",
    cause: str = "DENIED",
    waited: float = 2.5,
) -> tuple[str, dict]:
    return (
        "approval_decision",
        {
            "hold_id": hold_id,
            "decision": decision,
            "cause": cause,
            "waited": waited,
        },
    )


def _document(approval) -> dict:
    """The assembled machine document, with the approval section as given."""
    return VerifyReport(
        trace=None,
        turns=[],
        aggregate={},
        coverage={},
        exposure={},
        trajectory=None,
        claim=None,
        approval=approval,
        error=None,
    ).as_dict()


# --- Phase 1: the additive `approval` section on the JSON document ------------


def test_approval_section_reports_holds_and_decisions_by_cause(tmp_path: Path) -> None:
    """1 hold + 1 deny (`APPROVAL_TIMEOUT`) → the section reads exactly
    `{"holds": 1, "decisions": {"APPROVAL_TIMEOUT": 1}}` — decisions keyed by
    cause, only present causes as keys."""
    records = _approval_trace(
        tmp_path,
        [_hold(), _decision(cause="APPROVAL_TIMEOUT", waited=300.0)],
    )

    record = approval_record(derive_approval_events(records))

    assert record == {"holds": 1, "decisions": {"APPROVAL_TIMEOUT": 1}}
    assert _document(record)["approval"] == record


def test_approval_section_splits_a_mixed_run_by_cause(tmp_path: Path) -> None:
    """A trace mixing denied, approved and timed-out calls reports 3 holds with
    the exact per-cause split."""
    records = _approval_trace(
        tmp_path,
        [
            _hold("h1"),
            _decision("h1", "approve", "APPROVED", 1.0),
            _hold("h2"),
            _decision("h2", "deny", "DENIED", 2.0),
            _hold("h3"),
            _decision("h3", "deny", "APPROVAL_TIMEOUT", 300.0),
        ],
    )

    record = approval_record(derive_approval_events(records))

    assert record == {
        "holds": 3,
        "decisions": {"APPROVED": 1, "DENIED": 1, "APPROVAL_TIMEOUT": 1},
    }


def test_approval_section_is_absent_when_the_trace_has_no_approval_records() -> None:
    """No approval records → the key is ABSENT entirely — never a zero, never an
    empty dict."""
    assert approval_record([]) is None
    assert (
        approval_record(
            derive_approval_events(
                [{"kind": "frame", "seq": 0, "dir": "c2s", "raw": "e30="}]
            )
        )
        is None
    )

    document = _document(None)
    assert "approval" not in document, (
        "a trace without approval records must not carry the key at all"
    )


def test_approval_section_counts_holds_and_decisions_independently(
    tmp_path: Path,
) -> None:
    """A hold with no decision (a trace cut mid-hold — the shutdown path) still
    reports the hold: the section states what the trace states, and never
    fabricates a cause for a decision that was not recorded."""
    records = _approval_trace(tmp_path, [_hold("h1")])

    record = approval_record(derive_approval_events(records))

    assert record == {"holds": 1, "decisions": {}}
    assert _document(record)["approval"] == {"holds": 1, "decisions": {}}