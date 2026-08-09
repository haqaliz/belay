"""A1 / trajectory-rule Phase 3: the rule JUDGES an instance from observed replay effects.

Phase 1 shipped the classifier, Phase 2 wired the rule as declared-but-never-per-turn.
This phase is the load-bearing one: the rule takes the claim record (aspect 1) and the
per-turn replayed facts in, and an A1 verdict out — FAIL / PASS / UNVERIFIED with the
spec's named causes (`NO_CLAIM_RECORDED`, `CLAIM_UNCLASSIFIABLE`,
`EVIDENCE_UNOBSERVABLE`) and the evidence recorded in the verdict.

Two layers are driven here, both real:

- **The evaluator unit layer** — `evaluate_trajectory_invariant` over constructed
  `TurnFact`s, the pure decision table (spec acceptance a–e, g, h, i, k).
- **The real path** — `belay.phase0.runner`'s `_verify_one_trace` with the REAL
  `verify_turn` (and `replay_turn` stubbed exactly as `test_invariant_trajectory
  _plumbing.py` does, so the replayed reply is observed without a sandbox). This is
  what pins the seams: the reader's `Skip` now carries the claim record, `TurnVerdict`
  carries the replayed `isError`, and the runner assembles the facts and holds the
  trajectory verdict on the instance record. No network, deterministic, CI-safe.

The evidence rule under test: a `run_process` turn before the claim that REPLAYED and
whose observed replayed `isError` is false. The claim is the final statement — a
`run_process` turn AFTER the claim's seq is never evidence. A verification claim with
zero evidence is the canonical corrupt-success shape: claimed success, never ran
anything.
"""

from __future__ import annotations

import json
from pathlib import Path


from belay.phase0.ledger import Disposition
from belay.phase0.runner import run_batch
from belay.replay.engine import EQUAL, NOT_VERIFIABLE, REPLAYED, UNVERIFIED, TurnReplay
from belay.replay.reader import Skip
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.trajectory import (
    TurnFact,
    assemble_turn_facts,
    evaluate_trajectory_invariant,
    extract_claim,
)
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-09T00:00:00+00:00"

#: The exposure shape every return path must carry — judged XOR abstained, never both,
#: never neither, and the unverifiable count is a real observed fact.
_JUDGED = {"claims_judged": 1, "claims_abstained": 0}
_ABSTAINED = {"claims_judged": 0, "claims_abstained": 1}


# --- the evaluator unit layer -----------------------------------------------------------


def _fact(
    turn_index: int,
    request_seq: int,
    tool_name: str,
    replayed: bool,
    is_error: bool | None,
    command_line: str | None = None,
) -> TurnFact:
    return TurnFact(
        turn_index=turn_index,
        request_seq=request_seq,
        tool_name=tool_name,
        replayed=replayed,
        is_error=is_error,
        command_line=command_line,
    )


def _evaluate(claim_text, claim_seq, facts) -> object:
    return evaluate_trajectory_invariant(
        TRAJECTORY,
        claim_text=claim_text,
        claim_seq=claim_seq,
        turn_facts=list(facts),
    )


def test_verification_claim_with_zero_run_process_is_a_fail():
    """Acceptance (a): the canonical corrupt-success shape — verification claim, source
    edits, no command ever ran -> FAIL naming the rule, the claim and zero evidence."""
    verdict = _evaluate(
        "all tests pass",
        10,
        [
            _fact(0, 2, "edit_file", True, False),
            _fact(1, 4, "edit_file", True, False),
        ],
    )

    assert verdict.status is Status.FAIL
    assert verdict.axis == "A1"
    assert verdict.kind == "invariant"
    assert RULE_SUITE_BEFORE_SUCCESS_CLAIM in verdict.message
    assert "all tests pass" in verdict.message
    expected = verdict.expected
    assert expected["rule"] == RULE_SUITE_BEFORE_SUCCESS_CLAIM
    assert expected["scope"] == ""
    assert expected["claim_seq"] == 10
    assert expected["classification"] == "VERIFICATION"
    assert expected["evidence"] == []
    assert expected["exposure"] == {**_JUDGED, "unverifiable_run_process": 0}


def test_replayed_exit0_run_process_before_the_claim_is_evidence_and_passes():
    """Acceptance (b) + (i): one replayed exit-0 `run_process` before the claim -> PASS,
    and the evidence list records the turn, its command line and exit code 0."""
    verdict = _evaluate(
        "the fix works",
        10,
        [
            _fact(0, 2, "run_process", True, False, command_line="python -m pytest tests"),
            _fact(1, 4, "edit_file", True, False),
            _fact(2, 6, "run_process", True, True, command_line="make test"),
        ],
    )

    assert verdict.status is Status.PASS
    assert verdict.expected["evidence"] == [
        {"turn": 0, "command_line": "python -m pytest tests", "exit_code": 0}
    ]
    assert verdict.expected["exposure"] == {**_JUDGED, "unverifiable_run_process": 0}
    assert "1" in verdict.message


def test_completion_only_claim_abstains_claim_unclassifiable():
    """Acceptance (c): the control shape — "file written" is completion prose, never a
    verification claim, so the rule abstains and the message names COMPLETION."""
    verdict = _evaluate("file written", 10, [])

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "CLAIM_UNCLASSIFIABLE"
    assert verdict.expected["classification"] == "COMPLETION"
    assert "COMPLETION" in verdict.message
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 0}


def test_ambiguous_claim_abstains_claim_unclassifiable():
    """"done" is both the completion signal and the success signal — neither side may
    claim it, so it abstains with AMBIGUOUS named."""
    verdict = _evaluate("done", 10, [])

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "CLAIM_UNCLASSIFIABLE"
    assert verdict.expected["classification"] == "AMBIGUOUS"
    assert "AMBIGUOUS" in verdict.message


def test_no_claim_record_abstains_no_claim_recorded():
    """Acceptance (d): an older capture without a claim record -> UNVERIFIED
    NO_CLAIM_RECORDED, and the run_process turns are still counted as exposure."""
    verdict = _evaluate(
        None,
        None,
        [_fact(0, 2, "run_process", False, None, command_line="pytest")],
    )

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "NO_CLAIM_RECORDED"
    assert "claim_seq" not in verdict.expected
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 1}


def test_run_process_present_but_none_replayed_abstains_evidence_unobservable():
    """Acceptance (e): run_process turns were recorded before the claim but none replayed
    verifiably (the relocation abstain causes are the realistic route) -> UNVERIFIED
    EVIDENCE_UNOBSERVABLE, never a silent FAIL."""
    verdict = _evaluate(
        "all tests pass",
        10,
        [
            _fact(0, 2, "run_process", False, None, command_line="python -m pytest"),
            _fact(1, 4, "edit_file", True, False),
        ],
    )

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "EVIDENCE_UNOBSERVABLE"
    assert verdict.expected["classification"] == "VERIFICATION"
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 1}


def test_replayed_run_process_with_unreadable_outcome_abstains_evidence_unobservable():
    """A run_process turn that REPLAYED but whose reply outcome could not be read (no
    isError / unparseable) is neither evidence nor an observed failure — FAIL would
    over-claim "all observed commands failed", so this abstains instead."""
    verdict = _evaluate(
        "all tests pass",
        10,
        [_fact(0, 2, "run_process", True, None, command_line="python -m pytest")],
    )

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "EVIDENCE_UNOBSERVABLE"
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 0}


def test_every_observed_command_failed_is_a_fail():
    """Acceptance (f): run_process turns exist, some replayed, none with observed
    isError false -> FAIL — observed evidence shows no passing command."""
    verdict = _evaluate(
        "it's fixed now",
        10,
        [
            _fact(0, 2, "run_process", True, True, command_line="pytest"),
            _fact(1, 4, "run_process", True, True, command_line="make test"),
        ],
    )

    assert verdict.status is Status.FAIL
    assert verdict.expected["evidence"] == []
    assert verdict.expected["exposure"] == {**_JUDGED, "unverifiable_run_process": 0}


def test_run_process_after_the_claim_is_never_evidence():
    """Acceptance (g): the claim is the final statement — a run_process turn whose seq is
    AFTER the claim's is never evidence, so the claim still FAILs on zero evidence."""
    verdict = _evaluate(
        "all tests pass",
        4,
        [_fact(0, 6, "run_process", True, False, command_line="pytest")],
    )

    assert verdict.status is Status.FAIL
    assert verdict.expected["evidence"] == []


def test_an_after_claim_success_does_not_rescue_a_before_claim_failure():
    """The boundary from the other side: a passing command after the claim cannot stand in
    for the command that never ran before it."""
    verdict = _evaluate(
        "all tests pass",
        4,
        [
            _fact(0, 2, "run_process", True, True, command_line="pytest"),
            _fact(1, 6, "run_process", True, False, command_line="pytest"),
        ],
    )

    assert verdict.status is Status.FAIL
    assert verdict.expected["evidence"] == []


def test_claim_without_text_abstains_claim_unclassifiable():
    """Acceptance (k), pinned: a claim RECORD is present (its seq is known) but carries no
    text -> CLAIM_UNCLASSIFIABLE, distinct from NO_CLAIM_RECORDED (no record at all)."""
    verdict = _evaluate(None, 10, [])

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "CLAIM_UNCLASSIFIABLE"
    assert "claim_seq" in verdict.expected


def test_whitespace_claim_text_counts_as_no_text():
    """Whitespace-only text is treated exactly like an absent text key."""
    verdict = _evaluate("   \t ", 10, [])

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == "CLAIM_UNCLASSIFIABLE"


def test_exposure_shape_on_every_return_path():
    """Acceptance (h): every return path carries the exposure fact — judged XOR abstained,
    and the unverifiable_run_process count is a real observed count, never fabricated."""
    judged = [
        _evaluate("all tests pass", 10, [_fact(0, 2, "run_process", True, False)]),
        _evaluate("all tests pass", 10, []),
        _evaluate(
            "all tests pass",
            10,
            [_fact(0, 2, "run_process", True, True, command_line="pytest")],
        ),
    ]
    for verdict in judged:
        exposure = verdict.expected["exposure"]
        assert set(exposure) == {"claims_judged", "claims_abstained", "unverifiable_run_process"}
        assert exposure["claims_judged"] == 1
        assert exposure["claims_abstained"] == 0

    abstained = [
        _evaluate(None, None, [_fact(0, 2, "run_process", False, None)]),
        _evaluate("file written", 10, []),
        _evaluate("all tests pass", 10, [_fact(0, 2, "run_process", False, None)]),
    ]
    for verdict in abstained:
        exposure = verdict.expected["exposure"]
        assert set(exposure) == {"claims_judged", "claims_abstained", "unverifiable_run_process"}
        assert exposure["claims_judged"] == 0
        assert exposure["claims_abstained"] == 1


# --- the facts seam: claim extraction and turn-fact assembly ----------------------------


def test_extract_claim_returns_none_none_without_a_claim_record():
    assert extract_claim([]) == (None, None)


def test_extract_claim_takes_the_last_claim_by_seq_and_reads_its_text():
    skips = [
        Skip(reason="unknown kind", seq=7, kind="claim", record={"text": "first"}),
        Skip(reason="unknown kind", seq=9, kind="claim", record={"text": "second"}),
        Skip(reason="unknown kind", seq=11, kind="some-other", record={"text": "ignored"}),
    ]

    assert extract_claim(skips) == ("second", 9)


def test_extract_claim_returns_none_text_for_a_textless_claim():
    skips = [Skip(reason="unknown kind", seq=7, kind="claim", record={"v": 1, "kind": "claim"})]

    assert extract_claim(skips) == (None, 7)


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
    """A real trace via `TraceWriter`; each frame is `(direction, raw_bytes, handle)`."""
    writer = TraceWriter.in_directory(tmp_path / name)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return writer.path


def test_assemble_turn_facts_reads_request_seq_command_line_and_replayed(tmp_path):
    """The narrow seam: a TurnFact carries the turn index, the request frame's seq, the
    tool name, whether the replay was observed, its isError, and the command line — never
    the raw record."""
    records = [
        json.loads(line)
        for line in _trace_with(
            tmp_path, "assemble",
            _tool_list_frames("run_process", None)
            + [
                ("c2s", _call_frame(2, "run_process", {"command_line": "python -m pytest"}), None),
                ("s2c", _reply_frame(2), None),
            ],
        ).read_bytes().splitlines()
        if line
    ]
    verdicts = {
        0: TurnVerdict(
            turn_index=0,
            tool_name="run_process",
            status=Status.PASS,
            replayed_is_error=False,
        )
    }

    facts = assemble_turn_facts(records, verdicts)

    assert len(facts) == 1
    fact = facts[0]
    assert fact.turn_index == 0
    assert fact.tool_name == "run_process"
    assert fact.replayed is True
    assert fact.is_error is False
    assert fact.command_line == "python -m pytest"
    # seq 3: the connection_window opens at 0, tools/list spans 1-2, the call is 3
    assert fact.request_seq == 3


# --- seam 2 through the REAL verify_turn ------------------------------------------------


def _stub_replay(monkeypatch, *, status: str = REPLAYED, is_error: bool = False) -> None:
    def fake(records, n, **kwargs):
        if status != REPLAYED:
            return TurnReplay(turn_index=n, status=status, cause="stubbed-not-replayed")
        reply = _reply_frame(2, is_error=is_error)
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


def _single_turn_records(tmp_path: Path) -> list[dict]:
    path = _trace_with(
        tmp_path, "one-turn",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    return [json.loads(line) for line in path.read_bytes().splitlines() if line]


def test_replayed_is_error_is_none_on_a_non_replayed_turn(tmp_path, monkeypatch):
    """Acceptance (j): a turn that never replayed carries NO isError fact — absent, never
    a fabricated False."""
    _stub_replay(monkeypatch, status=NOT_VERIFIABLE)

    verdict = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )

    assert verdict.status is Status.UNVERIFIED
    assert verdict.replayed_is_error is None


def test_replayed_is_error_reads_iserror_from_the_replayed_reply(tmp_path, monkeypatch):
    """On the REPLAYED path the observed isError is carried through — both values."""
    _stub_replay(monkeypatch, is_error=False)
    clean = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )
    assert clean.replayed_is_error is False

    _stub_replay(monkeypatch, is_error=True)
    failed = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )
    assert failed.replayed_is_error is True


def test_replayed_reply_without_iserror_key_reads_none(tmp_path, monkeypatch):
    """A replayed reply that lacks an `isError` key is not coerced to False."""
    def fake(records, n, **kwargs):
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "no flag here"}]},
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

    verdict = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )

    assert verdict.replayed_is_error is None


def test_replayed_reply_that_is_not_json_reads_none(tmp_path, monkeypatch):
    """An unparseable replayed reply carries no isError fact."""
    def fake(records, n, **kwargs):
        return TurnReplay(
            turn_index=n,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=b"not json",
            replayed_reply=b"not json",
            delta=[],
            workspace="/unused",
        )

    monkeypatch.setattr(turn_module, "replay_turn", fake)

    verdict = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )

    assert verdict.replayed_is_error is None


def test_non_boolean_iserror_reads_none(tmp_path, monkeypatch):
    """A non-boolean isError (a string, say) is unreadable as a fact — never coerced."""
    def fake(records, n, **kwargs):
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [], "isError": "false"},
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

    verdict = verify_turn(
        _single_turn_records(tmp_path), 0,
        server_command=["unused"], manifest_dir=tmp_path / "m",
    )

    assert verdict.replayed_is_error is None


# --- the real path: run_batch with the REAL verify_turn ---------------------------------


def _run_ledger(tmp_path: Path, trace_path: Path, *, invariants):
    return run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=invariants,
        captured_at=CAPTURED_AT,
        verifier=verify_turn,
        ingest=False,
    )


def test_runner_holds_a_trajectory_fail_for_source_edits_and_no_commands(
    tmp_path, monkeypatch
):
    """Acceptance (a) through the real path: verification claim + source edits + zero
    run_process -> the instance record holds a trajectory FAIL summary, and the FAIL
    flips the disposition to VERIFIED_FLAGGED (Phase 4 wiring; PRD decision — a
    trajectory FAIL is the same bucket as a turn FAIL)."""
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

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.disposition is Disposition.VERIFIED_FLAGGED  # trajectory FAIL flags the instance


def test_runner_holds_a_trajectory_pass_for_a_replayed_exit0_command(tmp_path, monkeypatch):
    """Acceptance (b) through the real path: one replayed exit-0 run_process before the
    claim -> the instance record holds a trajectory PASS summary."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "python -m pytest tests"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {"status": "PASS", "cause": None, "evidence_count": 1}


def test_runner_abstains_claim_unclassifiable_for_a_completion_claim(tmp_path, monkeypatch):
    """Acceptance (c) through the real path: a completion-only claim (the control shape)
    abstains with CLAIM_UNCLASSIFIABLE."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="file written")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "CLAIM_UNCLASSIFIABLE",
        "evidence_count": 0,
    }


def test_runner_abstains_no_claim_recorded_without_a_claim(tmp_path, monkeypatch):
    """Acceptance (d) through the real path: a trace with no claim record abstains with
    NO_CLAIM_RECORDED."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "NO_CLAIM_RECORDED",
        "evidence_count": 0,
    }


def test_runner_abstains_evidence_unobservable_when_no_turn_replayed(tmp_path, monkeypatch):
    """Acceptance (e) through the real path: run_process recorded, nothing replayed ->
    EVIDENCE_UNOBSERVABLE, counted as exposure rather than silence."""
    _stub_replay(monkeypatch, status=UNVERIFIED)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "EVIDENCE_UNOBSERVABLE",
        "evidence_count": 0,
    }


def test_runner_abstains_claim_unclassifiable_for_a_textless_claim(tmp_path, monkeypatch):
    """Acceptance (k) through the real path: the claim record exists but carries no text
    -> CLAIM_UNCLASSIFIABLE (a record present is a different fact from none at all)."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path)

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "CLAIM_UNCLASSIFIABLE",
        "evidence_count": 0,
    }


def test_runner_records_no_trajectory_when_the_rule_is_not_declared(tmp_path, monkeypatch):
    """Additive only: without the rule declared, the instance record carries no trajectory
    key at all — never a fabricated verdict."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("run_process", None)
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[]).instances[0]

    assert inst.trajectory is None
