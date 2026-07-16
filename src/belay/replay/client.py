"""The client half of replay: spawn a server, send recorded frames, read the reply.

`proxy.py` is a PUMP — it forwards between two live pipes and originates nothing.
C3 replays a recorded turn, and replaying means being the *client*: spawn the
server, send the frames the trace recorded, and await the reply that answers each
one. Nothing reusable existed for that half; this module is it. It reports facts —
which frame was answered by what, and whether a reply arrived at all — and emits no
verdict. Whether the observed reply matches the recorded one is C4's diff.

## Two things carry a Fatal risk, and the module is shaped around them.

**Replay runs against a scratch copy, never live state.** `replay_turn` restores
the snapshot into a fresh throwaway directory and runs the server there, with its
cwd set to that copy. The snapshot tree the trace points at, and the workspace it
was taken from, are never handed to the server. C3's contract — *"replay never
mutates the original trace or live state"* — is asserted by
`test_replay_runs_against_a_scratch_copy_and_leaves_the_original_untouched`, which
runs a server that mutates its workspace and proves both originals are byte-identical
(BTH-1) afterwards.

**A request with no usable id is unanswerable, so the wait must be bounded.** By
JSON-RPC a response is correlated to its request by id; a `tools/call` whose id is
absent, null, or a container has no id a response could ever carry back. That is
exactly `gate._UntrackableTurn` — the turn the gate says can *never be retired* —
and this module reuses that very sentinel as the await-key so that no reply can
match it and the wait falls through to the timeout. The client never blocks forever
on a reply that cannot exist: it times out on a bounded wait and names which frame
had no answer (`NO_USABLE_ID`). A server that emits a spurious `id: null` reply must
NOT be allowed to retire such a request — there is no id to match on — which is why
the sentinel, not the bare id, is the key.

## Correlation is by `(direction, type(id), id)`, never the bare id.

Reused from `belay.index._id_key`: `1`, `"1"`, `1.0` and `True` are four different
ids on the wire that Python would otherwise conflate. A reply travels back the way
its request came, so a client-to-server request (`c2s`) is answered server-to-client
(`s2c`); both the await-key and the reply-key are computed in the `s2c` id space.

## A fresh process per replay.

`replay_turn` spawns the server once, per call, and tears it down after. C2's
argument for why v0 is stdio-only: a fresh process avoids most
PROCESS_INTERNAL_STATE (open fds, pools, sessions) leaking between replays.

## Zero runtime dependencies.

stdlib only — `subprocess` to spawn, `select`/`os.read` for the bounded read, `json`
to read a **copy** of a frame for its id (never to re-emit it). The `mcp` SDK is
dev-only and is never imported here; `tests/test_import_guard.py` enforces it.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.index import _id_key, classify
from belay.replay.persist import load_snapshot
from belay.sandbox.gate import _UntrackableTurn
from belay.sandbox.launch import contained, network_policy
from belay.snapshot.substrate import guarded_restore

#: A reply arrived and its id matched the request's.
ANSWERED = "answered"
#: The frame was a notification (or otherwise expects no reply); none was awaited.
NO_REPLY_EXPECTED = "no-reply-expected"
#: The frame is a request with no usable id — the `_UntrackableTurn` condition. No
#: response can carry an id back to answer it, so the bounded wait timed out. Named
#: distinctly from `TIMED_OUT` because the cause is structural, not slowness.
NO_USABLE_ID = "no-usable-id"
#: The frame had a usable id but no matching reply arrived before the deadline.
TIMED_OUT = "timed-out"
#: The server's stdout reached EOF (it exited) before the awaited reply, or its
#: stdin was already closed when we tried to send.
SERVER_EXITED = "server-exited"

#: The direction a reply to a client request travels. Requests we send are `c2s`;
#: their replies come back `s2c`, and that is the id space both keys live in.
_SERVER_TO_CLIENT = "s2c"

#: A generous default for a real replay; tests override it with a short value to
#: exercise the timeout path fast.
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class FrameOutcome:
    """What became of one sent frame: its position, the exact bytes, and the fact.

    `frame` is carried so the caller can name *which* frame had no reply without
    reconstructing it — the brief's requirement that a no-reply outcome name its
    frame rather than losing it. `reply` is the raw reply line when one arrived,
    byte-for-byte as the server wrote it, and `None` otherwise.
    """

    index: int
    frame: bytes
    status: str
    reply: Optional[bytes] = None


@dataclass(frozen=True)
class ReplayResult:
    """The per-frame outcomes of a replay, and the scratch workspace it ran in.

    `workspace` is the restored scratch copy the server ran against — the *post*-state
    a later diff (C4) reads. It is deliberately left on disk; the caller owns it.
    """

    outcomes: list[FrameOutcome]
    workspace: Optional[str] = None

    @property
    def replies(self) -> list[bytes]:
        return [o.reply for o in self.outcomes if o.reply is not None]


def _first_object(frame: bytes) -> Optional[dict]:
    """The first JSON-RPC object in a frame, read from a copy; `None` if unreadable.

    A batch (array) is unpacked to its first object, mirroring `gate._messages`;
    anything that is not a JSON object carries no request we can await.
    """
    try:
        message = json.loads(frame)
    except (ValueError, RecursionError):
        return None
    if isinstance(message, list):
        for item in message:
            if isinstance(item, dict):
                return item
        return None
    return message if isinstance(message, dict) else None


def _await_key(message: Optional[dict]) -> Any:
    """The key a reply to `message` must carry, or a marker that none is expected.

    Returns one of:

    - ``None`` — no reply is expected: the frame is not a request (it carries no
      `method`), or it is a genuine `notifications/*` notification.
    - a `_UntrackableTurn` — the frame is a request with no usable id (absent, null,
      or a container: the exact condition `gate._turn_id` names untrackable). It is
      awaited, but no reply can ever match, so the wait times out. Reusing the gate's
      own sentinel keeps "unanswerable" one definition, not two.
    - a ``(direction, type, id)`` tuple — the frame is an answerable request; a
      matching reply must carry this key.
    """
    if message is None:
        return None
    method = message.get("method")
    if method is None:
        # No method: not a request we originate a wait for (a lone response, say).
        return None
    if isinstance(method, str) and method.startswith("notifications/"):
        # A genuine JSON-RPC notification: no id, no reply, by definition.
        return None
    identifier = message.get("id")
    if identifier is None or isinstance(identifier, (list, dict)):
        # The request has a method but no id a response could name — `tools/call`
        # with the id absent, null, or a container. Unanswerable; the gate's
        # sentinel is the await-key precisely because nothing can retire it.
        return _UntrackableTurn()
    return _id_key(_SERVER_TO_CLIENT, identifier)


class _Replies:
    """A newline-framed reader over the server's stdout fd, with a hard deadline.

    Reads on the raw fd via `os.read` so the wait can be bounded by `select`; the
    server's stdout file object is never read through, so nothing is buffered out of
    reach. The read buffer persists across `await_reply` calls: a server may have
    written the next reply already, and dropping the tail between frames would lose
    it.
    """

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._buf = b""
        self._eof = False

    def _pop_line(self) -> Optional[bytes]:
        newline = self._buf.find(b"\n")
        if newline < 0:
            return None
        line, self._buf = self._buf[:newline], self._buf[newline + 1 :]
        return line

    def await_reply(self, key: Any, timeout: float) -> tuple[Optional[bytes], str]:
        """Read lines until one is a response matching `key`, or the deadline passes.

        Returns `(line, ANSWERED)` on a match, `(None, TIMED_OUT)` if the bounded
        wait elapses (which includes the `_UntrackableTurn` key that nothing can
        match), or `(None, SERVER_EXITED)` on EOF.
        """
        deadline = time.monotonic() + timeout
        while True:
            line = self._pop_line()
            if line is not None:
                if self._matches(line, key):
                    return line, ANSWERED
                # Not our reply — a server-originated request, a notification, a log
                # line, or a response to a different id. Keep reading.
                continue
            if self._eof:
                return None, SERVER_EXITED
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, TIMED_OUT
            ready, _, _ = select.select([self._fd], [], [], remaining)
            if not ready:
                return None, TIMED_OUT
            chunk = os.read(self._fd, 65536)
            if chunk == b"":
                self._eof = True
                continue
            self._buf += chunk

    @staticmethod
    def _matches(line: bytes, key: Any) -> bool:
        """True iff `line` is a JSON-RPC response whose id-key equals `key`.

        Only responses can answer a request: a server-originated request also
        carries an id (in the server's own id space) and must never be mistaken for
        our reply, so `classify` gates on `result`/`error` with no `method`. A
        `_UntrackableTurn` key is an object, never equal to the reply's tuple key, so
        this is always False for it — which is exactly why an unanswerable frame
        times out.
        """
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            return False
        if not isinstance(message, dict) or classify(message) != "response":
            return False
        return _id_key(_SERVER_TO_CLIENT, message.get("id")) == key


def converse(
    proc: subprocess.Popen, frames: Sequence[bytes], *, timeout: float = DEFAULT_TIMEOUT
) -> list[FrameOutcome]:
    """Send each frame to `proc`, await the reply it expects, and record the outcome.

    The conversation core, independent of the sandbox: `proc` is any spawned server
    with `stdin`/`stdout` pipes. For each frame it derives whether a reply is
    expected and, if so, the key that reply must carry, sends the frame, and reads —
    bounded by `timeout` — until the match arrives or the wait is over. A frame that
    cannot be sent (the server's stdin is gone) or whose reply never arrives before
    the server exits ends the conversation, because every later frame would fail the
    same way; what was collected so far is returned rather than lost.
    """
    if proc.stdin is None or proc.stdout is None:
        raise ValueError("converse needs a process spawned with stdin=PIPE and stdout=PIPE")
    stdin, stdout = proc.stdin, proc.stdout
    replies = _Replies(stdout.fileno())
    outcomes: list[FrameOutcome] = []
    for index, frame in enumerate(frames):
        key = _await_key(_first_object(frame))
        try:
            stdin.write(frame + b"\n")
            stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            # The server's read end is gone; it exited before we finished sending.
            outcomes.append(FrameOutcome(index=index, frame=frame, status=SERVER_EXITED))
            break
        if key is None:
            outcomes.append(FrameOutcome(index=index, frame=frame, status=NO_REPLY_EXPECTED))
            continue
        reply, why = replies.await_reply(key, timeout)
        if reply is not None:
            outcomes.append(FrameOutcome(index=index, frame=frame, status=ANSWERED, reply=reply))
            continue
        if isinstance(key, _UntrackableTurn):
            # The defining fact is the missing id, not the clock: even a live server
            # could never answer this. Name it as such regardless of how the wait ended.
            status = NO_USABLE_ID
        else:
            status = why  # TIMED_OUT or SERVER_EXITED
        outcomes.append(FrameOutcome(index=index, frame=frame, status=status))
        if why == SERVER_EXITED:
            break
    return outcomes


def replay_turn(
    server_command: Sequence[str],
    *,
    snapshot_manifest: Path | str,
    frames: Sequence[bytes],
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> ReplayResult:
    """Restore the snapshot to a scratch copy, spawn the server in the sandbox, replay.

    The workspace handed to the sandbox is a **fresh** restore of the snapshot into a
    throwaway directory — never the snapshot tree and never the original workspace,
    so the replay cannot mutate live state. The server runs contained (Seatbelt,
    `deny-all` network unless the caller widens it) with its cwd set to that scratch
    copy, so a server that writes relative paths mutates the copy and nothing else.
    A fresh process is spawned and torn down within the sandbox's lifetime.

    Off macOS `contained` raises `UnsupportedPlatform` rather than running unsandboxed.
    """
    snap = load_snapshot(Path(snapshot_manifest))
    scratch = Path(tempfile.mkdtemp(prefix="belay-replay-"))
    # Restore INTO the fresh scratch dir (restore replaces whatever is there). The
    # snapshot tree `snap.snapshot.path` is the source and is never handed to the
    # server — running against it would be the Fatal "replay mutates live state".
    guarded_restore(snap, scratch)

    net = network if network is not None else network_policy(None)
    outcomes: list[FrameOutcome] = []
    resolved = str(scratch)
    with contained(list(server_command), workspace=scratch, network=net) as spawn:
        resolved = spawn.scope.snapshot_root
        proc = subprocess.Popen(
            spawn.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=resolved,
        )
        try:
            outcomes = converse(proc, frames, timeout=timeout)
        finally:
            _terminate(proc)
    return ReplayResult(outcomes=outcomes, workspace=resolved)


def _terminate(proc: subprocess.Popen) -> None:
    """Close the pipes and make sure the process is gone — killed if it will not stop."""
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


__all__ = [
    "ANSWERED",
    "NO_REPLY_EXPECTED",
    "NO_USABLE_ID",
    "SERVER_EXITED",
    "TIMED_OUT",
    "FrameOutcome",
    "ReplayResult",
    "converse",
    "replay_turn",
]
