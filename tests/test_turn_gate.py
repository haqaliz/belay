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
from belay.snapshot.substrate import guarded_restore

MUTATING = Path(__file__).parent / "fixtures" / "mutating_server.py"

# CLIENT_LINES[3] is the scripted client's `tools/call`. Taken from the shared rig
# rather than hand-written here: the gate must recognise the same adversarial
# frame (scrambled key order, a \uXXXX escape) the differential feeds, not a
# tidied-up rewrite of it that only this test would ever produce.
TOOLS_CALL = CLIENT_LINES[3]
NOT_A_TOOLS_CALL = CLIENT_LINES[2]

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


def test_a_batched_write_puts_the_turns_handle_on_its_whole_chunk(tmp_path):
    """A KNOWN LIMIT, pinned so it is a decision rather than a discovery.

    When a client packs several frames into ONE write, every frame in that chunk
    carries the turn's handle — including ones that crossed before the snapshot.

    This is C1's shape, not a gate bug, and it is not fixable from here. The pump
    forwards a whole chunk and observes it afterwards, on purpose: *"Deliberately
    after the forward, and it stays there: forwarding must never wait on the
    recorder."* The hook runs per frame (the gate needs that), but observation is
    still per chunk, so a `tools/call` sharing a chunk with earlier frames has
    already snapshotted by the time any of them are recorded. Interleaving
    observation per-frame would put the recorder's hashing on the data path and
    trade C1's guarantee for C2's convenience.

    **What it costs:** on a batched write, `present` on a non-`tools/call` frame
    means "a snapshot was current when this frame was recorded", not "this frame
    crossed after it". The load-bearing claim — the `tools/call` frame carries its
    OWN turn's pre-state — is unaffected, and that is the one C4 reads.
    C2 records; C4 renders. This is on the list of what it must know.
    """
    scope = make_scope(tmp_path)
    trace_dir = tmp_path / "trace"
    run_over_pipes(  # communicate(): all four lines in a single write
        proxied(MUTATING),
        env=gated_env(scope, tmp_path / "snaps", trace_dir=trace_dir),
    )
    handles = [f["state_handle"] for f in frames_of(read_trace(trace_dir), "c2s")]
    assert len(handles) == 4
    assert all(h["status"] == "present" for h in handles), (
        "the batched-chunk limit changed shape - if observation is now per-frame, "
        "this test should become the strict assertion instead of being relaxed"
    )


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

        def set_state_handle(self, handle: dict) -> None:
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
