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

import subprocess
import sys
from pathlib import Path

from belay.approval.reader import derive_approval_events
from belay.cli import _approval_line
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


# --- Phase 2: the text surface's approval line --------------------------------


def _event(kind: str, seq: int, **fields: object) -> dict:
    return {"kind": kind, "seq": seq, **fields}


def test_approval_line_prints_holds_and_denied_causes_once() -> None:
    events = [
        _event(
            "approval_hold", 1, hold_id="h1", tool="rm", request_id=7,
            triggers=["destructiveHint"], timeout=300.0,
        ),
        _event(
            "approval_decision", 2, hold_id="h1", decision="deny",
            cause="APPROVAL_TIMEOUT", waited=300.0,
        ),
    ]

    assert _approval_line(events) == "approval: 1 held, 1 denied (APPROVAL_TIMEOUT)"


def test_approval_line_splits_a_mixed_run_by_cause() -> None:
    events = [
        _event("approval_hold", 1, hold_id="h1"),
        _event("approval_decision", 2, hold_id="h1", decision="approve", cause="APPROVED", waited=1.0),
        _event("approval_hold", 3, hold_id="h2"),
        _event("approval_decision", 4, hold_id="h2", decision="deny", cause="DENIED", waited=2.0),
        _event("approval_hold", 5, hold_id="h3"),
        _event("approval_decision", 6, hold_id="h3", decision="deny", cause="APPROVAL_TIMEOUT", waited=300.0),
    ]

    line = _approval_line(events)

    assert line == "approval: 3 held, 1 approved, 2 denied (DENIED, APPROVAL_TIMEOUT)"


def test_approval_line_approved_only_and_hold_without_decision() -> None:
    assert (
        _approval_line(
            [
                _event("approval_hold", 1, hold_id="h1"),
                _event("approval_decision", 2, hold_id="h1", decision="approve", cause="APPROVED", waited=1.0),
            ]
        )
        == "approval: 1 held, 1 approved"
    )
    assert _approval_line([_event("approval_hold", 1, hold_id="h1")]) == "approval: 1 held"


def test_approval_line_is_none_when_the_trace_has_no_approval_events() -> None:
    assert _approval_line([]) is None
    assert _approval_line([{"kind": "frame", "seq": 0}]) is None


def _zero_turn_trace(tmp_path: Path, *, approval: bool) -> Path:
    """A trace with no tool calls — so `belay verify` replays nothing, needs no
    sandbox and no manifests — optionally carrying one held-and-timed-out call."""
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        if approval:
            writer.record(
                "approval_hold",
                hold_id="h1", tool="rm", request_id=7,
                triggers=["destructiveHint"], timeout=300,
            )
            writer.record(
                "approval_decision",
                hold_id="h1", decision="deny", cause="APPROVAL_TIMEOUT", waited=300.0,
            )
    finally:
        writer.close()
    traces = sorted((tmp_path / "trace").glob("*.jsonl"))
    assert len(traces) == 1, traces
    return traces[0]


def _verify_text(trace: Path, tmp_path: Path) -> str:
    """The REAL `belay verify` text run. A zero-turn trace exits 1 (the worst
    status across no turns is UNVERIFIED) with the full report on stdout."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    run = subprocess.run(
        [
            sys.executable, "-m", "belay.cli", "verify",
            str(trace),
            "--manifest-dir", str(manifest_dir),
            "--server", "true",
        ],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=120,
    )
    assert run.returncode == 1, run.stdout + run.stderr
    return run.stdout


def test_text_approval_line_prints_exactly_once_with_the_coverage_statement(
    tmp_path: Path,
) -> None:
    """The line prints exactly once when records exist, and the coverage
    statement still prints on the same surface — the honesty contract."""
    stdout = _verify_text(_zero_turn_trace(tmp_path, approval=True), tmp_path)

    assert stdout.count("approval:") == 1, stdout
    assert "approval: 1 held, 1 denied (APPROVAL_TIMEOUT)" in stdout, stdout
    assert "what a verdict here means, exactly" in stdout, (
        "the coverage statement travels with the approval line"
    )


def test_text_prints_no_approval_line_when_the_trace_has_no_approval_records(
    tmp_path: Path,
) -> None:
    stdout = _verify_text(_zero_turn_trace(tmp_path, approval=False), tmp_path)

    assert "approval:" not in stdout, stdout
    assert "what a verdict here means, exactly" in stdout, stdout