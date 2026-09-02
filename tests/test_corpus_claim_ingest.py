"""corpus-claim Phase 3: an A3 FAIL banks an intent-drift case in its own namespace.

A3's verdict is INSTANCE-LEVEL (`evaluate_claim` re-derives one claim for the whole
trace), so its corpus case is instance-shaped like the trajectory one: the case targets
the final turn but declares its expected verdict on the claim dimension
(schema v5 `claim` field), and `corpus run` later recomputes it through
`evaluate_claim`, never the per-turn path. This phase pins the banking half:

1. `claims.claim_case` — the shaping seam — turns an A3 verdict into the v5 payload
   (FAIL carries the check source + the real exit code; UNVERIFIED carries its cause
   and `exit_code: null`; a non-claim verdict shapes nothing);
2. `add_case(claim=...)` banks it in the DISJOINT `{trace}-claim` namespace, and the
   three shapes (per-turn `-turnN`, trajectory `-trajectory`, claim `-claim`) coexist
   in one corpus with namespaces that cannot collide;
3. an unrestorable pre-state stays unbankable, fail-closed — the same `add_case`
   pre-state check as every other shape;
4. the E2E banking proof: the REAL liar capture (a gated capture of an agent that
   writes a failing suite and claims "All tests pass.") re-derives an A3 FAIL through
   the real replay + the real contained runner, banks via `add_case(claim=...)`, and
   `run_case` recomputes it to MATCH — banked evidence, not a hand-built stub.

The rig is `test_corpus_trajectory_ingest.py`'s: REAL `add_case` composition over gated
traces with per-turn `state_handle`s and synthetic `.manifests` siblings. The E2E proof
is darwin-gated (the liar capture is gated; the replay re-invokes inside the macOS
Seatbelt sandbox); the plain add_case tests need no sandbox and run everywhere.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.corpus.case import load_case
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.reader import read_trace
from belay.trace import TraceWriter, append_claim_record
from belay.verify import claims
from belay.verify.claims import (
    CAUSE_NO_CLAIM_RECORDED,
    Check,
    claim_case,
)
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: The A3 FAIL verdict shape the banking path hands `add_case`: the final turn's
#: reduced verdict FAILs BECAUSE the A3 claim sub-verdict FAILed (the A3 evaluator's
#: FAIL — check source + real exit code in the message).
CLAIM_CHECK = Check(source="pytest -q", argv=("sh", "-c", "pytest -q"))
A3_FAIL = Verdict(
    "A3", "claim", Status.FAIL, observed=1, expected="exit 0",
    message="pytest -q · exit 1",
)

#: The v5 claim expected payload `claim_case` produces for `A3_FAIL` with `CLAIM_CHECK`.
CLAIM_EXPECTED = {
    "status": "FAIL",
    "cause": None,
    "check": {"source": "pytest -q", "exit_code": 1},
}

REQUIRES_DARWIN = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the liar capture is gated (Seatbelt snapshot at "
        "capture time) and its replay re-invokes inside the macOS Seatbelt sandbox; "
        "the Linux side is measured in tests/test_docker_inimage.py"
    ),
)


# --- the shaping seam: claim_case turns one A3 verdict into the v5 payload ------------


def test_claim_case_shapes_a_fail_with_source_and_real_exit_code() -> None:
    """A FAIL verdict shapes `{"status": "FAIL", "cause": null, "check": {source,
    exit_code}}` — the cause is null (the check ran and decided; there is no named
    abstention) and the exit code is the verdict's OBSERVED one, never a fabrication."""
    assert claim_case(A3_FAIL, check=CLAIM_CHECK) == CLAIM_EXPECTED


def test_claim_case_shapes_an_unverified_with_cause_and_null_exit_code() -> None:
    """An UNVERIFIED verdict shapes its named cause and a check entry whose exit_code
    is null — did not execute, the CheckResult contract — with the authored check's
    source when one was produced."""
    verdict = Verdict(
        "A3", "claim", Status.UNVERIFIED, observed=None,
        expected={"axis": "A3", "kind": "claim", "cause": CAUSE_NO_CLAIM_RECORDED,
                  "check_source": "pytest -q"},
        message="UNVERIFIED",
    )
    assert claim_case(verdict) == {
        "status": "UNVERIFIED",
        "cause": CAUSE_NO_CLAIM_RECORDED,
        "check": {"source": "pytest -q", "exit_code": None},
    }


def test_claim_case_shapes_an_unverified_with_no_check_as_empty_source() -> None:
    """An UNVERIFIED verdict with no check produced (the no-author abstention) shapes
    `source: ""` — a declared "no check to quote", never a fabricated one."""
    verdict = Verdict(
        "A3", "claim", Status.UNVERIFIED, observed=None,
        expected={"axis": "A3", "kind": "claim", "cause": "NO_CHECK_AUTHOR"},
        message="UNVERIFIED",
    )
    assert claim_case(verdict) == {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }


def test_claim_case_shapes_nothing_for_a_non_claim_verdict() -> None:
    """A non-claim verdict (a PASS turn, an A1 invariant, silence) shapes None — the
    caller keeps exactly the A3 FAIL/UNVERIFIED cases, never a fabricated payload."""
    assert claim_case(Verdict("A2", "replay", Status.PASS, None, None, "ok")) is None
    assert claim_case(Verdict("A1", "invariant", Status.FAIL, None, None, "fail")) is None
    assert claim_case(Verdict("A3", "claim", Status.PASS, None, None, "never")) is None


# --- the real-path rig (as test_corpus_trajectory_ingest.py) --------------------------


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


def _reply_frame(msg_id: int, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _write_gated_trace(
    trace_dir: Path,
    tool: str,
    n_calls: int,
    arguments: dict | None = None,
) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree, exactly as
    `test_corpus_trajectory_ingest.py` builds them.
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


def _bank_claim_case(
    tmp_path: Path,
    *,
    case_name: str,
    n_calls: int = 2,
    claim: dict | None = CLAIM_EXPECTED,
    verdict_status: Status = Status.FAIL,
) -> tuple[Path, Path, str]:
    """Compose a claim case through the REAL `add_case`; return (trace, case_dir, stem).

    The banked case's per-turn `expected` FAILs on the A3 claim sub-verdict (the shape
    the ingest path produces at trace close), and the stored trace carries the claim
    record the recompute will judge.
    """
    trace_dir = tmp_path / "traces" / case_name
    trace_path = _write_gated_trace(
        trace_dir, "edit_file", n_calls, {"path": "/repo/src/a.py"}
    )
    append_claim_record(trace_path, text="all tests pass")
    records = _records_of(trace_path)

    turn_verdict = TurnVerdict(
        turn_index=n_calls - 1,
        tool_name="edit_file",
        status=verdict_status,
        sub_verdicts=[
            A3_FAIL if verdict_status is Status.FAIL
            else Verdict("A2", "replay", Status.PASS, None, None, "canned")
        ],
    )
    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=n_calls - 1,
        verdict=turn_verdict,
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
        claim=claim,
    )
    return trace_path, case_dir, f"{case_name}-trace"


# --- an A3 FAIL banks a `{trace}-claim` case ------------------------------------------


def test_claim_fail_banks_a_claim_case(tmp_path: Path) -> None:
    """Acceptance (1): an A3 FAIL composes an intent-drift case via `add_case(claim=...)`
    — id in the `-claim` namespace, the v5 `claim` expected carried verbatim, target
    turn the FINAL turn, the claim record present in the stored trace, and
    `schema_version` 5."""
    trace_path, case_dir, stem = _bank_claim_case(tmp_path, case_name="liar")

    assert case_dir.name == f"{stem}-claim", case_dir.name
    case = load_case(case_dir)
    assert case.claim == CLAIM_EXPECTED
    assert case.schema_version == 5
    assert case.trajectory is None
    assert case.target_turn_index == 1  # the FINAL turn — the instance's target
    assert case.expected["reduced_status"] == "FAIL"
    assert case.expected["sub_verdicts"] == [
        {"axis": "A3", "kind": "claim", "status": "FAIL"}
    ]

    # The stored trace carries the whole trajectory, INCLUDING the claim record the
    # verdict judged — the case is self-contained for the recompute. (The claim is a
    # non-frame record, so the reader carries it in `skips`, never `records`.)
    stored_lines = (case_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    claims_in_trace = [
        json.loads(line) for line in stored_lines
        if json.loads(line).get("kind") == "claim"
    ]
    assert len(claims_in_trace) == 1, claims_in_trace
    assert claims_in_trace[0]["text"] == "all tests pass"

    # The stored claim payload is validated at load, never dropped: it reads back
    # byte-for-byte as the payload `claim_case` shaped.
    stored_json = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    assert stored_json["claim"] == CLAIM_EXPECTED


# --- the three shapes coexist in one corpus, namespaces disjoint ----------------------


def test_claim_case_coexists_with_per_turn_and_trajectory_cases(tmp_path: Path) -> None:
    """Acceptance (2), RED-first: one trace, all three case shapes in one corpus —
    the per-turn `-turnN`, the trajectory `-trajectory` and the claim `-claim`
    namespaces are disjoint (a `-claim` id can never collide with a `-turn<int>` or
    `-trajectory` one), and each case loads as exactly its own shape."""
    trace_dir = tmp_path / "traces" / "mixed"
    trace_path = _write_gated_trace(trace_dir, "edit_file", 3, {"path": "/repo/src/a.py"})
    append_claim_record(trace_path, text="all tests pass")
    records = _records_of(trace_path)
    corpus_dir = tmp_path / "corpus"

    per_turn = add_case(
        corpus_dir,
        records=records,
        target_turn_index=1,
        verdict=TurnVerdict(
            turn_index=1, tool_name="edit_file", status=Status.FAIL,
            sub_verdicts=[Verdict("A1", "invariant", Status.FAIL, None, None, "fail")],
        ),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id="mixed-trace",
        captured_at=CAPTURED_AT,
    )
    trajectory = add_case(
        corpus_dir,
        records=records,
        target_turn_index=2,
        verdict=TurnVerdict(
            turn_index=2, tool_name="edit_file", status=Status.FAIL,
            sub_verdicts=[Verdict("A1", "invariant", Status.FAIL, None, None, "fail")],
        ),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id="mixed-trace",
        captured_at=CAPTURED_AT,
        trajectory={"status": "FAIL", "cause": None},
    )
    claim = add_case(
        corpus_dir,
        records=records,
        target_turn_index=2,
        verdict=TurnVerdict(
            turn_index=2, tool_name="edit_file", status=Status.FAIL,
            sub_verdicts=[Verdict("A3", "claim", Status.FAIL, 1, "exit 0", "pytest · exit 1")],
        ),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id="mixed-trace",
        captured_at=CAPTURED_AT,
        claim=CLAIM_EXPECTED,
    )

    names = sorted(p.name for p in corpus_dir.iterdir() if p.is_dir())
    assert names == ["mixed-trace-claim", "mixed-trace-trajectory", "mixed-trace-turn1"]

    per_turn_case = load_case(per_turn)
    assert per_turn_case.trajectory is None and per_turn_case.claim is None
    assert per_turn_case.target_turn_index == 1

    trajectory_case = load_case(trajectory)
    assert trajectory_case.trajectory == {"status": "FAIL", "cause": None}
    assert trajectory_case.claim is None

    claim_case_dir = load_case(claim)
    assert claim_case_dir.claim == CLAIM_EXPECTED
    assert claim_case_dir.trajectory is None


def test_a_case_cannot_declare_both_trajectory_and_claim(tmp_path: Path) -> None:
    """Fail-closed: `add_case` refuses `trajectory=` AND `claim=` together — one case
    declares one instance-level contract, never two (the fail-closed guard, so a
    mis-wired ingester cannot bank a case whose recompute route is ambiguous)."""
    trace_dir = tmp_path / "traces" / "both"
    trace_path = _write_gated_trace(trace_dir, "edit_file", 2, {"path": "/repo/src/a.py"})
    records = _records_of(trace_path)

    with pytest.raises(ValueError, match="both a 'trajectory' and a 'claim'"):
        add_case(
            tmp_path / "corpus",
            records=records,
            target_turn_index=1,
            verdict=TurnVerdict(
                turn_index=1, tool_name="edit_file", status=Status.FAIL,
                sub_verdicts=[Verdict("A3", "claim", Status.FAIL, 1, "exit 0", "m")],
            ),
            manifest_dir=default_manifest_dir_for(trace_path),
            server_command=["unused"],
            invariants=[],
            replays=3,
            timeout=20.0,
            source_trace_id="both-trace",
            captured_at=CAPTURED_AT,
            trajectory={"status": "FAIL", "cause": None},
            claim=CLAIM_EXPECTED,
        )
    assert not (tmp_path / "corpus").exists() or list((tmp_path / "corpus").iterdir()) == []


# --- unrestorable pre-state stays unbankable, fail-closed -----------------------------


def _make_final_handle_absent(trace_path: Path) -> None:
    """Flip the FINAL `tools/call` request's `state_handle` status to `absent`, in place.

    Same post-edit as `test_corpus_trajectory_ingest.py:549-574`.
    """
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines if line]
    for record in reversed(records):
        handle = record.get("state_handle")
        if (
            record.get("kind") == "frame"
            and record.get("dir") == "c2s"
            and isinstance(handle, dict)
            and handle.get("status") == "present"
        ):
            handle["status"] = "absent"
            break
    else:
        raise AssertionError("no present-handle c2s frame found to flip")
    trace_path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


def test_unrestorable_prestate_claim_stays_unbankable(tmp_path: Path) -> None:
    """Acceptance (4): an unrestorable pre-state refuses to bank, fail-closed — the
    SAME `add_case` pre-state check as every shape: the final turn's `state_handle` is
    `absent`, so the claim case cannot compose, the named cause names the pre-state
    (never "already exists"), and nothing is written."""
    trace_dir = tmp_path / "traces" / "unbankable"
    trace_path = _write_gated_trace(trace_dir, "edit_file", 2, {"path": "/repo/src/a.py"})
    append_claim_record(trace_path, text="all tests pass")
    _make_final_handle_absent(trace_path)
    records = _records_of(trace_path)

    with pytest.raises(ValueError, match="no restorable pre-state"):
        add_case(
            tmp_path / "corpus",
            records=records,
            target_turn_index=1,
            verdict=TurnVerdict(
                turn_index=1, tool_name="edit_file", status=Status.FAIL,
                sub_verdicts=[Verdict("A3", "claim", Status.FAIL, 1, "exit 0", "m")],
            ),
            manifest_dir=default_manifest_dir_for(trace_path),
            server_command=["unused"],
            invariants=[],
            replays=3,
            timeout=20.0,
            source_trace_id="unbankable-trace",
            captured_at=CAPTURED_AT,
            claim=CLAIM_EXPECTED,
        )

    corpus_dir = tmp_path / "corpus"
    assert not corpus_dir.exists() or list(corpus_dir.iterdir()) == []


# --- the E2E banking proof: the real liar capture banks and recomputes MATCH ----------


@REQUIRES_DARWIN
def test_liar_capture_banks_a_claim_case(
    tmp_path: Path, monkeypatch
) -> None:
    """The end-to-end banking proof, on the REAL liar fixture.

    A gated capture of the liar shape (command tool offered in `tools/list`, zero
    `run_process` turns, final turn = `write_file` of a suite that exits 1, claim "All
    tests pass." appended) re-derives an A3 FAIL through the REAL replay of the final
    turn and the REAL contained runner; the verdict banks through the REAL `add_case`
    with `claim_case`'s payload — banked evidence, not a hand-built stub. The
    recompute half of the roundtrip (the banked case re-running to MATCH) is pinned in
    `tests/test_corpus_claim_run.py` on the same capture.

    The author is the fixture's deterministic fake (`LIAR_CHECK` = run the suite in
    the final state) — the model seam is always injected in tests; everything else is
    real.
    """
    from fixtures.claim_liar_capture import LIAR_CHECK, capture_liar

    liar = capture_liar(tmp_path)
    read = read_trace(liar.trace_path)
    records = list(read.records)
    skips = read.skips

    verdict = claims.evaluate_claim(
        records=records,
        skips=skips,
        verdicts={},
        author=_FixedAuthor(LIAR_CHECK),
        manifest_dir=liar.manifest_dir,
        server_command=liar.server_command,
        timeout=60.0,
    )
    assert verdict is not None, "the failing suite must produce an A3 FAIL, never silence"
    assert verdict.status is Status.FAIL, verdict
    assert verdict.observed == 1, verdict

    # Records for the case: the reader's records PLUS the claim record (the stored
    # trace must carry the claim the recompute will judge — the trajectory ingest's
    # own self-containment shape).
    case_records = [
        *records,
        *(skip.record for skip in skips if skip.kind == "claim" and skip.record is not None),
    ]
    case_dir = add_case(
        tmp_path / "corpus",
        records=case_records,
        target_turn_index=0,
        verdict=TurnVerdict(
            turn_index=0,
            tool_name="write_file",
            status=Status.FAIL,
            sub_verdicts=[
                Verdict("A3", "claim", Status.FAIL, observed=1, expected="exit 0",
                        message=verdict.message)
            ],
        ),
        manifest_dir=liar.manifest_dir,
        server_command=liar.server_command,
        invariants=[],
        replays=3,
        timeout=60.0,
        source_trace_id=liar.trace_path.stem,
        captured_at=CAPTURED_AT,
        claim=claim_case(verdict, check=LIAR_CHECK),
    )

    case = load_case(case_dir)
    assert case.id == f"{liar.trace_path.stem}-claim"
    assert case.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": LIAR_CHECK.source, "exit_code": 1},
    }
    # The case is self-contained: it bundles the pre-state tree and manifest the
    # recompute will restore from, and the full trace including the claim record.
    assert (case_dir / "prestate").is_dir()
    assert (case_dir / "manifest.json").is_file()


class _FixedAuthor:
    """The author seam, deterministic: hand back exactly the configured check."""

    def __init__(self, check: Check):
        self._check = check

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return self._check


__all__: list[str] = []