"""A byte-transparent stdio MCP proxy.

Sits between an MCP client and its server:

    client stdin  --[stream chunks verbatim]-->  server stdin
    server stdout --[stream chunks verbatim]-->  client stdout
                            |
                            +--> [bounded copy] --> (future: trace writer)

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
from typing import Callable, Optional

# Caps only the observed copy. The data path stays unbounded so a pathological
# frame can never be truncated or dropped on its way through.
MAX_FRAME = 16 * 1024 * 1024

_CHUNK = 64 * 1024
_EXIT_GRACE = 5.0

# (frame, truncated) — `truncated` is true when the frame exceeded MAX_FRAME and
# the observed copy is therefore incomplete. The forwarded bytes never are.
Observer = Callable[[bytes, bool], None]


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


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view) :]


def _pump(src_fd: int, dst_fd: int, peek: Optional[BoundedPeek] = None) -> None:
    """Stream src_fd to dst_fd verbatim until either end closes."""
    while True:
        try:
            chunk = os.read(src_fd, _CHUNK)
        except OSError:
            return
        if not chunk:
            return
        try:
            _write_all(dst_fd, chunk)
        except OSError:
            return
        if peek is not None:
            try:
                peek.feed(chunk)
            except Exception:  # observation is best-effort, forwarding is not
                peek = None


def _pump_client_stdin(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    try:
        _pump(sys.stdin.fileno(), proc.stdin.fileno())
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


def run(command: list[str], observe: Optional[Observer] = None) -> int:
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stderr is not None

    # Daemon: if the server dies while the client is quiet, this pump is still
    # blocked on a read that will never return, and must not hold up our exit.
    threading.Thread(target=_pump_client_stdin, args=(proc,), daemon=True).start()

    peek = BoundedPeek(observe) if observe is not None else None
    forwarders = [
        threading.Thread(target=_pump, args=(proc.stdout.fileno(), sys.stdout.fileno(), peek)),
        threading.Thread(target=_pump, args=(proc.stderr.fileno(), sys.stderr.fileno())),
    ]
    for thread in forwarders:
        thread.start()
    for thread in forwarders:
        thread.join()

    status = _reap(proc)
    return 128 - status if status < 0 else status


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m belay.proxy <server-command> [args...]", file=sys.stderr)
        return 2
    return run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
