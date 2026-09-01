"""corpus-trajectory Phase 2: a trajectory FAIL ingests as a corrupt-success corpus case.

Aspect 2 (`trajectory-rule`) made `suite-before-success-claim` an INSTANCE-level verdict:
`_verify_one_trace` computes `instance["trajectory"]` and a FAIL flips the disposition to
VERIFIED_FLAGGED — but the corpus is turn-shaped, so a caught trajectory violation had
nowhere to be banked (moat #2: "every caught failure becomes a case"). This phase closes
that: `phase0 run` with `ingest=True` ingests a trajectory FAIL as a case exactly as it
ingests flagged turns — through the REAL `add_case` path, so the corpus-collision guard,
the pre-state bundling and the self-containment contract all apply identically — with the
schema-v4 `trajectory` field carrying the instance-level expected verdict and the case's
`trace.jsonl` carrying the full trajectory including the claim record.

The rig drives the REAL `verify_turn` with `replay_turn` stubbed exactly as
`test_invariant_trajectory_eval.py` does (the replayed outcome is observed without a
sandbox), over a trace with per-turn `state_handle`s and a synthetic `.manifests` sibling
exactly as `test_phase0_runner.py`'s gated-trace fixture does — so the case COMPOSITION is
real: `add_case` resolves manifests, copies pre-state trees, and writes `case.json`
fail-closed. No network, no Seatbelt, deterministic, CI-safe.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.corpus.add import add_case
from belay.corpus.case import load_case
from belay.corpus.curate import set_label
from belay.corpus.metrics import score
from belay.phase0.ledger import Disposition
from belay.phase0.runner import default_manifest_dir_for, run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.replay.reader import read_trace
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


# --- the real-path rig: stubbed replay (as test_invariant_trajectory_eval.py) ----------
# over a gated trace with state handles + manifests (as test_phase0_runner.py)


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
    really writes the `task_manifest.json` / `task_prestate/` pair. Trees live under a
    `<stem>.trees` sibling so two traces in one directory cannot collide. `offered`
    names extra tools the tools/list boundary offers alongside `tool` — the command tool
    when a trajectory FAIL needs the suite-run ability to have existed.
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


def _ingest_run(trace_path: Path, tmp_path: Path, *, invariants):
    """`run_batch` with the REAL verifier (stub replay) and the REAL `add_case`."""
    return run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=invariants,
        captured_at=CAPTURED_AT,
        verifier=verify_turn,
        ingester=add_case,
        ingest=True,
    )


def _stored_records(case_dir: Path) -> list[dict]:
    lines = (case_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


# --- a trajectory FAIL ingests a corrupt-success case -----------------------------------


def test_trajectory_fail_ingests_a_corrupt_success_case(tmp_path, monkeypatch) -> None:
    """Acceptance (a): verification claim + source edits + zero run_process -> the
    instance's ONLY failure is the trajectory FAIL, and it ingests ONE case: kind
    corrupt-success, rule suite-before-success-claim, target turn = the FINAL turn, the
    schema-v4 `trajectory` expected verdict carried, and the claim record present in the
    stored trace."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 2, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")

    ledger = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.flagged_turns == []  # every turn is clean on its own — the flag is trajectory-only
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.trajectory_addable is True
    assert inst.trajectory_unaddable is None

    stem = trace_path.stem
    case_dirs = [p for p in (tmp_path / "corpus").iterdir() if p.is_dir()]
    assert [p.name for p in case_dirs] == [f"{stem}-trajectory"]  # exactly one case, no per-turn one

    case = load_case(tmp_path / "corpus" / f"{stem}-trajectory")
    # The schema-v4 expected: an INSTANCE-LEVEL FAIL with cause null.
    assert case.trajectory == {"status": "FAIL", "cause": None}
    # The corrupt-success shape: an A1 invariant FAIL under the trajectory rule.
    assert case.expected["reduced_status"] == "FAIL"
    assert case.expected["sub_verdicts"] == [
        {"axis": "A1", "kind": "invariant", "status": "FAIL"}
    ]
    assert case.invariants == [{"scope": "", "rule": RULE_SUITE_BEFORE_SUCCESS_CLAIM}]
    # The target turn is the instance's FINAL turn.
    assert case.target_turn_index == 1
    assert case.schema_version == 4
    assert case.provenance == {"source_trace_id": stem, "captured_at": CAPTURED_AT}

    # The stored trace carries the whole trajectory, including the claim record the
    # verdict judged — the case is self-contained.
    claims = [r for r in _stored_records(tmp_path / "corpus" / f"{stem}-trajectory")
              if r.get("kind") == "claim"]
    assert len(claims) == 1, claims
    assert claims[0]["text"] == "all tests pass"


# --- a trajectory UNVERIFIED (the control shape) ingests nothing -----------------------


def test_trajectory_unverified_ingests_no_case(tmp_path, monkeypatch) -> None:
    """A completion-only claim (the control shape) abstains CLAIM_UNCLASSIFIABLE and the
    instance stays VERIFIED_CLEAN — an abstention is never a violation, so no case is
    ingested and the corpus dir is never even created."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 1, {"path": "/repo/src/a.py"}
    )
    append_claim_record(trace_path, text="file written")

    ledger = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "CLAIM_UNCLASSIFIABLE",
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.flagged_turns == []
    assert inst.trajectory_addable is False
    assert inst.trajectory_unaddable is None

    corpus_dir = tmp_path / "corpus"
    assert not corpus_dir.exists() or list(corpus_dir.iterdir()) == []


def test_trajectory_unverified_no_command_tool_offered_ingests_no_case(
    tmp_path, monkeypatch
) -> None:
    """The cause-specific abstention shape: a VERIFICATION claim on an fs-only boundary
    (no `run_process` offered, zero commands) abstains NO_COMMAND_TOOL_OFFERED — the
    re-mint's by-construction shape. An abstention is never a violation, so nothing is
    ingested and the instance stays VERIFIED_CLEAN. (The completion-claim abstention is
    pinned above; this pins the toolset-shape one under the ability-aware rule.)"""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 1, {"path": "/repo/src/a.py"}
    )
    append_claim_record(trace_path, text="all tests pass")

    ledger = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])

    inst = ledger.instances[0]
    assert inst.trajectory == {
        "status": "UNVERIFIED",
        "cause": "NO_COMMAND_TOOL_OFFERED",
        "evidence_count": 0,
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.flagged_turns == []
    assert inst.trajectory_addable is False
    assert inst.trajectory_unaddable is None

    corpus_dir = tmp_path / "corpus"
    assert not corpus_dir.exists() or list(corpus_dir.iterdir()) == []


# --- a mixed instance ingests BOTH cases ------------------------------------------------


def _stem_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier keyed by the trace's stem (read off `manifest_dir`'s name), exactly
    as `test_phase0_runner.py` — with `replayed_is_error` carried so the trajectory rule
    can assemble its facts."""

    def verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _canned_verdict(n: int, status: Status) -> TurnVerdict:
    return TurnVerdict(
        turn_index=n,
        tool_name="edit_file",
        status=status,
        replayed_is_error=False,
        sub_verdicts=[
            Verdict(
                "A1" if status is Status.FAIL else "A2",
                "invariant" if status is Status.FAIL else "replay",
                status,
                None,
                None,
                "canned",
            )
        ],
    )


def test_mixed_instance_ingests_both_the_turn_case_and_the_trajectory_case(
    tmp_path,
) -> None:
    """Every caught failure becomes a case: an instance with a turn FAIL (turn 1) AND a
    trajectory FAIL (zero run_process before the claim) ingests BOTH — the per-turn case
    targeting the failing turn (turn-shaped, no `trajectory` field) and the trajectory
    case targeting the final turn (v4, with the instance-level expected)."""
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 3, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")
    canned = {
        trace_path.stem: [
            _canned_verdict(0, Status.PASS),
            _canned_verdict(1, Status.FAIL),
            _canned_verdict(2, Status.PASS),
        ]
    }

    ledger = run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=[TRAJECTORY],
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=add_case,
        ingest=True,
    )

    inst = ledger.instances[0]
    assert inst.flagged_turns == [1]
    assert inst.flagged_addable == [1]
    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.trajectory_addable is True
    assert inst.disposition is Disposition.VERIFIED_FLAGGED

    stem = trace_path.stem
    case_names = sorted(
        p.name for p in (tmp_path / "corpus").iterdir() if p.is_dir()
    )
    assert case_names == [f"{stem}-trajectory", f"{stem}-turn1"]

    # The per-turn case is turn-shaped: target = the failing turn, no trajectory verdict.
    turn_case = load_case(tmp_path / "corpus" / f"{stem}-turn1")
    assert turn_case.target_turn_index == 1
    assert turn_case.trajectory is None
    assert turn_case.expected["reduced_status"] == "FAIL"

    # The trajectory case targets the instance's final turn and carries the
    # instance-level expected verdict.
    trajectory_case = load_case(tmp_path / "corpus" / f"{stem}-trajectory")
    assert trajectory_case.target_turn_index == 2
    assert trajectory_case.trajectory == {"status": "FAIL", "cause": None}
    assert trajectory_case.invariants == [{"scope": "", "rule": RULE_SUITE_BEFORE_SUCCESS_CLAIM}]


def test_final_turn_fail_coexists_with_trajectory_fail(tmp_path) -> None:
    """The defect shape: a per-turn FAIL on the instance's FINAL turn AND a trajectory FAIL
    on the same instance bank BOTH cases — the per-turn loop runs first, and the trajectory
    case's id no longer collides with the final turn's per-turn id."""
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 3, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")
    canned = {
        trace_path.stem: [
            _canned_verdict(0, Status.PASS),
            _canned_verdict(1, Status.PASS),
            _canned_verdict(2, Status.FAIL),
        ]
    }

    ledger = run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=["unused"],
        invariants=[TRAJECTORY],
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=add_case,
        ingest=True,
    )

    inst = ledger.instances[0]
    assert inst.flagged_turns == [2]
    assert inst.flagged_addable == [2]
    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.trajectory_addable is True
    assert inst.disposition is Disposition.VERIFIED_FLAGGED

    stem = trace_path.stem
    case_names = sorted(
        p.name for p in (tmp_path / "corpus").iterdir() if p.is_dir()
    )
    assert case_names == [f"{stem}-trajectory", f"{stem}-turn2"]

    turn_case = load_case(tmp_path / "corpus" / f"{stem}-turn2")
    assert turn_case.target_turn_index == 2
    assert turn_case.trajectory is None

    trajectory_case = load_case(tmp_path / "corpus" / f"{stem}-trajectory")
    assert trajectory_case.target_turn_index == 2
    assert trajectory_case.trajectory == {"status": "FAIL", "cause": None}
    assert trajectory_case.expected["reduced_status"] == "FAIL"


# --- the corpus-collision guard applies identically to the trajectory case -------------


def test_rerun_trajectory_collision_never_errors_the_instance(tmp_path, monkeypatch) -> None:
    """The anti-fake-PIVOT property extends to the trajectory case: a re-run over the same
    traces AND the same corpus hits an existing trajectory case id, and the collision is
    bucketed as an unaddable trajectory case — the instance stays VERIFIED_FLAGGED with
    its counts and disposition, never ERRORED, so the denominator cannot shrink."""
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 2, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")

    first = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])

    # A human adjudication on the stored trajectory case must survive the rerun refusal
    # byte-for-byte — the collision is decided before any write (the per-turn analogue is
    # pinned in test_corpus_add.py's re-add tests).
    from belay.corpus.curate import set_label

    stem = trace_path.stem
    trajectory_case_dir = tmp_path / "corpus" / f"{stem}-trajectory"
    root_cause = {"key": "suite-before-claim", "note": "verified without running the suite"}
    set_label(
        tmp_path / "corpus", f"{stem}-trajectory", "true-positive", root_cause
    )
    before = {
        name: (trajectory_case_dir / name).read_bytes()
        for name in ("trace.jsonl", "case.json")
    }

    second = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])

    assert first.violation_denominator() == 1
    assert second.violation_denominator() == first.violation_denominator()
    assert first.violating_instances() == 1
    assert second.violating_instances() == first.violating_instances()

    run_two = second.instances[0]
    assert run_two.disposition is Disposition.VERIFIED_FLAGGED
    assert run_two.error is None
    assert run_two.trajectory_addable is False
    assert run_two.trajectory_unaddable is not None
    assert "already exists" in run_two.trajectory_unaddable["cause"]

    for name in ("trace.jsonl", "case.json"):
        assert (trajectory_case_dir / name).read_bytes() == before[name], name
    stored = load_case(trajectory_case_dir)
    assert stored.human_label == "true-positive", stored.human_label
    assert stored.root_cause == root_cause, stored.root_cause


# --- aspect 2: the score-denominator proof (measurement pipeline end-to-end) ------------


def _mint_trajectory_fail(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """A synthetic mint whose ONLY failure is the trajectory FAIL; return `(trace, corpus)`.

    The real verifier (stub replay) over a 2-call `edit_file` trace with `run_process`
    offered and a verification claim — the exact shape of
    `test_trajectory_fail_ingests_a_corrupt_success_case` — banks exactly one case,
    `<stem>-trajectory`, targeting the final turn.
    """
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 2, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")
    _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])
    return trace_path, tmp_path / "corpus"


def _mint_clean_per_turn_case(corpus_dir: Path, trace_path: Path) -> Path:
    """A per-turn case for a CLEAN turn, through the REAL `add_case` — the recorded-miss path.

    The trajectory-rule mint flags no turns, so a per-turn case cannot come from the ingest
    loop; `add_case` has no verdict precondition by design, so a PASS turn composes just as
    well — the per-turn shape this proof needs as its second corpus cell.
    """
    verdict = TurnVerdict(
        turn_index=0,
        tool_name="edit_file",
        status=Status.PASS,
        sub_verdicts=[Verdict("A2", "replay", Status.PASS, None, None, "canned")],
    )
    return add_case(
        corpus_dir,
        records=list(read_trace(trace_path).records),
        target_turn_index=0,
        verdict=verdict,
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["unused"],
        invariants=[],
        human_label="pending",
        replays=3,
        timeout=20.0,
        source_trace_id=trace_path.stem,
        captured_at=CAPTURED_AT,
    )


def _make_final_handle_absent(trace_path: Path) -> None:
    """Flip the FINAL `tools/call` request's `state_handle` status to `absent`, in place.

    The rig always writes `{"status": "present", ...}` per call; the final turn's handle is
    the last c2s frame record whose handle is present (the tools/list handshake frames carry
    the writer's default absent handle and are untouched). Post-editing keeps the real trace
    shape — the same bytes `read_trace` and `add_case` read — rather than a bespoke writer
    path.
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


def test_labeled_trajectory_case_scores_with_real_denominators(
    tmp_path, monkeypatch
) -> None:
    """Acceptance (1): a labeled trajectory FAIL case counts precision/recall with REAL
    denominators, in a corpus holding BOTH shapes.

    The trajectory case banks as `<stem>-trajectory` and is labeled `true-positive` through
    the SAME `set_label` API `belay corpus label` uses — never a hand-edited `case.json` —
    beside a labeled per-turn case (a clean turn minted through the real `add_case`)
    labeled `false-positive`. Hand-computed from the two cells:

        trajectory FAIL + true-positive   -> TP  (1)
        per-turn    PASS + false-positive -> TN  (1)

        precision = 1/(1+0) = 1.0, recall = 1/(1+0) = 1.0, coverage = 2/2 = 1.0
    """
    trace_path, corpus_dir = _mint_trajectory_fail(tmp_path, monkeypatch)
    stem = trace_path.stem
    trajectory_case_dir = corpus_dir / f"{stem}-trajectory"
    assert trajectory_case_dir.is_dir()

    set_label(
        corpus_dir,
        f"{stem}-trajectory",
        "true-positive",
        root_cause={"key": "suite-before-claim", "note": "verified without running the suite"},
    )
    _mint_clean_per_turn_case(corpus_dir, trace_path)
    set_label(corpus_dir, f"{stem}-turn0", "false-positive")

    m = score(
        [
            load_case(trajectory_case_dir),
            load_case(corpus_dir / f"{stem}-turn0"),
        ]
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


def test_pending_trajectory_label_keeps_precision_na_never_one(
    tmp_path, monkeypatch
) -> None:
    """Acceptance (2): the SAME corpus with the trajectory case's label left `pending`.

    A `pending` label carries no human ground truth, so the trajectory FAIL is excluded from
    the matrix (the label-trap guard); with the per-turn TN the only decided case, `tp+fp ==
    0` and precision is `None` — the `_ratio` zero-denominator contract, never a fabricated
    1.00. Mirrors `test_zero_denominator_recall_is_na_never_one`'s assertion style.
    """
    trace_path, corpus_dir = _mint_trajectory_fail(tmp_path, monkeypatch)
    stem = trace_path.stem
    trajectory_case_dir = corpus_dir / f"{stem}-trajectory"
    assert trajectory_case_dir.is_dir()

    _mint_clean_per_turn_case(corpus_dir, trace_path)
    set_label(corpus_dir, f"{stem}-turn0", "false-positive")

    m = score(
        [
            load_case(trajectory_case_dir),
            load_case(corpus_dir / f"{stem}-turn0"),
        ]
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


def test_unrestorable_prestate_trajectory_fail_stays_unbankable(
    tmp_path, monkeypatch
) -> None:
    """Acceptance (3): an unrestorable-pre-state trajectory FAIL refuses to bank, fail-closed.

    The final turn's `state_handle` is `absent`, so `add_case`'s pre-state check — which runs
    BEFORE the collision check — refuses the trajectory case. No case is banked, the failure
    is bucketed in `trajectory_unaddable` with the NAMED pre-state cause (never "already
    exists"), the disposition stays `VERIFIED_FLAGGED`, and the instance remains in
    `violation_denominator()`.
    """
    _stub_replay(monkeypatch, is_error=False)
    trace_path = _write_gated_trace(
        tmp_path / "traces", "edit_file", 2, {"path": "/repo/src/a.py"},
        offered=("run_process",),
    )
    append_claim_record(trace_path, text="all tests pass")
    _make_final_handle_absent(trace_path)

    ledger = _ingest_run(trace_path, tmp_path, invariants=[TRAJECTORY])
    inst = ledger.instances[0]

    # The verdict is unchanged: still a trajectory FAIL — the handle never feeds the rule.
    assert inst.trajectory == {"status": "FAIL", "cause": None, "evidence_count": 0}
    assert inst.flagged_turns == []
    assert inst.trajectory_addable is False
    assert inst.trajectory_unaddable is not None
    cause = inst.trajectory_unaddable["cause"]
    assert "no restorable pre-state" in cause, cause
    assert "absent" in cause, cause
    assert "already exists" not in cause, cause

    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.error is None
    assert ledger.violation_denominator() == 1
    assert ledger.violating_instances() == 1
    assert ledger.errored_count() == 0

    corpus_dir = tmp_path / "corpus"
    assert not corpus_dir.exists() or list(corpus_dir.iterdir()) == []
