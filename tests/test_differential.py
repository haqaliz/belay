"""The gate: proves the proxy is byte-transparent (Task 2).

Runs the same scripted client against (a) the fake server directly and
(b) the fake server through the proxy, over REAL stdio pipes, and asserts
the two output byte streams are identical.

This test is expected to FAIL right now: `belay.proxy` does not exist yet
(that's Task 3). It must fail for that reason — not because of a typo, a
broken fixture, or a timeout.
"""

from __future__ import annotations

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


def run_over_pipes(cmd: list[str], timeout: float = 5.0) -> list[bytes]:
    """Spawn `cmd` over real stdio pipes, feed it CLIENT_LINES, return stdout lines as bytes."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = b"\n".join(CLIENT_LINES) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=timeout)
    returncode = proc.wait(timeout=timeout)
    if returncode != 0:
        raise RuntimeError(
            f"command {cmd!r} exited {returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    return [line for line in stdout.split(b"\n") if line]


def test_proxy_is_byte_identical_to_direct_connection(tmp_path):
    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])

    env_trace_dir = tmp_path / "trace"
    env_trace_dir.mkdir()
    import os

    proxied_env = os.environ.copy()
    proxied_env["BELAY_TRACE_DIR"] = str(env_trace_dir)

    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", sys.executable, str(FIXTURE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=proxied_env,
    )
    payload = b"\n".join(CLIENT_LINES) + b"\n"
    stdout, stderr = proc.communicate(payload, timeout=5.0)
    returncode = proc.wait(timeout=5.0)
    if returncode != 0:
        raise RuntimeError(
            "proxy command exited "
            f"{returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    proxied_lines = [line for line in stdout.split(b"\n") if line]

    if direct_lines != proxied_lines:
        first_diff = None
        for i, (d, p) in enumerate(zip(direct_lines, proxied_lines)):
            if d != p:
                first_diff = i
                break
        else:
            first_diff = min(len(direct_lines), len(proxied_lines))

        direct_at = direct_lines[first_diff] if first_diff < len(direct_lines) else b"<missing>"
        proxied_at = proxied_lines[first_diff] if first_diff < len(proxied_lines) else b"<missing>"
        raise AssertionError(
            "proxy output diverged from direct connection at line "
            f"{first_diff}:\n  direct : {direct_at!r}\n  proxied: {proxied_at!r}"
        )
