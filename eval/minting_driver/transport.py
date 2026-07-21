"""An interactive MCP stdio transport: one request at a time, awaited by id.

`StdioMcp` spawns a given server command and speaks newline-delimited JSON-RPC
over its stdio pipes. It is deliberately the *interactive* half of what
`belay.replay.client` already has (`converse`, which sends a pre-built list of
frames and walks them in order): the minting-driver loop (Task 3) does not know
its next frame until the model responds to the previous one, so this transport
exposes `request`/`notify` as single calls a caller makes one at a time.

## Adapted from `belay.replay.client`, copied rather than imported

The send/await/correlate core below (`_Replies`, the newline-framed
`select`-bounded read loop, and id-based correlation) mirrors
`belay.replay.client._Replies` / `converse`
(`src/belay/replay/client.py:175-244,260-290`) almost line for line. **Decision
(from the plan):** copy the ~30 lines here rather than `import belay.replay` —
`eval/` is a new, eval-only top-level tree that must never depend on
`src/belay`, so that the isolation contract stays structural, not a matter of
discipline. `tests/test_minting_driver_transport.py::
test_transport_module_is_standalone` checks this by AST, the same way
`tests/test_import_guard.py` checks `src/belay`'s dependency graph.

One simplification versus the replay client: correlation here only ever runs
in one direction (this transport is always the client of one spawned server),
so the id key drops the `direction` component `belay.index._id_key` carries
for a byte-transparent *proxy*, which sees both directions on one pipe.

## Every failure is explicit, never a hang and never a wrong match

A reply that never arrives before the process exits raises `ServerExited`
(EOF on stdout, or a broken pipe on send). A reply that never arrives before
`timeout` elapses raises `ReplyTimeout`. Neither path can return a reply that
doesn't carry the id-key the request was sent with — `_Replies.await_reply`
never returns on a match; it only returns by raising once the wait is
genuinely over.

Stdlib only (`subprocess`, `json`, `select`, `os`, `time`) — no `mcp` SDK, no
`belay` import. Zero runtime dependencies, matching the rest of the repo.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from typing import Any, Optional

#: A generous default for a real run; tests pass a short value to exercise the
#: timeout paths fast.
DEFAULT_TIMEOUT = 10.0

#: Bounded tail of the server's stderr kept for diagnostics (e.g. surfacing in
#: a `ServerExited`/`ReplyTimeout` message). Draining discards everything past
#: this many trailing bytes — the point is to never let the OS pipe buffer
#: fill, not to buffer the server's whole log in memory.
_STDERR_TAIL_BYTES = 8192


class TransportError(RuntimeError):
    """Base class for every explicit failure `StdioMcp` can raise."""


class ServerExited(TransportError):
    """The server's stdout hit EOF, or its stdin was already closed, before a
    reply this transport was waiting for arrived."""


class ReplyTimeout(TransportError):
    """No reply matching the awaited id arrived before the deadline, and the
    server process is still alive (otherwise this would be `ServerExited`)."""


def _id_key(id_: Any) -> tuple:
    """The correlation key, carrying the id's type.

    Adapted from `belay.index._id_key`: `1`, `"1"`, `1.0`, and `True` are four
    different ids on the wire that plain `==` would otherwise conflate (Python
    treats `1 == True` and `1 == 1.0` as true). Single-direction here (see
    module docstring), so unlike the original there is no `direction`
    component to key on.
    """
    return (type(id_).__name__, id_)


class _Replies:
    """A newline-framed reader over a stdout fd, with a hard per-call deadline.

    Adapted from `belay.replay.client._Replies` (see module docstring). Reads
    on the raw fd via `os.read` so the wait can be bounded by `select`; the
    read buffer persists across calls, because a server may already have
    written the next line before this call started reading.
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

    def await_reply(self, key: Any, timeout: float) -> bytes:
        """Read lines until one is a response matching `key`.

        Raises `ReplyTimeout` if the bounded wait elapses with the process
        still alive, or `ServerExited` if stdout reaches EOF first. Never
        returns anything other than the one matching line.
        """
        deadline = time.monotonic() + timeout
        while True:
            line = self._pop_line()
            if line is not None:
                if self._matches(line, key):
                    return line
                # Not our reply — a stray notification, a mismatched id, or a
                # log-shaped line. Keep reading rather than trusting the first
                # response-shaped line we see.
                continue
            if self._eof:
                raise ServerExited(
                    "server's stdout closed before a matching reply arrived"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReplyTimeout(f"no reply matching id {key[1]!r} within {timeout}s")
            ready, _, _ = select.select([self._fd], [], [], remaining)
            if not ready:
                raise ReplyTimeout(f"no reply matching id {key[1]!r} within {timeout}s")
            chunk = os.read(self._fd, 65536)
            if chunk == b"":
                self._eof = True
                continue
            self._buf += chunk

    @staticmethod
    def _matches(line: bytes, key: Any) -> bool:
        """True iff `line` is a JSON-RPC response whose id-key equals `key`.

        A response is `result`/`error` present, mirroring `belay.index.classify`;
        anything unparsable or request/notification-shaped is never a match.
        """
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            return False
        if not isinstance(message, dict):
            return False
        if "result" not in message and "error" not in message:
            return False
        return _id_key(message.get("id")) == key


class _StderrDrain:
    """Continuously drains a child's stderr in a background daemon thread.

    Started once from `StdioMcp.__init__` and runs until the stream hits EOF
    (the child exited) or is closed out from under it. This is the fix for a
    real deadlock: `StdioMcp` spawns its server with `stderr=subprocess.PIPE`,
    and if nothing reads that pipe, a server that logs verbosely to stderr
    fills the OS pipe buffer (typically 64KB) and blocks on its own
    `write()`. A blocked server never gets around to writing the stdout reply
    a caller is awaiting, which then surfaces as a spurious `ReplyTimeout`
    against a perfectly healthy server. Draining continuously, independent of
    whether anyone is awaiting a reply, is the only fix — reading stderr only
    from inside `request()`/`close()` would still leave gaps where the pipe
    can fill.

    Only a bounded tail (`_STDERR_TAIL_BYTES`) is kept, for diagnostics; the
    goal is to keep the pipe empty, not to buffer a chatty server's whole log.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._tail = b""
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                chunk = self._stream.read(65536)
                if not chunk:
                    return  # EOF: the server exited (or never wrote anything)
                with self._lock:
                    self._tail = (self._tail + chunk)[-_STDERR_TAIL_BYTES:]
        except (ValueError, OSError):
            # The stream was closed out from under us during teardown —
            # nothing left to drain, and nothing to raise here for.
            return

    def tail(self) -> bytes:
        """The last `_STDERR_TAIL_BYTES` of stderr seen so far, for diagnostics."""
        with self._lock:
            return self._tail

    def join(self, timeout: float) -> None:
        self._thread.join(timeout)


class StdioMcp:
    """One spawned MCP server, spoken to interactively over newline-JSON stdio.

    Not thread-safe and not meant to have two `request` calls in flight at
    once — the minting-driver loop is sequential (one tool call awaited before
    the next is proposed), which is exactly what this shape supports.
    """

    def __init__(self, command: list[str], env: dict) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert (
            self._proc.stdin is not None
            and self._proc.stdout is not None
            and self._proc.stderr is not None
        )
        self._replies = _Replies(self._proc.stdout.fileno())
        # Drain stderr continuously from the moment the process is spawned —
        # see `_StderrDrain` for why this can't wait until `request()` or
        # `close()` without reintroducing the pipe-buffer deadlock.
        self._stderr_drain = _StderrDrain(self._proc.stderr)

    def _send(self, obj: dict) -> None:
        assert self._proc.stdin is not None
        frame = json.dumps(obj).encode() + b"\n"
        try:
            self._proc.stdin.write(frame)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise ServerExited(f"could not write to server's stdin: {exc}") from exc

    def request(self, obj: dict, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """Send `obj` (a JSON-RPC request dict with an `id`) and await its reply.

        Returns the parsed reply object. Raises `ValueError` up front if `obj`
        carries no usable id — such a request could never be correlated to a
        reply, so failing fast beats awaiting something that can't arrive.
        """
        identifier = obj.get("id")
        if "id" not in obj or identifier is None:
            raise ValueError("request() requires a non-null 'id' to correlate its reply on")
        key = _id_key(identifier)
        self._send(obj)
        line = self._replies.await_reply(key, timeout)
        return json.loads(line)

    def notify(self, obj: dict) -> None:
        """Send `obj` (a JSON-RPC notification: no `id`) without awaiting a reply."""
        self._send(obj)

    def close(self) -> None:
        """Tear down the subprocess cleanly: close pipes, then terminate/kill.

        stderr is deliberately NOT closed in the same pass as stdin/stdout:
        `_StderrDrain` owns that stream from another thread, and closing it
        out from under an in-flight read is a race. Instead, terminate/kill
        the process first (which drives the drain thread to EOF on its own),
        then join the thread, then close the stream — never blocking forever
        even if the process was already dead on entry.
        """
        proc = self._proc
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
        self._stderr_drain.join(timeout=5)
        try:
            if proc.stderr is not None:
                proc.stderr.close()
        except Exception:
            pass


__all__ = ["DEFAULT_TIMEOUT", "ReplyTimeout", "ServerExited", "StdioMcp", "TransportError"]
