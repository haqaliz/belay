"""corpus-claim Phase 4: `corpus run` recomputes INSTANCE-LEVEL A3 claim verdicts.

A claim case (schema v5 — `case.json` carries `claim: {"status", "cause", "check"}`
and the stored trace includes the claim record) is an INSTANCE-LEVEL case: its expected
verdict is the A3 claim re-derivation's, not any turn's, so the per-turn `verify_turn`
recompute cannot re-derive it. This phase gives `corpus run` the claim path: a claim
case is re-verified through `evaluate_claim` DIRECTLY — the stored trace + manifests,
the stored check re-issued by a deterministic author and re-executed — and its
recomputed claim status is compared against the declared expected status, so the
regression-suite property ("the corpus still reaches the verdict it recorded") holds
for the claim axis too.

Pinned here, in order:

1. an INGESTED claim-FAIL case re-runs to MATCH (recompute reproduces the FAIL through
   the stored check — the re-execution convention: `sh -c <stored source>`);
2. a divergence reads REGRESSION, named on the claim dimension (`claim status`) —
   silence (the check now exits 0) is a REGRESSION on an undeclared case, never a
   pass and never a MATCH;
3. a claim case whose stored trace lost its claim record recomputes the
   `NO_CLAIM_RECORDED` abstention — a divergence vs the declared FAIL is a REGRESSION
   (the case's own claim vanished: that IS a regression);
4. `disable_claim_axis=True` SKIPs with the named cause `CLAIM_AXIS_DISABLED` — before
   any replay, never a REGRESSION (the refutation's load-bearing rule);
5. declared-miss semantics (§2 of the plan): silence-on-recompute of a declared miss is
   STILL_MISSED (the drift is still open), a FAIL recompute is MISS_CLOSED (a
   sharpened check catches the banked drift again), and there is NO PASS close — A3
   never emits PASS, so no branch for it exists;
6. a mixed corpus discriminates claim and per-turn shapes — each classifies on its own
   contract and a claim case never diverges on the per-turn dimensions;
7. the E2E roundtrip: the REAL liar capture's banked case recomputes to MATCH through
   the real replay + the real contained runner (the Phase-3 banking proof's recompute
   half).

The rig drives the REAL `run_case` with `claims.replay_turn` and `claims.runner`
stubbed (the deterministic seams — the replayed outcome is observed without a
substrate), over gated traces with per-turn `state_handle`s and synthetic
`.manifests` siblings — so case COMPOSITION (`add_case`) is real and the recompute is
deterministic. Darwin-gated only because `run_case` re-invokes the server inside the
Seatbelt sandbox by design; with both seams stubbed the recompute never touches the
substrate.
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
    CLAIM_AXIS_DISABLED,
    MATCH,
    MISS_CLOSED,
    REGRESSION,
    SKIP,
    STILL_MISSED,
    Divergence,
    run_case,
    run_corpus,
)
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.replay.reader import read_trace
from belay.trace import TraceWriter, append_claim_record
from belay.verify import claims
from belay.verify import turn as turn_module
from belay.verify.claims import Check, CheckResult
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

#: The stored check source the recompute re-issues and re-executes.
CHECK_SOURCE = "pytest -q"

#: The stored claim expected the undeclared tests bank: an A3 FAIL with the check that
#: ran (exit 1).
CLAIM_FAIL = {
    "status": "FAIL",
    "cause": None,
    "check": {"source": CHECK_SOURCE, "exit_code": 1},
}

#: The stored claim expected a DECLARED-MISS case carries: the engine's non-catch on
#: the claim dimension (an UNVERIFIED abstention — silence has no status), which a
#: human adjudicated a real intent drift. The per-turn `expected` records the clean
#: final-turn verdict (PASS), so the v3 declaration itself is legal.
CLAIM_MISS = {
    "status": "UNVERIFIED",
    "cause": "NO_CHECK_AUTHOR",
    "check": {"source": "", "exit_code": None},
}

#: run_case re-invokes the server inside the macOS Seatbelt sandbox; off darwin it is an
#: up-front platform SKIP (pinned in test_corpus_roundtrip.py), so every recompute test
#: here is darwin-only. With `replay_turn` stubbed the recompute never touches the
#: substrate — deterministic and CI-safe on darwin.
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: run_case re-invokes the server inside the macOS "
        "Seatbelt sandbox"
    ),
)


# --- the real-path rig (as test_corpus_trajectory_run.py) -----------------------------


class RecordingRunner:
    """The runner seam, deterministic: returns the configured result and records what
    it was asked to run — the recompute's re-execution convention is observable."""

    def __init__(self, result: CheckResult):
        self._result = result
        self.calls: list[tuple[Check, Path, float]] = []

    def run(self, check: Check, *, workspace, timeout):
        self.calls.append((check, workspace, timeout))
        return self._result


class SourceKeyedRunner:
    """The runner seam keyed by the check's stored source — one seam, per-case results.

    The runner is a module-level binding, so a single `run_corpus` sees ONE runner; a
    mixed corpus whose cases must recompute differently needs the decision keyed on
    the stored check (the only per-case input the runner receives), never on hidden
    state.
    """

    def __init__(self, by_source: dict[str, CheckResult]):
        self._by_source = by_source
        self.calls: list[tuple[Check, Path, float]] = []

    def run(self, check: Check, *, workspace, timeout):
        self.calls.append((check, workspace, timeout))
        return self._by_source[check.source]


def _stub_replay(monkeypatch, tmp_path=None, workspace: str | None = None) -> list[dict]:
    """Stub the final-state replay, recording what the evaluator asked it to do.

    The workspace must be a REAL directory: `evaluate_claim` scans the materialized
    final state (the author sees its file list), so a fabricated path would crash the
    scan, not short-circuit it.
    """
    if workspace is None:
        ws = (tmp_path or Path("/tmp")) / "stub-workspace"
        ws.mkdir(parents=True, exist_ok=True)
        workspace = str(ws)
    seen: list[dict] = []

    def fake(records, n, **kwargs):
        seen.append({"n": n, **kwargs})
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
            workspace=workspace,
        )

    monkeypatch.setattr(claims, "replay_turn", fake)
    # The PER-TURN path (`verify_turn` for the turn-shaped cases in a mixed corpus)
    # re-invokes through `turn.replay_turn` — its own binding, stubbed with the same
    # deterministic reply so both paths observe the same replayed outcome.
    monkeypatch.setattr(turn_module, "replay_turn", fake)
    return seen


def _use_runner(monkeypatch, result: CheckResult) -> RecordingRunner:
    runner = RecordingRunner(result)
    monkeypatch.setattr(claims, "runner", runner)
    return runner


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
    trace_dir: Path, tool: str, n_calls: int, arguments: dict | None = None
) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree — exactly as
    `test_corpus_trajectory_run.py` builds them.
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


def _build_claim_case(
    tmp_path: Path,
    *,
    case_name: str,
    declared: dict | None = CLAIM_FAIL,
    recorded_miss: dict | None = None,
    with_claim_record: bool = True,
) -> Path:
    """A self-contained schema-v5 claim case via the REAL `add_case` path.

    `declared` is the INSTANCE-LEVEL claim expected written into the case — deliberately
    caller-controlled, so a test can bank a case that DECLARES any claim shape, exactly
    as a mis-banked case would read on disk. `recorded_miss`, when given, is written
    into the stored `case.json` afterwards (the declaration `add_case` itself never
    sets). `with_claim_record=False` stores a trace without the claim record — the
    recompute's `NO_CLAIM_RECORDED` shape. The case holds everything a recompute
    needs: the full trace, the bundled pre-states, the stored invariants and server
    command.
    """
    trace_dir = tmp_path / "traces" / case_name
    trace_path = _write_gated_trace(
        trace_dir, "edit_file", 2, {"path": "/repo/src/a.py"}
    )
    if with_claim_record:
        append_claim_record(trace_path, text="all tests pass")
    records = _records_of(trace_path)

    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
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
    if recorded_miss is not None:
        case = dataclasses.replace(load_case(case_dir), recorded_miss=recorded_miss)
        write_case(case_dir, case)
    return case_dir


def _build_declared_miss_case(tmp_path: Path, *, case_name: str) -> Path:
    """A declared-miss claim case: the per-turn expected records the CLEAN final-turn
    verdict (PASS — the engine's certified-clean shape the v3 declaration exempts), the
    claim dimension records the engine's non-catch (UNVERIFIED — the A3 axis never
    emits PASS), and `recorded_miss` declares the drift real."""
    case_dir = _build_claim_case(
        tmp_path, case_name=case_name, declared=CLAIM_MISS
    )
    case = dataclasses.replace(
        load_case(case_dir),
        recorded_miss={"note": "the drift was real: the suite was never executed"},
        expected={
            "reduced_status": "PASS",
            "sub_verdicts": [
                {"axis": "A2", "kind": "replay", "status": "PASS"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
    )
    write_case(case_dir, case)
    return case_dir


def _build_per_turn_case(tmp_path: Path, *, case_name: str, expected_status: str) -> Path:
    """A TURN-SHAPED case (no `trajectory`, no `claim`) via the real `add_case` path."""
    trace_dir = tmp_path / "traces" / case_name
    trace_path = _write_gated_trace(trace_dir, "edit_file", 2, {"path": "/repo/src/a.py"})
    verdict = (
        _clean_turn("edit_file")
        if expected_status == "PASS"
        else TurnVerdict(
            turn_index=1,
            tool_name="edit_file",
            status=Status.FAIL,
            sub_verdicts=[Verdict("A1", "invariant", Status.FAIL, None, None, "fail")],
        )
    )
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
        source_trace_id=f"{case_name}-trace",
        captured_at=CAPTURED_AT,
    )


# --- (1) an ingested claim-FAIL case re-runs to MATCH ---------------------------------


def test_claim_fail_case_recomputes_to_match_through_the_stored_check(
    tmp_path, monkeypatch
) -> None:
    """Acceptance (b): the banked claim case re-runs through `evaluate_claim` — the
    stored trace + manifests re-verified, the STORED check re-issued and re-executed —
    and reproduces the same FAIL: MATCH, no divergence. The runner is asked to run
    exactly the stored check source (`sh -c <source>`, the re-execution convention)."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    runner = _use_runner(monkeypatch, CheckResult(1, "boom", None))
    case_dir = _build_claim_case(tmp_path, case_name="match")

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []

    assert len(runner.calls) == 1, runner.calls
    check, _workspace, _timeout = runner.calls[0]
    assert check.source == CHECK_SOURCE
    assert check.argv == ("sh", "-c", CHECK_SOURCE)


# --- (2) a divergence reads REGRESSION, named on the claim dimension ------------------


def test_claim_silence_recompute_is_regression_named_on_the_dimension(
    tmp_path, monkeypatch
) -> None:
    """A stored claim FAIL whose recompute is SILENCE (the check now exits 0) reads
    REGRESSION — named on the claim dimension (`claim status`, FAIL -> silence), never
    hidden in the per-turn `(axis, kind)` sub-verdict keying. Silence is not a pass and
    not agreement: the drift the case banked is no longer caught."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(0, "clean", None))
    case_dir = _build_claim_case(tmp_path, case_name="silenced")

    result = run_case(case_dir)
    assert result.outcome == REGRESSION, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("claim", "status", "FAIL", None)]


# --- (3) a claim record that vanished is a REGRESSION, never a MATCH ------------------


def test_claim_case_whose_trace_lacks_the_claim_record_regresses(
    tmp_path, monkeypatch
) -> None:
    """Fail-closed (§4 edge case): a claim case whose stored trace lost its claim record
    recomputes the `NO_CLAIM_RECORDED` abstention — a divergence vs the declared FAIL
    is a REGRESSION, honest and named: the case's own claim vanished, which IS a
    regression. Never a MATCH (MATCH would certify the vanished claim as agreement).
    The abstention fires before the author/runner, so the runner seam is never
    reached."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    runner = _use_runner(monkeypatch, CheckResult(1, "boom", None))
    case_dir = _build_claim_case(
        tmp_path, case_name="no-claim-record", with_claim_record=False
    )

    result = run_case(case_dir)
    assert result.outcome == REGRESSION, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("claim", "status", "FAIL", "UNVERIFIED")]
    assert runner.calls == [], "NO_CLAIM_RECORDED fires before any re-execution"


# --- (4) disable_claim_axis SKIPs with a named cause, never REGRESSES ----------------


def test_disable_claim_axis_skips_with_named_cause_never_regresses(
    tmp_path, monkeypatch
) -> None:
    """The refutation's load-bearing rule: under `disable_claim_axis=True` a claim case
    SKIPs with the named cause `CLAIM_AXIS_DISABLED` — decided BEFORE any replay or
    re-execution (the stub seams are never reached), so it can never be a REGRESSION.
    A SKIP is "this box did not evaluate the case on this axis", never a pass and
    never a regression."""
    seen = _stub_replay(monkeypatch, tmp_path=tmp_path)
    runner = _use_runner(monkeypatch, CheckResult(1, "boom", None))
    case_dir = _build_claim_case(tmp_path, case_name="flag-skip")

    result = run_case(case_dir, disable_claim_axis=True)
    assert result.outcome == SKIP, result
    assert result.skip_reason == CLAIM_AXIS_DISABLED
    assert seen == [], "the flag must short-circuit before any replay"
    assert runner.calls == [], "the flag must short-circuit before any re-execution"


def test_run_corpus_threads_disable_claim_axis_to_claim_cases_only(
    tmp_path, monkeypatch
) -> None:
    """The corpus-level entry point threads the flag too (`corpus run --no-claim-axis`
    calls `run_corpus`): the claim case SKIPs with the named cause while every other
    case classifies exactly as in the axis-on run — the acceptance-5 refutation, at
    the run surface."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(1, "boom", None))
    claim_case_dir = _build_claim_case(tmp_path, case_name="flag-corpus-claim")
    per_turn_dir = _build_per_turn_case(tmp_path, case_name="flag-corpus-turn",
                                        expected_status="PASS")

    with_flag = run_corpus(tmp_path / "corpus", disable_claim_axis=True)
    without_flag = run_corpus(tmp_path / "corpus")

    by_id = {r.case_id: r for r in with_flag.results}
    assert by_id[claim_case_dir.name].outcome == SKIP
    assert by_id[claim_case_dir.name].skip_reason == CLAIM_AXIS_DISABLED
    # The per-turn case is byte-identical across the flag: PASS/FAIL verdicts survive
    # the axis-off run unchanged — the refutation's whole claim.
    axis_off = {r.case_id: r for r in without_flag.results}
    assert axis_off[claim_case_dir.name].outcome == MATCH, axis_off[claim_case_dir.name]
    assert by_id[per_turn_dir.name].outcome == axis_off[per_turn_dir.name].outcome


# --- (5) declared-miss semantics: STILL_MISSED on silence, MISS_CLOSED on FAIL ---------


def test_declared_miss_claim_case_stays_missed_on_silence(tmp_path, monkeypatch) -> None:
    """STILL_MISSED: a declared miss whose recompute is SILENCE (the check still exits
    0) is the known, DECLARED blindness — the drift is still open. Never called
    agreement, never counted as a MATCH, and never closed: silence is not a catch."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(0, "clean", None))
    case_dir = _build_declared_miss_case(tmp_path, case_name="miss-silent")

    result = run_case(case_dir)
    assert result.outcome == STILL_MISSED, (result.outcome, result.divergences)
    assert result.divergences == []


def test_declared_miss_claim_case_closes_when_the_check_fails_again(
    tmp_path, monkeypatch
) -> None:
    """MISS_CLOSED: the ONE exempted claim-dimension transition — a sharpened check
    now FAILs the banked drift. The divergence list names the very transition that
    closed the miss (claim status, UNVERIFIED -> FAIL), and a closed miss never breaks
    the build. There is no PASS close: A3 never emits PASS, so no branch exists."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(3, "boom", None))
    case_dir = _build_declared_miss_case(tmp_path, case_name="miss-closes")

    result = run_case(case_dir)
    assert result.outcome == MISS_CLOSED, (result.outcome, result.divergences)
    assert result.divergences == [Divergence("claim", "status", "UNVERIFIED", "FAIL")]


# --- (6) a mixed corpus discriminates the claim and per-turn shapes -------------------


def test_mixed_corpus_discriminates_claim_and_per_turn_shapes(
    tmp_path, monkeypatch
) -> None:
    """One corpus, both case shapes: the claim cases classify on the claim dimension
    (MATCH / REGRESSION on `claim status` — keyed by the stored check, since the
    runner seam is one binding), while the per-turn cases classify exactly as before.
    A claim case never diverges on the per-turn dimensions, and a per-turn case never
    diverges on the claim dimension."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(
        claims,
        "runner",
        SourceKeyedRunner(
            {
                "pytest -q": CheckResult(1, "boom", None),          # claim MATCH
                "python3 suite.py": CheckResult(0, "clean", None),  # claim REGRESSION
            }
        ),
    )

    claim_match = _build_claim_case(tmp_path, case_name="mix-claim-match")
    claim_reg = _build_claim_case(tmp_path, case_name="mix-claim-reg", declared={
        "status": "FAIL",
        "cause": None,
        "check": {"source": "python3 suite.py", "exit_code": 1},
    })
    turn_match = _build_per_turn_case(tmp_path, case_name="mix-turn-match",
                                      expected_status="PASS")
    turn_reg = _build_per_turn_case(tmp_path, case_name="mix-turn-reg",
                                    expected_status="FAIL")

    run = run_corpus(tmp_path / "corpus")
    assert len(run.results) == 4, [(r.case_id, r.outcome) for r in run.results]
    by_id = {r.case_id: r for r in run.results}

    assert by_id[claim_match.name].outcome == MATCH, by_id[claim_match.name]
    assert by_id[claim_match.name].divergences == []

    assert by_id[claim_reg.name].outcome == REGRESSION, by_id[claim_reg.name]
    assert by_id[claim_reg.name].divergences == [
        Divergence("claim", "status", "FAIL", None)
    ]

    assert by_id[turn_match.name].outcome == MATCH, by_id[turn_match.name]
    assert by_id[turn_reg.name].outcome == REGRESSION, by_id[turn_reg.name]
    kinds = {d.kind for d in by_id[turn_reg.name].divergences}
    assert {"reduced_status", "invariant"} <= kinds, kinds
    assert not any(d.axis == "claim" for d in by_id[turn_reg.name].divergences), (
        "a per-turn case must never diverge on the claim dimension"
    )
    assert run.matches == 2, run.matches
    assert run.regressions == 2, run.regressions


# --- (7) the E2E roundtrip: the real liar case recomputes to MATCH --------------------


def test_liar_capture_case_recomputes_to_match_with_real_machinery(
    tmp_path,
) -> None:
    """The Phase-3 banking proof's recompute half, on the REAL liar fixture: the banked
    claim case re-materializes its final state from its OWN bundled pre-state (real
    replay of the `write_file` turn, fast), re-executes the stored check through the
    real contained runner, and observes the same FAIL — MATCH, the regression-suite
    property held on the claim dimension with no stubs in the path."""
    from fixtures.claim_liar_capture import LIAR_CHECK, capture_liar

    liar = capture_liar(tmp_path)
    read = read_trace(liar.trace_path)
    case_records = [
        *read.records,
        *(skip.record for skip in read.skips if skip.kind == "claim" and skip.record is not None),
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
                        message="python3 run_tests.py · exit 1")
            ],
        ),
        manifest_dir=liar.manifest_dir,
        server_command=liar.server_command,
        invariants=[],
        replays=3,
        timeout=60.0,
        source_trace_id=liar.trace_path.stem,
        captured_at=CAPTURED_AT,
        claim={
            "status": "FAIL",
            "cause": None,
            "check": {"source": LIAR_CHECK.source, "exit_code": 1},
        },
    )

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)
    assert result.divergences == []