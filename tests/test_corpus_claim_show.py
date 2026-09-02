"""corpus-claim Phase 5: a claim case is LEGIBLE on `corpus show`.

The show surface is where a human reads a banked case — the corpus is the regression
suite, and a case a human cannot read correctly is a case that cannot be adjudicated.
A schema-v5 claim case's expected verdict is INSTANCE-LEVEL (`case.claim`), which the
per-turn `expected status`/`sub-verdicts` block cannot express. So `corpus show`
renders a distinct block: the DECLARED instance-level claim expected (status + cause,
the check source and its recorded exit code — the artifacts A3 surfaces) beside the
RECOMPUTED outcome of the same instance path `corpus run` uses (`run_case`) — the
declared-vs-recomputed distinction the run surface draws, now readable on the case
itself. Per-turn cases render exactly as before (zero claim lines).

The rig is `test_corpus_claim_run.py`'s: REAL `add_case` composition and REAL
`run_case` recompute, with the `claims.replay_turn` / `claims.runner` seams stubbed
(the replayed outcome is observed without a sandbox). The recompute tests are
darwin-gated only because `run_case` re-invokes the server inside the Seatbelt sandbox
by design; the per-turn zero-claim pin runs on every box.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.add import add_case
from belay.corpus.case import Case, write_case
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import claims
from belay.verify import turn as turn_module
from belay.verify.claims import CheckResult
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: run_case re-invokes the server inside the macOS Seatbelt sandbox; off darwin it is an
#: up-front platform SKIP (pinned in test_corpus_roundtrip.py), so every recompute test
#: here is darwin-only. With the seams stubbed the recompute never touches the
#: substrate — deterministic and CI-safe on darwin. The zero-claim pin needs no
#: recompute at all and runs everywhere.
REQUIRES_DARWIN = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: run_case re-invokes the server inside the macOS "
        "Seatbelt sandbox"
    ),
)


# --- the real-path rig (as test_corpus_claim_run.py) ----------------------------------


def _stub_replay(monkeypatch, tmp_path: Path) -> None:
    ws = tmp_path / "stub-workspace"
    ws.mkdir()

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
            workspace=str(ws),
        )

    monkeypatch.setattr(claims, "replay_turn", fake)
    monkeypatch.setattr(turn_module, "replay_turn", fake)


def _stub_runner(monkeypatch, exit_code: int | None) -> None:
    class _Runner:
        def run(self, check, *, workspace, timeout):
            return CheckResult(exit_code, "boom" if exit_code else "clean", None)

    monkeypatch.setattr(claims, "runner", _Runner())


def _tool_list_frames(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [{"name": tool, "annotations": {"readOnlyHint": False}}]
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


def _reply_frame(msg_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ).encode()


def _write_gated_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in _tool_list_frames(tool):
            writer.observer(direction)(raw, False)
        for i in range(n_calls):
            call_id = 10 + i
            call = _call_frame(call_id, tool, {"path": "/repo/src/a.py"})
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


def _build_claim_case(
    tmp_path: Path,
    *,
    case_name: str,
    declared: dict,
) -> Path:
    """A self-contained schema-v5 claim case via the REAL `add_case` path.

    `declared` is the INSTANCE-LEVEL claim expected — caller-controlled, exactly as
    `test_corpus_claim_run.py` builds them.
    """
    trace_dir = tmp_path / "traces" / case_name
    trace_path = _write_gated_trace(trace_dir, "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")
    return add_case(
        tmp_path / "corpus",
        records=_records_of(trace_path),
        target_turn_index=1,
        verdict=_clean_turn("edit_file"),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
        claim=declared,
    )


def _plain_case(case_id: str = "turn-shaped-0001") -> Case:
    """A turn-shaped case (no `claim` field) — the shape every pre-v5 case has."""
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


# --- a claim case shows its declared expected AND the recomputed outcome -------------


@REQUIRES_DARWIN
def test_show_renders_claim_expected_and_recomputed_match(
    tmp_path, monkeypatch, capsys
) -> None:
    """A claim-FAIL case shows the INSTANCE-LEVEL declared expected (status + cause,
    the check source and its real exit code) and the recomputed MATCH — a block
    DISTINCT from the per-turn expected, which on this case reads PASS (the clean
    final-turn proxy record) beside a claim FAIL that no single turn carries."""
    _stub_replay(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, exit_code=1)
    case_dir = _build_claim_case(
        tmp_path,
        case_name="claim-match",
        declared={
            "status": "FAIL",
            "cause": None,
            "check": {"source": "pytest -q", "exit_code": 1},
        },
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    lines = out.splitlines()
    expected_line = next(line for line in lines if "claim expected" in line)
    assert expected_line.strip() == "claim expected        FAIL  (cause: none)", out
    check_line = next(line for line in lines if "check:" in line and "exit" in line)
    assert check_line.strip() == "check: pytest -q  (exit 1)", out
    recomputed_line = next(line for line in lines if "claim recomputed" in line)
    assert recomputed_line.strip() == "claim recomputed      MATCH", out
    # The per-turn block still renders, untouched, above the claim block.
    assert "expected status" in out, out
    assert "sub-verdicts" in out, out
    assert out.index("expected status") < out.index("claim expected"), out


@REQUIRES_DARWIN
def test_show_renders_claim_regression_named_on_the_dimension(
    tmp_path, monkeypatch, capsys
) -> None:
    """A stored claim FAIL whose recompute is silence shows REGRESSION with the
    claim-dimension divergence (FAIL -> silence) — never collapsed into the per-turn
    `(axis, kind)` sub-verdict set."""
    _stub_replay(monkeypatch, tmp_path)
    _stub_runner(monkeypatch, exit_code=0)  # the check now exits 0 -> silence
    case_dir = _build_claim_case(
        tmp_path,
        case_name="claim-reg",
        declared={
            "status": "FAIL",
            "cause": None,
            "check": {"source": "pytest -q", "exit_code": 1},
        },
    )

    rc = cli.main(["corpus", "show", case_dir.name, "--corpus-dir", str(tmp_path / "corpus")])
    out = capsys.readouterr().out
    assert rc == 0, out

    recomputed_line = next(line for line in out.splitlines() if "claim recomputed" in line)
    assert recomputed_line.strip() == "claim recomputed      REGRESSION", out
    assert "claim status" in out, out
    assert "FAIL -> " in out, out


# --- a turn-shaped case renders exactly as before: zero claim lines ------------------


def test_show_of_a_turn_shaped_case_renders_zero_claim_lines(tmp_path, capsys) -> None:
    """A pre-v5 turn-shaped case (no `claim` field) shows no claim rendering at all:
    the per-turn expected block reads exactly as it always did, and no recompute
    fires."""
    corpus = tmp_path / "corpus"
    case = _plain_case()
    write_case(corpus / case.id, case)

    rc = cli.main(["corpus", "show", case.id, "--corpus-dir", str(corpus)])
    out = capsys.readouterr().out
    assert rc == 0, out

    assert "claim" not in out, out
    assert "expected status" in out, out
    assert "sub-verdicts" in out, out