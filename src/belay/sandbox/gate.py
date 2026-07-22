"""The turn gate: snapshot a turn's pre-state before the call reaches the server.

This module is where C1 and C2 meet, and the join is the hard part of both.

## Why this exists at all

C2's snapshot is only worth taking if it captures the state the turn *started*
from. That state stops existing the moment the server executes the call — so the
snapshot must complete **before** the `tools/call` is forwarded, which means
holding the request. C1 deliberately built the opposite: its observation branch
runs off the hot path and is structurally unable to block or alter it, which is
exactly why anyone can trust a Belay trace.

Snapshotting from the observer would type-check, pass a naive test, and be wrong.
By the time a frame is observed it has already been written to the server's stdin;
the server may have already executed the call and already mutated the tree. The
snapshot would then be racing the mutation, and the trace would carry a
`present` handle pointing at a "pre-state" that is really a mid-state. Nothing
downstream could tell — every verdict grounded on it would be grounded on a tree
that never existed at the time it claims. That is a false PASS with a hash on it,
which is worse than no snapshot at all.

## How the tension resolves

`proxy.py` gained one thing: an optional `before_frame` hook, called with a
frame's bytes before any of them are forwarded (`proxy._FrameHold`). The hook is
**opaque to the proxy**. It stays `json`-free and cannot recognise a `tools/call`
— structurally, enforced by `tests/test_import_guard.py` — so it remains incapable
of parsing and re-emitting a frame. All the parsing lives here.

And here it is safe, because of a distinction that is easy to lose:

> **Parsing to read and parsing to re-emit are different operations. Only the
> latter mutates.**

This module calls `json.loads` on a **copy** and throws the result away. It never
serialises anything, never returns bytes to the proxy, and has no path by which
its opinion could reach the stream. The bytes the proxy forwards are the bytes
the client sent, byte for byte, whatever this module concludes about them —
`tests/test_turn_gate.py::test_byte_identity_holds_with_the_gate_installed` runs
C1's own differential through a gated proxy to keep that true.

**The gate buys latency, and only latency.** C1's neutrality claim was written
narrowly — it asserts bytes, never timing — and this is the thing that claim was
written narrowly *for*.

## The moment a turn begins is not the moment its frame is forwarded

Snapshotting before the forward is necessary and **not sufficient**, and the gap
between those two is subtle enough that this module shipped with it open.

"Forward the frame" and "the turn starts executing" are the same instant only if
at most one call is ever in flight. Nothing makes that true. JSON-RPC ids exist
precisely so a client may **pipeline**, and the agents Belay exists to wrap all do:
Claude Code is instructed to batch independent tool calls into one block, and
Cursor and the OpenAI agents SDK do the same. A parallel tool call is the common
case, not the corner.

So when two `tools/call` frames arrive back to back, snapshotting each as it is
forwarded takes *both* pre-states up front, before the server has executed either.
The second one is a lie: by the time turn 2 runs, turn 1 has already mutated the
tree, and the recorded "pre-state" is a tree that never existed at the moment it
claims. It is `present`, hashed, self-consistent and wrong — the same false PASS
this module's own argument above rejects, reached through a different door.

**The ledger.** The gate therefore tracks the request ids that are outstanding. A
`tools/call` is snapshotted only when the ledger is **empty**; one that arrives
while another is in flight is refused by name — `UNRESTORABLE_CONCURRENT_TURN` —
and the turn **still forwards**. C4 renders UNVERIFIED. The alternative was to
serialise turns (hold call N+1 until N's response), which would make the pre-state
true by making Belay **concurrency-altering**: a proxy that changes how the agent
behaves is a much larger claim than one that records honestly, and it is the one
thing this proxy exists not to do. Coverage is the honest thing to lose here.

This is why `before_frame` is installed on **both** directions. The gate learns a
turn is over from the response, and it must learn it from the s2c *hold* rather
than the s2c observer: the observer runs after the bytes reach the client, so the
client's next call could beat it to the gate and a perfectly sequential turn would
be refused for concurrency it never had. Holding a reply costs a `json.loads` and
buys the ledger being sound.

## Two rules this module cannot break

**It must never hang a turn.** A blocked proxy is worse than an unsnapshotted
turn: the agent stops. So every failure path here forwards. `before_frame` catches
everything, including from itself.

**It must never leave a stale handle.** The state handle is sticky — set on the
writer, describing subsequent frames — so a turn whose snapshot failed must
overwrite the previous turn's `present` with its own named failure. Failing
silently would leave the *last* turn's handle sitting on *this* turn's frame,
claiming a pre-state that was never taken. Every `tools/call` therefore sets
exactly one handle, whatever happens.

Stickiness is also why every handle is set **with the frame it describes**
(`set_state_handle(handle, frame=...)`). Sticky alone is a per-*chunk* answer to a
per-*frame* question: when a chunk holds two `tools/call`, both are gated before
either is recorded, so both frames read whichever handle was set last and at least
one names a snapshot that is not its own. The frame pins it.

## No verdicts

The gate records facts: a snapshot exists, or it could not be taken and here is
the named reason. **C4 renders UNVERIFIED.** A mechanism that graded its own
fidelity would collapse the grounding argument.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional, Protocol

from belay.replay.persist import persist_snapshot
from belay.snapshot.clone import TreeRoot
from belay.snapshot.substrate import (
    GuardedSnapshot,
    Unrestorable,
    UnrestorableCause,
    present_handle,
    take_snapshot,
    unrestorable_handle,
)

#: The JSON-RPC method that mutates the world, and so the only frame worth the
#: cost of a clone. `initialize`, `tools/list` and the notifications are not
#: turns: snapshotting them would pay for a tree walk that grounds nothing and
#: would make the handle mean "some frame went past" instead of "this is the
#: state the turn began from".
TOOLS_CALL = "tools/call"

#: The direction a request travels. Only this one precedes a tool executing.
CLIENT_TO_SERVER = "c2s"

#: The direction a response travels — the only evidence a turn has ENDED, and so
#: the only thing that can retire an entry from the in-flight ledger. Nothing is
#: snapshotted on this side; a reply mutates nothing.
SERVER_TO_CLIENT = "s2c"

#: What the gate emits when the snapshot fails for a reason C2's taxonomy does
#: not name — `ENOSPC`, `EXDEV`, a `clonefile` errno nobody has hit yet.
#:
#: Deliberately **not** a member of `UnrestorableCause`. That enum is Task 6's:
#: every member is classified as raised-there or deferred-to-a-named-owner and a
#: test asserts the partition is exhaustive, so adding one from here would break
#: that contract quietly. The alternatives are all worse than an unfamiliar name.
#: `absent` means *"no snapshot was attempted"* and would be a lie — one was
#: attempted. Reusing a real cause would be a lie about the reason. So: a named
#: fact, with the exception's own text as the detail, and a name C4 will not
#: recognise — which is the honest state of affairs, and strictly better than a
#: familiar name that is wrong.
#: `test_the_gate_owned_cause_is_not_smuggled_into_the_taxonomy` pins the
#: distinction so that reconciling it stays a visible decision.
SNAPSHOT_FAILED = "UNRESTORABLE_SNAPSHOT_FAILED"

_SOURCE_GATE = "turn-gate"


class StateSink(Protocol):
    """Where a turn's state handle goes. Structural on purpose, exactly as
    `proxy.CaptureSink` is: the gate knows the shape of a recorder and nothing
    about any particular one."""

    def set_state_handle(self, handle: dict[str, Any], *, frame: bytes) -> None: ...


class _UntrackableTurn:
    """A turn whose end this gate can never observe, standing in for its id.

    A `tools/call` with no usable id is unanswerable: JSON-RPC has no reply to
    send, so no response will ever retire it from the ledger. That is not a reason
    to ignore it — a call with no id still *executes*, and a later turn
    snapshotted while it runs would clone a tree it is in the middle of changing.

    So it occupies the ledger forever, and every subsequent turn in the run is
    refused for concurrency. That is severe, and it is the honest reading: we
    genuinely cannot tell when this call finished, and the only alternatives are
    to guess or to keep quiet. Its *own* pre-state is still real and still
    snapshotted — nothing was outstanding when it began.

    Identity-hashed, so two of them never collide and neither can be discarded by
    an id from the wire.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "<tools/call with no id: unanswerable, so never retired>"


def _messages(frame: bytes) -> tuple[Any, ...]:
    """Every JSON-RPC message in `frame`. Read from a **copy**, never re-emitted.

    Anything unparseable is not this module's business. The proxy forwards
    everything and polices nothing — a non-conforming frame is a trap for a later
    capability, not something to reject here — so a frame we cannot read carries
    no turn we can recognise, and it crosses untouched either way.

    Batches are unpacked because the 2025-03-26 spec allowed them and 2025-06-18
    removed them again: a client on the older revision can legally put a
    `tools/call` inside an array, and a gate that only understood objects would
    silently skip the snapshot for it.
    """
    try:
        message = json.loads(frame)
    except (ValueError, RecursionError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError both; a
        # non-UTF-8 frame is exactly the kind the proxy exists to carry intact.
        return ()
    return tuple(message) if isinstance(message, list) else (message,)


def _turn_ids(frame: bytes) -> list[Any]:
    """The id of every `tools/call` in `frame`; empty if it carries none.

    A list rather than a count, because the ledger is keyed on ids and a batch may
    legally begin more than one turn in a single frame.
    """
    ids = []
    for message in _messages(frame):
        if isinstance(message, dict) and message.get("method") == TOOLS_CALL:
            ids.append(_turn_id(message))
    return ids


def _turn_id(message: dict) -> Any:
    identifier = message.get("id")
    if identifier is None or isinstance(identifier, (list, dict)):
        # Absent, null (a notification: unanswerable), or a container (illegal,
        # and unhashable besides). Either way there is no id a response can name.
        return _UntrackableTurn()
    return identifier


def _answered_ids(frame: bytes) -> list[Any]:
    """The ids `frame` answers — the turns it proves are over.

    A message is a response when it carries a `result` or an `error` and **no
    method**. The method check is what keeps a server-originated request
    (`sampling/createMessage`, `roots/list`) from retiring a turn that is still
    running: those travel the same direction, carry an id from the server's own id
    space, and answer nothing.
    """
    ids = []
    for message in _messages(frame):
        if not isinstance(message, dict) or "method" in message:
            continue
        if "result" not in message and "error" not in message:
            continue
        identifier = message.get("id")
        if identifier is not None and not isinstance(identifier, (list, dict)):
            ids.append(identifier)
    return ids


def _concurrent_handle(detail: str) -> dict[str, Any]:
    """The refusal, shaped exactly like every other named one Task 6 emits."""
    return unrestorable_handle(
        Unrestorable(
            UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN,
            detail,
            source=_SOURCE_GATE,
        )
    )


def _snapshot_failed_handle(exc: BaseException) -> dict[str, Any]:
    return {
        "status": "unrestorable",
        "cause": SNAPSHOT_FAILED,
        "detail": f"{type(exc).__name__}: {exc}",
        "source": _SOURCE_GATE,
    }


class TurnGate:
    """Holds a snapshottable `tools/call` for as long as its snapshot takes.

    Not every `tools/call` is snapshottable: one that arrives while another is
    outstanding has no pre-state left to capture, and is refused by name instead of
    cloned and mislabelled. See the module docstring — that distinction is the
    difference between a fact and a false PASS with a hash on it.

    Installed via `proxy.run(before_frame=gate.before_frame)` on **both**
    directions, and only when a sandbox is configured — with no scope there is no
    gate object at all, and the proxy runs C1's pump untouched.
    """

    def __init__(
        self,
        scope: TreeRoot,
        snapshot_root: TreeRoot,
        trace: Optional[StateSink] = None,
    ) -> None:
        self._scope = Path(scope).resolve()
        self._snapshot_root = Path(snapshot_root).resolve()
        self._trace = trace
        self._turn = 0

        if self._snapshot_root == self._scope or self._scope in self._snapshot_root.parents:
            # Turn 1 would clone turn 0's snapshot into itself, and every turn
            # after would carry all the ones before it. The recorded "pre-state"
            # would then contain artifacts that were never in the agent's
            # workspace — and it would look impeccable: `present` handle,
            # self-consistent hash, nothing downstream able to tell. Refused at
            # startup, because the alternative is a run that quietly grounds
            # every verdict on a tree that never existed.
            raise ValueError(
                f"snapshot_root {str(self._snapshot_root)!r} is inside the scope "
                f"{str(self._scope)!r}: each turn would snapshot the previous "
                f"turns' snapshots, and record a pre-state the agent never had"
            )

        #: Live snapshots by handle — the same id the trace's `present` handle
        #: carries, so a reader holding a trace record can resolve it to the tree
        #: it names. Kept for the in-process fast path; a later process resolves
        #: the same handle through the persisted manifest below instead.
        self.snapshots: dict[str, GuardedSnapshot] = {}

        #: Where each turn's manifest is persisted, one `<handle>.json` per turn,
        #: joining the trace's handle to the tree and the sidecar `clone.restore`
        #: needs. This is what lets `belay replay` restore in a *later* process —
        #: the in-memory `snapshots` map above does not survive one. Kept OUT of
        #: `snapshot_root` on purpose: that directory holds one entry per turn and
        #: is enumerated as such, so the manifests live in a sibling directory
        #: rather than as extra entries beside the `turn-NNNN` trees.
        self.manifest_root = self._snapshot_root.parent / f"{self._snapshot_root.name}.manifests"

        #: What each gated turn cost, in milliseconds. Measured rather than
        #: estimated: the gate is the first thing ever allowed to delay the data
        #: path, so what it actually costs is a fact worth carrying, not a
        #: footnote in a design doc.
        self.durations_ms: list[float] = []

        #: The request ids of every `tools/call` that has been forwarded and not
        #: yet answered. A turn is snapshottable only when this is EMPTY; see the
        #: module docstring for why "forwarded" and "began executing" are not the
        #: same instant.
        self._in_flight: set[Any] = set()

        #: `_in_flight` is the one thing here touched by both pump threads — c2s
        #: adds, s2c retires — so it is the one thing that needs a lock. The
        #: snapshot deliberately happens OUTSIDE it: a clone can take tens of
        #: milliseconds, and holding the lock across one would stall every reply
        #: the server sends while it runs.
        self._ledger = threading.Lock()

    def before_frame(self, frame: bytes, direction: str) -> None:
        """The hook, on both directions. Requests may snapshot; responses retire.

        **Never raises.** The proxy guards this call too, but that guard is a
        backstop for a bug rather than this method's error handling: a gate that
        threw would kill the direction and hang the agent, and no snapshot is
        worth that.
        """
        try:
            if direction == CLIENT_TO_SERVER:
                self._on_request(frame)
            elif direction == SERVER_TO_CLIENT:
                self._on_response(frame)
        except BaseException as exc:  # noqa: BLE001 - the bytes outrank this module
            self._degrade(f"turn gate failed outside the snapshot: {exc!r}")

    def _on_request(self, frame: bytes) -> None:
        ids = _turn_ids(frame)
        if not ids:
            return
        started = time.perf_counter()
        try:
            with self._ledger:
                # Checked and claimed together: the check is only meaningful if
                # nothing can join the ledger between reading it and acting on it.
                outstanding = sorted(str(entry) for entry in self._in_flight)
                self._in_flight.update(ids)
            if outstanding:
                self._set_handle(
                    _concurrent_handle(
                        f"this tools/call was forwarded while {len(outstanding)} "
                        f"other call(s) were still outstanding (ids {outstanding}), "
                        f"so the tree it would have cloned is already a mid-state "
                        f"of those turns rather than this turn's pre-state"
                    ),
                    frame,
                )
            elif len(ids) > 1:
                # One frame, several turns. The first one's pre-state is real, but
                # a frame carries one handle and the rest ran against whatever the
                # calls before them did — so there is no honest per-turn answer to
                # give here, and the frame is refused as a whole.
                self._set_handle(
                    _concurrent_handle(
                        f"this frame is a batch of {len(ids)} tools/call, which "
                        f"begin together: only the first has this tree as its "
                        f"pre-state, and one frame carries one handle"
                    ),
                    frame,
                )
            else:
                self._snapshot_turn(frame)
        finally:
            self.durations_ms.append((time.perf_counter() - started) * 1000)

    def _on_response(self, frame: bytes) -> None:
        """Retire the turns this response ends.

        Reached from the s2c hold, so this runs before the client can see the
        reply — which is what stops a client's next call racing its own response
        to the gate and being refused for a concurrency it did not have.
        """
        ids = _answered_ids(frame)
        if not ids:
            return
        with self._ledger:
            self._in_flight.difference_update(ids)

    def _snapshot_turn(self, frame: bytes) -> None:
        dest = self._snapshot_root / f"turn-{self._turn:04d}"
        self._turn += 1
        try:
            self._snapshot_root.mkdir(parents=True, exist_ok=True)
            snap = take_snapshot(self._scope, dest)
            # Persist inside the try, before the handle is emitted: a snapshot that
            # cannot be written to disk is not resolvable in a later process, so it
            # must be reported as a failure rather than as a `present` handle that
            # promises a restore no later process could perform.
            persist_snapshot(
                snap,
                self.manifest_root / f"{snap.manifest.handle}.json",
                # The original workspace root, already resolved at `__init__`
                # (`Path(scope).resolve()`). Recorded per turn so replay can know the
                # source prefix; recorded only — this axis never consumes it.
                source_root=str(self._scope),
            )
        except Unrestorable as exc:
            # Task 6 refused by name — a FIFO, a socket, a capability gap. The
            # refusal is the useful fact, and it is already named.
            self._set_handle(unrestorable_handle(exc), frame)
        except Exception as exc:  # noqa: BLE001
            self._set_handle(_snapshot_failed_handle(exc), frame)
        else:
            self.snapshots[snap.manifest.handle] = snap
            self._set_handle(present_handle(snap), frame)

    def _set_handle(self, handle: dict[str, Any], frame: bytes) -> None:
        """Record `handle` as this turn's, and as the frame `frame`'s specifically.

        The frame is passed so the writer can put this handle on *this* frame
        rather than on whichever frame it happens to record next. Without it the
        handle is sticky-only, which is a per-chunk answer to a per-frame
        question — see the module docstring.
        """
        if self._trace is None:
            return
        try:
            self._trace.set_state_handle(handle, frame=frame)
        except Exception as exc:  # noqa: BLE001
            # The recorder is what broke, so do not try to record it there. This
            # is the one failure that can leave a previous turn's handle sitting
            # on this turn's frames, so it must be loud where someone will see it.
            self._degrade(
                f"could not record the state handle for turn {self._turn - 1} "
                f"({handle.get('status')}/{handle.get('cause', '-')}): {exc!r}. "
                f"Frames from this turn may carry the PREVIOUS turn's handle."
            )

    @staticmethod
    def _degrade(message: str) -> None:
        print(f"belay: {message}", file=sys.stderr)


__all__ = [
    "CLIENT_TO_SERVER",
    "SERVER_TO_CLIENT",
    "SNAPSHOT_FAILED",
    "TOOLS_CALL",
    "StateSink",
    "TurnGate",
]
