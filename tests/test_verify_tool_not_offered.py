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

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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
    not_offered = next(
        s
        for s in verify_turn(
            _run_process_records(tmp_path, "probe-not-offered"),
            0,
            server_command=shell_server_cmd(),
            manifest_dir="/nonexistent",
        ).sub_verdicts
        if s.kind == "replay"
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

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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
    assert next(s for s in single.sub_verdicts if s.kind == "replay").status is Status.FAIL
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

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
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
    assert next(s for s in verdict.sub_verdicts if s.kind == "replay").status is Status.PASS
