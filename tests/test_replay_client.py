"""The minimal stdio MCP client: send recorded frames, read the matching replies.

C3 replays a recorded turn. `proxy.py` is a PUMP that forwards between two live
pipes and originates nothing; replay needs the *client* half — the thing that
spawns a server, sends the recorded frames, and awaits the reply. This suite pins
the five properties that make that client trustworthy:

1. It matches a reply to its request by ``(direction, type(id), id)``, never the
   bare id, so ``2`` and ``"2"`` and ``2.0`` cannot cross-answer.
2. **Replay never touches live state.** The server runs against a scratch copy
   restored from the snapshot; the snapshot tree and the original workspace are
   both byte-identical afterwards. This is a Fatal risk and gets the strongest
   assertion in the file (BTH-1 byte hash), plus a non-vacuity guard proving the
   mutation really happened — to the copy.
3. A frame with no usable id is **unanswerable** by JSON-RPC (`gate._UntrackableTurn`):
   no response can ever carry an id back to retire it. The client must TIME OUT on
   a bounded wait and name which frame had no reply — never block forever.
4. A server that dies mid-conversation is handled: the client returns what it got
   plus a named failure, never hangs, never raises away the frame context.
5. Positive control: a well-formed request against a live server really does get
   its reply. Without this, a client that *always* timed out would pass (3) for the
   wrong reason.

The conversation core (`converse`) is exercised over a plain spawned server so the
id-matching and the timeout are isolated from the sandbox. The scratch-restore path
(`replay_turn`) is exercised on a real snapshot, which is where the sandbox spawn
and the live-state guarantee live.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from belay.replay.client import (
    ANSWERED,
    NO_REPLY_EXPECTED,
    NO_USABLE_ID,
    SERVER_EXITED,
    converse,
    replay_turn,
)
from belay.replay.persist import persist_snapshot
from belay.snapshot.bth1 import hash_tree
from belay.snapshot.substrate import take_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
DIES_MIDWAY = FIXTURES / "dies_midway_server.py"
MUTATING = FIXTURES / "mutating_server.py"

# Frames as they would have been recorded on the wire: initialize (id=1), the
# handshake notification (no id, no reply), and a tools/call (id=2).
INITIALIZE = (
    b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
    b'{"protocolVersion":"2025-11-25","capabilities":{},'
    b'"clientInfo":{"name":"t","version":"1"}}}'
)
INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'
TOOLS_CALL = b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"s":"hi"}}}'
# A tools/call with NO id: on the wire indistinguishable from a notification, but
# semantically a request the server can never answer. This is the gate's
# `_UntrackableTurn` condition.
TOOLS_CALL_NO_ID = b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"echo","arguments":{"s":"hi"}}}'

# mutating_server.py replies with fixed ids and clobbers a file on tools/call; its
# tools/call reply carries id=3, so the frame must too.
MUTATING_CALL = b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"clobber","arguments":{}}}'

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="replay_turn spawns inside the macOS Seatbelt sandbox"
)


def _spawn(server: Path) -> subprocess.Popen:
    """A plain, unsandboxed server over real stdio pipes — the conversation core's rig."""
    return subprocess.Popen(
        [sys.executable, str(server)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _reply_id(frame: bytes) -> object:
    import json

    return json.loads(frame)["id"]


# --- 1. Match replies to requests by id --------------------------------------


def test_matches_each_reply_to_its_request_by_id():
    """initialize and tools/call each get their own reply; the notification gets none.

    The tools/call's reply must carry the tools/call's id (2), not the
    initialize's (1) — a client keyed on arrival order rather than id would pass a
    single round trip and fail the moment two are in flight.
    """
    proc = _spawn(CONFORMING)
    try:
        outcomes = converse(proc, [INITIALIZE, INITIALIZED, TOOLS_CALL], timeout=5.0)
    finally:
        _terminate(proc)

    assert [o.status for o in outcomes] == [ANSWERED, NO_REPLY_EXPECTED, ANSWERED]

    import json

    init_reply = json.loads(outcomes[0].reply)
    call_reply = json.loads(outcomes[2].reply)
    assert init_reply["id"] == 1
    assert call_reply["id"] == 2, (
        "the tools/call was answered with the wrong reply — ids were not matched: "
        f"{call_reply!r}"
    )
    # The notification carried no reply and none was invented.
    assert outcomes[1].reply is None


# --- 2. Replay never touches live state (Fatal risk) -------------------------


def test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched(tmp_path, monkeypatch):
    """C3's contract, asserted not assumed: the snapshot tree and the original are
    byte-identical after a replay whose server *mutates its workspace*.

    Non-vacuous by construction: mutating_server clobbers a file the instant the
    tools/call lands, and the test asserts that clobber DID happen — in the scratch
    copy. So the replay really exercised a mutation, and it still left both the
    snapshot tree and the original byte-for-byte unchanged. A replay that ran the
    server against live state would change the snapshot tree's BTH-1 hash and fail.
    """
    original = tmp_path / "original"
    original.mkdir()
    (original / "keep.txt").write_text("do not touch me")

    snapshot_tree = tmp_path / "snap"
    snap = take_snapshot(original, snapshot_tree)
    manifest = tmp_path / "manifest.json"
    persist_snapshot(snap, manifest)

    original_before = hash_tree(original)
    snapshot_before = hash_tree(snapshot_tree)

    # mutating_server writes to $BELAY_TEST_MUTATE_PATH; a relative name lands in
    # the server's cwd, which replay sets to the scratch workspace.
    monkeypatch.setenv("BELAY_TEST_MUTATE_PATH", "clobbered.txt")

    result = replay_turn(
        [sys.executable, str(MUTATING)],
        snapshot_manifest=manifest,
        frames=[MUTATING_CALL],
        timeout=15.0,
    )

    assert result.outcomes[0].status == ANSWERED, (
        "the mutating server never answered — the mutation may not have run, making "
        f"the untouched assertion vacuous: {result.outcomes!r}"
    )
    clobbered = Path(result.workspace) / "clobbered.txt"
    assert clobbered.read_bytes() == b"MUTATED", (
        "the replayed server did not mutate its scratch workspace — the untouched "
        "guarantee below would be proving nothing"
    )

    assert hash_tree(snapshot_tree) == snapshot_before, (
        "REPLAY MUTATED THE SNAPSHOT TREE: it ran the server against live state, not "
        "a scratch copy. This is the Fatal risk C3 exists to preclude."
    )
    assert hash_tree(original) == original_before, "replay mutated the original workspace"


# --- 3. A frame with no usable id times out, named (Fatal risk) --------------


def test_a_frame_with_no_usable_id_times_out_rather_than_hanging():
    """A tools/call with no id can never be answered — the client must bound the wait.

    conforming_server actually emits a reply with ``id: null`` here, which is the
    adversarial case: the client MUST NOT match that null-id reply to the no-id
    request (there is no id to match on), so it waits out the timeout and reports
    NO_USABLE_ID against the exact frame that had no answer. A short timeout keeps
    the test fast; the assertion that it *returned at all* is the anti-hang.
    """
    proc = _spawn(CONFORMING)
    started = time.monotonic()
    try:
        outcomes = converse(proc, [INITIALIZE, INITIALIZED, TOOLS_CALL_NO_ID], timeout=0.5)
    finally:
        _terminate(proc)
    elapsed = time.monotonic() - started

    # It returned — did not hang — within a small multiple of the timeout.
    assert elapsed < 10.0, f"converse did not bound its wait: took {elapsed:.1f}s"

    assert outcomes[0].status == ANSWERED
    assert outcomes[1].status == NO_REPLY_EXPECTED
    assert outcomes[2].status == NO_USABLE_ID, (
        "the no-id tools/call was not named unanswerable — a null-id reply was "
        f"wrongly matched to it, or it hung: {outcomes[2]!r}"
    )
    # The fact names WHICH frame had no reply.
    assert outcomes[2].frame == TOOLS_CALL_NO_ID
    assert outcomes[2].reply is None


# --- 4. A server that dies mid-conversation is named, not hung ---------------


def test_a_server_that_dies_midway_is_reported_not_hung():
    """The first frame is answered; the second finds the pipe gone and is named.

    Never a hang, never an exception that loses which frame was in flight.
    """
    proc = _spawn(DIES_MIDWAY)
    try:
        outcomes = converse(proc, [INITIALIZE, TOOLS_CALL], timeout=2.0)
    finally:
        _terminate(proc)

    assert outcomes[0].status == ANSWERED, "the server's one reply was lost"
    assert outcomes[1].status == SERVER_EXITED, (
        f"the death of the server was not reported against the in-flight frame: {outcomes!r}"
    )
    assert outcomes[1].frame == TOOLS_CALL


# --- 5. Positive control: a well-formed request really gets its reply ---------


def test_positive_control_a_well_formed_request_gets_its_reply():
    """Without this, a client that always timed out would pass test 3 vacuously."""
    proc = _spawn(CONFORMING)
    try:
        outcomes = converse(proc, [INITIALIZE], timeout=5.0)
    finally:
        _terminate(proc)

    assert len(outcomes) == 1
    assert outcomes[0].status == ANSWERED
    assert outcomes[0].reply is not None
    assert _reply_id(outcomes[0].reply) == _reply_id(INITIALIZE) == 1


def _terminate(proc: subprocess.Popen) -> None:
    for stream in (proc.stdin, proc.stdout):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
