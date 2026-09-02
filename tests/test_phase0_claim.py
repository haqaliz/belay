"""A3 surfaces Phase 3 (RED): the claim verdict reaches disposition, ledger, report.

The evaluator and the corpus banking shipped in earlier aspects; this module is the
PHASE-0 wiring, mirroring `test_phase0_trajectory.py` on the claim axis:

1. `_verify_one_trace` evaluates A3 at trace close, beside the trajectory rule, gated
   by `disable_claim_axis` and by the presence of an author (the axis is ABSENT when
   either is off — absent, never UNVERIFIED, never PASS);
2. an A3 FAIL flips the instance to `VERIFIED_FLAGGED` (same bucket as a trajectory
   FAIL) and banks a `{trace}-claim` intent-drift case through the real `add_case`
   with `claims.claim_case`'s payload — carrying the EXACT check the verdict was
   decided by;
3. an A3 UNVERIFIED abstention never flags, and a check that exits 0 (D3 silence)
   records no verdict at all;
4. the ledger serializes the claim summary additively (absent-never-zero — old
   ledgers re-render byte-identically) and the report renders the claim section with
   the trajectory section's discipline (FAIL names the check + exit code, UNVERIFIED
   names its cause, unrecorded says so in words).

Written FIRST, before the runner/ledger/report wiring exists (strict TDD). The
synthetic-rig tests stub the replay and the check runner (deterministic — no sandbox
involved); the liar-capture test drives the REAL machinery end to end and is
darwin-gated like the fixture that builds it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.corpus.case import load_case
from belay.corpus.metrics import Metrics
from belay.phase0.ledger import (
    Disposition,
    InstanceRecord,
    RunLedger,
    _REQUIRED_INSTANCE_FIELDS,
    from_json,
    to_json,
)
from belay.phase0.report import render_report
from belay.phase0.runner import run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import claims
from belay.verify import turn as turn_module
from belay.verify.claims import Check, CheckResult

CAPTURED_AT = "2026-09-02T00:00:00+00:00"

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)

CHECK = Check(source="pytest -q", argv=("pytest", "-q"))


class FixedAuthor:
    """The author seam, deterministic: hand back exactly the configured check."""

    def __init__(self, check: Check):
        self._check = check

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return self._check


class NoCheckAuthor:
    """The author seam abstaining: returns None -> NO_CHECK_AUTHOR (UNVERIFIED)."""

    def author_check(self, claim_text, *, classification, turns, final_state_files):
        return None


class FixedRunner:
    """The check-runner seam, deterministic: the configured exit code."""

    def __init__(self, exit_code):
        self._exit_code = exit_code
        self.calls: list[tuple] = []

    def run(self, check: Check, *, workspace, timeout):
        self.calls.append((check, workspace, timeout))
        return CheckResult(self._exit_code, "output", "stderr")


# --- the real-path rig (as test_corpus_claim_run.py) -----------------------------------


def _stub_replay(monkeypatch, tmp_path=None, workspace: str | None = None) -> None:
    """Stub the replay seams the per-turn verifier and the claim evaluator use.

    The workspace must be a REAL directory: `evaluate_claim` scans the materialized
    final state (the author sees its file list), so a fabricated path would crash the
    scan, not short-circuit it.
    """
    if workspace is None:
        ws = (tmp_path or Path("/tmp")) / "stub-workspace"
        ws.mkdir(parents=True, exist_ok=True)
        workspace = str(ws)

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
            workspace=workspace,
        )

    monkeypatch.setattr(claims, "replay_turn", fake)
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


def _reply_frame(msg_id: int, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _write_gated_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """A real trace with per-turn `state_handle`s, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree — the
    `test_corpus_claim_run.py` rig, so the banked case is composed through the REAL
    `add_case` path.
    """
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

    manifest_dir = trace_path.parent / (trace_path.stem + ".manifests")
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


def _make_final_handle_absent(trace_path: Path) -> None:
    """Flip the FINAL `tools/call` request's `state_handle` status to `absent`, in place."""
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


def _batch(tmp_path: Path, trace_path: Path, **kwargs) -> RunLedger:
    """`run_batch` over the trace's directory with the claim seams stubbed."""
    kwargs.setdefault("server_command", ["unused"])
    kwargs.setdefault("invariants", [])
    kwargs.setdefault("ingest", True)
    return run_batch(
        trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        captured_at=CAPTURED_AT,
        **kwargs,
    )


# --- (1) `_verify_one_trace` evaluates A3 at trace close, flag-gated -------------------


def test_claim_fail_flags_the_instance_and_banks_the_claim_case(
    tmp_path, monkeypatch
) -> None:
    """An A3 FAIL through the REAL path: `run_batch` with a configured author runs the
    claim through `evaluate_claim` (stubbed replay + runner — deterministic), the
    instance reads VERIFIED_FLAGGED, and the `{trace}-claim` intent-drift case is
    banked through the real `add_case` carrying `claim_case`'s payload with the exact
    check source and the observed exit code."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    runner = FixedRunner(1)
    monkeypatch.setattr(claims, "runner", runner)
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(tmp_path, trace_path, claim_author=FixedAuthor(CHECK))

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": "pytest -q", "exit_code": 1},
    }
    assert inst.claim_addable is True
    assert inst.claim_unaddable is None
    assert ledger.violating_instances() == 1
    assert ledger.violation_denominator() == 1

    case_dir = tmp_path / "corpus" / f"{trace_path.stem}-claim"
    assert case_dir.is_dir(), "the A3 FAIL must bank its intent-drift case"
    case = load_case(case_dir)
    assert case.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": "pytest -q", "exit_code": 1},
    }
    assert case.trajectory is None
    assert case.target_turn_index == 1  # the FINAL turn

    assert len(runner.calls) == 1, runner.calls
    check, _workspace, _timeout = runner.calls[0]
    assert check.source == "pytest -q", check


def test_disable_claim_axis_skips_a3_evaluation_entirely(tmp_path, monkeypatch) -> None:
    """`disable_claim_axis=True` + an author configured: the axis is OFF — the claim
    is never evaluated (the runner seam is never reached), no claim summary is
    recorded, nothing flags, nothing banks. Absent, never UNVERIFIED, never PASS."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    runner = FixedRunner(1)
    monkeypatch.setattr(claims, "runner", runner)
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(
        tmp_path, trace_path,
        claim_author=FixedAuthor(CHECK),
        disable_claim_axis=True,
    )

    inst = ledger.instances[0]
    assert inst.claim is None, inst.claim
    assert inst.disposition is Disposition.VERIFIED_CLEAN, inst.disposition
    assert runner.calls == [], "the flag must short-circuit before any re-execution"
    corpus = tmp_path / "corpus"
    assert not corpus.exists() or list(corpus.iterdir()) == []


def test_absent_author_never_evaluates_a3(tmp_path, monkeypatch) -> None:
    """No author configured: the axis is ABSENT — the claim is not evaluated at all,
    the ledger records no claim summary, and the disposition is decided by the turns
    alone. This is the dark-by-default contract on the batch surface."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(tmp_path, trace_path, claim_author=None)

    inst = ledger.instances[0]
    assert inst.claim is None
    assert inst.disposition is Disposition.VERIFIED_CLEAN


# --- (2) A3 UNVERIFIED never flags; D3 silence records nothing -------------------------


def test_claim_unverified_never_flags_the_instance(tmp_path, monkeypatch) -> None:
    """An author that abstains (NO_CHECK_AUTHOR) records an UNVERIFIED claim summary
    and stays VERIFIED_CLEAN — an abstention is never a violation — and nothing is
    banked."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(claims, "runner", FixedRunner(1))
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(tmp_path, trace_path, claim_author=NoCheckAuthor())

    inst = ledger.instances[0]
    assert inst.claim == {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }
    assert inst.disposition is Disposition.VERIFIED_CLEAN, inst.disposition
    assert inst.claim_addable is False
    assert ledger.violating_instances() == 0
    corpus = tmp_path / "corpus"
    assert not corpus.exists() or list(corpus.iterdir()) == []


def test_claim_silence_records_no_verdict(tmp_path, monkeypatch) -> None:
    """The check exits 0: D3 silence — the evaluator returns None, the ledger records
    NO claim summary (absent-never-zero), and nothing flags. Never a fabricated clean
    and never a PASS."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(claims, "runner", FixedRunner(0))
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")

    ledger = _batch(tmp_path, trace_path, claim_author=FixedAuthor(CHECK))

    inst = ledger.instances[0]
    assert inst.claim is None, inst.claim
    assert inst.disposition is Disposition.VERIFIED_CLEAN


# --- (3) an unbankable A3 FAIL is a bucketed fact, never an error ----------------------


def test_claim_fail_with_unbankable_prestate_buckets_claim_unaddable(
    tmp_path, monkeypatch
) -> None:
    """The final turn's pre-state is unrestorable: the claim FAILs (the instance is
    still VERIFIED_FLAGGED and still counts in the numerator — the violation is
    unaffected), the case cannot compose, and the failure is bucketed into
    `claim_unaddable` — never an exception that errors the instance and shrinks the
    denominator."""
    _stub_replay(monkeypatch, tmp_path=tmp_path)
    monkeypatch.setattr(claims, "runner", FixedRunner(1))
    trace_path = _write_gated_trace(tmp_path / "traces", "edit_file", 2)
    append_claim_record(trace_path, text="all tests pass")
    _make_final_handle_absent(trace_path)

    ledger = _batch(tmp_path, trace_path, claim_author=FixedAuthor(CHECK))

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED, inst.disposition
    assert inst.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": "pytest -q", "exit_code": 1},
    }
    assert inst.claim_addable is False
    assert inst.claim_unaddable is not None
    assert "pre-state" in inst.claim_unaddable["cause"], inst.claim_unaddable
    assert ledger.violating_instances() == 1


# --- (4) the ledger: additive serialization, absent-never-zero -------------------------


def _instance(trace_id: str, disposition: Disposition, **kwargs) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=kwargs.pop("turn_status_counts", {}),
        flagged_turns=kwargs.pop("flagged_turns", []),
        flagged_addable=kwargs.pop("flagged_addable", []),
        flagged_unaddable=kwargs.pop("flagged_unaddable", []),
        unverified_causes=kwargs.pop("unverified_causes", {}),
        error=kwargs.pop("error", None),
        **kwargs,
    )


def test_ledger_round_trips_the_claim_field() -> None:
    """A recorded claim summary survives `to_json` / `from_json` exactly — status,
    cause, check source and exit code all preserved."""
    flagged = _instance(
        "trace-flagged",
        Disposition.VERIFIED_FLAGGED,
        claim={"status": "FAIL", "cause": None,
               "check": {"source": "pytest -q", "exit_code": 1}},
    )
    abstained = _instance(
        "trace-abstained",
        Disposition.VERIFIED_CLEAN,
        claim={"status": "UNVERIFIED", "cause": "NO_CHECK_AUTHOR",
               "check": {"source": "", "exit_code": None}},
    )
    ledger = RunLedger(instances=[flagged, abstained])

    rebuilt = from_json(to_json(ledger))

    by_id = {inst.trace_id: inst for inst in rebuilt.instances}
    assert by_id["trace-flagged"].claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": "pytest -q", "exit_code": 1},
    }
    assert by_id["trace-abstained"].claim == {
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }


def test_ledger_without_claim_omits_the_key_and_reads_back_absent() -> None:
    """`to_json` never writes `"claim"` when unrecorded — asserted on BYTES — and an
    old-ledger-shaped payload (no key) loads back with `claim is None`, never a
    fabricated zero or clean verdict."""
    ledger = RunLedger(instances=[_instance("trace-x", Disposition.VERIFIED_CLEAN)])

    rendered = json.dumps(to_json(ledger))
    assert "claim" not in rendered

    old_payload: dict = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "VERIFIED_CLEAN",
                "turn_status_counts": {},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
                # "claim" deliberately omitted, like every ledger before this field
            }
        ]
    }

    rebuilt = from_json(old_payload)

    assert rebuilt.instances[0].claim is None


def test_claim_is_not_a_required_ledger_field() -> None:
    """`claim` is absent from `_REQUIRED_INSTANCE_FIELDS` — an old ledger must load,
    fail-closed here would turn 'predates the field' into a corrupt-ledger error."""
    assert "claim" not in _REQUIRED_INSTANCE_FIELDS


def test_claim_does_not_pollute_turn_status_counts() -> None:
    """The claim verdict is orthogonal to the turn tally — `total_turns()` stays a
    count of turns, and the FAIL rate's denominator is untouched."""
    inst = _instance(
        "trace-x",
        Disposition.VERIFIED_FLAGGED,
        turn_status_counts={"PASS": 2},
        claim={"status": "FAIL", "cause": None,
               "check": {"source": "pytest -q", "exit_code": 1}},
    )
    ledger = RunLedger(instances=[inst])

    assert "claim" not in inst.turn_status_counts
    assert ledger.total_turns() == 2
    assert ledger.fail_turns() == 0


# --- (5) the report: the claim line in the trajectory area ------------------------------


def _metrics() -> Metrics:
    return Metrics(
        tp=0, fp=0, fn=0, tn=0, precision=None, recall=None, coverage=None,
        unverified=0, pending=0, unverifiable=0, total=0,
    )


def test_report_renders_the_claim_line_per_instance_with_named_causes() -> None:
    """One ledger holding every claim state: FAIL names the check source and the real
    exit code plus the disposition it produced, UNVERIFIED names its cause and says
    never PASS, and an instance without a verdict renders the unrecorded form — never
    a fabricated clean. The aggregate line counts each state (there is no PASS line:
    A3 never emits PASS)."""
    flagged = _instance(
        "trace-flagged",
        Disposition.VERIFIED_FLAGGED,
        claim={"status": "FAIL", "cause": None,
               "check": {"source": "pytest -q", "exit_code": 1}},
    )
    abstained = _instance(
        "trace-abstained",
        Disposition.VERIFIED_CLEAN,
        claim={"status": "UNVERIFIED", "cause": "NO_CHECK_AUTHOR",
               "check": {"source": "", "exit_code": None}},
    )
    unrecorded = _instance("trace-unrecorded", Disposition.VERIFIED_CLEAN)
    ledger = RunLedger(instances=[flagged, abstained, unrecorded])

    report = render_report(ledger, _metrics())

    assert "claim (A3" in report
    assert "trace-flagged" in report
    assert "claim FAIL" in report
    assert "'pytest -q'" in report
    assert "VERIFIED_FLAGGED" in report
    assert "trace-abstained" in report
    assert "claim UNVERIFIED [NO_CHECK_AUTHOR]" in report
    assert "never PASS" in report
    assert "trace-unrecorded" in report
    assert "claim unrecorded" in report
    assert "NOT a claim that the intent drift was clean" in report
    assert "aggregate: 1 FAIL / 1 UNVERIFIED" in report
    assert "NO_CHECK_AUTHOR: 1" in report


def test_report_claim_section_survives_instrument_suspect() -> None:
    """The claim section is a limit statement, not a rate: it renders even when the
    violation-rate headline is suppressed — exactly the trajectory section's
    discipline."""
    ledger = RunLedger(
        instances=[
            _instance(
                "trace-a",
                Disposition.NO_VERIFIABLE_TURNS,
                claim={"status": "UNVERIFIED", "cause": "NO_CLAIM_RECORDED",
                       "check": {"source": "", "exit_code": None}},
            ),
            _instance("trace-b", Disposition.NO_VERIFIABLE_TURNS),
        ]
    )

    report = render_report(ledger, _metrics())

    assert "INSTRUMENT SUSPECT" in report
    assert "claim" in report
    assert "trace-a" in report
    assert "trace-b" in report


# --- (6) the E2E: the REAL liar capture flags and banks through the REAL machinery -----


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "replay-reinvokes-seatbelt: the liar capture is gated (Seatbelt snapshot at "
        "capture time) and its replay re-invokes inside the macOS Seatbelt sandbox; "
        "the Linux side is measured in tests/test_docker_inimage.py"
    ),
)
def test_liar_capture_flags_and_banks_through_the_real_machinery(tmp_path) -> None:
    """The Phase-4 proof on the REAL liar fixture, with NOTHING stubbed: `run_batch`
    verifies the gated capture (real replay of the `write_file` turn), the A3 check
    runs in the MATERIALIZED final state through the real contained runner and exits
    1, the instance reads VERIFIED_FLAGGED, and the `{trace}-claim` case banks with
    the real add_case — a `corpus run` later recomputes it to MATCH (pinned in
    `tests/test_corpus_claim_run.py`)."""
    from fixtures.claim_liar_capture import LIAR_CHECK, capture_liar

    liar = capture_liar(tmp_path)
    ledger = run_batch(
        liar.trace_path.parent,
        corpus_dir=tmp_path / "corpus",
        server_command=liar.server_command,
        invariants=[],
        captured_at=CAPTURED_AT,
        claim_author=FixedAuthor(LIAR_CHECK),
        ingest=True,
        # The liar fixture persists manifests beside the SNAPSHOT dir
        # (`<name>.snapshots.manifests`), not beside the trace file stem — the
        # phase0-input convention `default_manifest_dir_for` computes. Resolve them
        # explicitly, as `corpus run`'s instance path does for a self-contained case.
        manifest_dir_for=lambda _trace_path: liar.manifest_dir,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED, inst.disposition
    assert inst.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": LIAR_CHECK.source, "exit_code": 1},
    }
    assert inst.claim_addable is True
    assert ledger.violating_instances() == 1
    assert ledger.violation_denominator() == 1

    case_dir = tmp_path / "corpus" / f"{liar.trace_path.stem}-claim"
    assert case_dir.is_dir()
    case = load_case(case_dir)
    assert case.claim == {
        "status": "FAIL",
        "cause": None,
        "check": {"source": LIAR_CHECK.source, "exit_code": 1},
    }