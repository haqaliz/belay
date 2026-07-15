"""Shared rig for the byte-level differential tests and the derivation tests.

`CLIENT_LINES` and `run_over_pipes` live here because three tests need the same
scripted client driven over the same real stdio pipes: the gate
(`test_differential.py`), its teeth (`test_teeth.py`), and the fixture's
anti-vacuity guard (`test_fixture_guard.py`). All three must feed byte-identical
input, or they stop being comparable to each other.

`trace_of` and `run_traced` serve the derivation tests, which need trace records
to derive from. Both go through the real `TraceWriter` rather than hand-building
record dicts: a derivation fed a fabricated envelope is only ever tested against
the fabricator's idea of the format, and would keep passing after the writer's
real output drifted away from it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def proxy_cmd(server: Path) -> list[str]:
    return [sys.executable, "-m", "belay.proxy", sys.executable, str(server)]


def read_trace(trace_dir: Path) -> list[dict]:
    traces = sorted(trace_dir.glob("*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    lines = traces[0].read_bytes().split(b"\n")
    return [json.loads(line) for line in lines if line]


def run_traced(tmp_path: Path, name: str, server: Path = FIXTURE) -> list[dict]:
    """Run the scripted client through the proxy and return the trace records."""
    trace_dir = tmp_path / name
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    run_over_pipes(proxy_cmd(server), env=env)
    return read_trace(trace_dir)


def trace_of(tmp_path: Path, frames: list[tuple]) -> list[dict]:
    """Record `frames` through the real writer and read the records back.

    Each frame is `(direction, raw_bytes)`, or `(direction, raw_bytes,
    truncated)`. For derivations whose input shape is the point of the test and
    which would need an implausible server to reach end-to-end.
    """
    from belay.trace import TraceWriter

    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for direction, raw, *rest in frames:
            writer.observer(direction)(raw, bool(rest[0]) if rest else False)
    finally:
        writer.close()
    return read_trace(tmp_path / "trace")
