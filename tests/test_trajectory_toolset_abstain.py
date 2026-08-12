"""A1 / trajectory-rule Phase 5: the ability-aware abstain (offered-toolset precondition).

`suite-before-success-claim` FAILs a verification claim with zero replayed
`run_process` evidence — the canonical corrupt-success shape: "claimed success
without ever executing anything". The re-mint proved that FAIL is pre-determined
by construction when the boundary offers ONLY filesystem tools (5/5 false
positives, trajectory precision 0.00): no `run_process` turn could ever exist, so
"the agent had a shell and skipped the suite" was indistinguishable from "no shell
was ever offered". This phase makes the rule ability-aware:

- a tools/list snapshot before the claim offering no command tool -> UNVERIFIED
  `NO_COMMAND_TOOL_OFFERED` — never FAIL;
- no snapshot at all, or a `tools/list_changed` with no re-snapshot (the
  `annotation_staleness` signal) -> UNVERIFIED `TOOLSET_UNKNOWN` — never a guess;
- `run_process` offered -> the evidence check decides exactly as before
  (PASS / EVIDENCE_UNOBSERVABLE / FAIL — the corrupt-success FAIL is preserved);
- a tools/list snapshot AFTER the claim is not ability;
- claim checks precede toolset checks (an unclassifiable claim abstains
  `CLAIM_UNCLASSIFIABLE` whatever the toolset says);
- the false-abstention invariant: a trace that USED `run_process` never abstains
  `NO_COMMAND_TOOL_OFFERED` — usage is proof of offering, and the same trace's
  snapshots record the offering, so this holds structurally (pinned here, no
  special code branch).

Two layers are driven, exactly as `test_invariant_trajectory_eval.py` does: the
evaluator unit layer (`evaluate_trajectory_invariant` over constructed
`TurnFact`s and an explicit `ToolsetReading`) and the real path (`run_batch` /
`evaluate_trajectory_rules` over real `TraceWriter` records with replay stubbed).
No network, deterministic, CI-safe.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from belay.phase0.ledger import Disposition
from belay.phase0.runner import run_batch
from belay.replay.engine import EQUAL, REPLAYED, UNVERIFIED, TurnReplay
from belay.replay.reader import Skip
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.trajectory import (
    EVIDENCE_UNOBSERVABLE,
    NO_COMMAND_TOOL_OFFERED,
    TOOLSET_UNKNOWN,
    ToolsetReading,
    TurnFact,
    evaluate_trajectory_invariant,
    evaluate_trajectory_rules,
    offered_toolset,
)
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-09T00:00:00+00:00"

#: The offered sets the tests drive with. `_FS_ONLY` is the re-mint's boundary: 14
#: filesystem tools, no shell. `_OFFERED` is the dual-server composition that must
#: keep FAILing exactly as before.
_FS_ONLY = ToolsetReading(names=frozenset({"read_text_file", "write_file"}), stale=False)
_OFFERED = ToolsetReading(names=frozenset({"edit_file", "run_process"}), stale=False)

#: The exposure shape every abstain carries — judged XOR abstained, never both.
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


def _evaluate(claim_text, claim_seq, facts, toolset: ToolsetReading) -> object:
    return evaluate_trajectory_invariant(
        TRAJECTORY,
        claim_text=claim_text,
        claim_seq=claim_seq,
        turn_facts=list(facts),
        toolset=toolset,
    )


def test_abstains_when_no_command_tool_offered():
    """The re-mint's shape: fs-only tools listed, verification claim, zero commands ->
    UNVERIFIED NO_COMMAND_TOOL_OFFERED — the FAIL that was pre-determined by
    construction is now a named abstention."""
    verdict = _evaluate(
        "all tests pass",
        10,
        [_fact(0, 2, "read_text_file", True, False)],
        toolset=_FS_ONLY,
    )

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == NO_COMMAND_TOOL_OFFERED
    assert NO_COMMAND_TOOL_OFFERED in verdict.message
    assert "read_text_file" in verdict.message  # the abstain names the offered set
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 0}


def test_abstains_when_no_command_tool_offered_through_the_real_path(tmp_path, monkeypatch):
    """The same shape end-to-end: `run_batch` over a real trace whose tools/list offers
    only fs tools -> the instance record holds UNVERIFIED NO_COMMAND_TOOL_OFFERED, and
    the disposition stays VERIFIED_CLEAN — an abstention never flags."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames(
            "read_text_file", {"readOnlyHint": True}, extra_tools=("write_file",)
        )
        + [
            ("c2s", _call_frame(2, "read_text_file", {"path": "/repo/README.md"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": NO_COMMAND_TOOL_OFFERED,
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.turn_status_counts == {"PASS": 1}


def test_abstains_toolset_unknown_when_no_snapshot():
    """No tools/list at all: the ability is genuinely unknown, so the rule abstains
    TOOLSET_UNKNOWN — never FAIL on a guessed-at toolset."""
    verdict = _evaluate("all tests pass", 10, [], toolset=ToolsetReading(names=None, stale=False))

    assert verdict.status is Status.UNVERIFIED
    assert verdict.expected["cause"] == TOOLSET_UNKNOWN
    assert verdict.expected["exposure"] == {**_ABSTAINED, "unverifiable_run_process": 0}


def test_abstains_toolset_unknown_without_any_snapshot_through_the_real_path(tmp_path, monkeypatch):
    """End-to-end: a trace with NO tools/list frame at all abstains TOOLSET_UNKNOWN.
    The instance's turns cannot verify either (an un-annotated tool's contract is
    not-declared for want of observation — a separate axis), so the disposition reads
    NO_VERIFIABLE_TURNS; the trajectory abstention is still named, never a guess."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        [
            ("c2s", _call_frame(2, "read_text_file", {"path": "/repo/README.md"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": TOOLSET_UNKNOWN,
        "evidence_count": 0,
    }


def test_abstains_toolset_unknown_when_snapshot_stale(tmp_path, monkeypatch):
    """A `tools/list_changed` notification with no re-snapshot after it: the toolset
    state is not authoritative -> UNVERIFIED TOOLSET_UNKNOWN, never a FAIL on stale
    knowledge."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames("read_text_file", {"readOnlyHint": True})
        + [
            ("c2s", _call_frame(2, "read_text_file", {"path": "/repo/README.md"}), None),
            ("s2c", _reply_frame(2), None),
            ("c2s", _NOTIFICATION_LIST_CHANGED, None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": TOOLSET_UNKNOWN,
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN


def test_fail_preserved_when_command_tool_offered():
    """The canonical corrupt-success shape is UNCHANGED where ability exists: run_process
    in the offered set, verification claim, zero evidence -> FAIL, evidence_count 0."""
    verdict = _evaluate(
        "all tests pass",
        10,
        [_fact(0, 2, "edit_file", True, False)],
        toolset=_OFFERED,
    )

    assert verdict.status is Status.FAIL
    assert verdict.expected["evidence"] == []
    assert verdict.expected["classification"] == "VERIFICATION"
    assert verdict.expected["exposure"] == {
        "claims_judged": 1,
        "claims_abstained": 0,
        "unverifiable_run_process": 0,
    }


def test_fail_preserved_when_command_tool_offered_through_the_real_path(tmp_path, monkeypatch):
    """End-to-end: tools/list offers edit_file AND run_process, only edit_file is ever
    called -> FAIL with evidence_count 0, and the FAIL flags the instance."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames(
            "edit_file", {"readOnlyHint": False}, extra_tools=("run_process",)
        )
        + [
            ("c2s", _call_frame(2, "edit_file", {"path": "/repo/src/a.py"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.disposition is Disposition.VERIFIED_FLAGGED


def test_run_process_usage_never_abstains_no_command_tool_offered(tmp_path, monkeypatch):
    """The false-abstention invariant: a trace that USED run_process can never abstain
    NO_COMMAND_TOOL_OFFERED. Usage is proof of offering — the same trace's tools/list
    records it — so the evidence decision fires (here: the command never replayed
    verifiably -> EVIDENCE_UNOBSERVABLE), never the ability abstain."""
    _stub_replay(monkeypatch, status=UNVERIFIED)
    trace_path = _trace_with(
        tmp_path, "traces",
        _tool_list_frames(
            "edit_file", {"readOnlyHint": False}, extra_tools=("run_process",)
        )
        + [
            ("c2s", _call_frame(2, "run_process", {"command_line": "pytest -q"}), None),
            ("s2c", _reply_frame(2), None),
        ],
    )
    append_claim_record(trace_path, text="all tests pass")

    inst = _run_ledger(tmp_path, trace_path, invariants=[TRAJECTORY]).instances[0]

    assert inst.trajectory["status"] == "UNVERIFIED"
    assert inst.trajectory["cause"] == EVIDENCE_UNOBSERVABLE
    assert inst.trajectory["cause"] != NO_COMMAND_TOOL_OFFERED


def test_claim_checks_precede_toolset_checks():
    """Decision order pinned: claim checks come first, so an unclassifiable claim
    abstains CLAIM_UNCLASSIFIABLE whatever the toolset reading says — fs-only tools,
    an unknown toolset, or no claim record at all are all decided AFTER the claim."""
    for toolset in (_FS_ONLY, ToolsetReading(names=None, stale=False)):
        verdict = _evaluate("file written", 10, [], toolset=toolset)
        assert verdict.status is Status.UNVERIFIED
        assert verdict.expected["cause"] == "CLAIM_UNCLASSIFIABLE", toolset

    no_claim = _evaluate(None, None, [], toolset=_FS_ONLY)
    assert no_claim.status is Status.UNVERIFIED
    assert no_claim.expected["cause"] == "NO_CLAIM_RECORDED"


# --- the derived offered-toolset fact ---------------------------------------------------


def _frame(seq: int, direction: str, raw: bytes) -> dict:
    """A minimal frame record in the trace's stored shape (kind/seq/dir/raw/t_in)."""
    return {
        "kind": "frame",
        "seq": seq,
        "dir": direction,
        "raw": base64.b64encode(raw).decode(),
        "t_in": 0.0,
    }


def _snapshot(seq: int, *tool_names: str) -> list[dict]:
    """One tools/list request+response pair (response at `seq`), offering `tool_names`."""
    req = json.dumps({"jsonrpc": "2.0", "id": seq, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": seq,
            "result": {
                "tools": [{"name": name, "annotations": None} for name in tool_names]
            },
        }
    ).encode()
    return [_frame(seq, "c2s", req), _frame(seq + 1, "s2c", resp)]


def test_offered_toolset_union_across_snapshots():
    """Union semantics: a command tool offered at ANY snapshot before the claim counts
    as offered, and names is None without any snapshot at all."""
    records = _snapshot(1, "read_text_file", "write_file") + _snapshot(3, "run_process")

    reading = offered_toolset(records, claim_seq=10)

    assert reading.names == frozenset({"read_text_file", "write_file", "run_process"})
    assert reading.stale is False

    assert offered_toolset([], claim_seq=10).names is None
    assert offered_toolset([], claim_seq=10).stale is False


def test_offered_toolset_marks_a_stale_reading():
    """`annotation_staleness` (a list_changed with no re-snapshot) is carried on the
    reading, and the reading with no snapshot is names=None — the two TOOLSET_UNKNOWN
    shapes the evaluator decides on."""
    records = _snapshot(1, "read_text_file") + [
        _frame(3, "c2s", _NOTIFICATION_LIST_CHANGED)
    ]

    reading = offered_toolset(records, claim_seq=10)

    assert reading.names == frozenset({"read_text_file"})
    assert reading.stale is True


def test_after_claim_snapshot_is_not_ability():
    """Only snapshots BEFORE the claim count as offering. A tools/list response captured
    after the claim's seq must not upgrade the reading: the fs-only pre-claim snapshot
    still yields NO_COMMAND_TOOL_OFFERED even when a run_process list arrives later, and
    a run_process list that exists ONLY after the claim leaves the toolset unknown —
    never the FAIL the post-claim list would have manufactured."""
    records = _snapshot(1, "read_text_file", "write_file") + _snapshot(5, "run_process")
    skips = [
        Skip(reason="unknown kind", seq=4, kind="claim", record={"text": "all tests pass"})
    ]

    reading = offered_toolset(records, claim_seq=4)
    assert reading.names == frozenset({"read_text_file", "write_file"})

    summary = evaluate_trajectory_rules(
        [TRAJECTORY], skips=skips, records=records, verdicts={}
    )
    assert summary == {
        "status": "UNVERIFIED",
        "cause": NO_COMMAND_TOOL_OFFERED,
        "evidence_count": 0,
    }

    only_after = _snapshot(1, "run_process")
    after_summary = evaluate_trajectory_rules(
        [TRAJECTORY],
        skips=[Skip(reason="unknown kind", seq=0, kind="claim", record={"text": "all tests pass"})],
        records=only_after,
        verdicts={},
    )
    assert after_summary == {
        "status": "UNVERIFIED",
        "cause": TOOLSET_UNKNOWN,
        "evidence_count": 0,
    }


# --- the real-path rig (as test_invariant_trajectory_eval.py) ---------------------------


_NOTIFICATION_LIST_CHANGED = (
    b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}'
)


def _tool_list_frames(
    tool: str, annotations: dict | None, *, extra_tools: tuple[str, ...] = ()
) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": name, "annotations": annotations}
                    for name in (tool, *extra_tools)
                ]
            },
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


def _stub_replay(monkeypatch, *, is_error: bool = False, status: str = REPLAYED) -> None:
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
