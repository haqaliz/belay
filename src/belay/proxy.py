"""A byte-transparent stdio MCP proxy.

Sits between an MCP client and its server:

    client stdin  --[stream chunks verbatim]-->  server stdin
                            |
                            +--> [bounded copy] --> trace writer (c2s)
    server stdout --[stream chunks verbatim]-->  client stdout
                            |
                            +--> [bounded copy] --> trace writer (s2c)

Both directions are observed; each has its own reassembly buffer, because they
are independent streams. Set `BELAY_TRACE_DIR` to record; with it unset the
proxy runs with no observer at all and writes nothing. The server's stderr is
forwarded but not traced: it is diagnostics, not protocol.

Bytes are forwarded verbatim and ordering is preserved; observation is
best-effort and never blocks or alters the data path. The forwarding path
streams chunks and never reassembles frames, so byte-exactness is structural
rather than something the tests have to catch. Any inspection happens on a
bounded copy that is structurally unable to reach the bytes being forwarded.

Both directions are pumped concurrently: MCP is bidirectional, so a server may
originate requests and notifications at any time, unprompted.

stdout belongs to the protocol. Diagnostics go to stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Callable, Optional, Protocol

# Caps only the observed copy. The data path stays unbounded so a pathological
# frame can never be truncated or dropped on its way through.
MAX_FRAME = 16 * 1024 * 1024

_CHUNK = 64 * 1024
_EXIT_GRACE = 5.0

# (frame, truncated) — `truncated` is true when the frame exceeded MAX_FRAME and
# the observed copy is therefore incomplete. The forwarded bytes never are.
Observer = Callable[[bytes, bool], None]

# Called when observation of a direction dies. Forwarding continues; the cause
# gets a name rather than a silence.
CaptureError = Callable[[BaseException], None]


class CaptureSink(Protocol):
    """Where observed frames go. Structural on purpose: this module knows the
    shape of a recorder and nothing about any particular one."""

    def observer(self, direction: str) -> Observer: ...

    def capture_error(self, direction: str, cause: BaseException) -> None: ...


class _CaptureGate:
    """Stops one direction's observation at a defined point.

    The c2s pump must stay a daemon: it can be blocked forever on a read from a
    quiet client, and joining it would hang the exit. But a daemon still running
    when the recorder closes is how a frame gets observed into a closed writer —
    it vanishes, and the trace keeps its matched open/close pair and looks like a
    complete capture. That is the false-completeness this project exists to
    catch.

    So the daemon is paired with this instead of a join. `stop()` takes the lock,
    which means it waits for any observation already in flight and blocks any
    that has not started. Once it returns, the recorder is provably idle and can
    close knowing its window means what the format says: everything up to the
    close was observed.

    One gate per direction, never one shared: the two streams are independent,
    and a shared gate would put them back to waiting on each other's hashing —
    the exact contention `TraceWriter._record_frame` is arranged to avoid.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stopped = False

    def guard(self, fn: Callable) -> Callable:
        def gated(*args) -> None:
            with self._lock:
                if self._stopped:
                    # Past the window's close. Not a loss to name — the window
                    # says where observation ended, which is the honest claim.
                    return
                fn(*args)

        return gated

    def stop(self) -> None:
        with self._lock:
            self._stopped = True


class BoundedPeek:
    """Reassembles newline-delimited frames from a *copy* of a stream.

    Holds no reference to the buffers being forwarded and returns nothing to the
    pump, so no defect here can alter or stall the data path.
    """

    def __init__(self, observe: Observer) -> None:
        self._observe = observe
        self._buf = bytearray()
        self._truncated = False

    def feed(self, chunk: bytes) -> None:
        start = 0
        while True:
            newline = chunk.find(b"\n", start)
            if newline == -1:
                self._accumulate(chunk[start:])
                return
            self._accumulate(chunk[start:newline])
            self._emit()
            start = newline + 1

    def _accumulate(self, data: bytes) -> None:
        if self._truncated:
            return
        room = MAX_FRAME - len(self._buf)
        if len(data) > room:
            self._buf.extend(data[:room])
            self._truncated = True
        else:
            self._buf.extend(data)

    def _emit(self) -> None:
        frame, truncated = bytes(self._buf), self._truncated
        self._buf.clear()
        self._truncated = False
        if frame:
            self._observe(frame, truncated)

    def close(self) -> int:
        """End the stream; return the bytes left over from an unfinished frame.

        Mid-stream a partial buffer is correct: the rest of the frame is still
        coming. At EOF nothing more is coming, so the same bytes are a frame that
        crossed to the peer and never reached the trace. The residue is reported
        rather than emitted as a frame — a partial frame is not a frame, and
        recording it as one would be a worse lie than naming the loss.
        """
        residue = len(self._buf)
        self._buf.clear()
        self._truncated = False
        return residue


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


class StreamEndedMidFrame(Exception):
    """EOF arrived with an unterminated frame in the reassembly buffer."""


def _name(on_capture_error: Optional[CaptureError], cause: BaseException) -> None:
    """Say why capture lost something. Never at the expense of forwarding."""
    if on_capture_error is None:
        return
    try:
        on_capture_error(cause)
    except Exception:
        # The recorder failed while recording that the recorder failed. It has
        # already degraded to stderr; forwarding must survive even this.
        pass


def _observe(
    peek: Optional[BoundedPeek],
    chunk: bytes,
    on_capture_error: Optional[CaptureError],
) -> Optional[BoundedPeek]:
    """Feed the observed copy. Returns the peek, or None once it has died."""
    if peek is None:
        return None
    try:
        peek.feed(chunk)
    except Exception as exc:
        # Observation is best-effort; forwarding is not. But dropping `peek`
        # silently would leave the trace ending early while looking complete,
        # which is a false-completeness claim and the exact thing this project
        # exists to catch. Stop observing this direction, and say why.
        _name(on_capture_error, exc)
        return None
    return peek


def _pump(
    src_fd: int,
    dst_fd: int,
    peek: Optional[BoundedPeek] = None,
    on_capture_error: Optional[CaptureError] = None,
) -> None:
    """Stream src_fd to dst_fd verbatim until either end closes.

    Every exit from this loop is a stream ending, so every exit runs the peek's
    close: bytes this proxy took custody of must reach the trace or leave a named
    cause, and "the stream stopped" is not an excuse for neither.
    """
    try:
        while True:
            try:
                chunk = os.read(src_fd, _CHUNK)
            except OSError:
                # Nothing was consumed, so nothing was lost on the way in: the
                # source is simply gone. Any residue is named by close() below.
                return
            if not chunk:
                return
            try:
                _write_all(dst_fd, chunk)
            except OSError as exc:
                # The chunk is already out of the source pipe — Belay has taken
                # custody of bytes it can no longer deliver. Returning here would
                # drop them with no record and no cause, which is the same silent
                # loss this module exists to prevent. So: observe what existed,
                # then name why forwarding stopped.
                peek = _observe(peek, chunk, on_capture_error)
                _name(on_capture_error, exc)
                return
            # Deliberately after the forward, and it stays there: forwarding must
            # never wait on the recorder. Only the failure path above observes
            # first, and only because there is no forward left to delay.
            peek = _observe(peek, chunk, on_capture_error)
    finally:
        if peek is not None:
            residue = peek.close()
            if residue:
                _name(
                    on_capture_error,
                    StreamEndedMidFrame(
                        f"stream ended mid-frame; {residue} bytes were forwarded to the "
                        f"peer and observed without a terminating newline, so they are "
                        f"not recorded as a frame"
                    ),
                )


def _pump_client_stdin(
    proc: subprocess.Popen,
    peek: Optional[BoundedPeek] = None,
    on_capture_error: Optional[CaptureError] = None,
) -> None:
    assert proc.stdin is not None
    try:
        _pump(sys.stdin.fileno(), proc.stdin.fileno(), peek, on_capture_error)
    finally:
        # Client hung up: let the server see EOF so it can exit on its own terms.
        try:
            proc.stdin.close()
        except OSError:
            pass


def _reap(proc: subprocess.Popen) -> int:
    for stop in (proc.terminate, proc.kill):
        try:
            return proc.wait(timeout=_EXIT_GRACE)
        except subprocess.TimeoutExpired:
            stop()
    return proc.wait()


def _capture_for(
    capture: Optional[CaptureSink], direction: str
) -> tuple[Optional[BoundedPeek], Optional[CaptureError], _CaptureGate]:
    """Build one direction's independent observation branch, and its off switch.

    Each direction gets its own BoundedPeek: the two streams are unrelated, and
    a shared reassembly buffer would splice one direction's partial frame onto
    the other's.

    Both ways of reaching the recorder — the observer and the capture_error — go
    through the gate. Either one arriving after the recorder closed is the same
    bug; gating only the first would leave the second writing into a closed fd.
    """
    gate = _CaptureGate()
    if capture is None:
        return None, None, gate
    return (
        BoundedPeek(gate.guard(capture.observer(direction))),
        gate.guard(lambda exc: capture.capture_error(direction, exc)),
        gate,
    )


def run(command: list[str], capture: Optional[CaptureSink] = None) -> int:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None

    c2s_peek, c2s_error, c2s_gate = _capture_for(capture, "c2s")
    s2c_peek, s2c_error, s2c_gate = _capture_for(capture, "s2c")

    try:
        # Daemon: if the server dies while the client is quiet, this pump is still
        # blocked on a read that will never return, and must not hold up our exit.
        threading.Thread(
            target=_pump_client_stdin,
            args=(proc, c2s_peek, c2s_error),
            daemon=True,
        ).start()

        forwarders = [
            threading.Thread(
                target=_pump,
                args=(proc.stdout.fileno(), sys.stdout.fileno(), s2c_peek, s2c_error),
            ),
            threading.Thread(target=_pump, args=(proc.stderr.fileno(), sys.stderr.fileno())),
        ]
        for thread in forwarders:
            thread.start()
        for thread in forwarders:
            thread.join()

        status = _reap(proc)
        return 128 - status if status < 0 else status
    finally:
        # Observation ends here, before the caller closes the recorder. The c2s
        # daemon may still be blocked on a client read and may still wake with
        # bytes; after this it forwards them and records nothing, which the
        # connection window already states. What it can no longer do is observe
        # into a closed writer and disappear.
        c2s_gate.stop()
        s2c_gate.stop()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m belay.proxy <server-command> [args...]", file=sys.stderr)
        return 2

    trace_dir = os.environ.get("BELAY_TRACE_DIR")
    if not trace_dir:
        return run(argv)

    # Imported here, not at module scope, so that everything above stays unable
    # to reach a serialiser even by accident: the forwarding path has no name
    # for `json` in scope. main() is the composition root and the only place
    # that knows a recorder exists.
    from belay.trace import TraceWriter

    writer = TraceWriter.in_directory(trace_dir)
    try:
        return run(argv, capture=writer)
    finally:
        writer.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
