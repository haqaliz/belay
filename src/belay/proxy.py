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

# (frame, direction) — called with a frame's bytes, without the terminating
# newline, BEFORE any of them are forwarded. Returns nothing.
#
# This is the one hook allowed to make the data path wait, and the reason is
# narrow: a turn's pre-state can only be captured before the request reaches the
# server. Observation cannot do it — by the time a frame is observed it has been
# forwarded, the call may already have run, and a "pre-state" captured then is a
# race whose loser is invisible. So the hook blocks; see `_FrameHold`.
#
# It is OPAQUE to this module, and that is structural rather than stylistic. This
# module does not import `json`, cannot recognise a `tools/call`, and therefore
# cannot re-serialise one even by accident (tests/test_import_guard.py). Whoever
# installs the hook owns the parse; `belay.sandbox.gate` is that owner today.
BeforeFrame = Callable[[bytes, str], None]

# How a chunk reaches the peer. `_write_all` *is* this when nothing is gating the
# path, so an ungated proxy runs C1's pump with nothing new on it to be wrong.
Forward = Callable[[int, bytes], None]


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


class _FrameHold:
    """Holds each frame until `before_frame` has run, then forwards it verbatim.

    The only thing in this proxy permitted to make the data path wait. It buys one
    property, and nothing else: when the hook runs, **no byte of that frame has
    reached the peer**. A snapshot taken from the observer would be a race against
    a server that may already have executed the call, and a pre-state containing
    the call's own effects is not a weaker pre-state — it is a false one.

    What it must never do is change a byte. So the hook reads a COPY and the bytes
    that were held are the bytes that go out, unexamined and untransformed. This
    module has no serialiser in scope and cannot acquire one
    (tests/test_import_guard.py), so "forward the original" is structural here
    rather than a promise: there is nothing available to re-emit them with.

    *Parsing to read and parsing to re-emit are different operations. Only the
    latter mutates, and only the latter happens somewhere else — in the gate.*

    Frame boundaries are found the same way `BoundedPeek` finds them, and the hook
    gets the frame without its newline for the same reason: that is what the trace
    calls a frame, and a hook that saw a different shape than the record it
    annotates would be answering about something else.
    """

    def __init__(
        self,
        before_frame: BeforeFrame,
        direction: str,
        on_capture_error: Optional[CaptureError] = None,
    ) -> None:
        self._before_frame = before_frame
        self._direction = direction
        self._on_capture_error = on_capture_error
        self._held = bytearray()

    def __call__(self, fd: int, chunk: bytes) -> None:
        start = 0
        while True:
            newline = chunk.find(b"\n", start)
            if newline == -1:
                # The frame is unfinished, so the hook has nothing to rule on yet
                # and the peer has nothing it could act on: no line-delimited
                # parser dispatches a frame it has not seen the end of. Hold.
                self._held.extend(chunk[start:])
                return
            self._held.extend(chunk[start : newline + 1])
            data = bytes(self._held)
            self._held.clear()
            if len(data) > 1:
                # A bare newline is not a frame — `BoundedPeek` does not emit one
                # either — but it is still bytes the peer is owed.
                self._run(data[:-1])
            _write_all(fd, data)
            start = newline + 1

    def _run(self, frame: bytes) -> None:
        try:
            self._before_frame(frame, self._direction)
        except Exception as exc:
            # The gate is contractually total and catches its own failures, so
            # this should be unreachable through it. It is here because "should
            # be" is not a property the data path can afford to assume: a hook
            # that raised would otherwise kill this direction outright, turning a
            # snapshot bug into a dead proxy. Capture is best-effort; forwarding
            # is not. The hook is capture.
            #
            # Deliberately NOT disabled after a failure, unlike `_observe`. The
            # state handle is sticky — a later turn whose gate never ran would
            # inherit the previous turn's `present` handle and claim a snapshot
            # of a pre-state that was never taken. Better it keep trying and keep
            # naming its failures.
            _name(self._on_capture_error, exc)

    def flush(self, fd: int) -> None:
        """Deliver bytes held from a frame the stream ended in the middle of.

        The hook never runs for them: a partial frame is not a frame, and calling
        one would be inventing a turn. But they are bytes this proxy took custody
        of, and holding them until exit and then dropping them would be a silent
        loss on the data path — the one thing the hold is not allowed to cost.
        The peek names the same event from the observation side.
        """
        if not self._held:
            return
        data = bytes(self._held)
        self._held.clear()
        try:
            _write_all(fd, data)
        except OSError as exc:
            _name(self._on_capture_error, exc)


def _forwarder(
    before_frame: Optional[BeforeFrame],
    direction: str,
    on_capture_error: Optional[CaptureError] = None,
) -> Forward:
    """How a direction reaches its peer.

    With no hook installed this returns `_write_all` **itself**, not a wrapper
    around it: an unsandboxed run is C1's byte pump exactly — same code path, same
    behaviour, nothing added to be wrong. The hold only exists when someone asked
    for it.
    """
    if before_frame is None:
        return _write_all
    return _FrameHold(before_frame, direction, on_capture_error)


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
    forward: Forward = _write_all,
) -> None:
    """Stream src_fd to dst_fd verbatim until either end closes.

    Every exit from this loop is a stream ending, so every exit runs the peek's
    close: bytes this proxy took custody of must reach the trace or leave a named
    cause, and "the stream stopped" is not an excuse for neither.

    `forward` defaults to `_write_all`, which is what every direction used before
    the gate existed and what every ungated direction still uses. A gated one
    swaps in `_FrameHold`, which delays a frame but never edits it — the loop
    below hands over the chunk it read and never learns which one it got.
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
                forward(dst_fd, chunk)
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
        if forward is not _write_all:
            # Only a hold can owe the peer anything at exit, and `_write_all`
            # never holds. Identity rather than a capability check: the ungated
            # path must not grow so much as a `getattr` it did not have before.
            forward.flush(dst_fd)  # type: ignore[union-attr]
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
    forward: Forward = _write_all,
) -> None:
    assert proc.stdin is not None
    try:
        _pump(sys.stdin.fileno(), proc.stdin.fileno(), peek, on_capture_error, forward)
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


def run(
    command: list[str],
    capture: Optional[CaptureSink] = None,
    before_frame: Optional[BeforeFrame] = None,
    stderr_capture: Optional[CaptureSink] = None,
) -> int:
    """Proxy `command`'s stdio, optionally observing it and gating its requests.

    `command` is spawned exactly as C1 spawned it, and this module has no idea
    whether it is contained: a sandboxed run is one whose argv already begins with
    `sandbox-exec`, composed by `belay.sandbox.launch` at the composition root
    below. The spawn is therefore the same line either way — there is no sandbox
    branch on this path to take wrongly, and an unsandboxed run pays nothing.

    `before_frame` is installed on **c2s only**. The client-to-server direction is
    the only one that precedes a tool executing, so it is the only one where
    blocking buys anything; holding a reply would cost latency for nothing. The
    direction is still passed to the hook, because a hook that had to assume which
    stream it was reading would be one refactor away from being wrong quietly.

    `stderr_capture` observes the server's **stderr**, which is diagnostics rather
    than protocol and so is forwarded but never traced as frames. It exists because
    a live child's refusals are only visible in what it prints
    (`belay.sandbox.launch.DenialCapture`), and it is a separate sink from `capture`
    for exactly that reason: same machinery, different question, and one of them
    must not start recording the other's records.
    """
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None

    c2s_peek, c2s_error, c2s_gate = _capture_for(capture, "c2s")
    s2c_peek, s2c_error, s2c_gate = _capture_for(capture, "s2c")
    err_peek, err_error, err_gate = _capture_for(stderr_capture, "stderr")

    try:
        # Daemon: if the server dies while the client is quiet, this pump is still
        # blocked on a read that will never return, and must not hold up our exit.
        threading.Thread(
            target=_pump_client_stdin,
            args=(proc, c2s_peek, c2s_error, _forwarder(before_frame, "c2s", c2s_error)),
            daemon=True,
        ).start()

        forwarders = [
            threading.Thread(
                target=_pump,
                args=(proc.stdout.fileno(), sys.stdout.fileno(), s2c_peek, s2c_error),
            ),
            threading.Thread(
                target=_pump,
                args=(proc.stderr.fileno(), sys.stderr.fileno(), err_peek, err_error),
            ),
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
        err_gate.stop()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m belay.proxy <server-command> [args...]", file=sys.stderr)
        return 2

    trace_dir = os.environ.get("BELAY_TRACE_DIR")
    scope = os.environ.get("BELAY_SANDBOX_SCOPE")
    snapshot_dir = os.environ.get("BELAY_SNAPSHOT_DIR")

    if not trace_dir and not scope:
        # Nothing to record and nothing to gate: C1's byte pump, reached by the
        # same line it was always reached by.
        return run(argv)

    if scope and not snapshot_dir:
        # Loud, and at startup rather than mid-turn. A proxy that came up and
        # then declined to snapshot would leave every turn `absent` — "no
        # snapshot was attempted" — which is true and useless: the operator asked
        # for one and would have no idea it never happened.
        print(
            "belay: BELAY_SANDBOX_SCOPE is set but BELAY_SNAPSHOT_DIR is not; "
            "refusing to start rather than run a sandbox that snapshots nowhere",
            file=sys.stderr,
        )
        return 2

    # Imported here, not at module scope, so that everything above stays unable
    # to reach a serialiser even by accident: the forwarding path has no name
    # for `json` in scope. main() is the composition root and the only place that
    # knows a recorder exists — and now the only place that knows a gate does.
    # `belay.sandbox.gate` imports `json` and is welcome to: it parses a copy to
    # READ it, and nothing it returns can reach the bytes being forwarded.
    writer = None
    if trace_dir:
        from belay.trace import TraceWriter

        writer = TraceWriter.in_directory(trace_dir)

    try:
        if not scope:
            return run(argv, capture=writer)
        return _contained_run(argv, scope, snapshot_dir, writer)
    finally:
        if writer is not None:
            writer.close()


def _contained_run(
    argv: list[str], scope: str, snapshot_dir: str, writer
) -> int:
    """Spawn the server INSIDE the sandbox, gating and snapshotting each turn.

    The two halves of C2 meet here and nowhere else. `launch.contained` composes
    the profile onto the argv, so `run` above spawns a contained server with the
    same `Popen` it always used; the gate snapshots the scope's **snapshot_root**,
    which is the workspace and deliberately NOT everything the profile grants —
    the server's `$TMPDIR` is writable and is not in any snapshot
    (`belay.sandbox.scope` explains why both halves of that are load-bearing).

    The zero-config scope is built here rather than only in `belay sandbox check`:
    a default boundary that only the self-test could see would leave every real run
    with a hand-authored one, which is the risk the default exists to retire.
    """
    from contextlib import ExitStack

    from belay.sandbox.gate import TurnGate
    from belay.sandbox.launch import DenialCapture, contained, network_policy
    from belay.snapshot.bth1 import UnsupportedPlatform

    # The stack, rather than a `with` around everything, so that the refusal below
    # covers SETUP ONLY. A `ValueError` escaping the run itself is not a
    # misconfiguration, and reporting it as one would print a confident `belay:`
    # diagnosis of the wrong thing — while the profile it names was already applied.
    with ExitStack() as stack:
        try:
            policy = network_policy(os.environ.get("BELAY_SANDBOX_NETWORK"))
            spawn = stack.enter_context(contained(argv, workspace=scope, network=policy))
            gate = TurnGate(
                scope=spawn.scope.snapshot_root,
                snapshot_root=snapshot_dir,
                trace=writer,
            )
        except (ValueError, UnsupportedPlatform) as exc:
            # A misconfigured or unsupported sandbox, refused before the first byte
            # moves. Every case here would otherwise mean running on past a
            # boundary the operator asked for and Belay did not apply, or recording
            # a pre-state that was never real. Neither has an honest degraded mode.
            print(f"belay: {exc}", file=sys.stderr)
            return 2

        if writer is not None:
            # A fact recorded before the child runs: what was applied. Not whether
            # it was enough — C2 records, C4 renders.
            writer.record("network_policy", policy=policy.mode, ports=list(policy.ports))
        return run(
            spawn.argv,
            capture=writer,
            before_frame=gate.before_frame,
            stderr_capture=DenialCapture(writer) if writer is not None else None,
        )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
