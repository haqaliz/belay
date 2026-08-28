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
