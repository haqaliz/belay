"""corpus-trajectory Phase 4: a trajectory case is LEGIBLE on `corpus show`.

The show surface is where a human reads a banked case — the corpus is the regression
suite, and a case a human cannot read correctly is a case that cannot be adjudicated.
A schema-v4 trajectory case's expected verdict is INSTANCE-LEVEL (`case.trajectory`),
which the per-turn `expected status`/`sub-verdicts` block cannot express — the per-turn
shape on the case is only the final turn's proxy record. So `corpus show` renders a
distinct block: the DECLARED instance-level expected (status + cause) beside the
RECOMPUTED outcome of the same instance path `corpus run` uses (`run_case`) — the
declared-vs-recomputed distinction the run surface draws, now readable on the case
itself. Per-turn cases render exactly as before (zero trajectory lines).

The rig is `test_corpus_trajectory_run.py`'s: REAL `add_case` composition and REAL
`run_case` recompute, with `replay_turn` stubbed (the replayed outcome is observed
without a sandbox). The recompute tests are darwin-gated only because `run_case`
re-invokes the server inside the Seatbelt sandbox by design; the per-turn
zero-trajectory pin runs on every box.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.add import add_case
from belay.corpus.case import Case, load_case, write_case
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-09T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: run_case re-invokes the server inside the macOS Seatbelt sandbox; off darwin it is an
#: up-front platform SKIP (pinned in test_corpus_roundtrip.py), so every recompute test
#: here is darwin-only. With `replay_turn` stubbed the recompute never touches the
#: substrate — deterministic and CI-safe on darwin. The zero-trajectory pin needs no
#: recompute at all and runs everywhere.
REQUIRES_DARWIN = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="run_case re-invokes the server inside the macOS Seatbelt sandbox",
)


# --- the real-path rig (as test_corpus_trajectory_run.py) -------------------------------


def _stub_replay(monkeypatch) -> None:
    def fake(records, n, **kwargs):
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
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


def _tool_list_frames(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": tool, "annotations": {"readOnlyHint": False}}]},
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


def _reply_frame(msg_id: int, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _write_gated_trace(
    trace_dir: Path, tool: str, n_calls: int, arguments: dict | None = None
) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree, so turn 0's
    pre-state is a distinct baseline from the target turn's and a case on a non-zero turn
    really writes the `task_manifest.json` / `task_prestate/` pair — exactly as
    `test_corpus_trajectory_run.py` does.
    """
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in _tool_list_frames(tool):
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
) -> Path:
    """A self-contained schema-v4 trajectory case via the REAL `add_case` path.

    `declared_status` is the INSTANCE-LEVEL expected verdict written into the case —
    deliberately caller-controlled, so a test can bank a case that DECLARES a clean
    trajectory verdict over a trace the rule FAILs (the tampered expected / declared-miss
    shapes), exactly as a mis-banked case would read on disk. `recorded_miss`, when given,
    is written into the stored `case.json` afterwards (the declaration `add_case` itself
    never sets). The case holds everything a recompute needs: the full trace including
    the claim record, the bundled pre-states, the stored invariants and server command.
    """
    trace_dir = tmp_path / "traces" / case_name
    arguments = (
        {"command_line": "pytest -q"} if tool == "run_process" else {"path": "/repo/src/a.py"}
    )
    trace_path = _write_gated_trace(trace_dir, tool, 2, arguments)
    append_claim_record(trace_path, text=claim_text)

    case_dir = add_case(
        tmp_path / "corpus",
        records=_records_of(trace_path),
        target_turn_index=1,
        verdict=_clean_turn(tool),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[TRAJECTORY],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
        trajectory={"status": declared_status, "cause": None},
    )
    if recorded_miss is not None:
        case = dataclasses.replace(load_case(case_dir), recorded_miss=recorded_miss)
        write_case(case_dir, case)
    return case_dir


def _plain_case(case_id: str = "turn-shaped-0001") -> Case:
    """A turn-shaped case (no `trajectory` field) — the shape every pre-v4 case has."""
    return Case(
        id=case_id,
        target_turn_index=3,
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [
                {"axis": "A1", "kind": "invariant", "status": "FAIL"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
        human_label="pending",
        invariants=[{"scope": "tests/", "rule": "read-only"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": CAPTURED_AT},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


# --- a trajectory case shows its declared expected AND the recomputed outcome -----------


@REQUIRES_DARWIN
def test_show_renders_trajectory_expected_and_recomputed_match(
    tmp_path, monkeypatch, capsys
) -> None:
    """A trajectory-FAIL case shows the INSTANCE-LEVEL declared expected (status + cause)
    and the recomputed MATCH — a block DISTINCT from the per-turn expected, which on this
    case reads PASS (the clean final-turn proxy record) beside a trajectory FAIL that no
    single turn carries."""
    _stub_replay(monkeypatch)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="traj-match",
        tool="edit_file",  # zero run_process before the claim -> the rule FAILs this trace
        claim_text="all tests pass",
        declared_status="FAIL",  # the honest banked verdict, what the recompute reproduces
        recorded_miss=None,
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    lines = out.splitlines()
    expected_line = next(line for line in lines if "trajectory expected" in line)
    assert expected_line.strip() == "trajectory expected   FAIL  (cause: none)", out
    recomputed_line = next(line for line in lines if "trajectory recomputed" in line)
    assert recomputed_line.strip() == "trajectory recomputed MATCH", out
    # The per-turn block still renders, untouched, above the trajectory block.
    assert "expected status" in out, out
    assert "sub-verdicts" in out, out
    assert out.index("expected status") < out.index("trajectory expected"), out


@REQUIRES_DARWIN
def test_show_renders_trajectory_regression_named_on_the_dimension(
    tmp_path, monkeypatch, capsys
) -> None:
    """A tampered expected (declared clean over a FAILing trace) shows REGRESSION with the
    trajectory-dimension divergence (PASS -> FAIL) — never collapsed into the per-turn
    `(axis, kind)` sub-verdict set."""
    _stub_replay(monkeypatch)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="traj-reg",
        tool="edit_file",  # zero run_process before the claim -> the recompute FAILs
        claim_text="all tests pass",
        declared_status="PASS",  # tampered: the stored expected disagrees with the trace
        recorded_miss=None,
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    recomputed_line = next(line for line in out.splitlines() if "trajectory recomputed" in line)
    assert recomputed_line.strip() == "trajectory recomputed REGRESSION", out
    assert "trajectory status" in out, out
    assert "PASS -> FAIL" in out, out


@REQUIRES_DARWIN
def test_show_renders_still_missed_for_a_declared_trajectory_miss(
    tmp_path, monkeypatch, capsys
) -> None:
    """A declared-miss trajectory case whose recompute is still clean shows STILL_MISSED —
    the known DECLARED blindness, on the show surface too — beside the recorded_miss
    declaration line."""
    _stub_replay(monkeypatch)
    case_dir = _build_trajectory_case(
        tmp_path,
        case_name="traj-miss",
        tool="run_process",  # a replayed clean command before the claim -> the rule PASSes
        claim_text="all tests pass",
        declared_status="PASS",
        recorded_miss={"note": "the claim was never grounded in a suite run"},
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    recomputed_line = next(line for line in out.splitlines() if "trajectory recomputed" in line)
    assert recomputed_line.strip() == "trajectory recomputed STILL_MISSED", out
    assert "the claim was never grounded in a suite run" in out, out  # the declaration


# --- a turn-shaped case renders exactly as before: zero trajectory lines ---------------


def test_show_of_a_turn_shaped_case_renders_zero_trajectory_lines(tmp_path, capsys) -> None:
    """A pre-v4 turn-shaped case (no `trajectory` field) shows no trajectory rendering at
    all: the per-turn expected block reads exactly as it always did, and no recompute
    fires."""
    corpus = tmp_path / "corpus"
    case = _plain_case()
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "show", case.id, "--corpus-dir", str(corpus)])
    out = capsys.readouterr().out
    assert rc == 0, out

    assert "trajectory" not in out, out
    assert "expected status" in out, out
    assert "sub-verdicts" in out, out
