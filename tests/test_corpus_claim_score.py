"""corpus-claim Phase 5: labeled intent-drift cases score with REAL denominators.

`belay.corpus.metrics.score` needed no change (an A3 FAIL is a FAIL — `metrics.py`'s
positive is the reduced status, and `case.claim` does not alter `expected`), so the
proof is that a claim-bearing case scores EXACTLY as any FAIL case does: labeled
`true-positive` through the same `set_label` API, it lands in the confusion matrix
with real denominators, and a `pending` label keeps precision n/a — never a fabricated
1.00. Pure `score` over loaded cases; no replay, no sandbox, runs everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.corpus.add import add_case
from belay.corpus.case import load_case
from belay.corpus.curate import set_label
from belay.corpus.metrics import score
from belay.phase0.runner import default_manifest_dir_for
from belay.trace import TraceWriter, append_claim_record
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

CLAIM_EXPECTED = {
    "status": "FAIL",
    "cause": None,
    "check": {"source": "pytest -q", "exit_code": 1},
}


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


def _write_gated_trace(trace_dir: Path, n_calls: int = 2) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in _tool_list_frames("edit_file"):
            writer.observer(direction)(raw, False)
        for i in range(n_calls):
            call_id = 10 + i
            call = _call_frame(call_id, "edit_file", {"path": "/repo/src/a.py"})
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


def _bank_case(
    tmp_path: Path,
    *,
    name: str,
    verdict: TurnVerdict,
    claim: dict | None = None,
) -> Path:
    """One case through the REAL `add_case`; the claim shape when `claim` is given."""
    trace_path = _write_gated_trace(tmp_path / "traces" / name)
    append_claim_record(trace_path, text="all tests pass")
    return add_case(
        tmp_path / "corpus",
        records=_records_of(trace_path),
        target_turn_index=1,
        verdict=verdict,
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{name}-trace",
        captured_at=CAPTURED_AT,
        claim=claim,
    )


def _claim_fail_turn() -> TurnVerdict:
    """The final-turn verdict a banked intent-drift case carries: FAIL on A3."""
    return TurnVerdict(
        turn_index=1,
        tool_name="edit_file",
        status=Status.FAIL,
        sub_verdicts=[
            Verdict("A3", "claim", Status.FAIL, observed=1, expected="exit 0",
                    message="pytest -q · exit 1")
        ],
    )


def _clean_turn() -> TurnVerdict:
    return TurnVerdict(
        turn_index=1,
        tool_name="edit_file",
        status=Status.PASS,
        sub_verdicts=[Verdict("A2", "replay", Status.PASS, None, None, "canned")],
    )


def test_labeled_intent_drift_case_scores_with_real_denominators(tmp_path: Path) -> None:
    """Acceptance (4): a labeled A3 FAIL case counts precision/recall with REAL
    denominators — the intent-drift case labeled `true-positive` through the SAME
    `set_label` API (never a hand-edited `case.json`) beside a labeled clean per-turn
    case. Hand-computed from the two cells:

        claim FAIL + true-positive   -> TP  (1)
        per-turn PASS + false-positive -> TN  (1)

        precision = 1/(1+0) = 1.0, recall = 1/(1+0) = 1.0, coverage = 2/2 = 1.0
    """
    claim_case_dir = _bank_case(
        tmp_path, name="drift", verdict=_claim_fail_turn(), claim=CLAIM_EXPECTED
    )
    assert load_case(claim_case_dir).claim == CLAIM_EXPECTED

    set_label(
        tmp_path / "corpus",
        claim_case_dir.name,
        "true-positive",
        root_cause={"key": "claimed-success-without-running", "note": "the suite fails"},
    )
    turn_case_dir = _bank_case(tmp_path, name="clean", verdict=_clean_turn())
    set_label(tmp_path / "corpus", turn_case_dir.name, "false-positive")

    m = score(
        [load_case(claim_case_dir), load_case(turn_case_dir)]
    )

    assert (m.tp, m.fp, m.fn, m.tn) == (1, 0, 0, 1)
    assert m.total == 2
    assert m.pending == 0
    assert m.precision == 1.0
    assert m.precision is not None
    assert m.recall == 1.0
    assert m.recall is not None
    assert m.coverage == 1.0
    assert m.coverage is not None
    # The independence counts group the A3 TP like any other: one root-cause key.
    assert m.independent_tp == 1


def test_pending_intent_drift_label_keeps_precision_na_never_one(tmp_path: Path) -> None:
    """The SAME corpus with the intent-drift case's label left `pending`: a `pending`
    label carries no human ground truth, so the A3 FAIL is excluded from the matrix;
    with the per-turn TN the only decided case, `tp+fp == 0` and precision is `None` —
    the `_ratio` zero-denominator contract, never a fabricated 1.00."""
    claim_case_dir = _bank_case(
        tmp_path, name="drift", verdict=_claim_fail_turn(), claim=CLAIM_EXPECTED
    )
    turn_case_dir = _bank_case(tmp_path, name="clean", verdict=_clean_turn())
    set_label(tmp_path / "corpus", turn_case_dir.name, "false-positive")

    m = score(
        [load_case(claim_case_dir), load_case(turn_case_dir)]
    )

    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 1)
    assert m.pending == 1
    assert m.precision is None
    assert m.precision != 1.0
    assert m.recall is None
    assert m.recall != 1.0
    # The one decided case keeps coverage real — only the P/R denominator is empty.
    assert m.coverage == 1.0
    assert m.coverage is not None


def test_zero_denominator_score_stays_na(tmp_path: Path) -> None:
    """Zero-denominator stays n/a: a corpus whose only claim-bearing case is
    unadjudicated scores precision/recall `None` (0 denominators), never 0.0 and never
    1.0 — the empty-after-exclusion shape, exactly as for any other FAIL case."""
    claim_case_dir = _bank_case(
        tmp_path, name="drift", verdict=_claim_fail_turn(), claim=CLAIM_EXPECTED
    )

    m = score([load_case(claim_case_dir)])

    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 0)
    assert m.pending == 1
    assert m.precision is None
    assert m.recall is None
    assert m.coverage is None  # no adjudicable case at all


def test_recorded_miss_declaration_on_a_claim_case_scores_as_clean_verdict(
    tmp_path: Path,
) -> None:
    """A declared-miss claim case (stored per-turn verdict PASS + UNVERIFIED claim
    dimension) scores through the SAME machinery as any clean case: the declaration
    lands via `set_label(recorded_miss=...)` — the human's fields, validated by
    `case.py` including the claim-dimension contradiction guard — and labeled
    `true-positive` it counts an FN (the drift the engine did not catch) with a real
    denominator, never excluded and never a TP."""
    claim_case_dir = _bank_case(
        tmp_path,
        name="miss",
        verdict=_clean_turn(),
        claim={
            "status": "UNVERIFIED",
            "cause": "NO_CHECK_AUTHOR",
            "check": {"source": "", "exit_code": None},
        },
    )
    set_label(
        tmp_path / "corpus",
        claim_case_dir.name,
        "true-positive",
        root_cause={"key": "drift-not-caught", "note": "no check was ever produced"},
        recorded_miss={"note": "the drift was real: the suite was never executed"},
    )

    m = score([load_case(claim_case_dir)])

    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 1, 0)
    assert m.recall == 0.0
    assert m.recall is not None