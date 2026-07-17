"""Single-turn replay: the first real re-execution, observed and never judged.

`engine.replay_turn(records, n, ...)` composes every earlier replay piece into one
act: pick the Nth recorded `tools/call`, restore the pre-state it ran against,
re-invoke it against a fresh sandboxed server, and capture the reply and the
field-level workspace delta. It emits **observations** — `replayed` (with a delta and
a result-equivalence fact), `unverified` (a named cause, and crucially no
re-invocation), `not-verifiable` (un-snapshotted) — never PASS/FAIL. C4 renders the
verdict; this suite pins that C3 produces the honest raw material and nothing more.

The load-bearing discipline, tested twice over: when a turn CANNOT be replayed, the
engine says so with the recorded cause and does **not** fabricate a result. A2 pairs
that with a positive control — a `present` turn in the SAME test that DOES get
re-invoked — so "no result" can never pass merely because replay is broken.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.replay import engine
from belay.replay.client import ANSWERED, FrameOutcome, ReplayResult
from belay.replay.engine import (
    DIVERGED,
    EQUAL,
    NOT_VERIFIABLE,
    REPLAYED,
    UNVERIFIED,
    replay_turn,
)
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import UnrestorableCause, present_handle, take_snapshot
from belay.sandbox.gate import SNAPSHOT_FAILED
from belay.trace import TraceWriter
from belay.verify.effect import render_effect_verdict
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
MUTATING = FIXTURES / "mutating_server.py"
DIES_MIDWAY = FIXTURES / "dies_midway_server.py"

CONFORMING_CMD = [sys.executable, str(CONFORMING)]
MUTATING_CMD = [sys.executable, str(MUTATING)]
DIES_MIDWAY_CMD = [sys.executable, str(DIES_MIDWAY)]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="replay re-invokes inside the macOS Seatbelt sandbox"
)


# --- rig ---------------------------------------------------------------------


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Build a real trace via `TraceWriter` and read its records back.

    Each frame is `(direction, raw_bytes, state_handle_or_None)`; a handle is pinned
    to that exact frame via `set_state_handle(..., frame=...)`. Going through the real
    writer keeps the records the exact envelope the engine reads in production, rather
    than a fabricated shape that could drift from it silently.
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
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _snapshot(tmp_path: Path, name: str, contents: dict[str, str]) -> tuple[Path, dict]:
    """A workspace with `contents`, snapshotted and persisted; returns the manifest
    directory and the `present` state handle naming that snapshot."""
    work = tmp_path / f"{name}-work"
    work.mkdir()
    for filename, text in contents.items():
        (work / filename).write_text(text)
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / "m.json")
    return manifest_dir, present_handle(snap)


def _echo_call(msg_id: int, text: str, *, meta: dict | None = None) -> bytes:
    params: dict = {"name": "echo", "arguments": {"s": text}}
    if meta is not None:
        params["_meta"] = meta
    return json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": params}
    ).encode()


def _echo_reply(msg_id: int, text: str) -> bytes:
    """The message `conforming_server` returns for an echo `tools/call`, semantically."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _initialize(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        }
    ).encode()


def _initialize_reply(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": version,
                "capabilities": {},
                "serverInfo": {"name": "x", "version": "1"},
            },
        }
    ).encode()


INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'


# --- 1. A1: a clean recorded run replays with result-equivalence -------------


def test_a1_clean_run_replays_with_result_equivalence(tmp_path):
    """A recorded echo turn, replayed, yields the same reply — an OBSERVATION.

    The recorded response and the replayed one are the same message, so
    `result_equivalence` is EQUAL and the parsed replies match. No verdict is emitted;
    equivalence is a fact C4 will weigh, not a PASS this module hands out.
    """
    manifest_dir, handle = _snapshot(tmp_path, "a1", {"keep.txt": "x"})
    call = _echo_call(2, "hi")
    records = _trace(
        tmp_path,
        "a1",
        [
            ("c2s", _initialize("2025-11-25"), None),
            ("s2c", _initialize_reply("2025-11-25"), None),
            ("c2s", INITIALIZED, None),
            ("c2s", call, handle),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.reinvoked is True
    assert out.result_equivalence == EQUAL, (
        f"the replayed reply diverged from the recorded one: {out.replayed_reply!r}"
    )
    assert json.loads(out.replayed_reply) == json.loads(_echo_reply(2, "hi"))
    assert out.recorded_version == "2025-11-25"
    assert out.replayed_version == "2025-11-25"
    assert out.version_drift is False


# --- 2. A2: an unrestorable turn is unverified with cause and NOT re-invoked --


def test_a2_unrestorable_turn_is_unverified_and_not_reinvoked(tmp_path):
    """An `unrestorable` turn yields `unverified` + its cause and NO result, while a
    `present` turn in the SAME trace really does get re-invoked.

    The positive control is the whole point: without a turn that DOES replay, "no
    result" on the unrestorable turn could just mean replay is broken. Here it is not
    — turn 1 spawns the server and gets its reply, so turn 0's silence is a decision,
    not a failure.
    """
    manifest_dir, present = _snapshot(tmp_path, "a2", {"keep.txt": "x"})
    unrestorable = {
        "status": "unrestorable",
        "cause": UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value,
    }
    records = _trace(
        tmp_path,
        "a2",
        [
            ("c2s", _echo_call(10, "no"), unrestorable),
            ("c2s", _echo_call(2, "yes"), present),
            ("s2c", _echo_reply(2, "yes"), None),
        ],
    )

    blocked = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)
    assert blocked.status == UNVERIFIED
    assert blocked.cause == "UNRESTORABLE_CONCURRENT_TURN"
    assert blocked.reinvoked is False, "an unrestorable turn must NOT re-invoke the server"
    assert blocked.replayed_reply is None
    assert blocked.delta is None

    replayed = replay_turn(records, 1, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)
    assert replayed.status == REPLAYED, "positive control: the present turn must re-invoke"
    assert replayed.reinvoked is True
    assert replayed.replayed_reply is not None
    assert json.loads(replayed.replayed_reply)["id"] == 2


# --- 3. The SNAPSHOT_FAILED parse trap ---------------------------------------


def test_snapshot_failed_cause_is_carried_without_parsing_it(tmp_path):
    """`UNRESTORABLE_SNAPSHOT_FAILED` is handled as a string, never through the enum.

    The gate emits this cause deliberately as a NON-member of `UnrestorableCause`, so
    `UnrestorableCause(cause)` would throw. The engine must carry the recorded string
    verbatim. The `pytest.raises` below proves the trap is real; the replay proves the
    engine does not step in it.
    """
    with pytest.raises(ValueError):
        UnrestorableCause(SNAPSHOT_FAILED)

    manifest_dir, _present = _snapshot(tmp_path, "trap", {"keep.txt": "x"})
    records = _trace(
        tmp_path,
        "trap",
        [("c2s", _echo_call(2, "no"), {"status": "unrestorable", "cause": SNAPSHOT_FAILED})],
    )

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == UNVERIFIED
    assert out.cause == SNAPSHOT_FAILED == "UNRESTORABLE_SNAPSHOT_FAILED"
    assert out.reinvoked is False


# --- 4. A8: a trace with NO handshake still replays ---------------------------


def test_a8_no_handshake_trace_still_replays(tmp_path):
    """A 2026-07-28-shape trace — no `initialize` frames, `_meta` on the tools/call —
    still re-invokes the target.

    There is no handshake to gather, so the engine sends the target alone; the
    stateless server answers it. No negotiated version comes back, which is not drift,
    just nothing to compare.
    """
    manifest_dir, handle = _snapshot(tmp_path, "a8", {"keep.txt": "x"})
    call = _echo_call(2, "hi", meta={"io.modelcontextprotocol/protocolVersion": "2026-07-28"})
    records = _trace(
        tmp_path,
        "a8",
        [
            ("c2s", call, handle),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.reinvoked is True
    assert out.replayed_reply is not None
    assert json.loads(out.replayed_reply)["id"] == 2
    assert out.recorded_version == "2026-07-28"
    assert out.replayed_version is None
    assert out.version_drift is False


# --- 5. The state delta names the field --------------------------------------


def test_delta_names_the_written_file(tmp_path, monkeypatch):
    """A server that writes a file yields a delta whose FieldDiff points at that path.

    `mutating_server` clobbers `clobbered.txt` in its cwd (the scratch copy). The delta
    must name that exact path — not merely report that "something changed".
    """
    monkeypatch.setenv("BELAY_TEST_MUTATE_PATH", "clobbered.txt")
    manifest_dir, handle = _snapshot(tmp_path, "delta", {"keep.txt": "x"})
    call = b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"clobber","arguments":{}}}'
    records = _trace(tmp_path, "delta", [("c2s", call, handle)])

    out = replay_turn(records, 0, server_command=MUTATING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    written = [d for d in out.delta if d.path == b"clobbered.txt"]
    assert written, (
        f"the delta did not name the written file; paths were "
        f"{sorted(d.path for d in out.delta)!r}"
    )


def test_delta_is_empty_for_a_no_op_turn(tmp_path):
    """A turn whose server writes nothing yields an empty delta.

    The anti-vacuity partner to the write case: if the delta were non-empty here, the
    write test above would be proving nothing.
    """
    manifest_dir, handle = _snapshot(tmp_path, "noop", {"keep.txt": "x"})
    records = _trace(tmp_path, "noop", [("c2s", _echo_call(2, "hi"), handle)])

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.delta == [], f"a no-op turn produced a non-empty delta: {out.delta!r}"


# --- 6. Version drift is a finding, not an error -----------------------------


def test_version_drift_is_a_finding_not_an_error(tmp_path):
    """When the replayed server negotiates a different version, that is a finding.

    The recorded handshake negotiated `2099-01-01`; the fresh `conforming_server`
    negotiates `2025-11-25`. The engine records both and flags the drift — it does NOT
    raise, and it does NOT swallow the difference.
    """
    manifest_dir, handle = _snapshot(tmp_path, "drift", {"keep.txt": "x"})
    call = _echo_call(2, "hi")
    records = _trace(
        tmp_path,
        "drift",
        [
            ("c2s", _initialize("2099-01-01"), None),
            ("s2c", _initialize_reply("2099-01-01"), None),
            ("c2s", INITIALIZED, None),
            ("c2s", call, handle),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.recorded_version == "2099-01-01"
    assert out.replayed_version == "2025-11-25"
    assert out.version_drift is True


# --- 7. A replay that never answers the target is UNVERIFIED, not REPLAYED ----


def test_replay_that_does_not_answer_target_is_unverified_not_replayed(tmp_path):
    """A `present` turn whose re-invoked server dies before the target frame is
    UNVERIFIED with a named cause — never a clean `replayed` with a null reply.

    `dies_midway_server` answers the first frame (the `initialize` handshake) then
    exits, so the `tools/call` target is never answered on replay. The old engine
    read only `outcomes[target_index].reply` (None here) and reported REPLAYED,
    reinvoked=True, result_equivalence=None — identical to a benign "nothing to
    compare" turn. That is a false-clean reading of exactly the shape C3 exists to
    catch: the server WAS spawned (reinvoked stays True, honestly), but it produced
    no result for the target, so the honest status is UNVERIFIED, keyed on the REPLAY
    outcome's status, and the cause names it.
    """
    manifest_dir, handle = _snapshot(tmp_path, "noans", {"keep.txt": "x"})
    call = _echo_call(2, "hi")
    records = _trace(
        tmp_path,
        "noans",
        [
            ("c2s", _initialize("2025-11-25"), None),
            ("s2c", _initialize_reply("2025-11-25"), None),
            ("c2s", INITIALIZED, None),
            ("c2s", call, handle),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    out = replay_turn(records, 0, server_command=DIES_MIDWAY_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == UNVERIFIED, out
    assert out.status != REPLAYED
    assert out.reinvoked is True, "the server WAS spawned — stay honest about that"
    assert out.replayed_reply is None
    assert out.cause is not None
    assert "did not answer the target frame" in out.cause, out.cause


def test_recording_had_no_reply_but_replay_answers_stays_replayed(tmp_path):
    """The benign converse of the bug: the RECORDING has no reply, but the REPLAY
    answers -> still REPLAYED. The flip must key on the REPLAY outcome, not the record.

    Here the trace holds only the `tools/call` — no recorded `s2c` reply. On replay a
    fresh `conforming_server` genuinely answers the target, so the turn stays REPLAYED
    with a real `replayed_reply`; `result_equivalence` is None only because there is
    nothing recorded to compare against. If the fix had keyed on the recorded side, it
    would have wrongly flipped this good turn to UNVERIFIED.
    """
    manifest_dir, handle = _snapshot(tmp_path, "recnone", {"keep.txt": "x"})
    call = _echo_call(2, "hi", meta={"io.modelcontextprotocol/protocolVersion": "2026-07-28"})
    records = _trace(tmp_path, "recnone", [("c2s", call, handle)])

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.reinvoked is True
    assert out.replayed_reply is not None, "the replay genuinely answered the target"
    assert json.loads(out.replayed_reply)["id"] == 2
    assert out.recorded_reply is None
    assert out.result_equivalence is None, "nothing recorded to compare — honest None, not a flip"


# --- 8. M3: no observed post-state -> delta None (never []), effect UNVERIFIED ----


def _tools_list_readonly() -> list[tuple]:
    """A `tools/list` request+response declaring `echo` as readOnlyHint:true."""
    req = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "echo", "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def test_no_observed_post_state_yields_none_delta_not_empty(tmp_path, monkeypatch):
    """A replay with NO post-state to scan must produce `delta=None`, never `[]`.

    This closes the latent false-PASS seam: if a REPLAYED turn's `workspace` is `None`
    (no post-state was ever observed), the delta must NOT be manufactured from
    `diff_records(before, before)` = `[]`. An empty delta means "scanned the post-state
    and saw no mutation" and lets a readOnlyHint:true tool render effect PASS — so an
    empty delta that never observed the post-state would be a FALSE PASS on a mutation
    that could not be ruled out. The invariant is made structural: no observed post-state
    -> `delta is None` -> effect UNVERIFIED, never PASS.

    The client replay is stubbed to return `workspace=None` with the target ANSWERED, the
    one shape the real client never produces today (client.py always resolves a workspace)
    but which C4's one grounded PASS silently depends on. Against the old `else before` this
    assertion fails: delta would be `[]` and the effect verdict PASS.
    """
    manifest_dir, handle = _snapshot(tmp_path, "nows", {"keep.txt": "x"})
    call = _echo_call(2, "hi")
    records = _trace(
        tmp_path,
        "nows",
        _tools_list_readonly() + [("c2s", call, handle), ("s2c", _echo_reply(2, "hi"), None)],
    )

    def _stub_client_replay(server_command, *, snapshot_manifest, frames, network, timeout):
        # A post-state that was never observed: workspace is None, yet the target answered.
        return ReplayResult(
            outcomes=[
                FrameOutcome(index=i, frame=f, status=ANSWERED, reply=_echo_reply(2, "hi"))
                for i, f in enumerate(frames)
            ],
            workspace=None,
        )

    monkeypatch.setattr(engine, "_client_replay_turn", _stub_client_replay)

    out = replay_turn(records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert out.status == REPLAYED, out
    assert out.delta is None, (
        f"a replay with no observed post-state must yield delta=None, not {out.delta!r}"
    )
    # And the downstream effect verdict on a readOnlyHint:true tool is UNVERIFIED — never a
    # PASS manufactured from an empty delta that never saw the post-state.
    effect = render_effect_verdict(records, 0, out.delta)
    assert effect.status is Status.UNVERIFIED, effect.message
    assert effect.status is not Status.PASS
