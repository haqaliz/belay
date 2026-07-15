"""The turn gate: the snapshot happens BEFORE the call reaches the server.

C1 built the forwarding path so that observation is structurally unable to block
or alter it. That is exactly right, and it is also why C2 cannot snapshot from
the observer: by the time a frame is observed it has already been forwarded, the
server may already have executed the call, and a "pre-state" captured then is a
race whose outcome nothing downstream can see. An after-the-fact snapshot does
not weaken the verdict — it invents one.

So the gate blocks, and these tests are about the two claims that makes:

**Ordering** (`test_no_byte_of_a_frame_is_forwarded_before_the_hook_returns` and
`test_snapshot_is_taken_before_the_call_reaches_the_server`) — the first is
deterministic and structural, the second is end-to-end against a server that
really does clobber the scope. Neither alone is enough: the structural one cannot
prove the wiring reaches a real server, and the end-to-end one is evidence rather
than proof, because it cannot force the losing schedule on a broken
implementation. Together they say the ordering is a property of the shape of the
code and that the shape is actually installed.

**Neutrality** (`test_byte_identity_holds_with_the_gate_installed` and
`test_no_sandbox_means_no_gate`) — C1's differential is the reason anyone can
trust a Belay trace, and the gate is the first thing that ever asked to sit on
the data path. It is allowed to add latency. It is not allowed to change a byte,
and with no sandbox configured it is not allowed to exist.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import CLIENT_LINES, FIXTURE, read_trace, run_over_pipes

from belay import proxy
from belay.snapshot.bth1 import hash_tree
from belay.snapshot.substrate import UnrestorableCause, guarded_restore
from belay.trace import TraceWriter

MUTATING = Path(__file__).parent / "fixtures" / "mutating_server.py"
PIPELINING = Path(__file__).parent / "fixtures" / "pipelining_server.py"

# CLIENT_LINES[3] is the scripted client's `tools/call`. Taken from the shared rig
# rather than hand-written here: the gate must recognise the same adversarial
# frame (scrambled key order, a \uXXXX escape) the differential feeds, not a
# tidied-up rewrite of it that only this test would ever produce.
TOOLS_CALL = CLIENT_LINES[3]
NOT_A_TOOLS_CALL = CLIENT_LINES[2]

# Two calls a client may legally have outstanding at once, and the reply to the
# first. Ids are what the in-flight ledger is keyed on, so they are distinct and
# they are what the pipelining fixture echoes back.
CALL_ONE = b'{"params":{"name":"touch","arguments":{"name":"alpha.txt"}},"method":"tools/call","id":1,"jsonrpc":"2.0"}'
CALL_TWO = b'{"params":{"name":"touch","arguments":{"name":"beta.txt"}},"method":"tools/call","id":2,"jsonrpc":"2.0"}'
REPLY_ONE = b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"alpha.txt"}]}}'

CONCURRENT = UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value

PRE_STATE = b"pre-state"
MUTATED = b"MUTATED"

# The brief's expectation is ~14ms. The bound is deliberately an order of
# magnitude looser: this asserts the gate cannot hang a turn, not that a
# clonefile hits a stopwatch on someone else's loaded CI box. Asserting a floor
# of zero would be asserting something false — the gate blocks, and says so.
LATENCY_BUDGET_MS = 200.0


# Enough furniture that the latency number means something: a two-file scope
# would measure the syscall rather than a workspace, and the gate's cost claim is
# about the latter.
#
# It does NOT buy the end-to-end test teeth, and it was tried for that first.
# Measured: a deliberately broken gate — one that forwards the frame and *then*
# snapshots — still passes `test_snapshot_is_taken_before_the_call_reaches_the_server`
# at this size, and at 5x it. The mutation and the clone land within a
# millisecond of each other and the winner is the scheduler's to pick. Growing
# the tree until the race reliably tips would be tuning a test to a machine, and
# it would go quiet on a faster one. The ordering is proved where it is enforced
# — in the pump, deterministically — and that division is stated in this module's
# docstring and in the e2e test itself.
SCOPE_FILES = 400


def make_scope(tmp_path: Path) -> Path:
    scope = tmp_path / "scope"
    (scope / "sub").mkdir(parents=True)
    (scope / "marker.txt").write_bytes(PRE_STATE)
    (scope / "sub" / "keep.txt").write_bytes(b"keep")
    for n in range(SCOPE_FILES):
        directory = scope / "sub" / f"d{n % 20:02d}"
        directory.mkdir(exist_ok=True)
        (directory / f"f{n:03d}.txt").write_bytes(b"x" * 512)
    return scope


def gated_env(scope: Path, snaps: Path, trace_dir: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["BELAY_SANDBOX_SCOPE"] = str(scope)
    env["BELAY_SNAPSHOT_DIR"] = str(snaps)
    env["BELAY_TEST_MUTATE_PATH"] = str(scope / "marker.txt")
    if trace_dir is not None:
        env["BELAY_TRACE_DIR"] = str(trace_dir)
    return env


def proxied(server: Path) -> list[str]:
    return [sys.executable, "-m", "belay.proxy", sys.executable, str(server)]


def frames_of(records: list[dict], direction: str) -> list[dict]:
    return [r for r in records if r["kind"] == "frame" and r["dir"] == direction]


class Rig:
    """The real pump, the real gate and the real writer, in one process.

    Two things this buys that a subprocess run cannot, and both are load-bearing
    for the attribution tests:

    **Chunk boundaries the test decides.** Each `chunk()` writes its whole payload
    into the pipe *before* the pump reads, so it arrives as exactly one read. What
    shares a chunk with what is then a property of the test rather than of the
    scheduler — which matters, because sharing a chunk is precisely the condition
    under which a handle used to be attributed to the wrong frame.

    **A handle that can be resolved.** `state_handle` names a snapshot by id, and
    nothing in the trace maps that id to a directory — resolving one in a later
    process is C3's problem and deliberately not a promise C2 makes. In here,
    `gate.snapshots` is that map, so "the frame carries its OWN turn's pre-state"
    becomes a claim about a tree on disk instead of a claim about a hex string.

    Everything on the path is production code. The rig picks the boundaries; it
    does not reimplement the pump.
    """

    def __init__(self, tmp_path: Path, scope: Path) -> None:
        from belay.sandbox.gate import TurnGate

        self.trace_dir = tmp_path / "trace"
        self.writer = TraceWriter.in_directory(self.trace_dir)
        self.gate = TurnGate(
            scope=scope, snapshot_root=tmp_path / "snaps", trace=self.writer
        )
        self._peek = proxy.BoundedPeek(self.writer.observer("c2s"))
        self._forward = proxy._forwarder(self.gate.before_frame, "c2s")
        self._dst = os.open(tmp_path / "forwarded.bin", os.O_WRONLY | os.O_CREAT, 0o600)

    def chunk(self, *frames: bytes) -> None:
        """Deliver `frames` to the server as ONE chunk, through the real pump."""
        src_r, src_w = os.pipe()
        proxy._write_all(src_w, b"".join(frame + b"\n" for frame in frames))
        os.close(src_w)
        try:
            proxy._pump(src_r, self._dst, self._peek, None, self._forward)
        finally:
            os.close(src_r)

    def reply(self, frame: bytes) -> None:
        """A response reaching the gate where the s2c hold reaches it: before the
        client can see it, and so before the client can send what comes next."""
        self.gate.before_frame(frame, "s2c")

    def handles(self) -> dict[bytes, dict]:
        """Every c2s frame the trace recorded, by its exact bytes."""
        self.writer.close()
        os.close(self._dst)
        return {
            base64.b64decode(f["raw"]): f["state_handle"]
            for f in frames_of(read_trace(self.trace_dir), "c2s")
        }

    def resolve(self, handle: dict) -> Path:
        """The tree a `present` handle names, or fail saying it names nothing."""
        assert handle["status"] == "present", f"not a present handle: {handle!r}"
        snap = self.gate.snapshots.get(handle["handle"])
        assert snap is not None, (
            f"handle {handle['handle']!r} resolves to no snapshot this gate took: "
            f"it names {sorted(self.gate.snapshots)}"
        )
        return snap.snapshot.path


# --- Ordering ---------------------------------------------------------------


def test_no_byte_of_a_frame_is_forwarded_before_the_hook_returns(tmp_path):
    """The structural claim, held to a file so it is decided rather than raced.

    The destination is a real fd written with `os.write`, so what the file holds
    at the moment the hook runs *is* what has been forwarded. At the first frame's
    hook nothing has crossed; at the second frame's hook the first frame has
    crossed **whole** and the second has not started. That second assertion is the
    one with teeth: a gate that forwarded the chunk and then ran the hook would
    show the second frame already delivered.
    """
    src_r, src_w = os.pipe()
    dest = tmp_path / "forwarded.bin"
    dst_fd = os.open(dest, os.O_WRONLY | os.O_CREAT, 0o600)

    forwarded_at_hook_time: list[bytes] = []

    def before_frame(frame: bytes, direction: str) -> None:
        forwarded_at_hook_time.append(dest.read_bytes())

    os.write(src_w, NOT_A_TOOLS_CALL + b"\n" + TOOLS_CALL + b"\n")
    os.close(src_w)
    try:
        proxy._pump(
            src_r,
            dst_fd,
            forward=proxy._forwarder(before_frame, "c2s"),
        )
    finally:
        os.close(dst_fd)
        os.close(src_r)

    assert forwarded_at_hook_time == [b"", NOT_A_TOOLS_CALL + b"\n"], (
        "the hook must run before any byte of its own frame is forwarded"
    )
    # Byte-exactness of the whole stream, still: holding is a delay, not an edit.
    assert dest.read_bytes() == NOT_A_TOOLS_CALL + b"\n" + TOOLS_CALL + b"\n"


def test_snapshot_is_taken_before_the_call_reaches_the_server(tmp_path):
    """End-to-end, against a server that clobbers the scope on `tools/call`.

    What this proves: the whole composition — env config, hook installation, real
    pipes, a real server, a real clone — produces a snapshot holding the
    pre-state. That is worth having and nothing else here covers it.

    **What it does not prove, measured rather than assumed: ordering.** A
    deliberately broken gate that forwards the frame and *then* snapshots still
    passes this test. The server's mutation and the clone land within about a
    millisecond of each other, so the schedule decides, and it usually decides in
    the bug's favour. Do not read a green here as evidence the snapshot came
    first.

    `test_no_byte_of_a_frame_is_forwarded_before_the_hook_returns` is where the
    ordering is actually decided: at the point it is enforced, with no concurrency
    to race. Ablating the hook order fails that test every time and this one never.
    """
    scope = make_scope(tmp_path)
    snaps = tmp_path / "snaps"

    run_over_pipes(proxied(MUTATING), env=gated_env(scope, snaps))

    # Anti-vacuity, and it is not a formality: if the fixture silently stopped
    # mutating, every assertion below would pass while proving nothing about
    # ordering at all. The mutation must have really happened.
    assert scope.joinpath("marker.txt").read_bytes() == MUTATED, (
        "the server did not mutate the scope - this test would pass vacuously"
    )

    turns = sorted(snaps.iterdir())
    assert len(turns) == 1, f"expected exactly one turn snapshot, found {turns!r}"
    assert turns[0].joinpath("marker.txt").read_bytes() == PRE_STATE, (
        "the snapshot captured the POST-mutation state: it was taken after the "
        "tools/call reached the server, which is a race, not a pre-state"
    )
    assert turns[0].joinpath("sub", "keep.txt").read_bytes() == b"keep"


# --- The handle, and what it points at --------------------------------------


def test_the_turns_frame_carries_a_present_state_handle(tmp_path):
    scope = make_scope(tmp_path)
    trace_dir = tmp_path / "trace"

    run_over_pipes(
        proxied(MUTATING),
        env=gated_env(scope, tmp_path / "snaps", trace_dir=trace_dir),
    )
    records = read_trace(trace_dir)

    call_frames = [
        f for f in frames_of(records, "c2s") if base64.b64decode(f["raw"]) == TOOLS_CALL
    ]
    assert len(call_frames) == 1, "expected exactly one tools/call frame in the trace"

    handle = call_frames[0]["state_handle"]
    assert handle["status"] == "present", (
        f"the turn's own frame must carry its pre-state snapshot; got {handle!r}"
    )
    assert handle["handle"], "a present handle that names no snapshot resolves to nothing"
    assert handle["backend"] == "clonefile-apfs"
    # `present` must keep naming what it did NOT preserve (Task 6's contract).
    assert "UNRESTORABLE_ATIME" in handle["fidelity_gaps"]


def test_frames_that_crossed_before_the_turn_do_not_claim_its_snapshot(tmp_path):
    """A frame that crossed before the snapshot must still say `absent`.

    Stepped deliberately — one frame per write, the reply read before the next is
    sent — because that is what an agent actually does, and because the ordering
    is then a guarantee rather than a coincidence: the c2s pump observes a chunk
    before it can read the next one, so `initialize` is in the trace before the
    gate can possibly run for the `tools/call`.

    Its batched sibling below is the same question with the answer the
    architecture really gives.
    """
    scope = make_scope(tmp_path)
    trace_dir = tmp_path / "trace"
    proc = subprocess.Popen(
        proxied(MUTATING),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=gated_env(scope, tmp_path / "snaps", trace_dir=trace_dir),
    )
    try:
        proc.stdin.write(CLIENT_LINES[0] + b"\n")
        proc.stdin.flush()
        assert proc.stdout.readline(), "no reply to initialize - the rig is broken"
        proc.stdin.write(TOOLS_CALL + b"\n")
        proc.stdin.flush()
        assert proc.stdout.readline(), "no reply to tools/call - the rig is broken"
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)

    handles = {
        json.loads(base64.b64decode(f["raw"]))["method"]: f["state_handle"]
        for f in frames_of(read_trace(trace_dir), "c2s")
    }
    assert handles["initialize"] == {"status": "absent"}, (
        "a frame that crossed before any snapshot was taken claimed one"
    )
    assert handles["tools/call"]["status"] == "present"


def test_a_batched_write_resolves_each_tools_call_to_its_own_pre_state(tmp_path):
    """The load-bearing claim, on the chunk shape that used to break it.

    A client that packs several frames into ONE write is the common case, not the
    corner: JSON-RPC ids exist so a client may pipeline, and Claude Code, Cursor
    and the OpenAI agents SDK all batch independent tool calls by default. So this
    chunk carries a notification and TWO `tools/call` frames, and every frame in it
    is gated before any of them is recorded.

    **What is asserted strictly:** each `tools/call` frame's handle *resolves to
    its own turn's pre-state* — the tree on disk is checked, not just the status.
    The previous version of this test asserted only
    `all(h["status"] == "present")`, which passed while every handle in the trace
    named the WRONG snapshot, and reassured in its docstring that the load-bearing
    claim was unaffected. It was not: both frames reported one handle, and the
    second frame claimed a pre-state its turn never ran against.

    **What is a KNOWN LIMIT, pinned here so it stays a decision:** a frame that is
    not a `tools/call` carries whatever handle was current when the chunk was
    recorded, which on a batched write can be a later frame's. That is C1's shape
    and not fixable from here — the pump forwards a whole chunk and observes it
    afterwards on purpose (*"forwarding must never wait on the recorder"*). On such
    a frame the handle means "this was current when the frame was recorded", never
    "this frame crossed after it". C2 records; C4 renders; this is on the list of
    what C4 must know.
    """
    scope = make_scope(tmp_path)
    rig = Rig(tmp_path, scope)

    rig.chunk(NOT_A_TOOLS_CALL, CALL_ONE, CALL_TWO)
    handles = rig.handles()
    assert len(handles) == 3, "the chunk's frames did not all reach the trace"

    # Turn 1 began with nothing outstanding, so its pre-state is real and its
    # frame must name the tree that holds it.
    assert rig.resolve(handles[CALL_ONE]).joinpath("marker.txt").read_bytes() == PRE_STATE

    # Turn 2 was gated while turn 1 was still outstanding. There is no pre-state to
    # claim: the tree it would clone is already whatever turn 1 has done to it so
    # far. A `present` here is the false PASS this gate exists to refuse.
    assert handles[CALL_TWO] == {
        "status": "unrestorable",
        "cause": CONCURRENT,
        "detail": handles[CALL_TWO].get("detail", ""),
        "source": "turn-gate",
    }, f"a turn gated behind an outstanding call claimed a pre-state: {handles[CALL_TWO]!r}"
    assert handles[CALL_TWO]["detail"], "an unrestorable that explains nothing"

    # Exactly one clone: the refusal must be a refusal, not a snapshot nobody names.
    assert len(rig.gate.snapshots) == 1, (
        f"a turn with a call outstanding was snapshotted anyway: "
        f"{sorted(rig.gate.snapshots)}"
    )

    # The limit, stated as an assertion so that fixing it is a visible change.
    assert handles[NOT_A_TOOLS_CALL] == handles[CALL_TWO], (
        "the batched-chunk limit changed shape - if observation is now per-frame, "
        "this becomes the strict assertion instead of being relaxed"
    )


def test_each_tools_call_frame_resolves_to_its_own_snapshot(tmp_path):
    """Two sequential turns, two snapshots, and each frame names the right one.

    The positive control for the in-flight ledger, and it is not a formality: the
    honest answer to a pipelined turn is `unrestorable`, and a gate that simply
    said that always would pass the pipelining tests while snapshotting nothing
    ever again. This is the test that fails if the ledger never clears — which is
    what a response reaching the gate is for.

    Resolution is by CONTENT, deliberately. Two handles that merely differ prove
    nothing about which tree either names; the marker file is what makes "its own"
    mean something. Turn 1 must resolve to the tree before the mutation, turn 2 to
    the tree after it.
    """
    scope = make_scope(tmp_path)
    rig = Rig(tmp_path, scope)

    rig.chunk(CALL_ONE)
    rig.reply(REPLY_ONE)  # turn 1 is over: the ledger is empty again
    scope.joinpath("marker.txt").write_bytes(MUTATED)  # what turn 1 did
    rig.chunk(CALL_TWO)

    handles = rig.handles()
    assert len(rig.gate.snapshots) == 2, (
        "a turn whose predecessor had already replied was refused a snapshot: the "
        "ledger never cleared, and the gate now refuses every turn after the first"
    )
    assert handles[CALL_ONE]["handle"] != handles[CALL_TWO]["handle"], (
        "two turns, two snapshots, one handle: at least one frame names a tree "
        "that is not its own pre-state"
    )
    assert rig.resolve(handles[CALL_ONE]).joinpath("marker.txt").read_bytes() == PRE_STATE
    assert rig.resolve(handles[CALL_TWO]).joinpath("marker.txt").read_bytes() == MUTATED


def test_a_pipelining_client_is_told_the_truth_end_to_end(tmp_path):
    """The whole composition, against a real server doing real work per call.

    The in-process tests decide the ordering; this one proves the wiring reaches a
    live server through a real sandbox — and that the gate learns of a response
    from the s2c path, which in-process tests hand it directly.

    The fixture sleeps before it acts, so while turn 2 is being gated turn 1 is
    provably still executing. That is what makes the outcome decided rather than
    raced: with an instant server the reply could legitimately beat the second
    call to the gate, and turn 2 would then have begun with nothing outstanding —
    an honest `present`, and a test whose verdict the scheduler picks.
    """
    scope = make_scope(tmp_path)
    snaps = tmp_path / "snaps"
    trace_dir = tmp_path / "trace"
    env = gated_env(scope, snaps, trace_dir=trace_dir)
    env["BELAY_TEST_TOUCH_DIR"] = str(scope)

    proc = subprocess.Popen(
        proxied(PIPELINING), stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
    )
    stdout, _ = proc.communicate(CALL_ONE + b"\n" + CALL_TWO + b"\n", timeout=30)
    assert proc.returncode == 0, "the proxied server did not exit cleanly"

    # Anti-vacuity, and it is the whole point of the fixture: turn 2 really ran,
    # and it really ran against a tree that already contained turn 1's file.
    assert stdout.count(b"\n") == 2, f"both calls must have been answered: {stdout!r}"
    assert scope.joinpath("alpha.txt").exists(), "turn 1 never ran - vacuous test"
    assert scope.joinpath("beta.txt").exists(), "turn 2 never ran - vacuous test"

    handles = {
        json.loads(base64.b64decode(f["raw"]))["id"]: f["state_handle"]
        for f in frames_of(read_trace(trace_dir), "c2s")
    }
    assert handles[1]["status"] == "present"
    assert handles[2]["status"] == "unrestorable", (
        f"turn 2 ran against a tree containing alpha.txt and was told it had a "
        f"pre-state without it: {handles[2]!r}"
    )
    assert handles[2]["cause"] == CONCURRENT

    turns = sorted(snaps.iterdir())
    assert len(turns) == 1, f"one turn was snapshottable; found {turns!r}"
    assert not turns[0].joinpath("alpha.txt").exists(), (
        "the one snapshot is not turn 1's pre-state"
    )


def test_a_batch_of_tools_calls_in_one_frame_is_refused(tmp_path):
    """Several turns, one frame, one handle slot: no honest per-turn answer.

    The 2025-03-26 revision allowed a JSON-RPC batch and 2025-06-18 removed it
    again, so a client on the older revision can legally open two turns in a single
    frame. They begin together: only the first has this tree as its pre-state, and
    a frame carries exactly one handle. Snapshotting once and stamping it on the
    frame would say something true about the first call and false about the rest.
    """
    scope = make_scope(tmp_path)
    rig = Rig(tmp_path, scope)
    batch = b"[" + CALL_ONE + b"," + CALL_TWO + b"]"

    rig.chunk(batch)

    handle = rig.handles()[batch]
    assert handle["status"] == "unrestorable", f"a batch claimed one pre-state: {handle!r}"
    assert handle["cause"] == CONCURRENT
    assert rig.gate.snapshots == {}


def test_a_tools_call_with_no_id_poisons_every_later_turn(tmp_path):
    """Unanswerable, so its end is never observable — and that is not ignorable.

    A `tools/call` with no id is not a legal request, but it is legal JSON and it
    still *executes*. No response can ever name it, so the gate can never learn it
    finished, so every later turn might be running against a tree it is in the
    middle of changing. Refusing all of them is severe and it is the honest
    reading: the alternative is to guess, and a guess here is a `present` handle on
    a tree that may never have existed.

    Its OWN pre-state is real — nothing was outstanding when it began — so it is
    snapshotted. Both halves are the point.
    """
    scope = make_scope(tmp_path)
    rig = Rig(tmp_path, scope)
    no_id = b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"echo","arguments":{}}}'

    rig.chunk(no_id)
    rig.reply(REPLY_ONE)  # answers nothing: there is no id here to answer
    rig.chunk(CALL_ONE)

    handles = rig.handles()
    assert handles[no_id]["status"] == "present", (
        "the first turn began with nothing outstanding; its pre-state is real"
    )
    assert handles[CALL_ONE]["status"] == "unrestorable", (
        "a turn was snapshotted while a call the gate can never see the end of was "
        "still outstanding"
    )
    assert handles[CALL_ONE]["cause"] == CONCURRENT


def test_a_server_request_does_not_retire_the_turn_it_interrupts(tmp_path):
    """`sampling/createMessage` is not a reply, however much it looks like one.

    A server-originated request travels s2c and carries an id from the **server's**
    id space — which may be any number, including one a client is currently using.
    Retiring a turn on it would mean a server could clear the ledger, by accident
    or on purpose, and buy itself a `present` handle on a tree it was already
    mutating. A response is what carries a `result` or `error` and no method.
    """
    scope = make_scope(tmp_path)
    rig = Rig(tmp_path, scope)
    sampling = b'{"jsonrpc":"2.0","id":1,"method":"sampling/createMessage","params":{}}'

    rig.chunk(CALL_ONE)
    rig.reply(sampling)  # id 1, s2c, and answers nothing
    rig.chunk(CALL_TWO)

    handles = rig.handles()
    assert handles[CALL_ONE]["status"] == "present"
    assert handles[CALL_TWO]["status"] == "unrestorable", (
        "a server request retired the turn it interrupted: turn 1 is still running"
    )
    assert handles[CALL_TWO]["cause"] == CONCURRENT


def test_the_snapshot_restores_the_pre_state(tmp_path):
    """The handle is only worth anything if it restores. Measured by BTH-1."""
    from belay.sandbox.gate import TurnGate

    scope = make_scope(tmp_path)
    before_hash = hash_tree(scope)

    gate = TurnGate(scope=scope, snapshot_root=tmp_path / "snaps")
    gate.before_frame(TOOLS_CALL, "c2s")

    assert len(gate.snapshots) == 1
    handle, snap = next(iter(gate.snapshots.items()))
    assert handle == snap.manifest.handle

    scope.joinpath("marker.txt").write_bytes(MUTATED)
    scope.joinpath("sub", "keep.txt").unlink()
    assert hash_tree(scope) != before_hash, "the mutation did not take - vacuous test"

    guarded_restore(snap, scope)
    assert hash_tree(scope) == before_hash
    assert scope.joinpath("marker.txt").read_bytes() == PRE_STATE


def test_only_a_tools_call_snapshots(tmp_path):
    """Every frame is not a turn. Snapshotting `tools/list` would make the handle
    meaningless and pay a clone for a frame that mutates nothing."""
    from belay.sandbox.gate import TurnGate

    scope = make_scope(tmp_path)
    gate = TurnGate(scope=scope, snapshot_root=tmp_path / "snaps")

    gate.before_frame(NOT_A_TOOLS_CALL, "c2s")
    gate.before_frame(CLIENT_LINES[1], "c2s")
    assert gate.snapshots == {}

    gate.before_frame(TOOLS_CALL, "c2s")
    assert len(gate.snapshots) == 1


# --- Neutrality: C1's guarantee, with the gate on the path ------------------


def test_byte_identity_holds_with_the_gate_installed(tmp_path):
    """C1's differential, re-run through a gated proxy.

    The gate blocks the data path — the first thing in this project ever to do so.
    C1's neutrality claim was written narrowly (bytes, never timing) precisely so
    that this is allowed. This test is what holds the other half: latency yes,
    edits no.
    """
    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])
    assert direct_lines, "fixture emitted nothing - this differential would pass vacuously"

    scope = make_scope(tmp_path)
    snaps = tmp_path / "snaps"
    gated_lines = run_over_pipes(
        proxied(FIXTURE),
        env=gated_env(scope, snaps, trace_dir=tmp_path / "trace"),
    )

    assert gated_lines == direct_lines, (
        "a gated proxy diverged from a direct connection: the gate changed bytes"
    )
    # And the gate really was installed - otherwise this proves only that a
    # proxy with no gate is byte-identical, which is C1's test, not this one.
    assert sorted(snaps.iterdir()), "no snapshot was taken - the gate was not installed"


def test_no_sandbox_means_no_gate(tmp_path):
    """No sandbox configured: C1's byte pump, unchanged, and `absent` intact."""
    trace_dir = tmp_path / "trace"
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    env.pop("BELAY_SANDBOX_SCOPE", None)

    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])
    lines = run_over_pipes(proxied(FIXTURE), env=env)
    assert lines == direct_lines

    records = read_trace(trace_dir)
    handles = [f["state_handle"] for f in records if f["kind"] == "frame"]
    assert handles, "no frames recorded - this test would pass vacuously"
    assert all(h == {"status": "absent"} for h in handles), (
        "a run with no sandbox configured attempted a snapshot; `absent` must keep "
        "meaning exactly 'no snapshot was attempted'"
    )


# --- The gate must never hang a turn ----------------------------------------


def test_a_failing_snapshot_still_forwards_and_names_a_cause(tmp_path):
    """A hung proxy is worse than an unsnapshotted turn.

    The scope holds a FIFO, which Task 6 refuses by name rather than snapshot
    lossily. The gate must record that refusal and get out of the way.
    """
    from belay.sandbox.gate import TurnGate

    scope = make_scope(tmp_path)
    os.mkfifo(scope / "pipe")

    class Sink:
        def __init__(self) -> None:
            self.handles: list[dict] = []

        def set_state_handle(self, handle: dict, *, frame: bytes) -> None:
            # `frame` is required, matching `StateSink`: the gate must name the
            # frame each handle belongs to, and a stub that accepted less would
            # let the gate stop passing it without a test noticing.
            assert frame == TOOLS_CALL
            self.handles.append(handle)

    sink = Sink()
    gate = TurnGate(scope=scope, snapshot_root=tmp_path / "snaps", trace=sink)
    gate.before_frame(TOOLS_CALL, "c2s")  # must not raise

    assert len(sink.handles) == 1
    assert sink.handles[0]["status"] == "unrestorable"
    assert sink.handles[0]["cause"] == "UNRESTORABLE_FIFO"
    assert sink.handles[0]["path"] == "pipe"


def test_a_stream_ending_mid_frame_still_delivers_what_was_held(tmp_path):
    """The hold's one real risk: bytes taken custody of and never handed over.

    A frame with no terminating newline never triggers the hook — a partial frame
    is not a frame, and calling the hook for one would be inventing a turn. But
    the bytes were read out of the client's pipe, and if the hold simply exits
    with them still in its buffer they are gone: the peer never sees them and
    nothing says so. That is a silent loss on the data path, which is the one
    thing the hold is not permitted to cost, and it is a loss C1's pump could not
    have had because it never held anything.
    """
    src_r, src_w = os.pipe()
    dest = tmp_path / "forwarded.bin"
    dst_fd = os.open(dest, os.O_WRONLY | os.O_CREAT, 0o600)
    hooked: list[bytes] = []

    partial = b'{"jsonrpc":"2.0","method":"tools/call","id":9'  # no newline: EOF mid-frame
    os.write(src_w, TOOLS_CALL + b"\n" + partial)
    os.close(src_w)
    try:
        proxy._pump(
            src_r,
            dst_fd,
            forward=proxy._forwarder(lambda f, d: hooked.append(f), "c2s"),
        )
    finally:
        os.close(dst_fd)
        os.close(src_r)

    assert dest.read_bytes() == TOOLS_CALL + b"\n" + partial, (
        "the hold kept bytes it had taken custody of; the peer never got them"
    )
    assert hooked == [TOOLS_CALL], "the hook fired for a partial frame - that is not a turn"


def test_a_broken_gate_cannot_stop_the_bytes(tmp_path):
    """Defence in depth: the gate catches its own failures, but if one ever
    escaped, the forwarding path must survive it. The hook is capture; capture is
    best-effort; the bytes are not."""
    src_r, src_w = os.pipe()
    dest = tmp_path / "forwarded.bin"
    dst_fd = os.open(dest, os.O_WRONLY | os.O_CREAT, 0o600)
    named: list[BaseException] = []

    def exploding(frame: bytes, direction: str) -> None:
        raise RuntimeError("the gate is broken")

    os.write(src_w, TOOLS_CALL + b"\n")
    os.close(src_w)
    try:
        proxy._pump(
            src_r,
            dst_fd,
            forward=proxy._forwarder(exploding, "c2s", named.append),
        )
    finally:
        os.close(dst_fd)
        os.close(src_r)

    assert dest.read_bytes() == TOOLS_CALL + b"\n", "a broken gate ate the frame"
    assert [type(e).__name__ for e in named] == ["RuntimeError"], (
        "a gate that failed silently leaves an unsnapshotted turn looking snapshotted"
    )


def test_a_snapshot_root_inside_the_scope_is_refused(tmp_path):
    """Snapshotting into the tree being snapshotted is a false pre-state.

    Turn 1 would clone turn 0's snapshot into itself, and every turn after would
    carry the ones before it. The tree grows, the clone slows, and — the part that
    matters — the recorded "pre-state" contains artifacts that were never in the
    agent's workspace. Nothing downstream could tell, because the handle would say
    `present` and the hash would be perfectly self-consistent.

    Refused at construction, which is startup, rather than per turn: a
    misconfiguration should stop the proxy coming up, not quietly poison a run.
    """
    from belay.sandbox.gate import TurnGate

    scope = make_scope(tmp_path)
    with pytest.raises(ValueError, match="inside the scope"):
        TurnGate(scope=scope, snapshot_root=scope / "snaps")


def test_the_gate_owned_cause_is_not_smuggled_into_the_taxonomy():
    """`UNRESTORABLE_SNAPSHOT_FAILED` is the gate's, not Task 6's.

    Task 6 partitions every `UnrestorableCause` into raised-here or
    deferred-to-a-named-owner, and asserts the partition is exhaustive. A cause
    added from outside would break that silently. The gate needs a name for "the
    snapshot failed for a reason the taxonomy does not cover" — ENOSPC, EXDEV —
    and every alternative is a lie: `absent` claims no snapshot was attempted when
    one was, and any real cause claims the wrong reason. So it lives here, is
    unfamiliar to C4 on purpose, and this test is what stops it drifting into the
    enum without anyone deciding to put it there.
    """
    from belay.sandbox.gate import SNAPSHOT_FAILED
    from belay.snapshot.substrate import UnrestorableCause

    assert SNAPSHOT_FAILED not in {cause.value for cause in UnrestorableCause}


def test_the_gate_is_bounded_and_reports_what_it_cost(tmp_path):
    """Measure the added latency. Assert a bound, never zero."""
    from belay.sandbox.gate import TurnGate

    scope = make_scope(tmp_path)
    gate = TurnGate(scope=scope, snapshot_root=tmp_path / "snaps")

    start = time.perf_counter()
    gate.before_frame(TOOLS_CALL, "c2s")
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert gate.durations_ms, "the gate must record what it cost the turn"
    assert elapsed_ms < LATENCY_BUDGET_MS, (
        f"the gate held the turn for {elapsed_ms:.1f}ms (budget {LATENCY_BUDGET_MS}ms)"
    )
    print(f"\nturn gate added {elapsed_ms:.1f}ms (recorded: {gate.durations_ms[0]:.1f}ms)")
