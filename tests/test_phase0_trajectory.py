"""A1 / trajectory-rule Phase 4: the verdict reaches disposition, ledger, report, CLI.

Phase 3 (`test_invariant_trajectory_eval.py`) computed and HELD the instance-level
trajectory verdict on the instance record without letting it move anything — a
trajectory FAIL still read `VERIFIED_CLEAN` and nothing serialized it. This module is
the wiring phase, per the PRD decision: a trajectory FAIL marks the instance
`VERIFIED_FLAGGED` and counts in the per-instance violation rate, same bucket as turn
FAILs; a trajectory UNVERIFIED (a completion-only claim, the control shape) does NOT
flag the instance; the ledger serializes the field additively (absent-never-zero);
the report renders the trajectory line; and `belay verify` prints the instance-level
verdict at trace close.

Written FIRST, before the disposition/ledger/report/CLI wiring exists, per strict TDD.
The runner-based tests drive the REAL `verify_turn` with `replay_turn` stubbed exactly
as `test_invariant_trajectory_eval.py` does, so the replayed outcome is observed
without a sandbox; the CLI tests fake `verify_turn` itself, because the trajectory
line is computed from the verdicts and the claim record, not from a live replay.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay import cli
from belay.corpus.metrics import Metrics
from belay.phase0.ledger import (
    Disposition,
    InstanceRecord,
    RunLedger,
    _REQUIRED_INSTANCE_FIELDS,
    from_json,
    to_json,
)
from belay.phase0.report import render_report, violation_rate
from belay.phase0.runner import run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-09T00:00:00+00:00"


# --- the real-path rig (reused verbatim from test_invariant_trajectory_eval.py) ----------


def _stub_replay(monkeypatch, *, status: str = REPLAYED, is_error: bool = False) -> None:
    def fake(records, n, **kwargs):
        if status != REPLAYED:
            return TurnReplay(turn_index=n, status=status, cause="stubbed-not-replayed")
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "ok"}], "isError": is_error},
            }
        ).encode()
        return TurnReplay(
            turn_index=n,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=reply,
            replayed_reply=reply,
            delta=[],
            workspace="/unused",
        )

    monkeypatch.setattr(turn_module, "replay_turn", fake)


def _tool_list_frames(tool: str, annotations: dict | None) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": tool, "annotations": annotations}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call_frame(msg_id: int, tool: str, arguments: dict) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()


def _reply_frame(msg_id: int, is_error: bool = False, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    ).encode()


def _trace_with(tmp_path: Path, name: str, frames: list[tuple]) -> Path:
    writer = TraceWriter.in_directory(tmp_path / name)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return writer.path


def _run_ledger(tmp_path: Path, trace_path: Path, *, invariants) -> RunLedger:
    return run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=invariants,
        captured_at=CAPTURED_AT,
        verifier=verify_turn,
        ingest=False,
    )


# --- disposition: a trajectory FAIL flips the instance; UNVERIFIED does not ---------------


def test_trajectory_fail_flags_the_instance_and_counts_in_the_rate(tmp_path, monkeypatch):
    """PRD decision through the real path: verification claim + source edits + zero
    run_process -> the ONLY failure is the trajectory FAIL, and the instance reads
    VERIFIED_FLAGGED — never VERIFIED_CLEAN — and the per-instance violation rate
    counts it (numerator 1 over denominator 1)."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("edit_file", {"readOnlyHint": False})
        + [
            ("c2s", _call_frame(2, "edit_file", {"path": "/repo/src/a.py"}), None),
            ("s2c", _reply_frame(2), None),
            ("c2s", _call_frame(3, "edit_file", {"path": "/repo/src/b.py"}), None),
            ("s2c", _reply_frame(3), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    ledger = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.turn_status_counts == {"PASS": 2}  # every turn is clean on its own
    assert inst.flagged_turns == []  # no turn-level FAIL — the flag is trajectory-only
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert ledger.violating_instances() == 1
    assert ledger.violation_denominator() == 1
    assert violation_rate(ledger) == 1.0


def test_trajectory_unverified_does_not_flag_the_instance(tmp_path, monkeypatch):
    """A completion-only claim (the control shape) abstains with CLAIM_UNCLASSIFIABLE,
    and the instance stays VERIFIED_CLEAN — an abstention is never a violation."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", {"readOnlyHint": True})
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="file written")

    ledger = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "CLAIM_UNCLASSIFIABLE",
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert ledger.violating_instances() == 0
    assert ledger.violation_denominator() == 1
    assert violation_rate(ledger) == 0.0


def test_trajectory_unverified_no_claim_does_not_flag_the_instance(tmp_path, monkeypatch):
    """An older capture with no claim record abstains NO_CLAIM_RECORDED and stays
    VERIFIED_CLEAN — absence of a claim is not a violation."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", {"readOnlyHint": True})
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )

    ledger = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "NO_CLAIM_RECORDED",
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert ledger.violating_instances() == 0


# --- ledger: additive serialization, absent-never-zero -----------------------------------


def _instance(
    trace_id: str,
    disposition: Disposition,
    **kwargs,
) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=kwargs.pop("turn_status_counts", {}),
        flagged_turns=kwargs.pop("flagged_turns", []),
        flagged_addable=kwargs.pop("flagged_addable", []),
        flagged_unaddable=kwargs.pop("flagged_unaddable", []),
        unverified_causes=kwargs.pop("unverified_causes", {}),
        error=kwargs.pop("error", None),
        **kwargs,
    )


def test_ledger_round_trips_the_trajectory_field() -> None:
    """A recorded trajectory verdict survives `to_json` / `from_json` exactly — status,
    cause and evidence count all preserved."""
    fail = _instance(
        "trace-fail",
        Disposition.VERIFIED_FLAGGED,
        trajectory={"status": "FAIL", "cause": None, "evidence_count": 0},
    )
    abstained = _instance(
        "trace-abstained",
        Disposition.VERIFIED_CLEAN,
        trajectory={"status": "UNVERIFIED", "cause": "NO_CLAIM_RECORDED", "evidence_count": 0},
    )
    ledger = RunLedger(instances=[fail, abstained])

    rebuilt = from_json(to_json(ledger))

    by_id = {inst.trace_id: inst for inst in rebuilt.instances}
    assert by_id["trace-fail"].trajectory == {
        "status": "FAIL",
        "cause": None,
        "evidence_count": 0,
    }
    assert by_id["trace-abstained"].trajectory == {
        "status": "UNVERIFIED",
        "cause": "NO_CLAIM_RECORDED",
        "evidence_count": 0,
    }


def test_ledger_without_trajectory_omits_the_key_and_reads_back_absent() -> None:
    """`to_json` never writes `"trajectory"` when unrecorded — asserted on BYTES — and
    an old-ledger-shaped payload (no key) loads back with `trajectory is None`, never a
    fabricated zero or clean verdict."""
    ledger = RunLedger(instances=[_instance("trace-x", Disposition.VERIFIED_CLEAN)])

    rendered = json.dumps(to_json(ledger))
    assert "trajectory" not in rendered

    old_payload: dict = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "VERIFIED_CLEAN",
                "turn_status_counts": {},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
                # "trajectory" deliberately omitted, like every ledger in runs/
            }
        ]
    }

    rebuilt = from_json(old_payload)

    assert rebuilt.instances[0].trajectory is None


def test_trajectory_is_not_a_required_ledger_field() -> None:
    """`trajectory` is absent from `_REQUIRED_INSTANCE_FIELDS` — an old ledger must load,
    fail-closed here would turn 'predates the field' into a corrupt-ledger error."""
    assert "trajectory" not in _REQUIRED_INSTANCE_FIELDS


def test_trajectory_does_not_pollute_turn_status_counts() -> None:
    """The trajectory verdict is orthogonal to the turn tally — `total_turns()` stays a
    count of turns, and the FAIL rate's denominator is untouched."""
    inst = _instance(
        "trace-x",
        Disposition.VERIFIED_FLAGGED,
        turn_status_counts={"PASS": 2},
        trajectory={"status": "FAIL", "cause": None, "evidence_count": 0},
    )
    ledger = RunLedger(instances=[inst])

    assert "trajectory" not in inst.turn_status_counts
    assert set(inst.turn_status_counts) == {"PASS"}
    assert ledger.total_turns() == 2


# --- report: the trajectory line in the exposure area ------------------------------------


def _metrics() -> Metrics:
    return Metrics(
        tp=0,
        fp=0,
        fn=0,
        tn=0,
        precision=None,
        recall=None,
        coverage=None,
        unverified=0,
        pending=0,
        unverifiable=0,
        total=0,
    )


def test_report_renders_the_trajectory_line_per_instance_with_named_causes() -> None:
    """One ledger holding every trajectory state: FAIL names the evidence count and the
    disposition it produced, PASS names the evidence, UNVERIFIED names its cause and says
    never PASS, and an instance without a verdict renders the unrecorded form — never a
    fabricated clean. The aggregate line counts each state."""
    fail = _instance(
        "trace-fail",
        Disposition.VERIFIED_FLAGGED,
        trajectory={"status": "FAIL", "cause": None, "evidence_count": 0},
    )
    passed = _instance(
        "trace-passed",
        Disposition.VERIFIED_CLEAN,
        trajectory={"status": "PASS", "cause": None, "evidence_count": 1},
    )
    abstained = _instance(
        "trace-abstained",
        Disposition.VERIFIED_CLEAN,
        trajectory={"status": "UNVERIFIED", "cause": "CLAIM_UNCLASSIFIABLE", "evidence_count": 0},
    )
    unrecorded = _instance("trace-unrecorded", Disposition.VERIFIED_CLEAN)
    ledger = RunLedger(instances=[fail, passed, abstained, unrecorded])

    report = render_report(ledger, _metrics())

    assert "trajectory (suite-before-success-claim" in report
    assert "trace-fail" in report
    assert "trajectory FAIL" in report
    assert "0 evidence turn(s)" in report
    assert "VERIFIED_FLAGGED" in report
    assert "trace-passed" in report
    assert "trajectory PASS" in report
    assert "1 replayed command turn(s)" in report
    assert "trace-abstained" in report
    assert "trajectory UNVERIFIED [CLAIM_UNCLASSIFIABLE]" in report
    assert "never PASS" in report
    # The instance without a verdict says so in words — never a fabricated zero/clean.
    assert "trace-unrecorded" in report
    assert "trajectory unrecorded" in report
    assert "NOT a claim that the trajectory was clean" in report
    # The should-have aggregate, counting the three verdict-carrying instances by state
    # and cause.
    assert "aggregate: 1 FAIL / 1 PASS / 1 UNVERIFIED" in report
    assert "CLAIM_UNCLASSIFIABLE: 1" in report


def test_report_trajectory_section_survives_instrument_suspect() -> None:
    """The trajectory section is a limit statement, not a rate: it renders even when the
    violation-rate headline is suppressed — exactly the exposure section's discipline."""
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                Disposition.NO_VERIFIABLE_TURNS,
                trajectory={"status": "UNVERIFIED", "cause": "NO_CLAIM_RECORDED", "evidence_count": 0},
            ),
            _instance("trace-b", Disposition.NO_VERIFIABLE_TURNS),
        ]
    )

    report = render_report(ledger, _metrics())

    assert "INSTRUMENT SUSPECT" in report
    assert "trajectory" in report
    assert "trace-a" in report
    assert "trace-b" in report


# --- CLI: `belay verify` prints the instance-level verdict at trace close ----------------


def _canned_verifier(status: Status = Status.PASS, *, is_error: bool = False):
    def verifier(records, n, *, server_command, manifest_dir, replays, invariants):
        return TurnVerdict(
            turn_index=n,
            tool_name="edit_file",
            status=status,
            replayed_is_error=is_error,
        )

    return verifier


def _edit_trace(tmp_path: Path, *, claim: str | None) -> Path:
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("edit_file", {"readOnlyHint": False})
        + [
            ("c2s", _call_frame(2, "edit_file", {"path": "/repo/src/a.py"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    if claim is not None:
        append_claim_record(trace_path, text=claim)
    return trace_path


def test_cli_prints_the_instance_level_fail_line_at_close(tmp_path, monkeypatch, capsys):
    """A claim-bearing trace with a verification claim and zero evidence prints the
    instance-level FAIL line at trace close, naming the rule and the zero evidence —
    even though every turn passes (the corrupt-success shape is an instance finding)."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(tmp_path / "m"), "--server", "unused"]
    )
    out = capsys.readouterr().out

    assert rc == 0, out  # turns are all PASS — the exit code stays turn-based
    assert "suite-before-success-claim" in out, out
    assert "0 evidence turn(s)" in out, out
    assert "never PASS" not in out, out


def test_cli_prints_the_abstain_line_without_a_claim(tmp_path, monkeypatch, capsys):
    """A trace without a claim prints the abstain line honestly — UNVERIFIED with its
    named cause, never a PASS and never a silence."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim=None)

    cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(tmp_path / "m"), "--server", "unused"]
    )
    out = capsys.readouterr().out

    assert "suite-before-success-claim" in out, out
    assert "UNVERIFIED" in out, out
    assert "NO_CLAIM_RECORDED" in out, out
    assert "never PASS" in out, out


def test_cli_prints_nothing_fabricated_when_the_rule_is_not_declared(
    tmp_path, monkeypatch, capsys
):
    """With `--no-default-invariants` and no invariants file, the instance-level rule is
    not declared: the CLI says unrecorded — never a verdict that did not happen."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--no-default-invariants",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert "suite-before-success-claim" in out, out
    assert "unrecorded" in out, out
    assert "0 evidence turn(s)" not in out, out
