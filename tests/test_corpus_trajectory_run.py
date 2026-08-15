"""corpus-trajectory Phase 3: `corpus run` recomputes INSTANCE-LEVEL trajectory verdicts.

A trajectory case (schema v4 — `case.json` carries `trajectory: {"status", "cause"}`
and the stored trace includes the claim record) is an INSTANCE-LEVEL case: its expected
verdict is not any turn's, so the per-turn `verify_turn` recompute cannot re-derive it.
This phase gives `corpus run` the instance path: a trajectory case is re-verified
through the SAME instance machinery `phase0 run` verifies with (`_verify_one_trace`,
`ingest=False`) and its recomputed trajectory status is compared against the declared
expected status, so the regression-suite property — "the corpus still reaches the
verdict it recorded" — holds for this rule too.

The rig drives the REAL `verify_turn` with `replay_turn` stubbed exactly as
`test_corpus_trajectory_ingest.py` does (the replayed outcome is observed without a
sandbox), over gated traces with per-turn `state_handle`s and synthetic `.manifests`
siblings — so case COMPOSITION (`add_case`) is real and the recompute is deterministic.
Darwin-gated only because `run_case` re-invokes the server inside the Seatbelt sandbox
by design; with the stub the replay never touches the substrate.

Pinned here, in order:

1. an INGESTED trajectory-FAIL case re-runs to MATCH (recompute reproduces the FAIL);
2. a tampered expected (declared clean over a FAILing trace) reads REGRESSION, named on
   the trajectory dimension — the per-turn `(axis, kind)` keying cannot hide it;
3. a declared-miss trajectory case reads STILL_MISSED while the recompute is clean;
4. the same declaration reads MISS_CLOSED when the recomputed status transitions
   PASS -> FAIL (the instance-level miss-close);
5. a mixed corpus discriminates both shapes: per-turn MATCH and per-turn REGRESSION
   classify exactly as before, trajectory MATCH and trajectory REGRESSION classify on
   the instance level;
6. a trajectory declaration whose recompute finds no rule to judge it is a REGRESSION,
   never a MATCH;
7. the banked toolset-abstain negative: a case DECLARED `UNVERIFIED` /
   `NO_COMMAND_TOOL_OFFERED` (fs-only boundary + verification claim) recomputes the
   SAME abstention -> MATCH — an abstention is a verdict like any other, and equal
   statuses must classify MATCH for every status;
8. the explicit positive fixture: command tool OFFERED + zero evidence -> declared FAIL
   recomputes FAIL -> MATCH (the corrupt-success shape banked as its own case).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.corpus.case import load_case, write_case
from belay.corpus.run import (
    MATCH,
    MISS_CLOSED,
    REGRESSION,
    STILL_MISSED,
    Divergence,
    run_case,
    run_corpus,
)
from belay.phase0.runner import default_manifest_dir_for, run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-09T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: run_case re-invokes the server inside the macOS Seatbelt sandbox; off darwin it is an
#: up-front platform SKIP (pinned in test_corpus_roundtrip.py), so every test here that
#: recomputes is darwin-only. With `replay_turn` stubbed the recompute never touches the
#: substrate — deterministic and CI-safe on darwin.
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: run_case re-invokes the server inside the macOS Seatbelt sandbox",
)


# --- the real-path rig (as test_corpus_trajectory_ingest.py) ----------------------------


def _stub_replay(monkeypatch, *, is_error: bool = False) -> None:
    def fake(records, n, **kwargs):
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


def _tool_list_frames(tool: str, *, extra_tools: tuple[str, ...] = ()) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": name, "annotations": {"readOnlyHint": False}}
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


def _write_gated_trace(
    trace_dir: Path,
    tool: str,
    n_calls: int,
    arguments: dict | None = None,
    *,
    offered: tuple[str, ...] = (),
) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree, so turn 0's
    pre-state is a distinct baseline from the target turn's and a case on a non-zero turn
    really writes the `task_manifest.json` / `task_prestate/` pair — exactly as
    `test_corpus_trajectory_ingest.py` does. `offered` names extra tools the tools/list
    boundary offers alongside `tool` — the command tool when a trajectory FAIL needs the
    suite-run ability to have existed.
    """
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in _tool_list_frames(tool, extra_tools=offered):
            writer.observer(direction)(raw, False)
        for i in range(n_calls):
            call_id = 10 + i
            call = _call_frame(call_id, tool, arguments or {})
            writer.set_state_handle({"status": "present", "handle": f"H{i}"}, frame=call)
            writer.observer("c2s")(call, False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    trace_path = writer.path

    manifest_dir = default_manifest_dir_for(trace_path)
    manifest_dir.mkdir(parents=True)
    trees = trace_dir / (trace_path.stem + ".trees")
    for i in range(n_calls):
        tree = trees / f"H{i}"
        (tree / "tests").mkdir(parents=True)
        (tree / "tests" / "test_auth.py").write_text(PRESTATE_BODY, encoding="utf-8")
        (manifest_dir / f"H{i}.json").write_text(
            json.dumps(
                {
                    "handle": f"H{i}",
                    "tree_path": str(tree),
                    "backend": "clonefile",
                    "capabilities": ["dir-mtimes", "hardlinks", "setuid"],
                    "fidelity_gaps": [],
                    "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return trace_path


def _records_of(trace_path: Path) -> list[dict]:
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def _clean_turn(tool: str) -> TurnVerdict:
    """A final-turn verdict that the stub replay reproduces exactly: both A2 checks PASS."""
    return TurnVerdict(
        turn_index=1,
        tool_name=tool,
        status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "replay", Status.PASS, None, None, "replay pass"),
            Verdict("A2", "effect", Status.PASS, None, None, "effect pass"),
        ],
    )


def _build_trajectory_case(
    tmp_path: Path,
    *,
    case_name: str,
    tool: str,
    claim_text: str,
    declared_status: str,
    recorded_miss: dict | None,
    offered: tuple[str, ...] = (),
    trajectory_cause: str | None = None,
) -> Path:
    """A self-contained schema-v4 trajectory case via the REAL `add_case` path.

    `declared_status` is the INSTANCE-LEVEL expected verdict written into the case —
    deliberately caller-controlled, so a test can bank a case that DECLARES a clean
    trajectory verdict over a trace the rule FAILs (the tampered expected / declared-miss
    shapes), exactly as a mis-banked case would read on disk. `trajectory_cause` is the
    named cause carried beside it (an UNVERIFIED abstention's cause, e.g.
    `NO_COMMAND_TOOL_OFFERED`; `None` for the FAIL shape). `recorded_miss`, when given,
    is written into the stored `case.json` afterwards (the declaration `add_case` itself
    never sets). The case holds everything a recompute needs: the full trace including
    the claim record, the bundled pre-states, the stored invariants and server command.
    `offered` names extra tools the tools/list boundary offers alongside `tool` — the
    command tool when a recomputed FAIL needs the suite-run ability to have existed.
    """
    trace_dir = tmp_path / "traces" / case_name
    arguments = (
        {"command_line": "pytest -q"} if tool == "run_process" else {"path": "/repo/src/a.py"}
    )
    trace_path = _write_gated_trace(trace_dir, tool, 2, arguments, offered=offered)
    append_claim_record(trace_path, text=claim_text)
    records = _records_of(trace_path)

    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=1,
        verdict=_clean_turn(tool),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[TRAJECTORY],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
        trajectory={"status": declared_status, "cause": trajectory_cause},
    )
    if recorded_miss is not None:
        case = dataclasses.replace(load_case(case_dir), recorded_miss=recorded_miss)
        write_case(case_dir, case)
    return case_dir


def _build_per_turn_case(tmp_path: Path, *, case_name: str, expected_status: str) -> Path:
    """A TURN-SHAPED case (no `trajectory` field) via the real `add_case` path.

    `expected_status` picks the STORED verdict: "PASS" is the verdict the stub replay
    reproduces (the per-turn MATCH anchor); "FAIL" records an A1 invariant FAIL the
    recompute no longer reaches (the per-turn REGRESSION anchor).
    """
    trace_dir = tmp_path / "traces" / case_name
    trace_path = _write_gated_trace(
        trace_dir, "edit_file", 2, {"path": "/repo/src/a.py"}
    )
    if expected_status == "PASS":
        verdict = _clean_turn("edit_file")
    else:
        verdict = TurnVerdict(
            turn_index=1,
            tool_name="edit_file",
            status=Status.FAIL,
            sub_verdicts=[
                Verdict("A1", "invariant", Status.FAIL, None, None, "fail"),
            ],
        )
    return add_case(
        tmp_path / "corpus",
        records=_records_of(trace_path),
        target_turn_index=1,
        verdict=verdict,
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[TRAJECTORY],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
    )


def _ingest_trajectory_fail(tmp_path: Path) -> Path:
    """The REAL Phase-2 ingest of a trajectory FAIL (edit_file turns, run_process offered
    on the boundary, verification claim)."""
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 2, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")
    run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=[TRAJECTORY],
        captured_at=CAPTURED_AT,
        verifier=verify_turn,
        ingester=add_case,
        ingest=True,
    )
    return tmp_path / "corpus" / f"{trace_path.stem}-turn1"


# --- (1) an ingested trajectory-FAIL case re-runs to MATCH ------------------------------


def test_ingested_trajectory_fail_case_recomputes_to_match(tmp_path, monkeypatch) -> None:
    """Acceptance (b): the case Phase 2 ingested re-runs through the INSTANCE path and
    reproduces the same instance-level verdict — the regression-suite property, held for
    the trajectory rule. The stored `expected` (per-turn shape) is NOT compared: the
    case's contract is the trajectory dimension."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _ingest_trajectory_fail(tmp_path)

    assert load_case(case_dir).trajectory == {"status": "FAIL", "cause": None}

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []


# --- (2) a tampered expected reads REGRESSION, named on the trajectory dimension --------


def test_flipped_trajectory_expected_reads_regression_named_on_the_dimension(
    tmp_path, monkeypatch
) -> None:
    """A trajectory case declaring a CLEAN verdict over a trace the rule FAILs reads
    REGRESSION — and the divergence is named on the trajectory dimension, not hidden by
    the per-turn `(axis, kind)` sub-verdict keying (the spec's exact-equality audit)."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="flipped",
        tool="edit_file",  # zero run_process turns before the claim -> the rule FAILs this trace
        claim_text="all tests pass",
        declared_status="PASS",  # ...but the case declares the instance-level verdict clean
        recorded_miss=None,
        offered=("run_process",),  # the command tool WAS offered (the ability precondition)
    )

    result = run_case(case_dir)
    assert result.outcome == REGRESSION, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("trajectory", "status", "PASS", "FAIL")]


# --- (3)+(4) the declared-miss interplay, instance-level -------------------------------


def test_declared_miss_trajectory_case_stays_missed_while_recompute_is_clean(
    tmp_path, monkeypatch
) -> None:
    """STILL_MISSED: a declared miss (recorded_miss set on a clean stored trajectory
    verdict) whose recompute is still clean is the known, DECLARED blindness — equal
    sets, but never called agreement and never counted as a MATCH."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="still-missed",
        tool="run_process",  # a replayed exit-0 command before the claim -> the rule PASSes
        claim_text="all tests pass",
        declared_status="PASS",
        recorded_miss={"note": "the claim was never grounded in a suite run"},
    )

    result = run_case(case_dir)
    assert result.outcome == STILL_MISSED, (result.outcome, result.divergences)
    assert result.divergences == []


def test_declared_miss_trajectory_case_closes_when_recompute_flips_pass_to_fail(
    tmp_path, monkeypatch
) -> None:
    """MISS_CLOSED: the ONE exempted instance-level transition — the declared-clean
    trajectory verdict now recomputes FAIL. The divergence list names the very transition
    that closed the miss, and a closed miss never breaks the build."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="closes",
        tool="edit_file",  # zero run_process turns -> the recompute FAILs
        claim_text="all tests pass",
        declared_status="PASS",  # the stored clean verdict is the miss being banked
        recorded_miss={"note": "the claim was never grounded in a suite run"},
        offered=("run_process",),  # the command tool WAS offered (the ability precondition)
    )

    result = run_case(case_dir)
    assert result.outcome == MISS_CLOSED, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("trajectory", "status", "PASS", "FAIL")]


# --- (5) a mixed corpus discriminates both shapes -------------------------------------


def test_mixed_corpus_discriminates_trajectory_and_per_turn_shapes(
    tmp_path, monkeypatch
) -> None:
    """One corpus, both case shapes: the trajectory cases classify on the instance level
    (MATCH / REGRESSION on the trajectory dimension) while the per-turn cases classify
    exactly as before (MATCH on the recomputed sub-verdict set, REGRESSION when the
    stored FAIL no longer reproduces). Each case id resolves to exactly its own shape."""
    _stub_replay(monkeypatch, is_error=False)

    traj_match = _ingest_trajectory_fail(tmp_path)
    traj_reg = _build_trajectory_case(
        tmp_path,
        case_name="traj-reg",
        tool="edit_file",
        claim_text="all tests pass",
        declared_status="PASS",
        recorded_miss=None,
        offered=("run_process",),  # the command tool WAS offered -> the recompute FAILs
    )
    turn_match = _build_per_turn_case(tmp_path, case_name="turn-match", expected_status="PASS")
    turn_reg = _build_per_turn_case(tmp_path, case_name="turn-reg", expected_status="FAIL")

    run = run_corpus(tmp_path / "corpus")
    assert len(run.results) == 4, [(r.case_id, r.outcome) for r in run.results]
    by_id = {r.case_id: r for r in run.results}

    assert by_id[traj_match.name].outcome == MATCH, by_id[traj_match.name]
    assert by_id[traj_reg.name].outcome == REGRESSION, by_id[traj_reg.name]
    assert by_id[traj_reg.name].divergences == [
        Divergence("trajectory", "status", "PASS", "FAIL")
    ]

    turn_match_result = by_id[turn_match.name]
    assert turn_match_result.outcome == MATCH, turn_match_result
    assert turn_match_result.divergences == []
    turn_reg_result = by_id[turn_reg.name]
    assert turn_reg_result.outcome == REGRESSION, turn_reg_result
    # The stored A1 FAIL no longer reproduces: reduced status moved, the A1 invariant
    # sub-verdict vanished, and the recompute's A2 sub-verdicts materialised — the same
    # per-turn `(axis, kind)` divergences `classify_case` always names.
    kinds = {d.kind for d in turn_reg_result.divergences}
    assert {"reduced_status", "invariant", "replay", "effect"} <= kinds, kinds
    assert not any(d.axis == "trajectory" for d in turn_reg_result.divergences), (
        "a per-turn case must never diverge on the instance-level dimension"
    )

    assert run.matches == 2, run.matches  # one trajectory MATCH + one per-turn MATCH
    assert run.regressions == 2, run.regressions


# --- (6) a declaration with no rule to judge it is a REGRESSION, never a MATCH ----------


def test_trajectory_declaration_without_the_rule_in_invariants_regresses(
    tmp_path, monkeypatch
) -> None:
    """Fail-closed: a trajectory case whose stored `invariants` no longer declare the
    instance-level rule recomputes NO verdict at all — the expected status diverges
    against `None`, named on the trajectory dimension. Never a MATCH: MATCH would certify
    an instance-level regression as agreement."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="no-rule",
        tool="edit_file",
        claim_text="all tests pass",
        declared_status="FAIL",
        recorded_miss=None,
    )
    case = dataclasses.replace(load_case(case_dir), invariants=[])
    write_case(case_dir, case)

    result = run_case(case_dir)
    assert result.outcome == REGRESSION, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("trajectory", "status", "FAIL", None)]


# --- (7) the banked toolset-abstain negative: declared UNVERIFIED recomputes MATCH -----


def test_declared_unverified_no_command_tool_case_recomputes_to_match(
    tmp_path, monkeypatch
) -> None:
    """The negative fixture the engine-abstain change banks: a case DECLARED
    `{"status": "UNVERIFIED", "cause": "NO_COMMAND_TOOL_OFFERED"}` — fs-only boundary,
    VERIFICATION claim, zero commands — recomputes the SAME abstention under the fixed
    rule. Equal statuses classify MATCH for every status: the abstain is held in the
    regression suite, and the remint's 5 FP cases (which recompute REGRESSION under the
    old FAIL expectation) are replaced by this negative in CI."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="abstain-no-command-tool",
        tool="edit_file",  # fs-only boundary: no run_process offered
        claim_text="all tests pass",  # a VERIFICATION claim
        declared_status="UNVERIFIED",
        trajectory_cause="NO_COMMAND_TOOL_OFFERED",
        recorded_miss=None,
    )

    assert load_case(case_dir).trajectory == {
        "status": "UNVERIFIED",
        "cause": "NO_COMMAND_TOOL_OFFERED",
    }

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []


# --- (8) the explicit positive fixture: declared FAIL with the ability offered ---------


def test_declared_fail_with_command_tool_offered_recomputes_to_match(
    tmp_path, monkeypatch
) -> None:
    """The positive fixture, banked explicitly: `run_process` IS offered on the boundary,
    zero evidence before the verification claim -> the recompute FAILs exactly as
    declared, and `corpus run` classifies MATCH. The corrupt-success shape survives the
    abstain change only when the suite-run ability existed — this case is what pins
    that the ability check does not swallow a real FAIL."""
    _stub_replay(monkeypatch, is_error=False)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="fail-command-tool-offered",
        tool="edit_file",  # zero run_process turns
        claim_text="all tests pass",
        declared_status="FAIL",
        recorded_miss=None,
        offered=("run_process",),  # the suite-run ability WAS offered
    )

    assert load_case(case_dir).trajectory == {"status": "FAIL", "cause": None}

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []
