"""A2 result-equivalence, gated on determinism — the first place C4 can lie.

C3's `engine.replay_turn` OBSERVES whether a replayed reply matched the recorded one
(`result_equivalence` EQUAL / DIVERGED / None). C4 turns that observation into a
grounded A2 verdict — but a single replay knows NOTHING about determinism, and a clock
or random tool DIVERGES on re-execution legitimately. Promoting that to FAIL is C2's
exact warning ("never let a timestamp diff render as FAIL — that's how you train users
to ignore the verifier"). So the rule is gated:

    EQUAL                      -> PASS                    (one replay; do NOT classify)
    DIVERGED + DETERMINISTIC   -> FAIL  (+ recorded-vs-observed diff, or "unparseable")
    DIVERGED + NONDETERMINISTIC-> UNVERIFIED (carry the axis; NEVER FAIL)
    DIVERGED + NOT_REPLAYABLE  -> UNVERIFIED
    None (nothing to compare)  -> UNVERIFIED

Two tests are the load-bearing controls and each was watched RED first:

- **A1 (positive control):** a fabricated result on a DETERMINISTIC tool -> FAIL. Watched
  failing against a stub that returns PASS for everything, proving FAIL is reachable.
- **A3 (the gate):** a clock tool that diverges across replays -> UNVERIFIED, not FAIL.
  Watched failing against a naive no-gate implementation that returns FAIL on any
  divergence. This is the whole reason the phase exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.replay.determinism import DETERMINISTIC, NONDETERMINISTIC, NOT_REPLAYABLE, DeterminismResult
from belay.replay.engine import DIVERGED, EQUAL, REPLAYED, TurnReplay
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify import result as result_module
from belay.verify.result import render_result_verdict, verify_result
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
NONDET = FIXTURES / "nondeterministic_server.py"

CONFORMING_CMD = [sys.executable, str(CONFORMING)]
NONDET_CMD = [sys.executable, str(NONDET)]

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- rig (mirrors test_replay_engine / test_determinism) ---------------------


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted(trace_dir.glob("*.jsonl"))[0]
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _snapshot(tmp_path: Path, name: str, contents: dict[str, str]) -> tuple[Path, dict]:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    for filename, text in contents.items():
        (work / filename).write_text(text)
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / "m.json")
    return manifest_dir, present_handle(snap)


def _call(msg_id: int, name: str, arguments: dict | None = None) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
            },
        }
    ).encode()


def _reply(msg_id: int, text: str) -> bytes:
    """A conforming-server-shaped tools/call result carrying `text`."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


# --- 1. A2 PASS: a clean deterministic turn reproduces ------------------------


@darwin_only
def test_a2_clean_deterministic_turn_is_pass(tmp_path):
    """A recorded echo turn whose reply reproduces on replay -> PASS, kind="replay".

    The recorded reply and the replayed one are the same message, so C3 reports EQUAL
    and C4 emits a grounded A2 PASS. The determinism classifier is NOT consulted — an
    EQUAL turn is a reproduction at one replay (see the cost-control test).
    """
    manifest_dir, handle = _snapshot(tmp_path, "pass", {"keep.txt": "x"})
    records = _trace(
        tmp_path,
        "pass",
        [
            ("c2s", _call(2, "echo", {"s": "hi"}), handle),
            ("s2c", _reply(2, "hi"), None),
        ],
    )

    verdict = verify_result(
        records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert verdict.status is Status.PASS, verdict
    assert verdict.axis == "A2"
    assert verdict.kind == "replay"


# --- 2. A1 FAIL (positive control): a fabricated result on a DETERMINISTIC tool


@darwin_only
def test_a1_fabricated_result_on_deterministic_tool_is_fail_with_diff(tmp_path):
    """The trace CLAIMS one reply; the deterministic tool reproduces a DIFFERENT one -> FAIL.

    `echo` is a pure function of its arguments, so replaying `{"s": "REAL-OUTPUT"}` always
    yields "REAL-OUTPUT". The recorded reply instead claims "FABRICATED-CLAIM" — trace
    infidelity. Because the tool is deterministic the divergence is grounded, so the
    verdict is FAIL and the message carries the exact recorded-vs-observed diff.

    This is the positive control: it was watched failing against a stub that returns PASS
    for everything, proving FAIL is reachable and not vacuously unreachable.
    """
    manifest_dir, handle = _snapshot(tmp_path, "fab", {"keep.txt": "x"})
    records = _trace(
        tmp_path,
        "fab",
        [
            ("c2s", _call(2, "echo", {"s": "REAL-OUTPUT"}), handle),
            ("s2c", _reply(2, "FABRICATED-CLAIM"), None),
        ],
    )

    verdict = verify_result(
        records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert verdict.status is Status.FAIL, verdict
    assert verdict.axis == "A2" and verdict.kind == "replay"
    assert "FABRICATED-CLAIM" in verdict.message, verdict.message
    assert "REAL-OUTPUT" in verdict.message, verdict.message


# --- 3. A3 THE GATE: a clock tool diverges -> UNVERIFIED, NEVER FAIL ----------


@darwin_only
def test_a3_clock_tool_divergence_is_unverified_not_fail(tmp_path, monkeypatch):
    """A tool whose reply embeds `time.time_ns()` diverges on replay -> UNVERIFIED.

    This is the single most likely place C4 produces a false verdict. The recorded reply
    cannot match the fresh timestamp, so C3 reports DIVERGED — but the determinism gate
    classifies the tool NONDETERMINISTIC (WALL_CLOCK axis) across three replays, so the
    divergence is legitimate and the verdict is UNVERIFIED, NEVER FAIL. A naive no-gate
    implementation returns FAIL here; that was watched RED first.
    """
    monkeypatch.setenv("BELAY_TEST_NONDET_SOURCE", "clock")
    manifest_dir, handle = _snapshot(tmp_path, "clock", {"keep.txt": "x"})
    records = _trace(
        tmp_path,
        "clock",
        [
            ("c2s", _call(2, "tick"), handle),
            ("s2c", _reply(2, "0000000000000000000"), None),
        ],
    )

    verdict = verify_result(
        records, 0, server_command=NONDET_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.FAIL
    assert "UNRESTORABLE_WALL_CLOCK" in verdict.message, verdict.message


# --- 4. Malformed replayed reply: distinct grounding, distinct message --------


def test_malformed_replayed_reply_message_differs_from_a_value_mismatch():
    """An unparseable replayed reply is a DISTINCT grounding from a value mismatch.

    C3's `_equivalence` returns DIVERGED both for a genuinely different value and for a
    replayed reply that fails to parse. The FAIL message must say WHICH. Rendered from a
    constructed observation (the live client only surfaces parseable, id-matched replies,
    so this branch is defensive but load-bearing): the malformed message names the parse
    failure plainly and must NOT read as a value diff.
    """
    det = DeterminismResult(turn_index=0, classification=DETERMINISTIC, replays=3, tool="brk")

    value_mismatch = render_result_verdict(
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(2, "FABRICATED-CLAIM"),
            replayed_reply=_reply(2, "REAL-OUTPUT"),
        ),
        det,
    )
    malformed = render_result_verdict(
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(2, "FABRICATED-CLAIM"),
            replayed_reply=b"<<<this is not json>>>",
        ),
        det,
    )

    assert value_mismatch.status is Status.FAIL
    assert malformed.status is Status.FAIL
    assert malformed.message != value_mismatch.message
    assert "pars" in malformed.message.lower(), malformed.message
    assert "REAL-OUTPUT" in value_mismatch.message


# --- 5. None equivalence: nothing to compare -> UNVERIFIED -------------------


def test_none_equivalence_is_unverified():
    """A turn with no reply to compare (recording had none, or nothing answered) is
    UNVERIFIED — never PASS. Nothing was verified, so nothing is passed."""
    verdict = render_result_verdict(
        TurnReplay(turn_index=0, status=REPLAYED, result_equivalence=None, replayed_reply=_reply(2, "hi")),
        None,
    )
    assert verdict.status is Status.UNVERIFIED, verdict


def test_nondeterministic_without_a_named_axis_is_still_unverified():
    """`axis=None` is a valid honest outcome: nondeterministic, source not legible. It
    is UNVERIFIED all the same — a divergence we cannot attribute is never a FAIL."""
    det = DeterminismResult(turn_index=0, classification=NONDETERMINISTIC, replays=3, tool="t", axis=None)
    verdict = render_result_verdict(
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(2, "a"),
            replayed_reply=_reply(2, "b"),
        ),
        det,
    )
    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.FAIL


def test_not_replayable_divergence_is_unverified():
    """DIVERGED but the classifier could not re-run the turn enough to decide
    (NOT_REPLAYABLE) -> UNVERIFIED. A divergence we cannot ground is not a FAIL."""
    det = DeterminismResult(
        turn_index=0, classification=NOT_REPLAYABLE, replays=1, tool="t",
        replay_status="unverified", cause="pre-state could not be restored",
    )
    verdict = render_result_verdict(
        TurnReplay(
            turn_index=0,
            status=REPLAYED,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(2, "a"),
            replayed_reply=_reply(2, "b"),
        ),
        det,
    )
    assert verdict.status is Status.UNVERIFIED, verdict


# --- 6. Cost control: classify is NEVER called on an EQUAL turn ---------------


def test_classify_determinism_is_not_called_on_an_equal_turn(monkeypatch):
    """An EQUAL turn is PASS at ONE replay; the determinism classifier must not run.

    Classifying an EQUAL turn buys nothing (a match is a reproduction) and triples the
    replay cost. `replay_turn` is stubbed to report EQUAL and `classify_determinism` is
    spied: it must not be touched, and the verdict must be PASS.
    """
    calls = {"n": 0}

    def fake_replay_turn(*args, **kwargs):
        return TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=_reply(2, "hi"),
            replayed_reply=_reply(2, "hi"),
        )

    def spy_classify(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("classify_determinism must not run on an EQUAL turn")

    monkeypatch.setattr(result_module, "replay_turn", fake_replay_turn)
    monkeypatch.setattr(result_module, "classify_determinism", spy_classify)

    verdict = verify_result(
        [], 0, server_command=CONFORMING_CMD, manifest_dir=tmp_manifest(),
    )

    assert calls["n"] == 0, "classify_determinism was called on an EQUAL turn"
    assert verdict.status is Status.PASS, verdict


def test_classify_determinism_runs_on_a_diverged_turn(monkeypatch):
    """The gate's positive control: a DIVERGED turn DOES consult the classifier.

    The cost-control test above would pass vacuously if the orchestrator never called
    `classify_determinism` at all. This proves it does — exactly once — on divergence,
    which is the branch the whole gate hangs on.
    """
    calls = {"n": 0}

    def fake_replay_turn(*args, **kwargs):
        return TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=DIVERGED,
            recorded_reply=_reply(2, "a"),
            replayed_reply=_reply(2, "b"),
        )

    def spy_classify(*args, **kwargs):
        calls["n"] += 1
        return DeterminismResult(turn_index=0, classification=NONDETERMINISTIC, replays=3, tool="t", axis=None)

    monkeypatch.setattr(result_module, "replay_turn", fake_replay_turn)
    monkeypatch.setattr(result_module, "classify_determinism", spy_classify)

    verdict = verify_result(
        [], 0, server_command=CONFORMING_CMD, manifest_dir=tmp_manifest(),
    )

    assert calls["n"] == 1, "a DIVERGED turn must consult the determinism classifier exactly once"
    assert verdict.status is Status.UNVERIFIED, verdict


def tmp_manifest() -> Path:
    """A placeholder path for the stubbed tests, which never touch disk."""
    return Path("/nonexistent-manifest-dir")
