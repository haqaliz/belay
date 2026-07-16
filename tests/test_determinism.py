"""Nondeterminism detection: replay a turn N times and CLASSIFY, never judge.

C3 replays a recorded turn against its restored pre-state. This module decides
the prior question — *is the tool replayable to the same result at all?* A
clock-dependent or random tool diverges across identical replays, and that
divergence is **legitimate nondeterminism, not a fabricated trace**. C2's sharpest
warning is the whole reason this exists:

    "Never let a timestamp diff render as FAIL — that's how you train users to
    ignore the verifier."

So the classifier replays N times from the SAME pre-state (each replay a fresh
scratch restore, so all N start identical) and reports `DETERMINISTIC` /
`NONDETERMINISTIC` — a classification, **never a verdict**. C4 decides what it
means. If a PASS/FAIL ever appears below, it is in the wrong capability.

Two disciplines carry this file:

- **The positive control is not optional.** A classifier that called EVERYTHING
  nondeterministic would pass the clock and random tests vacuously.
  `test_deterministic_tool_is_classified_deterministic` is the tool that must
  come back DETERMINISTIC, and it is what gives the other two teeth.
- **N=3 is the floor.** N=2 cannot tell a one-off flake from a genuinely random
  tool. The parameter is honoured (`test_replays_parameter_is_honoured`) and its
  default is 3.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from belay.replay import determinism
from belay.replay.determinism import (
    DETERMINISTIC,
    NONDETERMINISTIC,
    NOT_REPLAYABLE,
    classify_determinism,
    detect_axis,
)
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import (
    CAUSES_DEFERRED,
    CAUSES_RAISED_HERE,
    RAISED_BY,
    UnrestorableCause,
    present_handle,
    take_snapshot,
)
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
NONDET = FIXTURES / "nondeterministic_server.py"
DIES_MIDWAY = FIXTURES / "dies_midway_server.py"

CONFORMING_CMD = [sys.executable, str(CONFORMING)]
NONDET_CMD = [sys.executable, str(NONDET)]
DIES_MIDWAY_CMD = [sys.executable, str(DIES_MIDWAY)]

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- rig ---------------------------------------------------------------------


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> tuple[Path, list[dict]]:
    """Build a real trace via `TraceWriter`; return its path AND its records.

    The path is returned so a test can assert the source file is byte-unchanged
    after classification — the A4 guarantee that replay never mutates the trace.
    """
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
    records = [json.loads(line) for line in path.read_bytes().split(b"\n") if line]
    return path, records


def _snapshot(tmp_path: Path, name: str, contents: dict[str, str]) -> tuple[Path, dict]:
    work = tmp_path / f"{name}-work"
    work.mkdir()
    for filename, text in contents.items():
        (work / filename).write_text(text)
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / "m.json")
    return manifest_dir, present_handle(snap)


def _call(msg_id: int, name: str) -> bytes:
    """A 2026-shape `tools/call` (no handshake; `_meta` carries the version)."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": {},
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
            },
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


# --- 1. A3: a CLOCK tool is NONDETERMINISTIC, not a FAIL/divergence -----------


@darwin_only
def test_a3_clock_tool_is_nondeterministic_not_a_verdict(tmp_path, monkeypatch):
    """A tool whose result embeds `time.time_ns()` is classified NONDETERMINISTIC.

    This is C2's warning made executable: a timestamp diff must never surface as a
    FAIL or as `diverged`-as-infidelity. The classifier replays the turn 3 times
    from the same pre-state, sees the reply differ, and reports a **classification**
    — not a verdict, not the engine's `DIVERGED` result-equivalence. The axis is
    named `UNRESTORABLE_WALL_CLOCK` because the divergence is a monotone timestamp.
    """
    monkeypatch.setenv("BELAY_TEST_NONDET_SOURCE", "clock")
    manifest_dir, handle = _snapshot(tmp_path, "clock", {"keep.txt": "x"})
    _path, records = _trace(tmp_path, "clock", [("c2s", _call(2, "tick"), handle)])

    out = classify_determinism(
        records, 0, server_command=NONDET_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert out.classification == NONDETERMINISTIC, out
    # It is a determinism classification, NOT a PASS/FAIL and NOT the engine's
    # result-equivalence verdict. Those words must not appear as the answer.
    assert out.classification not in {"PASS", "FAIL", "WARN", "UNVERIFIED", "diverged"}
    assert out.axis is UnrestorableCause.UNRESTORABLE_WALL_CLOCK, out
    assert out.replays == 3
    assert out.tool == "tick"


# --- 2. A RANDOM tool is NONDETERMINISTIC ------------------------------------


@darwin_only
def test_random_tool_is_nondeterministic(tmp_path, monkeypatch):
    """128 bits of entropy in the reply -> NONDETERMINISTIC, axis RANDOMNESS."""
    monkeypatch.setenv("BELAY_TEST_NONDET_SOURCE", "random")
    manifest_dir, handle = _snapshot(tmp_path, "rand", {"keep.txt": "x"})
    _path, records = _trace(tmp_path, "rand", [("c2s", _call(2, "roll"), handle)])

    out = classify_determinism(
        records, 0, server_command=NONDET_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert out.classification == NONDETERMINISTIC, out
    assert out.axis is UnrestorableCause.UNRESTORABLE_RANDOMNESS, out


# --- 3. POSITIVE CONTROL: a DETERMINISTIC tool is DETERMINISTIC ---------------


@darwin_only
def test_deterministic_tool_is_classified_deterministic(tmp_path):
    """The anti-vacuity control: a pure-function tool comes back DETERMINISTIC.

    `conforming_server`'s echo is a pure function of its arguments, so 3 replays
    from the same pre-state produce byte-identical replies. Without this test, a
    classifier that called everything NONDETERMINISTIC would pass tests 1 and 2
    while being useless. This is what makes them mean something.
    """
    manifest_dir, handle = _snapshot(tmp_path, "det", {"keep.txt": "x"})
    _path, records = _trace(tmp_path, "det", [("c2s", _call(2, "echo"), handle)])

    out = classify_determinism(
        records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert out.classification == DETERMINISTIC, out
    assert out.axis is None, "a deterministic tool has no nondeterminism axis"
    assert out.replays == 3


# --- 4. N=2 vs N=3: the replay count is honoured -----------------------------


@darwin_only
def test_replays_parameter_is_honoured(tmp_path, monkeypatch):
    """`replays` actually drives how many times the turn is re-invoked.

    N=2 cannot tell a one-off flake from a genuinely random tool — with two runs
    they look identical — which is why the default is 3. The parameter must be
    real, not decorative: a spy on the engine's `replay_turn` counts the calls for
    replays=2 and replays=3 and they match. A deterministic tool is used so the
    classification is stable and only the count is under test.
    """
    manifest_dir, handle = _snapshot(tmp_path, "count", {"keep.txt": "x"})
    _path, records = _trace(tmp_path, "count", [("c2s", _call(2, "echo"), handle)])

    calls = {"n": 0}
    real = determinism.replay_turn

    def counting_replay_turn(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(determinism, "replay_turn", counting_replay_turn)

    calls["n"] = 0
    two = classify_determinism(
        records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir,
        replays=2, timeout=15.0,
    )
    assert calls["n"] == 2, "replays=2 must re-invoke the turn exactly twice"
    assert two.replays == 2

    calls["n"] = 0
    three = classify_determinism(
        records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir,
        replays=3, timeout=15.0,
    )
    assert calls["n"] == 3, "replays=3 must re-invoke the turn exactly three times"
    assert three.replays == 3


# --- 5. The record is appended to a SIBLING, never the source trace ----------


@darwin_only
def test_nondeterminism_record_is_appended_to_a_sibling_not_the_source(
    tmp_path, monkeypatch
):
    """A4: replay never mutates the original trace.

    Classifying appends a `nondeterminism` record — but to a SIBLING artifact, not
    the source trace, which is append-only and must stay byte-for-byte what C1
    wrote. The source file's hash is identical before and after; the sibling holds
    the record naming the tool, turn, classification, replays and axis.
    """
    monkeypatch.setenv("BELAY_TEST_NONDET_SOURCE", "clock")
    manifest_dir, handle = _snapshot(tmp_path, "sib", {"keep.txt": "x"})
    source_path, records = _trace(tmp_path, "sib", [("c2s", _call(2, "tick"), handle)])

    before = hashlib.sha256(source_path.read_bytes()).hexdigest()
    artifact_path = tmp_path / "sib-nondeterminism.jsonl"

    out = classify_determinism(
        records, 0, server_command=NONDET_CMD, manifest_dir=manifest_dir,
        artifact_path=artifact_path, timeout=15.0,
    )

    after = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert after == before, "the source trace was mutated — A4 violated"
    assert artifact_path != source_path

    sibling = [
        json.loads(line)
        for line in artifact_path.read_bytes().split(b"\n")
        if line
    ]
    marks = [r for r in sibling if r.get("kind") == "nondeterminism"]
    assert len(marks) == 1, sibling
    mark = marks[0]
    assert mark["classification"] == NONDETERMINISTIC
    assert mark["tool"] == "tick"
    assert mark["turn"] == 0
    assert mark["replays"] == 3
    assert mark["axis"] == UnrestorableCause.UNRESTORABLE_WALL_CLOCK.value
    assert out.classification == NONDETERMINISTIC


# --- 6a. The enum invariant survives C3 wiring in its three causes -----------


def test_enum_invariant_still_holds_with_c3_causes_accounted_for():
    """18 causes, partitioned, 0 unaccounted — and C3 owns exactly three.

    Raising the three inherited causes from C3 must not break the substrate
    partition. They stay DEFERRED *from substrate's lstat* (a running process,
    entropy and the wall clock are all invisible to a tree scan) and are owned by
    C3 in `RAISED_BY`. The partition is exactly as before; this pins it so a later
    edit that quietly drops one fails the build.
    """
    assert CAUSES_RAISED_HERE.isdisjoint(CAUSES_DEFERRED)
    assert CAUSES_RAISED_HERE | CAUSES_DEFERRED == set(UnrestorableCause)

    c3_causes = {
        UnrestorableCause.UNRESTORABLE_RUNNING_PROCESS,
        UnrestorableCause.UNRESTORABLE_RANDOMNESS,
        UnrestorableCause.UNRESTORABLE_WALL_CLOCK,
    }
    for cause in c3_causes:
        assert cause in CAUSES_DEFERRED, f"{cause} must stay deferred from substrate"
        assert "C3" in RAISED_BY[cause], f"{cause} must name C3 as its owner"


# --- 6b. C3 actually PRODUCES those three causes (reachability) --------------


def test_c3_axes_are_actually_produced():
    """The analogue of substrate's reachability test: no cause C3 cannot produce.

    `RAISED_BY` claims C3 raises WALL_CLOCK, RANDOMNESS and RUNNING_PROCESS. This
    reaches every one through the real `detect_axis`, from replies shaped exactly
    as the fixtures emit — so the claim is backed by production code, not prose. A
    deterministic (byte-identical) reply set is the control: it names no axis.
    """
    clock = [_reply(2, "1700000000000000001"), _reply(2, "1700000000000000042"),
             _reply(2, "1700000000000000099")]
    rand = [_reply(2, "%032x" % 0xA3F91), _reply(2, "b" * 32), _reply(2, "c" * 32)]
    pid = [_reply(2, "4011"), _reply(2, "4012"), _reply(2, "5090")]
    same = [_reply(2, "hi"), _reply(2, "hi"), _reply(2, "hi")]

    assert detect_axis(clock) is UnrestorableCause.UNRESTORABLE_WALL_CLOCK
    assert detect_axis(rand) is UnrestorableCause.UNRESTORABLE_RANDOMNESS
    assert detect_axis(pid) is UnrestorableCause.UNRESTORABLE_RUNNING_PROCESS
    assert detect_axis(same) is None

    produced = {detect_axis(clock), detect_axis(rand), detect_axis(pid)}
    assert produced == {
        UnrestorableCause.UNRESTORABLE_WALL_CLOCK,
        UnrestorableCause.UNRESTORABLE_RANDOMNESS,
        UnrestorableCause.UNRESTORABLE_RUNNING_PROCESS,
    }


# --- 7. A turn whose replay never answers the target is NOT_REPLAYABLE --------


def _initialize(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        }
    ).encode()


def _initialize_reply(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": version, "capabilities": {}, "serverInfo": {"name": "x", "version": "1"}},
        }
    ).encode()


_INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'


@darwin_only
def test_replay_that_never_answers_target_is_not_replayable_never_deterministic(tmp_path):
    """A turn whose re-invoked server never answers the target classifies
    NOT_REPLAYABLE — never DETERMINISTIC on a set of `None` replies.

    `dies_midway_server` answers the `initialize` handshake then exits, so the
    `tools/call` target is answered by no run. Before the fix each run's signature was
    `(None, delta)`, all N matched, and the turn was called DETERMINISTIC — the
    module's most reassuring label ("replayable, and A2 can speak to it") for a turn
    that answered nothing N times, a false-PASS-shaped observation fed to C4. The
    engine now returns UNVERIFIED for such a turn, so the classifier sees a non-REPLAYED
    status on the first run and honestly reports NOT_REPLAYABLE, carrying the cause.
    """
    manifest_dir, handle = _snapshot(tmp_path, "noans", {"keep.txt": "x"})
    _path, records = _trace(
        tmp_path,
        "noans",
        [
            ("c2s", _initialize("2025-11-25"), None),
            ("s2c", _initialize_reply("2025-11-25"), None),
            ("c2s", _INITIALIZED, None),
            ("c2s", _call(2, "tick"), handle),
            ("s2c", _reply(2, "hi"), None),
        ],
    )

    out = classify_determinism(
        records, 0, server_command=DIES_MIDWAY_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert out.classification == NOT_REPLAYABLE, out
    assert out.classification != DETERMINISTIC
    assert out.replay_status is not None
    assert out.cause is not None and "did not answer the target frame" in out.cause, out.cause
    assert out.replies is None, "a NOT_REPLAYABLE turn claims no reply set, least of all [None, None, None]"
