"""Task 4 — composing the per-turn verdict, and the NOT_VERIFIABLE-never-PASS hole.

C3's `engine.replay_turn` OBSERVES; Task 2 (result-equivalence) and Task 3
(effect-conformance) each render ONE grounded A2 sub-verdict. This composes them: one
replay, both checks on a REPLAYED turn, reduced worst-status-wins, carrying BOTH
sub-verdicts so "why did this turn FAIL?" stays answerable.

The load-bearing test is A6. A turn whose pre-state could not be restored (`unrestorable`)
or was never snapshotted at all (`NOT_VERIFIABLE`) has NO PASS/FAIL — A2 re-invoked
nothing, so it verified nothing — and is therefore UNVERIFIED, kept out of any "passed"
count. A naive "if not FAIL then PASS" composition reports the un-snapshotted turn as
clean; that is the exact false pass this project exists to prevent, and A6 is watched
failing against that naive version before the honest one closes it.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import TOOLS_LIST_REQUEST, TOOLS_LIST_RESPONSE

from belay.replay.determinism import DETERMINISTIC, DeterminismResult
from belay.replay.engine import (
    DIVERGED,
    EQUAL,
    NOT_VERIFIABLE,
    REPLAYED,
    UNVERIFIED,
    TurnReplay,
)
from belay.snapshot.bth1 import FieldDiff
from belay.snapshot.substrate import UnrestorableCause
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

# The canned tools/list: `read_file` is readOnlyHint:true (declared-true), `write_file`
# is declared-false, `mystery` is not-declared. The same fixture Task 3 grounds on.
LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]

# server_command / manifest_dir are never reached: every test stubs replay_turn.
UNUSED = ["unused-server"]


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _mutation(*paths: str) -> list[FieldDiff]:
    """A non-empty BTH-1 delta: replay observed a write at each of `paths`."""
    return [
        FieldDiff(path=p.encode(), field=None, left=None, right=b"content")
        for p in paths
    ]


def _stub_replay(monkeypatch, reply: TurnReplay) -> None:
    """Make `verify_turn`'s single `replay_turn` call return `reply` — no sandbox, no
    network. The composition is what is under test, not re-execution (C3 owns that)."""
    monkeypatch.setattr(turn_module, "replay_turn", lambda *a, **k: reply)


def _run(records, monkeypatch) -> TurnVerdict:
    return verify_turn(records, 0, server_command=UNUSED, manifest_dir="/nonexistent")


# --- 1. A6 THE HOLE: neither an unrestorable nor an un-snapshotted turn is a PASS ----


def test_a6_unrestorable_turn_is_unverified_not_pass(tmp_path, monkeypatch):
    """A turn whose pre-state could not be restored -> UNVERIFIED, NOT PASS, cause carried.

    The engine returns `UNVERIFIED` with the recorded cause; nothing was re-invoked, so
    A2 has no PASS/FAIL for it. Composition must keep it UNVERIFIED. A naive
    "if not FAIL then PASS" implementation returns PASS here — the false pass — and this
    was watched RED against exactly that.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(turn_index=0, status=UNVERIFIED, cause=UnrestorableCause.UNRESTORABLE_FIFO.value),
    )

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    assert verdict.cause == UnrestorableCause.UNRESTORABLE_FIFO.value, verdict
    # No check ran, so the single sub-verdict is the UNVERIFIED one — never a PASS.
    assert [v.status for v in verdict.sub_verdicts] == [Status.UNVERIFIED], verdict


def test_a6_absent_handle_turn_is_unverified_with_a_distinct_cause(tmp_path, monkeypatch):
    """An un-snapshotted turn (`NOT_VERIFIABLE`, absent handle) -> UNVERIFIED, NOT PASS.

    THE HOLE: `NOT_VERIFIABLE` must not fall through to PASS. A2 never snapshotted this
    turn, so it verified nothing about it. Its cause must be DISTINCT from an
    unrestorable turn's — "no snapshot was attempted" is a different fact from "the
    restore failed" — so a later failure corpus never conflates the two.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    absent = TurnReplay(
        turn_index=0,
        status=NOT_VERIFIABLE,
        cause="no snapshot was attempted for this turn; there is no pre-state to restore",
    )
    _stub_replay(monkeypatch, absent)
    absent_verdict = _run(records, monkeypatch)

    assert absent_verdict.status is Status.UNVERIFIED, absent_verdict
    assert absent_verdict.status is not Status.PASS

    # And its cause differs from an unrestorable turn's.
    _stub_replay(
        monkeypatch,
        TurnReplay(turn_index=0, status=UNVERIFIED, cause=UnrestorableCause.UNRESTORABLE_FIFO.value),
    )
    unrestorable_verdict = _run(records, monkeypatch)
    assert absent_verdict.cause != unrestorable_verdict.cause, (
        absent_verdict.cause,
        unrestorable_verdict.cause,
    )


# --- 2. Both sub-verdicts present: result PASS, effect FAIL -> reduced FAIL ----------


def test_both_sub_verdicts_are_carried_result_pass_effect_fail(tmp_path, monkeypatch):
    """A REPLAYED turn: reply reproduced (result PASS) but a readOnlyHint:true tool
    mutated (effect FAIL) -> reduced FAIL, and BOTH sub-verdicts are visible so the
    report can answer which drove the reduction.

    `read_file` is declared-true; the stubbed replay reports EQUAL (reply reproduced)
    AND a filesystem mutation. Result-equivalence is PASS, effect-conformance is FAIL,
    worst-wins -> FAIL.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(3, "contents"),
            replayed_reply=_reply(3, "contents"),
            delta=_mutation("written.txt"),
        ),
    )

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.FAIL, verdict
    assert verdict.cause is None, "a REPLAYED turn's sub-verdicts explain it; no named cause"
    kinds = {v.kind: v for v in verdict.sub_verdicts}
    assert "replay" in kinds and "effect" in kinds, verdict.sub_verdicts
    assert kinds["replay"].status is Status.PASS, "result-equivalence reproduced"
    assert kinds["effect"].status is Status.FAIL, "readOnlyHint:true tool mutated"
    # The FAIL that drove the reduction is inspectable, evidence and all.
    assert "written.txt" in kinds["effect"].message, kinds["effect"].message


# --- 3. Independence: result PASS, effect UNVERIFIED -> reduced UNVERIFIED -----------


def test_result_pass_effect_unverified_reduces_to_unverified(tmp_path, monkeypatch):
    """A REPLAYED turn on an un-annotated tool: result PASS, effect UNVERIFIED (no
    contract to check) -> reduced UNVERIFIED, because UNVERIFIED outranks PASS. Both
    sub-verdicts are still carried."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(3, "ok"),
            replayed_reply=_reply(3, "ok"),
            delta=_mutation("x"),
        ),
    )

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    kinds = {v.kind: v for v in verdict.sub_verdicts}
    assert kinds["replay"].status is Status.PASS
    assert kinds["effect"].status is Status.UNVERIFIED


# --- 4. Clean turn: result PASS, effect PASS -> PASS --------------------------------


def test_clean_turn_is_pass(tmp_path, monkeypatch):
    """The positive control: a REPLAYED turn whose reply reproduced (result PASS) and
    whose declared-false tool mutated as it declared it may (effect PASS) -> PASS.

    Proves PASS is reachable — the composition is not vacuously never-PASS.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(3, "wrote"),
            replayed_reply=_reply(3, "wrote"),
            delta=_mutation("written.txt"),
        ),
    )

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.PASS, verdict
    assert all(v.status is Status.PASS for v in verdict.sub_verdicts), verdict.sub_verdicts


# --- 5. SNAPSHOT_FAILED carried verbatim, never coerced through the enum -------------


def test_snapshot_failed_cause_is_carried_never_coerced(tmp_path, monkeypatch):
    """A turn whose recorded cause is the gate's `UNRESTORABLE_SNAPSHOT_FAILED` — which is
    deliberately NOT an `UnrestorableCause` member — is UNVERIFIED with that string
    carried, and no exception. Coercing it via `UnrestorableCause("UNRESTORABLE_SNAPSHOT_FAILED")`
    would throw; the string is carried as-is.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(turn_index=0, status=UNVERIFIED, cause="UNRESTORABLE_SNAPSHOT_FAILED"),
    )

    verdict = _run(records, monkeypatch)  # must not raise

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.cause == "UNRESTORABLE_SNAPSHOT_FAILED", verdict
    # Structural guard: the composition never imports the enum, so it cannot coerce.
    assert not hasattr(turn_module, "UnrestorableCause"), (
        "turn.py must not import UnrestorableCause; carry cause strings verbatim"
    )


# --- 6. The determinism gate is threaded through composition, run ONCE, only on DIVERGED


def test_diverged_deterministic_turn_composes_to_fail(tmp_path, monkeypatch):
    """A REPLAYED turn that DIVERGED on a deterministic tool composes to FAIL via the
    result axis — proving the determinism gate is wired through the composition, not
    bypassed. `classify_determinism` is consulted (exactly once) on the divergence."""
    calls = {"n": 0}

    def spy_classify(*a, **k):
        calls["n"] += 1
        return DeterminismResult(turn_index=0, classification=DETERMINISTIC, replays=3, tool="write_file")

    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(3, "FABRICATED"),
            replayed_reply=_reply(3, "REAL"),
            delta=[],  # declared-false, so effect PASSes; result drives the FAIL
        ),
    )
    monkeypatch.setattr(turn_module, "classify_determinism", spy_classify)

    verdict = _run(records, monkeypatch)

    assert calls["n"] == 1, "a DIVERGED turn must consult the determinism classifier exactly once"
    assert verdict.status is Status.FAIL, verdict
    result = {v.kind: v for v in verdict.sub_verdicts}["replay"]
    assert result.status is Status.FAIL and "REAL" in result.message


def test_classify_determinism_not_run_on_an_equal_turn(tmp_path, monkeypatch):
    """Cost + correctness: an EQUAL turn is PASS at one replay; the classifier must not
    run (it would triple the replay cost and buy nothing). It is spied and must not fire."""
    def spy_classify(*a, **k):
        raise AssertionError("classify_determinism must not run on an EQUAL turn")

    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(3, "ok"),
            replayed_reply=_reply(3, "ok"),
            delta=[],
        ),
    )
    monkeypatch.setattr(turn_module, "classify_determinism", spy_classify)

    verdict = _run(records, monkeypatch)

    assert verdict.status is Status.PASS, verdict


# --- 7. The tool name is carried for the report ------------------------------------


def test_tool_name_is_carried(tmp_path, monkeypatch):
    """The verdict names the tool, so the report can attribute the turn without re-deriving."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])
    _stub_replay(
        monkeypatch,
        TurnReplay(turn_index=0, status=NOT_VERIFIABLE, cause="no snapshot was attempted"),
    )

    verdict = _run(records, monkeypatch)

    assert verdict.tool_name == "read_file", verdict
    assert verdict.turn_index == 0
