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

## Two rules this module cannot break

**It must never hang a turn.** A blocked proxy is worse than an unsnapshotted
turn: the agent stops. So every failure path here forwards. `before_frame` catches
everything, including from itself.

**It must never leave a stale handle.** The state handle is sticky — it is set on
the writer and describes subsequent frames — so a turn whose snapshot failed must
overwrite the previous turn's `present` with its own named failure. Failing
silently would leave the *last* turn's handle sitting on *this* turn's frame,
claiming a pre-state that was never taken. Every `tools/call` therefore sets
exactly one handle, whatever happens.

## No verdicts

The gate records facts: a snapshot exists, or it could not be taken and here is
the named reason. **C4 renders UNVERIFIED.** A mechanism that graded its own
fidelity would collapse the grounding argument.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional, Protocol

from belay.snapshot.clone import TreeRoot
from belay.snapshot.substrate import (
    GuardedSnapshot,
    Unrestorable,
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

    def set_state_handle(self, handle: dict[str, Any]) -> None: ...


def _is_tools_call(frame: bytes) -> bool:
    """Does this frame carry a `tools/call`? Read from a **copy**, never re-emitted.

    Anything unparseable is not this module's business. The proxy forwards
    everything and polices nothing — a non-conforming frame is a trap for a later
    capability, not something to reject here — so a frame we cannot read simply
    is not a turn we can recognise, and it crosses untouched either way.

    Batches are handled because the 2025-03-26 spec allowed them and 2025-06-18
    removed them again: a client on the older revision can legally put a
    `tools/call` inside an array, and a gate that only understood objects would
    silently skip the snapshot for it.
    """
    try:
        message = json.loads(frame)
    except (ValueError, RecursionError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError both; a
        # non-UTF-8 frame is exactly the kind the proxy exists to carry intact.
        return False

    if isinstance(message, list):
        return any(_names_tools_call(item) for item in message)
    return _names_tools_call(message)


def _names_tools_call(message: object) -> bool:
    return isinstance(message, dict) and message.get("method") == TOOLS_CALL


def _snapshot_failed_handle(exc: BaseException) -> dict[str, Any]:
    return {
        "status": "unrestorable",
        "cause": SNAPSHOT_FAILED,
        "detail": f"{type(exc).__name__}: {exc}",
        "source": _SOURCE_GATE,
    }


class TurnGate:
    """Blocks each `tools/call` for exactly as long as its snapshot takes.

    Installed via `proxy.run(before_frame=gate.before_frame)`, and only when a
    sandbox is configured — with no scope there is no gate object at all, and the
    proxy runs C1's pump untouched.
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
        #: it names. In-process only: the sidecar `clone.restore` needs lives in
        #: memory, so restoring in a *later* process is C3's problem, not a
        #: promise made here.
        self.snapshots: dict[str, GuardedSnapshot] = {}

        #: What each gated turn cost, in milliseconds. Measured rather than
        #: estimated: the gate is the first thing ever allowed to delay the data
        #: path, so what it actually costs is a fact worth carrying, not a
        #: footnote in a design doc.
        self.durations_ms: list[float] = []

    def before_frame(self, frame: bytes, direction: str) -> None:
        """The hook. Returns having snapshotted, or having named why it could not.

        **Never raises.** The proxy guards this call too, but that guard is a
        backstop for a bug rather than this method's error handling: a gate that
        threw would kill the direction and hang the agent, and no snapshot is
        worth that.
        """
        try:
            if direction != CLIENT_TO_SERVER or not _is_tools_call(frame):
                return
            started = time.perf_counter()
            try:
                self._snapshot_turn()
            finally:
                self.durations_ms.append((time.perf_counter() - started) * 1000)
        except BaseException as exc:  # noqa: BLE001 - the bytes outrank this module
            self._degrade(f"turn gate failed outside the snapshot: {exc!r}")

    def _snapshot_turn(self) -> None:
        dest = self._snapshot_root / f"turn-{self._turn:04d}"
        self._turn += 1
        try:
            self._snapshot_root.mkdir(parents=True, exist_ok=True)
            snap = take_snapshot(self._scope, dest)
        except Unrestorable as exc:
            # Task 6 refused by name — a FIFO, a socket, a capability gap. The
            # refusal is the useful fact, and it is already named.
            self._set_handle(unrestorable_handle(exc))
        except Exception as exc:  # noqa: BLE001
            self._set_handle(_snapshot_failed_handle(exc))
        else:
            self.snapshots[snap.manifest.handle] = snap
            self._set_handle(present_handle(snap))

    def _set_handle(self, handle: dict[str, Any]) -> None:
        if self._trace is None:
            return
        try:
            self._trace.set_state_handle(handle)
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
    "SNAPSHOT_FAILED",
    "TOOLS_CALL",
    "StateSink",
    "TurnGate",
]
