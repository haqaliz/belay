"""THE REFUTATION: `--no-claim-axis` leaves every PASS and every FAIL verdict identical.

this test is the company's positioning encoded as CI — it must never be weakened.

This is the answer to the question every reviewer asks of A3: *"isn't this just an LLM
judge with extra steps?"* The refutation is the one-command proof that it is not — A3
is a **downgrade-only** axis, gated behind `--no-claim-axis`, and turning it OFF leaves
the deterministic spine's every PASS and every FAIL byte-identical. If A3 were a judge
bolted on top, disabling it would change nothing either — so what does this test
actually catch? It catches the axis LEAKING into the verdict: a surface that renders an
A3 verdict as a turn status, an instance disposition that flips because A3 abstained, a
claim case that REGRESSES under the flag, an A3 sub-verdict folded into a reduced
status. Those are the shapes of A3 becoming a judge-with-extra-steps, and each one
breaks the byte-identity this test demands.

Two surfaces, both through the REAL CLI:

1. **The corpus** (`belay corpus run`): one corpus holding all three case shapes — a
   per-turn PASS case, a trajectory FAIL case, and a banked A3 claim FAIL case. Run
   with and without `--no-claim-axis`: every non-claim case's outcome is identical
   (the recomputed verdicts reach the same stored PASS/FAIL), and the claim case SKIPs
   with `CLAIM_AXIS_DISABLED` under the flag — **never** a REGRESSION and never a
   MATCH (a case not evaluated is not agreed).
2. **`belay verify`** on the committed demo capture: the same trace verified twice —
   once with the claim axis live (a deterministic fake author; the check runs in the
   materialized final state and exits 0, D3 silence) and once with `--no-claim-axis`.
   Every PASS and every FAIL is identical; the two JSON documents are equal, byte for
   byte.

The refutation runs with a FAKE author — deterministic, no model in CI (acceptance 5).
The corpus half needs no sandbox (the replay and the check-runner seams are stubbed);
the demo half is a real re-execution and is darwin-gated like every capture test (the
Linux side is measured in-container by the docker job).

**Do not weaken this module.** The tests here are the plan's capstone
(`docs/planning/claim-re-derivation-a3/surfaces/plan_20260902.md`, Phase 4). If a
surface change breaks the byte-identity, the surface change is wrong — not this test.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.corpus.add import add_case
from belay.corpus.run import (
    CLAIM_AXIS_DISABLED,
    MATCH,
    REGRESSION,
    SKIP,
    run_corpus,
)
from belay.phase0.runner import default_manifest_dir_for
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import claims
from belay.verify import turn as turn_module
from belay.verify.claims import Check, CheckResult
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)

#: The stored check source the banked claim case carries; the recompute re-executes it
#: via `sh -c <source>` and the stubbed runner answers exit 1 -> the stored FAIL
#: reproduces (MATCH) with the axis on, and SKIPs under the flag.
CHECK_SOURCE = "pytest -q"

#: The banked claim expected: an A3 FAIL with the check that ran (exit 1).
CLAIM_FAIL = {
    "status": "FAIL",
    "cause": None,
    "check": {"source": CHECK_SOURCE, "exit_code": 1},
}

REQUIRES_CAPTURE = pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the demo capture's re-execution runs inside the "
        "macOS Seatbelt sandbox; the Linux side is measured in tests/test_docker_inimage.py"
    ),
)


class FixedAuthor:
    """The author seam, deterministic: hand back exactly the configured check."""

    def __init__(self, check: Check):
        self._check = check

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return self._check


# --- the deterministic rig (as test_corpus_claim_run.py) -------------------------------


def _stub_replay(monkeypatch, tmp_path=None) -> None:
    """Stub the replay seams (per-turn verifier + claim final-state materialization).

    The workspace must be a REAL directory: `evaluate_claim` scans the materialized
    final state, so a fabricated path would crash the scan, not short-circuit it.
    """
    ws = (tmp_path or Path("/tmp")) / "stub-workspace"
    ws.mkdir(parents=True, exist_ok=True)

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


def _use_runner(monkeypatch, result: CheckResult) -> None:
    monkeypatch.setattr(claims, "runner", _FixedRunner(result))


class _FixedRunner:
    def __init__(self, result: CheckResult):
        self._result = result

    def run(self, check: Check, *, workspace, timeout):
        return self._result


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


def _write_gated_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in _tool_list_frames(tool, extra_tools=("run_process",)):
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
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
    """A final-turn verdict the stub replay reproduces exactly: both A2 checks PASS."""
    return TurnVerdict(
        turn_index=1,
        tool_name=tool,
        status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "replay", Status.PASS, None, None, "replay pass"),
            Verdict("A2", "effect", Status.PASS, None, None, "effect pass"),
        ],
    )


def _build_corpus(tmp_path: Path) -> dict[str, str]:
    """One corpus, all three case shapes — per-turn, trajectory, banked claim.

    Each case is composed through the REAL `add_case` (self-contained: bundled
    pre-states, manifests, invariants), so `corpus run` re-verifies them against the
    stubbed seams exactly as it would against real replay.
    """
    corpus_dir = tmp_path / "corpus"
    names: dict[str, str] = {}

    per_turn_trace = _write_gated_trace(tmp_path / "traces" / "turn", "edit_file", 2)
    per_turn = add_case(
        corpus_dir,
        records=_records_of(per_turn_trace),
        target_turn_index=1,
        verdict=_clean_turn("edit_file"),
        manifest_dir=default_manifest_dir_for(per_turn_trace),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id="refute-turn",
        captured_at=CAPTURED_AT,
    )
    names["per_turn"] = per_turn.name

    trajectory_trace = _write_gated_trace(tmp_path / "traces" / "trajectory", "edit_file", 2)
    append_claim_record(trajectory_trace, text="all tests pass")
    trajectory = add_case(
        corpus_dir,
        records=_records_of(trajectory_trace),
        target_turn_index=1,
        verdict=TurnVerdict(
            turn_index=1,
            tool_name="edit_file",
            status=Status.FAIL,
            sub_verdicts=[
                Verdict(
                    "A1", "invariant", Status.FAIL, None, None,
                    "no run_process command before the claim",
                )
            ],
        ),
        manifest_dir=default_manifest_dir_for(trajectory_trace),
        server_command=["unused"],
        invariants=[TRAJECTORY],
        replays=3,
        timeout=20.0,
        source_trace_id="refute-trajectory",
        captured_at=CAPTURED_AT,
        trajectory={"status": "FAIL", "cause": None},
    )
    names["trajectory"] = trajectory.name

    claim_trace = _write_gated_trace(tmp_path / "traces" / "claim", "edit_file", 2)
    append_claim_record(claim_trace, text="all tests pass")
    claim = add_case(
        corpus_dir,
        records=_records_of(claim_trace),
        target_turn_index=1,
        verdict=TurnVerdict(
            turn_index=1,
            tool_name="edit_file",
            status=Status.FAIL,
            sub_verdicts=[
                Verdict("A3", "claim", Status.FAIL, observed=1, expected="exit 0",
                        message="pytest -q · exit 1")
            ],
        ),
        manifest_dir=default_manifest_dir_for(claim_trace),
        server_command=["unused"],
        invariants=[],
        replays=3,
        timeout=20.0,
        source_trace_id="refute-claim",
        captured_at=CAPTURED_AT,
        claim=CLAIM_FAIL,
    )
    names["claim"] = claim.name

    return names


# --- the corpus half: identical PASS/FAIL with and without the flag --------------------


def test_corpus_verdicts_are_identical_with_and_without_the_claim_axis(
    tmp_path, monkeypatch
) -> None:
    """THE REFUTATION, corpus surface: one corpus holding per-turn, trajectory and
    banked-claim cases, run with and without `--no-claim-axis`.

    Every non-claim case's outcome is BYTE-IDENTICAL across the two runs (each
    recompute reaches the same stored PASS/FAIL verdict — MATCH), and the claim case
    SKIPs with `CLAIM_AXIS_DISABLED` under the flag — never a REGRESSION (the
    refutation's load-bearing rule) and never a MATCH (a case not evaluated is not
    agreed). No case REGRESSES in either run.
    """
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(1, "boom", None))
    names = _build_corpus(tmp_path)

    axis_on = run_corpus(tmp_path / "corpus")
    axis_off = run_corpus(tmp_path / "corpus", disable_claim_axis=True)

    by_id = {r.case_id: r for r in axis_on.results}
    by_id_off = {r.case_id: r for r in axis_off.results}
    assert set(by_id) == set(by_id_off) == set(names.values()), (by_id, by_id_off)

    # The claim case: MATCH with the axis on (the stored FAIL reproduces), SKIP with
    # the named cause under the flag — NEVER a REGRESSION.
    assert by_id[names["claim"]].outcome == MATCH, by_id[names["claim"]]
    assert by_id_off[names["claim"]].outcome == SKIP, by_id_off[names["claim"]]
    assert by_id_off[names["claim"]].skip_reason == CLAIM_AXIS_DISABLED

    # Every other verdict: identical PASS/FAIL across the flag.
    for name in ("per_turn", "trajectory"):
        assert by_id[names[name]].outcome == MATCH, by_id[names[name]]
        assert by_id_off[names[name]].outcome == by_id[names[name]].outcome, name

    # The whole point: nothing REGRESSES in either run.
    assert axis_on.regressions == 0, [(r.case_id, r.outcome) for r in axis_on.results]
    assert axis_off.regressions == 0, [(r.case_id, r.outcome) for r in axis_off.results]


def test_corpus_run_cli_threads_the_flag_and_renders_the_skip(
    tmp_path, monkeypatch, capsys
) -> None:
    """The CLI surface: `belay corpus run --no-claim-axis` accepts the flag, exits 0
    (a SKIP is not a regression), and RENDERS the named cause — a reader can see the
    axis was off, not guess it."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    _use_runner(monkeypatch, CheckResult(1, "boom", None))
    names = _build_corpus(tmp_path)

    rc = cli.main(["corpus", "run", str(tmp_path / "corpus"), "--no-claim-axis"])
    out = capsys.readouterr().out

    assert rc == 0, out
    assert names["claim"] in out, out
    assert CLAIM_AXIS_DISABLED in out, out
    assert "REGRESSION            0" in out, out


# --- the verify half: the committed demo capture, twice --------------------------------


def _demo_verify(extra_flags: list[str], calls: list) -> tuple[int, dict, str]:
    """`belay verify --json` on the committed demo capture through the REAL CLI.

    `extra_flags` are placed BEFORE `--server` (the server argument is
    `argparse.REMAINDER`). `calls` receives one entry per A3 evaluation this run
    performed (the anti-vacuity spy — the JSON document itself cannot say whether A3
    ran, because D3 silence omits the claim record). Returns (exit code, parsed
    document, stdout text).
    """
    from test_demo_capture import (
        SERVER,
        _capture_trace,
        _manifest_dir,
        _recorded_source_root,
    )

    argv = [
        "verify",
        str(_capture_trace()),
        "--manifest-dir",
        str(_manifest_dir()),
        "--timeout",
        "300",
        "--json",
        *extra_flags,
        "--server",
        sys.executable,
        str(SERVER),
        _recorded_source_root(),
    ]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    text = buf.getvalue()
    return rc, json.loads(text), text


@pytest.fixture(scope="module")
def demo_verify_runs() -> tuple[tuple[int, dict, str, int], tuple[int, dict, str, int]]:
    """The SAME committed demo capture verified twice through the REAL CLI.

    Once with the claim axis LIVE (a deterministic fake author configured via
    `BELAY_CLAIM_AUTHOR` — the suite check runs in the materialized final state and
    exits 0, D3 silence) and once with `--no-claim-axis`. Both runs are real
    re-executions of the ~44s `run_process` turns, so this fixture is the slow half
    of the refutation (budget ~10 min for the module); it is darwin-gated. Each
    element carries the run's A3-evaluation CALL COUNT — the anti-vacuity spy.
    """
    from test_demo_capture import _DEMO_SUITE_CHECK

    evaluate_calls: list[int] = []

    def spying_evaluate_claim(**kwargs):
        evaluate_calls.append(1)
        return _real_evaluate_claim(**kwargs)

    monkeypatch = pytest.MonkeyPatch()
    _real_evaluate_claim = claims.evaluate_claim
    monkeypatch.setattr(claims, "evaluate_claim", spying_evaluate_claim)
    monkeypatch.setattr(
        "belay.verify.author.author_from_env", lambda: FixedAuthor(_DEMO_SUITE_CHECK)
    )
    try:
        with_axis = _demo_verify([], evaluate_calls)
        on_count = len(evaluate_calls)
        evaluate_calls.clear()
        without_axis = _demo_verify(["--no-claim-axis"], evaluate_calls)
        off_count = len(evaluate_calls)
    finally:
        monkeypatch.undo()
    return (*with_axis, on_count), (*without_axis, off_count)


@REQUIRES_CAPTURE
def test_verify_verdicts_are_identical_with_and_without_the_claim_axis(
    demo_verify_runs,
) -> None:
    """THE REFUTATION, verify surface: the demo capture's every PASS and every FAIL
    is identical with the claim axis live and with `--no-claim-axis` — the two JSON
    documents are EQUAL, and the exit codes agree.

    Anti-vacuity: the axis-on run really evaluated A3 (the evaluator was invoked and
    its check exited 0 — D3 silence, never a PASS); the axis-off run never invoked it
    at all. This is not two identical runs that both skipped A3.
    """
    (rc_on, doc_on, _text_on, on_calls), (rc_off, doc_off, _text_off, off_calls) = (
        demo_verify_runs
    )

    assert rc_on == rc_off == 0, (rc_on, rc_off)
    assert doc_on == doc_off, (
        "the claim axis must leave every PASS and every FAIL identical — a surface "
        "that lets A3 leak into the deterministic spine breaks this test"
    )
    assert doc_on["turns"], doc_on
    assert all(turn["status"] == "PASS" for turn in doc_on["turns"]), doc_on["turns"]
    assert doc_on["trajectory"]["status"] == "PASS", doc_on["trajectory"]

    # Anti-vacuity: the axis-on run really evaluated A3 (silence, D3); the axis-off
    # run never reached the evaluator. The JSON cannot show this itself — silence
    # omits the claim record — so the spy is the proof.
    assert on_calls == 1, on_calls
    assert off_calls == 0, off_calls