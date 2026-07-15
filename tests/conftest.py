"""Shared rig for the byte-level differential tests.

`CLIENT_LINES` and `run_over_pipes` live here because three tests need the same
scripted client driven over the same real stdio pipes: the gate
(`test_differential.py`), its teeth (`test_teeth.py`), and the fixture's
anti-vacuity guard (`test_fixture_guard.py`). All three must feed byte-identical
input, or they stop being comparable to each other.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "fake_server.py"

# Hostile key order, verbatim — the client is adversarial too.
CLIENT_LINES = [
    b'{"params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"t","version":"1"}},"method":"initialize","id":1,"jsonrpc":"2.0","belayFuture":"KEEP"}',
    b'{"jsonrpc":"2.0","method":"notifications/initialized","params":null}',
    b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
    b'{"params":{"name":"echo","arguments":{"s":"caf\\u00e9"}},"method":"tools/call","id":3,"jsonrpc":"2.0"}',
]


def run_over_pipes(
    cmd: list[str], timeout: float = 5.0, env: dict[str, str] | None = None
) -> list[bytes]:
    """Spawn `cmd` over real stdio pipes, feed it CLIENT_LINES, return stdout lines as bytes."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    payload = b"\n".join(CLIENT_LINES) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=timeout)
    returncode = proc.wait(timeout=timeout)
    if returncode != 0:
        raise RuntimeError(
            f"command {cmd!r} exited {returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    return [line for line in stdout.split(b"\n") if line]
