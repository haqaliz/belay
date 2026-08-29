"""Phase 1 — the ANTI-OVERREACH GUARD for `verify-tool-not-offered` (aspect `boundary-probe`).

The aspect being built teaches A2 to ABSTAIN when the replay boundary never offered the
recorded tool: `belay verify` currently emits a confident FAIL on such a turn, because
`replay_turn` sends a `tools/call` the server does not implement, the server answers with an
error envelope, `_equivalence` folds that into DIVERGED, and `classify_determinism` finds the
same broken answer three times running — DETERMINISTIC — so `_deterministic_divergence_verdict`
(`src/belay/verify/result.py`) reports a deterministic failure of the agent's tool call. The
turn genuinely succeeded at capture time. That FAIL is fabricated.

**The single most dangerous way to fix it is to fix too much.** A discriminator that is even
slightly over-broad converts REAL A2 failures into abstentions and silently guts A2's entire
detection power — trace infidelity is the ONLY thing A2 catches (`CLAUDE.md`: "A2 cannot catch
a cheating agent"), so an A2 that abstains where it used to FAIL is not a more honest engine,
it is a dead axis with a polite message. Nothing in the suite would go red: abstention is a
*weaker* claim, and weaker claims do not break tests written to pin stronger ones.

This file is the guard against exactly that, and it is written BEFORE the abstention path
exists (aspect spec AC-2; plan `plan_20260828.md` Phase 1). It pins the FAIL side — that a
genuine deterministic divergence **on a tool the boundary DOES offer** still FAILs, with its
message unchanged — over two shapes:

  (a) **a value mismatch** — both replies parse and carry different values. The textbook A2
      FAIL: the trace says one thing, re-execution says another.
  (b) **recorded success (`isError: false`) vs replayed `isError: true`, WHERE THE TOOL IS
      OFFERED.** This shape matters most, and it is why this file exists. It is the shape
      *closest* to the defect being fixed — a not-offered tool also produces a replayed error
      envelope — and it is the one an over-broad "the replay came back an error, so probably
      the boundary could not serve it" discriminator would sweep up first. It must NOT be
      swept up: an agent whose trace records a successful command that in fact fails on
      re-execution is precisely the trace infidelity A2 is for.

What each test pins:

  1. `test_value_mismatch_on_offered_tool_still_fails` — shape (a) through the real
     `render_result_verdict`: FAIL, and the VERBATIM message (recorded vs observed).
  2. `test_recorded_success_vs_replayed_is_error_still_fails` — shape (b) through the real
     `render_result_verdict`, with the two replies differing in `isError` and NOTHING ELSE, so
     the assertion isolates that single field: still FAIL.
  3. `test_verify_turn_composes_the_is_error_divergence_into_a_failing_turn` — shape (b)
     composed through the REAL `verify_turn` (sub-verdicts + reduction), so the guard covers
     the orchestrator that the aspect will actually modify, not only the renderer.
  4. `test_real_replay_value_mismatch_on_offered_tool_still_fails` — shape (a) on REAL
     re-execution against a REAL gated capture, where the boundary genuinely offers the tool
     (`read_abs` is in the recorded and served `tools/list`). Darwin-gated.
  5. `test_real_replay_recorded_success_vs_replayed_is_error_still_fails` — shape (b) on REAL
     re-execution: `run_process` IS offered and IS served, the recorded reply claims the
     command succeeded, and re-executing it exits non-zero. Darwin-gated.
  6. `test_a_deterministic_divergence_is_never_abstained` — the PROPERTY across both shapes:
     a DIVERGED + DETERMINISTIC reply whose replies both parse is FAIL, never UNVERIFIED, and
     carries both values as evidence.

## These tests are GREEN against today's code, on purpose

They describe EXISTING behavior. A regression guard that only goes green after the change it
guards is not a guard — by then the detection power it was meant to protect may already be
gone and nothing would say so. A red result here means the test is wrong, not the engine.

That they were shown to have TEETH is a separate obligation, discharged by mutation: with
`_deterministic_divergence_verdict` forced to return UNVERIFIED unconditionally — a maximally
over-broad discriminator, the exact failure mode above — tests 1-6 all fail. That mutation was
run and reverted; it is not in the tree.

## Why the darwin gate, and where it is NOT needed

Tests 4 and 5 drive REAL re-execution, which re-invokes inside the macOS Seatbelt sandbox, so
off-darwin they are an honest skip with the named cause `replay-reinvokes-seatbelt` — the
convention in `tests/test_verify_dual_server.py:86-89`, machine-checked by
`tests/test_platform_gate_named_causes.py`. Tests 1-3 need no Seatbelt and run on BOTH
platforms: 1, 2 and 6 call the pure renderer directly (it re-runs nothing and consults no
model), and 3 drives the real `verify_turn` over the same replay-stub seam
`tests/test_verify_turn.py` and `tests/test_verify_dual_server.py` use.

The frame-builders and gated-capture helpers are imported from the two relocation e2e suites
(`test_replay_relocation_e2e.py`, `test_replay_relocation_shell_e2e.py`) — the established
convention for not re-deriving them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fixtures.abs_path_editor_server import BENIGN_CONTENT as ABS_BENIGN_CONTENT
from fixtures.abs_path_editor_server import ORIGINAL_CONTENT as ABS_ORIGINAL_CONTENT
from fixtures.abs_path_editor_server import READ_TOOL
from fixtures.shell_command_server import ORIGINAL_CONTENT as SHELL_ORIGINAL_CONTENT
from fixtures.shell_command_server import PLAIN_REPLY, RUN_TOOL

from belay.replay.determinism import DETERMINISTIC, DeterminismResult
from belay.replay.engine import DIVERGED, REPLAYED, TurnReplay
from belay.verify import turn as turn_module
from belay.verify.result import render_result_verdict
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

from test_replay_relocation_e2e import (
    _abs_capture,
    _abs_path as fs_abs_path,
    _call as fs_call,
    _reply as fs_reply,
    _server_cmd as fs_server_cmd,
)
from test_replay_relocation_shell_e2e import (
    _abs_path as shell_abs_path,
    _call as shell_call,
    _reply as shell_reply,
    _server_cmd as shell_server_cmd,
    _shell_capture,
    _tools_list_request,
    _tools_list_response,
    _trace as shell_trace,
)

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- reply builders for the pure-renderer tests ---------------------------------------


def _result_reply(text: str, *, is_error: bool = False) -> bytes:
    """A `tools/call` response shaped exactly like the fixture servers' `_text_result`."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    ).encode()


def _diverged_deterministic(
    recorded: bytes, replayed: bytes, *, tool: str
) -> tuple[TurnReplay, DeterminismResult]:
    """A DIVERGED replay of an OFFERED tool, already classified DETERMINISTIC.

    This is the exact pair `verify_result`/`verify_turn` hand to `render_result_verdict` after
    a real replay diverged and the classifier re-invoked the turn three times and saw the same
    answer each time. Building it directly keeps the assertion on the SCORING decision — the
    seam the aspect changes — rather than on re-execution, which C3 owns and which tests 4 and
    5 cover for real.
    """
    reply = TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=DIVERGED,
        recorded_reply=recorded,
        replayed_reply=replayed,
        delta=[],
    )
    determinism = DeterminismResult(
        turn_index=0, classification=DETERMINISTIC, replays=3, tool=tool
    )
    return reply, determinism


#: Shape (a): the trace recorded one file body, re-execution read a different one.
VALUE_MISMATCH_RECORDED = _result_reply(ABS_ORIGINAL_CONTENT)
VALUE_MISMATCH_REPLAYED = _result_reply(ABS_BENIGN_CONTENT)

#: Shape (b): IDENTICAL text, differing ONLY in `isError` — the recorded reply claims the
#: call succeeded, the replayed one reports it failed. The single-field difference is
#: deliberate: it isolates "recorded success vs replayed error" from any value divergence, so
#: a discriminator that keys on the replayed error envelope has nowhere to hide.
IS_ERROR_RECORDED = _result_reply(PLAIN_REPLY, is_error=False)
IS_ERROR_REPLAYED = _result_reply(PLAIN_REPLY, is_error=True)


# --- 1. AC-2 shape (a): a value mismatch still FAILs, message unchanged ---------------


def test_value_mismatch_on_offered_tool_still_fails() -> None:
    """DIVERGED + DETERMINISTIC, both replies parse, values differ -> FAIL, verbatim message.

    The textbook A2 finding: the trace recorded one value and re-execution deterministically
    produced another. `render_result_verdict` must keep calling that a FAIL and must keep
    saying so in the same words — the message is what a reader acts on, and an abstention
    dressed in a FAIL's clothes (or a FAIL that stops naming both values) is a silent
    regression. The full message is pinned literally; only the two value reprs are derived,
    so this asserts the PROSE has not moved.
    """
    reply, determinism = _diverged_deterministic(
        VALUE_MISMATCH_RECORDED, VALUE_MISMATCH_REPLAYED, tool=READ_TOOL
    )

    verdict = render_result_verdict(reply, determinism)

    assert verdict.status is Status.FAIL, verdict
    assert verdict.axis == "A2" and verdict.kind == "replay", verdict
    recorded = json.loads(VALUE_MISMATCH_RECORDED)
    replayed = json.loads(VALUE_MISMATCH_REPLAYED)
    assert verdict.message == (
        f"result-equivalence FAIL on deterministic tool {READ_TOOL!r}: the trace recorded "
        f"{recorded!r} but replay deterministically reproduced {replayed!r}"
    ), verdict.message
    assert verdict.expected == recorded, verdict
    assert verdict.observed == replayed, verdict


# --- 2. AC-2 shape (b): recorded success vs replayed isError:true still FAILs ---------


def test_recorded_success_vs_replayed_is_error_still_fails() -> None:
    """Recorded `isError: false` vs replayed `isError: true` on an OFFERED tool -> FAIL.

    THE load-bearing case. The two replies are byte-identical apart from the `isError` flag,
    so nothing here is a value divergence in the ordinary sense — the only difference is that
    the trace claims the call succeeded and re-execution says it failed. That is trace
    infidelity, the one thing A2 exists to catch, and it must stay a FAIL.

    It is also the shape an over-broad boundary discriminator swallows first: a tool the
    server does not offer ALSO replays as an error envelope. "Replay came back an error" can
    therefore never, on its own, license an abstention — only evidence about what the boundary
    OFFERS can, and that evidence is not this reply. If this test ever goes UNVERIFIED, A2 has
    stopped being able to see a lying trace.
    """
    reply, determinism = _diverged_deterministic(
        IS_ERROR_RECORDED, IS_ERROR_REPLAYED, tool=RUN_TOOL
    )

    verdict = render_result_verdict(reply, determinism)

    assert verdict.status is Status.FAIL, verdict
    assert verdict.status is not Status.UNVERIFIED, (
        "a replayed error envelope from a tool the boundary DOES offer is a real A2 finding, "
        "never an abstention",
        verdict,
    )
    assert verdict.expected == json.loads(IS_ERROR_RECORDED), verdict
    assert verdict.observed == json.loads(IS_ERROR_REPLAYED), verdict
    assert "result-equivalence FAIL on deterministic tool" in verdict.message, verdict.message


# --- 3. AC-2 shape (b), composed through the REAL verify_turn -------------------------


def test_verify_turn_composes_the_is_error_divergence_into_a_failing_turn(
    tmp_path, monkeypatch
) -> None:
    """The same shape (b) through the REAL `verify_turn`: replay sub-verdict FAIL, turn FAIL.

    The renderer is not the only thing the aspect touches — `verify_turn` is where the probe
    is to be called and where `tool_offered` will be threaded — so the guard must cover the
    composition too, or the abstention could be introduced upstream of a renderer that is
    still perfectly capable of FAILing.

    Re-execution is stubbed at the same seam `tests/test_verify_turn.py` uses (its
    `_stub_replay`): the composition under test is `verify_turn`, and re-execution is C3's.
    The stub reports REPLAYED + DIVERGED with a replayed reply that differs from the recorded
    one only in `isError`; `classify_determinism` is stubbed to DETERMINISTIC exactly as
    `test_verify_turn.py` does for its divergence test. `run_process` declares NO annotations,
    so the effect axis is honestly UNVERIFIED — and FAIL outranks UNVERIFIED, so the turn
    still reduces to FAIL. That reduction is the reader-visible verdict.
    """
    records = shell_trace(
        tmp_path,
        "is-error-divergence",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", shell_call({"command_line": "exit 3", "reply_format": "plain"}), None),
            ("s2c", IS_ERROR_RECORDED, None),
        ],
    )
    monkeypatch.setattr(
        turn_module,
        "replay_turn",
        lambda *a, **k: TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=DIVERGED,
            recorded_reply=IS_ERROR_RECORDED,
            replayed_reply=IS_ERROR_REPLAYED,
            delta=[],
        ),
    )
    monkeypatch.setattr(
        turn_module,
        "classify_determinism",
        lambda *a, **k: DeterminismResult(
            turn_index=0, classification=DETERMINISTIC, replays=3, tool=RUN_TOOL
        ),
    )

    verdict = verify_turn(
        records,
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",  # never reached: replay_turn is stubbed
    )

    assert verdict.tool_name == RUN_TOOL, verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.FAIL, result.message
    assert verdict.status is Status.FAIL, verdict
    assert verdict.cause is None, (
        "`cause` explains an UNVERIFIED and nothing else; a FAILing turn must not acquire one",
        verdict,
    )


# --- 4. AC-2 shape (a) on REAL re-execution against an offering boundary --------------


@darwin_only
def test_real_replay_value_mismatch_on_offered_tool_still_fails(tmp_path) -> None:
    """A REAL replay of `read_abs` — a tool the boundary OFFERS — whose value diverges -> FAIL.

    A REAL gated capture (TraceWriter + take_snapshot + persist_snapshot WITH `source_root`,
    exactly as the relocation e2e) of a `read_abs` of the seeded file. The seed holds
    `ORIGINAL_CONTENT`, but the recorded reply claims the read returned `BENIGN_CONTENT` — a
    trace that misreports what the tool returned. On replay the snapshot is restored, the
    server really reads the file, and returns `ORIGINAL_CONTENT`: DIVERGED, and deterministic
    across the classifier's re-invocations (a read of a restored tree has no clock and no
    randomness). The verdict is a real FAIL.

    Nothing here is a boundary problem: `read_abs` is in the recorded `tools/list` AND in what
    `abs_path_editor_server.py` actually serves, so a probe asking the live boundary what it
    offers finds it. This turn must be untouched by the aspect.
    """

    def frames_for(root: str):
        # The call is honest; the RECORDED REPLY is the lie the replay catches.
        return (
            fs_call(READ_TOOL, {"path": fs_abs_path(root)}),
            fs_reply(ABS_BENIGN_CONTENT),
        )

    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "offered-value-mismatch", ABS_ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records,
        0,
        server_command=fs_server_cmd(root),
        manifest_dir=manifest_dir,
        invariants=(),
        timeout=20.0,
    )

    assert verdict.tool_name == READ_TOOL, verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.FAIL, result.message
    assert result.observed["result"]["content"][0]["text"] == ABS_ORIGINAL_CONTENT, (
        "the FAIL must still carry what re-execution actually observed",
        result.observed,
    )
    assert result.expected["result"]["content"][0]["text"] == ABS_BENIGN_CONTENT, (
        "…against what the trace claimed",
        result.expected,
    )
    assert verdict.status is Status.FAIL, verdict


# --- 5. AC-2 shape (b) on REAL re-execution against an offering boundary --------------


@darwin_only
def test_real_replay_recorded_success_vs_replayed_is_error_still_fails(tmp_path) -> None:
    """A REAL replay of `run_process` — OFFERED — recorded success, re-execution fails -> FAIL.

    The corrupt-trace shape at full strength, on real re-execution. The capture records a
    `run_process` of `exit 3` whose reply claims success (`isError: false`, `reply_format:
    "plain"` so the text is the fixture's fixed literal and carries no path). Replaying it
    really runs `/bin/sh -c 'exit 3'`, which exits 3, so the server answers with the SAME text
    and `isError: true` — the replies differ in that one field, and in nothing else.

    `run_process` is the only tool `shell_command_server.py` offers, it is in the recorded
    `tools/list`, and the replay boundary IS that server — so no honest probe can call this
    turn not-offered. It is a genuine A2 FAIL and must survive the aspect intact. `exit 3`
    embeds no path, so no relocation is involved; three classifier re-invocations all exit 3,
    so the tool classifies DETERMINISTIC.
    """

    def frames_for(_root: str):
        return (
            shell_call({"command_line": "exit 3", "reply_format": "plain"}),
            shell_reply(PLAIN_REPLY, is_error=False),  # the trace claims it succeeded
        )

    records, manifest_dir, _work, _root = _shell_capture(
        tmp_path, "offered-is-error", SHELL_ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records,
        0,
        server_command=shell_server_cmd(),
        manifest_dir=manifest_dir,
        invariants=(),
        timeout=20.0,
    )

    assert verdict.tool_name == RUN_TOOL, verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.FAIL, result.message
    assert result.status is not Status.UNVERIFIED, (
        "a command the trace claims succeeded and that really fails on re-execution is trace "
        "infidelity — the one thing A2 catches",
        result.message,
    )
    assert verdict.replayed_is_error is True, (
        "the replayed outcome was READ and it was an error — the evidence the FAIL rests on",
        verdict,
    )
    assert verdict.status is Status.FAIL, verdict


# --- 6. The property across both shapes ----------------------------------------------


def test_a_deterministic_divergence_is_never_abstained() -> None:
    """PROPERTY: DIVERGED + DETERMINISTIC with two parseable replies is FAIL, never UNVERIFIED.

    Stated over both shapes at once, because the guard is about a CLASS of outcome, not two
    examples: whenever re-execution reproduced a readable answer that differs from the trace's,
    and the classifier decided the tool reproduces, A2 has ground to stand on and must stand on
    it. The only DIVERGED+DETERMINISTIC shape today's engine declines to FAIL is an UNPARSEABLE
    replayed reply (`result.py`: "replay produced something we could not read, which is not a
    determinable value divergence") — and neither of these is that.

    Both verdicts must also carry `expected` and `observed`, the evidence a reader needs to
    adjudicate the FAIL; an abstention that kept the FAIL status but dropped the values would
    be the same loss wearing the same label.
    """
    cases = (
        ("value mismatch", VALUE_MISMATCH_RECORDED, VALUE_MISMATCH_REPLAYED, READ_TOOL),
        ("recorded success vs replayed isError", IS_ERROR_RECORDED, IS_ERROR_REPLAYED, RUN_TOOL),
    )
    for label, recorded, replayed, tool in cases:
        reply, determinism = _diverged_deterministic(recorded, replayed, tool=tool)
        verdict = render_result_verdict(reply, determinism)

        assert verdict.status is Status.FAIL, (label, verdict)
        assert verdict.status is not Status.UNVERIFIED, (label, verdict)
        assert verdict.expected == json.loads(recorded), (label, verdict)
        assert verdict.observed == json.loads(replayed), (label, verdict)


# =====================================================================================
# Phase 4 — the fix: a tool the boundary never offered is UNVERIFIED, never a FAIL
# =====================================================================================
#
# Everything above pins what must NOT move. Everything below is the defect itself.
#
# The seam these tests drive is `verify_turn`, because that is where the decision is made:
# on a DIVERGED reply it asks the replay boundary what it offers — `offered_tools`, the
# probe built in phase 3 — BEFORE consulting `classify_determinism`, and threads a
# three-way `tool_offered` into `render_result_verdict`. Ordering is not an optimisation
# here: the classifier re-invokes the turn `--replays` (>=3) more times, and re-proving
# that `"no such tool"` is self-consistent is pure waste (PRD M2). AC-9 asserts the saving
# rather than assuming it.
#
# **Where the probe's inputs come from, and why it matters for the guard above.** The probe
# must ask the SAME boundary the replay spawned — same resolved argv, same snapshot, same
# relocation root. Those are facts of the replay, so the replay now reports them:
# `TurnReplay.boundary` (`ReplayBoundary`) carries the argv `replay_turn` actually spawned,
# already resolved through the single `resolve_server_argv` site, together with the manifest
# it restored and the relocation root it used. Re-deriving them in `verify_turn` would be a
# second resolution of `{workspace}`, which the phase-2 guard exists to forbid.
#
# A consequence, deliberate and named: a `TurnReplay` that carries NO boundary is not a
# boundary that answered — it is a replay observation with no boundary identity at all, and
# the real engine never produces one on a REPLAYED status (the manifest, the resolved argv
# and the relocation decision are all settled before it can spawn). It is reachable only
# from a hand-built or stubbed replay, and there it means exactly "there is nothing here to
# ask", so scoring is byte-for-byte what it was before this phase. That is why guard test 3
# above — which stubs re-execution wholesale — is untouched by this phase, and it is
# asserted directly by `test_a_real_replayed_turn_always_reports_its_boundary`.

from belay.replay.engine import ReplayBoundary  # noqa: E402


def _replayed_with_boundary(*, recorded: bytes, replayed: bytes, argv=("srv",)) -> TurnReplay:
    """A REPLAYED + DIVERGED observation that reports the boundary it spawned.

    The shape the real engine returns for the defect: the server answered readably, the
    answer differs from the recording, and the replay names the boundary that produced it
    so the probe can go and ask that same boundary what it offers.
    """
    return TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=DIVERGED,
        recorded_reply=recorded,
        replayed_reply=replayed,
        delta=[],
        boundary=ReplayBoundary(
            argv=tuple(argv), manifest_path="/manifests/abc.json", source_root=None,
            relocation_root=None,
        ),
    )


def _run_process_records(tmp_path, name: str) -> list[dict]:
    """A one-turn trace whose recorded `run_process` SUCCEEDED — the PRD's shape."""
    return shell_trace(
        tmp_path,
        name,
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", shell_call({"command_line": "printf hi", "reply_format": "plain"}), None),
            ("s2c", IS_ERROR_RECORDED, None),
        ],
    )


class _DeterminismSpy:
    """A stand-in for `classify_determinism` that RECORDS whether it was consulted.

    AC-9 is a cost claim — probing first *saves* three spawns rather than adding one — and a
    cost claim asserted by reading the source is not asserted at all. The spy makes the call
    observable; a test that expects no classification asserts `calls == 0`.
    """

    def __init__(self, classification=DETERMINISTIC, tool=RUN_TOOL) -> None:
        self.calls = 0
        self._result = DeterminismResult(
            turn_index=0, classification=classification, replays=3, tool=tool
        )

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._result


def _result_sub(verdict):
    """The A2 RESULT sub-verdict of a composed turn, whichever `kind` it narrowed to.

    Aspect `cause-and-surfaces` gave the boundary abstentions their own sub-verdict kinds
    (`replay:tool-not-offered`, `replay:boundary-ambiguous`, `replay:boundary-undecided`),
    because `canonical_cause` buckets a replayed-but-unverified turn by the prefix
    `<axis>/<kind>` and an abstention that kept the bare `replay` kind was filed beside every
    other result-axis abstention — the reason the 2026-08-12 gate mint could not count them.
    The tests below assert what the abstention SAYS and what status it carries, which is
    unchanged; only the name it is filed under moved, so the lookup follows the family rather
    than the exact kind. The FAIL-side guard tests above keep the literal `== "replay"`
    deliberately: a genuine deterministic divergence must still carry the generic kind.
    """
    return next(
        s
        for s in verdict.sub_verdicts
        if s.axis == "A2" and (s.kind == "replay" or s.kind.startswith("replay:"))
    )


def _effect_sub(verdict):
    """The A2 filesystem-EFFECT sub-verdict, whichever `kind` it narrowed to.

    `effect:network` is excluded by name: it is the permanent coverage boundary, a THIRD
    sub-verdict that is deliberately never gated on the boundary probe, and folding it in
    here would make these assertions read the wrong dimension.
    """
    return next(
        s
        for s in verdict.sub_verdicts
        if s.axis == "A2"
        and s.kind != "effect:network"
        and (s.kind == "effect" or s.kind.startswith("effect:"))
    )


def _wire(monkeypatch, reply: TurnReplay, offered, spy: _DeterminismSpy):
    """Point `verify_turn` at a fixed replay observation, a fixed probe answer, and the spy.

    `offered` is handed to the probe seam exactly as `offered_tools` would return it: a set
    of names, `set()`, or `None`. Stubbing the probe (rather than spawning) is what lets the
    three-way DECISION — the part most likely to regress — be tested on both platforms,
    which is the split `tests/test_verify_dual_server.py` established.
    """
    monkeypatch.setattr(turn_module, "replay_turn", lambda *a, **k: reply)
    monkeypatch.setattr(turn_module, "classify_determinism", spy)
    seen: list[list[str]] = []

    def _probe(argv, **kwargs):
        seen.append(list(argv))
        return offered(list(argv)) if callable(offered) else offered

    monkeypatch.setattr(turn_module, "offered_tools", _probe)
    return seen


# --- 7. AC-1: the boundary does not offer the tool -> UNVERIFIED, not FAIL -------------


def test_a_tool_the_boundary_does_not_offer_is_unverified_not_fail(tmp_path, monkeypatch):
    """The defect, at the deciding seam: not offered -> UNVERIFIED, never FAIL.

    The recorded `run_process` succeeded; the replay boundary answers an error because it
    has no such tool. Nothing was re-executed, so nothing was refuted, and a FAIL would be
    a claim about the agent grounded in a fact about the operator's `--server`. The probe
    asks the boundary and gets back a toolset without `run_process`, which is POSITIVE
    evidence of absence (PRD M1) — not error-text matching, not an `isError` inference.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, {"read_text_file", "write_file"}, spy)

    verdict = verify_turn(
        _run_process_records(tmp_path, "not-offered"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",  # never reached: replay_turn is stubbed
    )

    result = _result_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert result.status is not Status.FAIL, result.message
    assert "does not offer" in result.message, result.message
    assert RUN_TOOL in result.message, result.message
    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.cause is not None, (
        "every UNVERIFIED turn must trace to a named cause", verdict,
    )


# --- 8. AC-9: the classifier is NOT consulted on a not-offered turn --------------------


def test_the_determinism_classifier_is_not_run_on_a_not_offered_turn(tmp_path, monkeypatch):
    """AC-9, the cost claim, asserted by a spy: zero calls, so three spawns are SAVED.

    The probe is placed BEFORE the determinism gate precisely so that a boundary which
    cannot serve the tool is settled at one spawn instead of four. If this ever regresses
    to "probe after classify", the verdict would still be honest and the run would silently
    cost 3x on exactly the turns that deserve it least.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, set(), spy)

    verify_turn(
        _run_process_records(tmp_path, "no-classify"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    assert spy.calls == 0, (
        "the determinism classifier re-invokes the turn >=3 times; it must not run once the "
        "boundary has said it does not offer the tool"
    )


# --- 9. AC-4: a probe that could not decide is DISTINCT, and still never a FAIL --------


def test_a_probe_that_could_not_be_read_is_unverified_with_a_distinct_message(
    tmp_path, monkeypatch
):
    """AC-4 / PRD M4: absence of evidence is never evidence of absence.

    `offered_tools` returns `None` when the probe could not run or its answer could not be
    read. That is ignorance about the boundary, not knowledge that the boundary lacks the
    tool — so the abstention must NOT say "does not offer", and must not be a FAIL either:
    a divergence we cannot attribute is not a divergence we can charge to the agent.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, None, spy)

    verdict = verify_turn(
        _run_process_records(tmp_path, "probe-unreadable"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    result = _result_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert "does not offer" not in result.message, (
        "an unreadable probe must never be reported as the boundary lacking the tool",
        result.message,
    )
    assert verdict.status is Status.UNVERIFIED, verdict
    assert spy.calls == 0, "an undecided boundary buys no determinism classification either"

    # …and it is a DIFFERENT finding from "not offered", in words a reader can tell apart.
    offered_reply = _replayed_with_boundary(
        recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED
    )
    _wire(monkeypatch, offered_reply, set(), _DeterminismSpy())
    not_offered = _result_sub(
        verify_turn(
            _run_process_records(tmp_path, "probe-not-offered"),
            0,
            server_command=shell_server_cmd(),
            manifest_dir="/nonexistent",
        )
    )
    assert result.message != not_offered.message, (
        "'could not decide' and 'does not offer' must not render as the same finding"
    )


# --- 10. The FAIL path still runs THROUGH the probe when the tool IS offered -----------


def test_a_boundary_that_offers_the_tool_still_reaches_the_failing_verdict(
    tmp_path, monkeypatch
):
    """The guard's property, now through the probe seam: offered -> classify -> FAIL.

    Tests 1-6 pin the renderer and the composition with no probe in the loop. This one pins
    that INSERTING the probe does not change the answer when the probe's answer is "yes":
    the classifier is consulted exactly once and the turn is still the FAIL it always was.
    Without this, the guard could stay green while the probe quietly short-circuited every
    divergence in production.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, {RUN_TOOL, "read_text_file"}, spy)

    verdict = verify_turn(
        _run_process_records(tmp_path, "offered-still-fails"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    result = _result_sub(verdict)
    assert result.status is Status.FAIL, result.message
    assert spy.calls == 1, ("the classifier must still gate a divergence on an offered tool", spy.calls)
    assert verdict.status is Status.FAIL, verdict


# --- 11. AC-1 end to end, on a REAL capture and a REAL boundary ------------------------


@darwin_only
def test_real_replay_of_a_tool_the_boundary_does_not_offer_is_unverified(tmp_path) -> None:
    """The PRD's live repro, as a regression test: capture with a shell server, replay
    against a filesystem-only one.

    A REAL gated capture of a `run_process` turn whose recorded reply SUCCEEDED, replayed
    against `abs_path_editor_server.py` — a boundary that offers `read_abs` and `edit_abs`
    and no command tool at all. This is the committed demo capture's shape reduced to
    fixtures: the reply is readable, it reproduces identically on every replay, and so it
    took `DIVERGED + DETERMINISTIC -> FAIL` and reported a deterministic failure of a call
    that really succeeded.

    The call carries an in-root `path` argument, so the engine's relocation gate fires and
    the boundary is spawned rooted at the scratch — which is exactly the boundary the probe
    must ask. Asking it the ordinary way (spawn, `tools/list`) returns `{read_abs, edit_abs}`;
    `run_process` is absent, and the verdict abstains.
    """

    def frames_for(root: str):
        return (
            shell_call(
                {
                    "command_line": "printf hi",
                    "reply_format": "plain",
                    "path": shell_abs_path(root),
                }
            ),
            shell_reply(PLAIN_REPLY, is_error=False),  # the recorded call SUCCEEDED
        )

    records, manifest_dir, _work, root = _shell_capture(
        tmp_path, "boundary-omits-run-process", SHELL_ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records,
        0,
        server_command=fs_server_cmd(root),  # offers read_abs/edit_abs, never run_process
        manifest_dir=manifest_dir,
        invariants=(),
        timeout=20.0,
    )

    assert verdict.tool_name == RUN_TOOL, verdict
    result = _result_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert "result-equivalence FAIL" not in result.message, (
        "the fabricated FAIL is exactly what this aspect removes", result.message,
    )
    assert "does not offer" in result.message, result.message
    assert verdict.status is Status.UNVERIFIED, verdict


# --- 12. The engine always reports its boundary on a REPLAYED turn ---------------------


@darwin_only
def test_a_real_replayed_turn_always_reports_its_boundary(tmp_path) -> None:
    """The premise the "no boundary -> score as before" branch rests on, asserted.

    `verify_turn` falls back to today's scoring when a replay observation carries no
    boundary. That fallback is only safe because the REAL engine cannot produce such an
    observation on a REPLAYED status: the manifest, the resolved argv and the relocation
    decision are all settled before it can spawn. If that ever stopped being true, the
    fallback would silently restore the fabricated FAIL, and this test is what would say so.
    """
    from belay.replay.engine import REPLAYED as ENGINE_REPLAYED
    from belay.replay.engine import replay_turn as engine_replay_turn

    def frames_for(root: str):
        return (fs_call(READ_TOOL, {"path": fs_abs_path(root)}), fs_reply(ABS_ORIGINAL_CONTENT))

    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "boundary-reported", ABS_ORIGINAL_CONTENT, frames_for
    )
    reply = engine_replay_turn(
        records, 0, server_command=fs_server_cmd(root), manifest_dir=manifest_dir, timeout=20.0
    )

    assert reply.status == ENGINE_REPLAYED, reply.cause
    assert reply.boundary is not None, "a replayed turn must name the boundary it spawned"
    assert reply.boundary.argv == tuple(fs_server_cmd(root)), reply.boundary
    assert Path(reply.boundary.manifest_path).exists(), reply.boundary


# --- 13. AC-5: two configured servers both offering the tool -> abstain, never guess ---


def test_a_tool_offered_by_two_configured_servers_abstains(tmp_path, monkeypatch):
    """AC-5 / PRD M3: routing between two servers that both claim a tool would be a guess.

    `verify_turn` routes by tool NAME — `run_process` goes to `--shell-server` when one is
    given, everything else to `--server` — so the moment both configured servers offer the
    same tool, "which boundary should have served this turn" stops being a fact and becomes
    a convention. The divergence might be the trace's, or it might be an artifact of routing
    to the wrong one of two willing servers, and this engine does not guess between them.

    The shape is REACHABLE, not hypothetical: it needs only `--shell-server` plus two
    servers with an overlapping toolset, which is the ordinary case for a shell server that
    also exposes file helpers. With no `--shell-server` there is exactly one configured
    server and the branch cannot fire — asserted by the second half of this test.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    probed = _wire(monkeypatch, reply, lambda _argv: {RUN_TOOL, "read_text_file"}, spy)

    verdict = verify_turn(
        _run_process_records(tmp_path, "ambiguous"),
        0,
        server_command=["python", "fs_server.py"],
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    result = _result_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert "more than one configured server" in result.message, result.message
    assert "does not offer" not in result.message, (
        "an ambiguous boundary is not an absent one", result.message,
    )
    assert verdict.status is Status.UNVERIFIED, verdict
    assert spy.calls == 0, "a routing guess buys no determinism classification"
    assert len(probed) == 2, (
        "both configured servers must be asked before ambiguity can be ruled in or out",
        probed,
    )

    # …and with only `--server` configured the same probe answer is unambiguous: one
    # configured server, no routing choice, so the FAIL stands exactly as it always did.
    spy_one = _DeterminismSpy()
    _wire(monkeypatch, reply, lambda _argv: {RUN_TOOL, "read_text_file"}, spy_one)
    single = verify_turn(
        _run_process_records(tmp_path, "unambiguous"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )
    assert _result_sub(single).status is Status.FAIL
    assert spy_one.calls == 1


def test_an_alternate_server_that_cannot_be_probed_is_undecided_not_ignored(
    tmp_path, monkeypatch
):
    """Fail-closed on the alternate too: an unreadable second probe is UNDECIDED.

    Treating an unreadable alternate as "does not offer it" would silently resolve the
    ambiguity in the direction that keeps the FAIL — the convenient direction — on no
    evidence at all. Same rule as everywhere else in this gate: unread is not empty.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(
        monkeypatch,
        reply,
        lambda argv: {RUN_TOOL} if argv == list(reply.boundary.argv) else None,
        spy,
    )

    verdict = verify_turn(
        _run_process_records(tmp_path, "alternate-unreadable"),
        0,
        server_command=["python", "fs_server.py"],
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    result = _result_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert "could not be probed" in result.message, result.message
    assert spy.calls == 0


def test_the_alternate_is_never_probed_once_the_routed_boundary_has_settled_it(
    tmp_path, monkeypatch
):
    """A not-offered routed boundary is decisive on its own — and costs ONE spawn.

    The reply the comparison diverged against came from the routed boundary. If that
    boundary does not offer the tool, no answer from any other configured server can make
    the divergence attributable, so asking one would be a spawn spent on nothing.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    probed = _wire(monkeypatch, reply, lambda _argv: {"read_text_file"}, spy)

    verify_turn(
        _run_process_records(tmp_path, "routed-settles-it"),
        0,
        server_command=["python", "fs_server.py"],
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    assert len(probed) == 1, ("only the routed boundary needed asking", probed)
    assert spy.calls == 0


# --- 14. The probe never fires on a reply that did not diverge ------------------------


def test_a_reply_that_reproduced_is_never_probed(tmp_path, monkeypatch):
    """No divergence, no question to ask: an EQUAL turn pays for nothing and is unchanged.

    The gate is keyed on DIVERGED, so the overwhelmingly common case — a turn that
    reproduced — spawns no probe, consults no classifier, and renders the PASS it always
    did. This is what keeps a fully-offered trace's cost and output where they were.
    """
    from belay.replay.engine import EQUAL

    reply = TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=EQUAL,
        recorded_reply=IS_ERROR_RECORDED,
        replayed_reply=IS_ERROR_RECORDED,
        delta=[],
        boundary=ReplayBoundary(argv=("srv",), manifest_path="/manifests/abc.json"),
    )
    spy = _DeterminismSpy()
    probed = _wire(monkeypatch, reply, lambda _argv: set(), spy)

    verdict = verify_turn(
        _run_process_records(tmp_path, "equal-no-probe"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    assert probed == [], ("a reply that reproduced must not spawn a probe", probed)
    assert spy.calls == 0
    assert _result_sub(verdict).status is Status.PASS


# =====================================================================================
# Phase 5 — the second fabricated sub-verdict: effect-conformance on a turn nothing ran
# =====================================================================================
#
# Phase 4 stopped the RESULT axis fabricating a FAIL. It left the EFFECT axis fabricating
# a PASS from the same false premise, and an adversarial review reproduced it live on the
# committed demo capture:
#
#     A2 replay  UNVERIFIED  (tool not offered)
#     A2 effect  PASS        "effect-conformance PASS: tool 'run_process' declared
#                             readOnlyHint: false (it may mutate); the observed effect
#                             conforms — there is no read-only contract to violate"
#
# Nothing was observed. The tool was never invoked: the boundary answered that it has no
# such tool, and `render_effect_verdict` then weighed the TRACE's recorded annotation
# against the replay's (empty) delta, where the rule table maps declared-false + any delta
# -> PASS. **A declaration read out of the capture is not an observation of this replay.**
#
# The turn's reduced status is UNVERIFIED either way (worst-status-wins), so there is no
# turn-level false PASS and no published number can move. That is exactly why this is worth
# fixing rather than shrugging at: `belay corpus show` and the C7 console render sub-verdicts
# INDIVIDUALLY, so a reader sees "the observed effect conforms" sitting beside an honest
# abstention. Partial honesty is the failure mode this project names everywhere else.
#
# The gate is the SAME evidence the result axis already uses — the `tool_offered` decision
# `verify_turn` computed once from one probe. It is threaded, never recomputed: a second
# probe would be a second answer, and two answers about one boundary is how the two axes
# come to disagree.

from fixtures.shell_command_server import RUN_TOOL as _RUN_TOOL  # noqa: E402

from belay.snapshot.bth1 import FieldDiff  # noqa: E402
from belay.verify.effect import render_effect_verdict  # noqa: E402

#: The exact sentence this phase exists to make unreachable on an un-executed turn. Asserted
#: as a literal substring, because the defect is the CLAIM, not the status.
CONFORMS = "the observed effect conforms"


def _declares(read_only: bool) -> bytes:
    """A `tools/list` response declaring `run_process`'s `readOnlyHint` — the demo shape.

    The committed demo capture's shell server declares `readOnlyHint: false` and
    `openWorldHint: false`, which is what routes the turn down the declared-false -> PASS
    branch. `test_replay_relocation_shell_e2e._tools_list_response` declares NO annotations
    (already UNVERIFIED for effect), so it cannot express this defect; this builder can.
    """
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": _RUN_TOOL,
                        "inputSchema": {"type": "object", "properties": {}},
                        "annotations": {
                            "readOnlyHint": read_only,
                            "openWorldHint": False,
                        },
                    }
                ]
            },
        }
    ).encode()


def _declared_records(tmp_path, name: str, *, read_only: bool = False) -> list[dict]:
    """A one-turn `run_process` trace whose tool DECLARES a `readOnlyHint`."""
    return shell_trace(
        tmp_path,
        name,
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _declares(read_only), None),
            ("c2s", shell_call({"command_line": "printf hi", "reply_format": "plain"}), None),
            ("s2c", IS_ERROR_RECORDED, None),
        ],
    )


# --- 15. AC-3: the effect axis abstains when the boundary never offered the tool -------


def test_effect_conformance_abstains_when_the_boundary_never_offered_the_tool(tmp_path):
    """The reproduced finding, at the renderer: not offered -> UNVERIFIED, never PASS.

    `readOnlyHint: false` is still declared in the capture and still read here — that is
    unchanged, and it is the point: the declaration is the *server's* statement about what
    the tool may do, not evidence that this replay ran it. With the boundary saying it does
    not offer the tool, no effect was observed, so there is nothing for an effect to conform
    TO, and the honest answer is an abstention naming why.
    """
    records = _declared_records(tmp_path, "effect-not-offered")

    verdict = render_effect_verdict(records, 0, [], tool_offered=False)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS, verdict
    assert CONFORMS not in verdict.message, verdict.message
    assert "does not offer" in verdict.message, verdict.message
    assert _RUN_TOOL in verdict.message, verdict.message
    assert verdict.observed is None, (
        "nothing was observed, so the verdict must not report an observation", verdict,
    )


def test_an_undecided_boundary_abstains_on_effect_too_and_says_so_differently(tmp_path):
    """AC-4's discipline, carried onto the effect axis: unread is not empty.

    A probe that could not be run or read, and two configured servers both claiming the
    tool, are IGNORANCE about the boundary. The effect axis must abstain for them as well —
    an un-attributable divergence is an un-attributable effect — and must not word it as
    "the boundary does not offer it", which would sell absence of evidence as evidence of
    absence on a second surface.
    """
    records = _declared_records(tmp_path, "effect-undecided")

    verdict = render_effect_verdict(
        records, 0, [], tool_offered=None, probe_note="the probe could not be read",
    )

    assert verdict.status is Status.UNVERIFIED, verdict
    assert CONFORMS not in verdict.message, verdict.message
    assert "does not offer" not in verdict.message, verdict.message
    assert "the probe could not be read" in verdict.message, verdict.message

    settled = render_effect_verdict(records, 0, [], tool_offered=False)
    assert verdict.message != settled.message, (
        "'could not decide' and 'does not offer' must not render as the same finding",
    )


def test_the_effect_gate_precedes_even_the_read_only_fail(tmp_path):
    """Fail-closed in BOTH directions: a not-offered turn cannot manufacture an effect FAIL.

    The mirror of the PASS defect, and it must be closed by the same gate. A delta observed
    on a turn the boundary never served is not that tool's effect, so scoring it against a
    declared `readOnlyHint: true` would fabricate a FAIL out of the replay harness's own
    footprint. The gate therefore sits AHEAD of the whole rule table, not inside its
    declared-false branch.
    """
    records = _declared_records(tmp_path, "effect-not-offered-ro", read_only=True)
    delta = [FieldDiff(path=b"a.txt", field="content", left=b"x", right=b"y")]

    verdict = render_effect_verdict(records, 0, delta, tool_offered=False)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.FAIL, verdict


def test_a_not_offered_turn_renders_no_sub_verdict_claiming_the_effect_conforms(
    tmp_path, monkeypatch
):
    """AC-3 composed: on a not-offered turn NO sub-verdict says the effect conforms.

    The end the review actually hit. `corpus show` and the console iterate `sub_verdicts`
    and print each one, so the assertion is over the whole list rather than over the effect
    verdict alone — a fabricated conformance claim anywhere in that list is the defect,
    whichever sub-verdict carries it. Both A2 sub-verdicts must abstain; the turn's reduced
    status is UNVERIFIED before and after, which is what keeps this a partial-honesty repair
    rather than a verdict change.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, {"read_text_file"}, spy)

    verdict = verify_turn(
        _declared_records(tmp_path, "effect-composed"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    assert all(CONFORMS not in s.message for s in verdict.sub_verdicts), [
        s.message for s in verdict.sub_verdicts
    ]
    result = _result_sub(verdict)
    effect = _effect_sub(verdict)
    assert result.status is Status.UNVERIFIED, result.message
    assert effect.status is Status.UNVERIFIED, effect.message
    assert verdict.status is Status.UNVERIFIED, verdict


def test_the_network_boundary_is_still_declared_on_a_turn_that_never_ran(
    tmp_path, monkeypatch
):
    """`NOT_COVERED` survives the gate, deliberately — it is a fact about BELAY.

    `effect:network` says "Belay has no network instrument". That is true of every trace
    ever recorded, whether or not this particular turn was re-invoked, so gating it on
    `tool_offered` would make a permanent coverage boundary look like a per-run abstention
    and lose the declared-false-vs-silent distinction the whole `NOT_COVERED` release exists
    to keep. It never lifts a turn (`reduce` drops it) and it never PASSes, so leaving it in
    place cannot manufacture confidence.
    """
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply, set(), _DeterminismSpy())

    verdict = verify_turn(
        _declared_records(tmp_path, "effect-network"),
        0,
        server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",
    )

    net = next(s for s in verdict.sub_verdicts if s.kind == "effect:network")
    assert net.status is Status.NOT_COVERED, net
    assert "openWorldHint" in net.message, net.message


# --- 16. The offered path is untouched — the anti-overreach guard, effect edition ------


def test_an_offered_tool_still_renders_the_effect_verdict_it_always_did(tmp_path, monkeypatch):
    """The guard: gating the effect axis must not cost it a single verdict it used to make.

    Same trace, same delta, an OFFERED tool — the declared-false PASS is byte-identical to
    the ungated renderer's, message included. If this ever goes red, the gate has become a
    discriminator rather than a gate, and the effect axis has been quietly widened into an
    abstention machine exactly the way tests 1-6 forbid for the result axis.
    """
    records = _declared_records(tmp_path, "effect-offered")
    ungated = render_effect_verdict(records, 0, [])

    assert ungated.status is Status.PASS, ungated
    assert CONFORMS in ungated.message, ungated.message
    assert render_effect_verdict(records, 0, [], tool_offered=True) == ungated

    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply, {_RUN_TOOL}, _DeterminismSpy())
    composed = verify_turn(
        records, 0, server_command=shell_server_cmd(), manifest_dir="/nonexistent",
    )
    assert _effect_sub(composed) == ungated


# =====================================================================================
# Phase 6 — the aspect moves NOTHING else: the no-op regression and the two invariants
# =====================================================================================
#
# The abstention paths are pinned above. This section pins the far larger claim the aspect
# depends on for its whole release story: **no other verdict moved.** Two properties carry
# it, and neither may be asserted by reading the source.
#
# **AC-6 — a fully-offered trace is byte-identical to before this aspect.** The gate is keyed
# on DIVERGED, so on the overwhelmingly common turn — one that reproduced — no probe spawns,
# no classifier runs, and both A2 sub-verdicts must come out EXACTLY as the pre-aspect
# composition produced them. "Exactly" is checkable rather than assertable in prose: the
# pre-aspect composition WAS `render_result_verdict(reply, determinism)` +
# `render_effect_verdict(records, n, reply.delta)` + `network_subverdict(records, n)`, with
# no boundary argument in sight. Calling the renderers that way is calling yesterday's code,
# because `tool_offered=True` is the default on both and the default is the untouched path.
# The comparison is whole-`Verdict` equality — axis, kind, status, observed, expected AND
# message — so a changed word is a red test, not a shrug.
#
# **AC-8 — the trajectory axis structurally CANNOT see this aspect.** This is the load-bearing
# one, and it is what lets the record say the 2026-08-12 gate's 11/60 = 18.3% stands unedited.
# `assemble_turn_facts` (`src/belay/verify/trajectory.py:248-286`) reads exactly two fields off
# a `TurnVerdict` — `replayed_is_error` and `tool_name` — and never `.status` or `.cause`.
# The aspect changes `.status`, `.cause` and sub-verdict messages on a not-offered turn and
# touches neither of those two fields. That is an argument; the tests below are the proof:
#
#   (a) `replayed_is_error` is IDENTICAL across all three probe answers on the same replay —
#       it is a fact read off the replayed reply, not a consequence of the verdict.
#   (b) an instance-level trajectory verdict over such turns is IDENTICAL — same status, same
#       cause, same evidence count, same message.
#   (c) the seam is proved structurally too: mutating a not-offered verdict's `.status` to
#       FAIL and clearing its `.cause` changes NO turn fact. If a future edit ever taught
#       `assemble_turn_facts` to read the status, (c) goes red immediately — before any mint
#       re-derives a published number under a rule that quietly started seeing A2.
#
# These are guards, so they are GREEN on arrival, exactly like tests 1-6. Their teeth were
# shown by mutation, not by hoping. Three were run and reverted; none is in the tree:
#
#   * `assemble_turn_facts` fed `replayed=False` whenever the verdict's status is UNVERIFIED
#     — the most plausible way the AC-8 invariant would ever break. (a) stays green, (b) and
#     (c) both fail, which is exactly the discrimination those two exist for.
#   * the probe's `if reply.result_equivalence == DIVERGED` guard removed, so it fires on
#     every reply. `test_a_reply_that_reproduced_is_never_probed` and AC-6's first test fail.
#   * `render_effect_verdict`'s `tool_offered` default flipped from `True` to `None`, so the
#     gate abstains for every ungated caller. Both AC-6 tests fail.

import dataclasses  # noqa: E402

from belay.replay.engine import EQUAL as _EQUAL  # noqa: E402
from belay.verify.effect import network_subverdict  # noqa: E402
from belay.verify.invariants import (  # noqa: E402
    RULE_SUITE_BEFORE_SUCCESS_CLAIM,
    Invariant,
)
from belay.verify.trajectory import (  # noqa: E402
    assemble_turn_facts,
    evaluate_trajectory_invariant,
    offered_toolset,
)


def _fields(verdict) -> tuple:
    """Every field of a Verdict, so equality cannot pass on status alone."""
    return (
        verdict.axis, verdict.kind, verdict.status,
        verdict.observed, verdict.expected, verdict.message,
    )


# --- 17. AC-6: a fully-offered trace is what it always was ----------------------------


def test_a_fully_offered_trace_renders_exactly_the_pre_aspect_verdicts(tmp_path, monkeypatch):
    """AC-6: no probe, no classifier, and every sub-verdict identical to the ungated ones.

    The reply reproduced, so the gate never fires and the composed turn must be the one the
    engine produced before any of this existed. Reconstructing that composition from the
    pure renderers with NO boundary argument is not an approximation of the old code — it IS
    the old code path, since `tool_offered=True` is the default on both renderers and the
    default branch is the one this aspect left untouched.
    """
    records = _declared_records(tmp_path, "fully-offered")
    reply = TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        result_equivalence=_EQUAL,
        recorded_reply=IS_ERROR_RECORDED,
        replayed_reply=IS_ERROR_RECORDED,
        delta=[],
        boundary=ReplayBoundary(argv=("srv",), manifest_path="/manifests/abc.json"),
    )
    spy = _DeterminismSpy()
    probed = _wire(monkeypatch, reply, lambda _argv: {_RUN_TOOL}, spy)

    verdict = verify_turn(
        records, 0, server_command=shell_server_cmd(), manifest_dir="/nonexistent",
    )

    # The pre-aspect composition, called the pre-aspect way.
    expected = [
        render_result_verdict(reply, None),
        render_effect_verdict(records, 0, reply.delta),
    ]
    net = network_subverdict(records, 0)
    if net is not None:
        expected.append(net)

    assert probed == [], ("a reproduced reply must ask the boundary nothing", probed)
    assert spy.calls == 0, "and must classify nothing"
    assert [_fields(s) for s in verdict.sub_verdicts] == [_fields(s) for s in expected]
    assert verdict.status is Status.PASS, verdict
    assert verdict.cause is None, verdict


def test_a_diverged_offered_turn_also_renders_exactly_the_pre_aspect_verdicts(
    tmp_path, monkeypatch
):
    """AC-6's harder half: even where the probe DOES fire, an offered tool is unchanged.

    A reproduced turn never reaches the gate at all, which is a weak place to prove
    invariance. This one diverges, so the probe runs, answers "offered", and the classifier
    is consulted exactly as it always was — and the composed sub-verdicts must still equal
    the ungated renderers' output field for field, message included. This is where a gate
    that had quietly become a discriminator would show up.
    """
    records = _declared_records(tmp_path, "diverged-offered")
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    spy = _DeterminismSpy()
    _wire(monkeypatch, reply, lambda _argv: {_RUN_TOOL}, spy)

    verdict = verify_turn(
        records, 0, server_command=shell_server_cmd(), manifest_dir="/nonexistent",
    )

    determinism = DeterminismResult(
        turn_index=0, classification=DETERMINISTIC, replays=3, tool=RUN_TOOL
    )
    expected = [
        render_result_verdict(reply, determinism),
        render_effect_verdict(records, 0, reply.delta),
    ]
    net = network_subverdict(records, 0)
    if net is not None:
        expected.append(net)

    assert spy.calls == 1, spy.calls
    assert [_fields(s) for s in verdict.sub_verdicts] == [_fields(s) for s in expected]
    assert verdict.status is Status.FAIL, verdict


# --- 18. AC-8: the trajectory axis cannot see any of this -----------------------------


#: A verification claim in the classifier's closed vocabulary, and a seq after every frame
#: in the one-turn traces above, so the `run_process` turn counts as "before the claim".
_CLAIM_TEXT = "I ran the suite and verified the fix; the tests pass."
_CLAIM_SEQ = 10_000

TRAJECTORY_RULE = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)


def _turn_under(tmp_path, monkeypatch, name: str, offered):
    """One `verify_turn` over the same replay, differing ONLY in the probe's answer."""
    reply = _replayed_with_boundary(recorded=IS_ERROR_RECORDED, replayed=IS_ERROR_REPLAYED)
    _wire(monkeypatch, reply, offered, _DeterminismSpy())
    records = _declared_records(tmp_path, name)
    return records, verify_turn(
        records, 0, server_command=shell_server_cmd(), manifest_dir="/nonexistent",
    )


def _trajectory(records, verdict):
    """The instance-level trajectory verdict over one turn, through the narrow facts seam."""
    facts = assemble_turn_facts(records, {0: verdict})
    return facts, evaluate_trajectory_invariant(
        TRAJECTORY_RULE,
        claim_text=_CLAIM_TEXT,
        claim_seq=_CLAIM_SEQ,
        turn_facts=facts,
        toolset=offered_toolset(records, claim_seq=_CLAIM_SEQ),
    )


def test_replayed_is_error_is_unchanged_by_the_boundary_decision(tmp_path, monkeypatch):
    """AC-8 (a): the trajectory rule's evidence field is a fact of the REPLAY, not the verdict.

    `replayed_is_error` is read off the replayed reply's `result.isError`. The boundary
    decision changes the STATUS and the MESSAGES of a turn; it must not touch this, or every
    trajectory verdict ever computed over a not-offered turn would move and the 2026-08-12
    gate's numbers would need re-deriving. All three probe answers, one replay, one value.
    """
    _r1, offered = _turn_under(tmp_path, monkeypatch, "traj-offered", {_RUN_TOOL})
    _r2, absent = _turn_under(tmp_path, monkeypatch, "traj-absent", set())
    _r3, undecided = _turn_under(tmp_path, monkeypatch, "traj-undecided", None)

    assert offered.status is Status.FAIL and absent.status is Status.UNVERIFIED, (
        "the three answers must really differ, or this invariant is vacuous",
        offered.status, absent.status, undecided.status,
    )
    assert offered.replayed_is_error is True, offered
    assert absent.replayed_is_error == offered.replayed_is_error
    assert undecided.replayed_is_error == offered.replayed_is_error


def test_the_instance_trajectory_verdict_is_identical_before_and_after(tmp_path, monkeypatch):
    """AC-8 (b): the whole instance-level verdict is identical across the three answers.

    Not just the evidence field — the rule's OUTPUT. Same status, same cause, same evidence,
    same message, whether the boundary offered the tool, said it did not, or could not be
    read. That is the sentence the release needs: this unit is strictly A2, and no A1
    trajectory number can have moved under it.
    """
    records_a, offered = _turn_under(tmp_path, monkeypatch, "traj-v-offered", {_RUN_TOOL})
    records_b, absent = _turn_under(tmp_path, monkeypatch, "traj-v-absent", set())
    records_c, undecided = _turn_under(tmp_path, monkeypatch, "traj-v-undecided", None)

    facts_a, verdict_a = _trajectory(records_a, offered)
    facts_b, verdict_b = _trajectory(records_b, absent)
    facts_c, verdict_c = _trajectory(records_c, undecided)

    assert facts_a == facts_b == facts_c, (facts_a, facts_b, facts_c)
    assert _fields(verdict_a) == _fields(verdict_b) == _fields(verdict_c), (
        verdict_a, verdict_b, verdict_c,
    )


def test_the_turn_facts_seam_cannot_read_a_status_or_a_cause(tmp_path, monkeypatch):
    """AC-8 (c): the STRUCTURAL proof, so the invariant survives a future edit.

    (a) and (b) show the invariant holds for the values this aspect produces. This shows
    WHY, and it is the half that keeps holding when someone later adds a field to
    `TurnVerdict` or a branch to the trajectory rule: the same verdict with its `.status`
    forced to FAIL and its `.cause` cleared — a mutation far larger than anything this
    aspect makes — yields byte-identical turn facts, because `assemble_turn_facts` reads
    only `replayed_is_error` and `tool_name`. The day that stops being true, this goes red.
    """
    records, absent = _turn_under(tmp_path, monkeypatch, "traj-structural", set())

    mutated = dataclasses.replace(
        absent, status=Status.FAIL, cause=None, sub_verdicts=[],
    )

    assert assemble_turn_facts(records, {0: absent}) == assemble_turn_facts(
        records, {0: mutated}
    ), "the trajectory facts seam must be blind to a turn's status, cause and sub-verdicts"
