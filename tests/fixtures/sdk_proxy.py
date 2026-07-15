"""A naive MCP stdio proxy that parses and re-serialises every frame.

DELIBERATELY WRONG, ON PURPOSE. Same CLI contract as `belay.proxy`
(`python sdk_proxy.py <server-command> [args...]`), and correct in every respect
except the one that matters: it decodes each frame with `json.loads` and re-encodes
it with `json.dumps` instead of forwarding the bytes it was given. It is full-duplex,
it forwards unsolicited notifications, it passes non-JSON lines through untouched,
and it propagates the server's exit status — so when `test_teeth.py` catches it, the
only thing it can be caught on is byte fidelity.

This is not a strawman. It is the implementation a reasonable engineer writes when
"proxy the messages" is the requirement, and the one the real proxy will eventually
be "simplified" into by someone who assumes a frame's meaning is a frame's bytes.
`test_teeth.py` exists to make that assumption fail loudly. Stdlib only: parsing and
re-serialising is what breaks byte fidelity, and any JSON library does it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import BinaryIO


def _reserialise(line: bytes) -> bytes:
    """Round-trip one frame through the JSON parser."""
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return line  # not JSON, so there is nothing to re-serialise
    return json.dumps(message).encode("utf-8")


def _pump(src: BinaryIO, dst: BinaryIO) -> None:
    """Forward newline-delimited frames from src to dst, re-serialising each one."""
    try:
        for raw_line in src:
            line = raw_line.strip()
            if not line:
                continue
            dst.write(_reserialise(line) + b"\n")
            dst.flush()
    except (OSError, ValueError):
        pass


def _pump_client_stdin(proc: subprocess.Popen) -> None:
    assert proc.stdin is not None
    try:
        _pump(sys.stdin.buffer, proc.stdin)
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python sdk_proxy.py <server-command> [args...]", file=sys.stderr)
        return 2

    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdout is not None

    threading.Thread(target=_pump_client_stdin, args=(proc,), daemon=True).start()

    _pump(proc.stdout, sys.stdout.buffer)
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
