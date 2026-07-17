"""Task 4 — composing the A1 invariant verdict INTO the per-turn reduction.

C4 (`verify_turn`) reduces the two A2 checks — result-equivalence and effect-conformance —
into one turn status. A1 (C5, an operator-declared invariant evaluated against the observed
replay delta) is the axis that catches a CHEATING agent that A2 cannot: a tool that declares
`readOnlyHint: false` and writes `tests/` is a C4 effect PASS (it announced it mutates,
nothing to violate), yet the TASK said `tests/` is read-only. Same turn, same delta,
divergent verdicts. This file proves that wiring A1 into the reduction ADDITIVELY — exactly
like the existing `net_verdict` block — makes an A1 FAIL lower an all-A2-PASS turn to FAIL.

The load-bearing test is `test_a1_fail_with_a2_pass_reduces_to_fail`: A1 FAIL + both A2
PASS -> reduced FAIL, with a POSITIVE CONTROL (the identical turn with `invariants=()` ->
PASS) proving it is A1, not something else, that flipped it. The harness is
`tests/test_verify_turn.py`'s verbatim: `replay_turn` is stubbed to return a chosen
`TurnReplay`, so the composition is under test, never re-execution.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import TOOLS_LIST_REQUEST, TOOLS_LIST_RESPONSE

from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.snapshot.bth1 import FieldDiff
from belay.verify import turn as turn_module
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

# `write_file` is readOnlyHint:false (declared-false) and declares no openWorldHint, so its
# A2 effect is PASS and it drags in NO network sub-verdict — the non-A1 sub-verdicts are
# exactly [result, effect], both PASS. That is the clean A2-PASS backdrop the A1 verdict
# rides on. (Same fixture the C4 composition tests use.)
LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]

# server_command / manifest_dir are never reached: every test stubs replay_turn.
UNUSED = ["unused-server"]

# The operator's task-scoped policy: `tests/` is read-only. The trailing slash makes it a
# directory prefix on raw path bytes, mirroring BTH-1.
READ_ONLY_TESTS = Invariant(b"tests/", "read-only")


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


def _verify(records, *, invariants) -> TurnVerdict:
    return verify_turn(
        records, 0,
        server_command=UNUSED, manifest_dir="/nonexistent",
        invariants=invariants,
    )


def _clean_replayed(delta) -> TurnReplay:
    """A REPLAYED `write_file` turn whose reply reproduced (result PASS) and whose
    declared-false effect PASSes — so the ONLY axis that can lower the turn is A1."""
    return TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=EQUAL,
        recorded_reply=_reply(3, "wrote"),
        replayed_reply=_reply(3, "wrote"),
        delta=delta,
    )


def _write_file_records(tmp_path):
    return trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])


# --- 1. The A1 sub-verdict is present and grounded; absent without invariants --------


def test_a1_subverdict_present_with_invariants_absent_without(tmp_path, monkeypatch):
    """A REPLAYED turn verified WITH a read-only invariant carries exactly one A1
    sub-verdict (`axis=="A1"`, `kind=="invariant"`) grounded in the observed delta; the
    SAME turn verified with `invariants=()` carries none. That the A1 sub-verdict appears
    only when an invariant is passed is what makes the new arg truly additive."""
    records = _write_file_records(tmp_path)
    _stub_replay(monkeypatch, _clean_replayed(_mutation("tests/x.py")))

    with_inv = _verify(records, invariants=[READ_ONLY_TESTS])
    a1 = [v for v in with_inv.sub_verdicts if v.axis == "A1"]
    assert len(a1) == 1, with_inv.sub_verdicts
    assert a1[0].kind == "invariant", a1[0]

    without = _verify(records, invariants=())
    assert [v for v in without.sub_verdicts if v.axis == "A1"] == [], without.sub_verdicts


# --- 2. THE DEMO MECHANISM: A1 FAIL + A2 PASS -> reduced FAIL, A1 the sole FAIL -------


def test_a1_fail_with_a2_pass_reduces_to_fail(tmp_path, monkeypatch):
    """A1 FAIL (write under a read-only `tests/`) on a turn whose BOTH A2 sub-verdicts
    PASS reduces the turn to FAIL, and A1 is the ONLY thing that could have driven it.

    `write_file` is declared-false (effect PASS) and the reply reproduced (result PASS),
    so every non-A1 sub-verdict is PASS; the delta writes `tests/test_auth.py`, which the
    read-only invariant FAILs. POSITIVE CONTROL (mandated): the identical turn with
    `invariants=()` reduces to PASS — proving it is A1, not a broken A2, that flipped it.
    """
    records = _write_file_records(tmp_path)
    _stub_replay(monkeypatch, _clean_replayed(_mutation("tests/test_auth.py")))

    verdict = _verify(records, invariants=[READ_ONLY_TESTS])

    assert verdict.status is Status.FAIL, verdict
    a1 = [v for v in verdict.sub_verdicts if v.axis == "A1"]
    non_a1 = [v for v in verdict.sub_verdicts if v.axis != "A1"]
    assert len(a1) == 1 and a1[0].status is Status.FAIL, verdict.sub_verdicts
    # Every OTHER sub-verdict passed: the reduction is driven SOLELY by A1.
    assert all(v.status is Status.PASS for v in non_a1), non_a1
    assert [v for v in verdict.sub_verdicts if v.status is Status.FAIL] == a1, verdict.sub_verdicts

    # POSITIVE CONTROL: same turn, no invariant -> NOT FAIL (it is PASS). This is what
    # proves A1 caused the FAIL rather than something already wrong with the turn.
    control = _verify(records, invariants=())
    assert control.status is not Status.FAIL, control
    assert control.status is Status.PASS, control


# --- 3. A1 UNVERIFIED + A2 PASS -> reduced UNVERIFIED (an unevaluable invariant never
#        lets PASS through) -----------------------------------------------------------


def test_a1_unverified_with_a2_pass_reduces_to_unverified(tmp_path, monkeypatch):
    """A REPLAYED turn whose post-state was not observed (`delta is None`) — a legal
    REPLAYED state: `engine.replay_turn` emits `status=REPLAYED` with `delta=None` when
    the answered turn's workspace was not captured (engine.py:321-324). `write_file` is
    declared-false so A2 effect is PASS even with no delta, and the reply reproduced so
    result is PASS; the read-only invariant cannot be grounded in an absent delta, so A1
    is UNVERIFIED. UNVERIFIED outranks PASS -> the turn is UNVERIFIED, never PASS."""
    records = _write_file_records(tmp_path)
    _stub_replay(monkeypatch, _clean_replayed(None))

    verdict = _verify(records, invariants=[READ_ONLY_TESTS])

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    a1 = [v for v in verdict.sub_verdicts if v.axis == "A1"]
    non_a1 = [v for v in verdict.sub_verdicts if v.axis != "A1"]
    assert len(a1) == 1 and a1[0].status is Status.UNVERIFIED, verdict.sub_verdicts
    # A2 both passed; A1 alone lifted the turn to UNVERIFIED.
    assert all(v.status is Status.PASS for v in non_a1), non_a1


# --- 4. No invariants -> byte-identical to today (the default-arg-changes-nothing guard)


def test_no_invariants_reduces_as_today_with_no_a1_subverdict(tmp_path, monkeypatch):
    """A REPLAYED clean turn with `invariants=()` reduces exactly as it does today (PASS)
    and carries NO A1 sub-verdict. The default empty tuple must leave C4's behavior
    byte-for-byte unchanged."""
    records = _write_file_records(tmp_path)
    _stub_replay(monkeypatch, _clean_replayed(_mutation("written.txt")))

    verdict = _verify(records, invariants=())

    assert verdict.status is Status.PASS, verdict
    assert all(v.axis != "A1" for v in verdict.sub_verdicts), verdict.sub_verdicts
    assert all(v.status is Status.PASS for v in verdict.sub_verdicts), verdict.sub_verdicts
