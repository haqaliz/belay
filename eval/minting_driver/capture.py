"""The proxy/env wiring helper: routes a real MCP server through `belay.proxy`, gated.

Two pure, no-subprocess-spawning functions:

- `proxy_command` builds the argv that spawns the downstream server *through* the proxy,
  so a real Task 5 run gets Belay's trace/sandbox machinery for free instead of talking to
  the server directly.
- `gated_env` builds the environment that turns that proxy on: `BELAY_TRACE_DIR` (record),
  `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` (contain + snapshot). It fails fast, in this
  process, with a clear `ValueError`, on the one combination the proxy itself refuses at
  startup — `BELAY_SANDBOX_SCOPE` set without `BELAY_SNAPSHOT_DIR`
  (`src/belay/proxy.py:544-554`) — because a driver that finds out only after the subprocess
  exits non-zero has to reverse-engineer a stderr line, and a driver that never checks would
  silently capture nothing.

No `belay` import here — `proxy_command` only ever writes the literal string
`"belay.proxy"` into an argv list, which is a subprocess module path, not a Python import.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, Union

StrPath = Union[str, "os.PathLike[str]"]


def proxy_command(server_command: list[str]) -> list[str]:
    """The argv that spawns `server_command` *through* `python -m belay.proxy`.

    Returns `[sys.executable, "-m", "belay.proxy", *server_command]`. CRITICAL: there is
    no `--` separator — the entire argv after `-m belay.proxy` IS the downstream server
    command (`src/belay/proxy.py:475-480`); inserting one would hand the proxy a literal
    `"--"` as the first token of the command it tries to spawn.
    """
    return [sys.executable, "-m", "belay.proxy", *server_command]


def gated_env(
    *,
    trace_dir: StrPath,
    scope: Optional[str],
    snapshot_dir: Optional[StrPath],
    base: Optional[dict] = None,
) -> dict:
    """A copy of `base` (default `os.environ`) with the gated capture vars set.

    Sets `BELAY_TRACE_DIR`, `BELAY_SANDBOX_SCOPE`, `BELAY_SNAPSHOT_DIR` — coercing
    `trace_dir`/`snapshot_dir` to `str` so a `pathlib.Path` is as welcome as a string.
    `base` is never mutated; the caller's environment (or `os.environ` itself) is left
    untouched.

    Raises `ValueError` if `scope` is set but `snapshot_dir` is falsy: the proxy hard-
    refuses to start in exactly that case (`src/belay/proxy.py:544-554`), and surfacing
    that here — before a subprocess is ever spawned — turns a cryptic non-zero exit code
    into a clear, in-process failure at the call site that made the mistake.
    """
    if scope and not snapshot_dir:
        raise ValueError(
            "gated_env: scope is set but snapshot_dir is not — the proxy refuses to "
            "start in this case (BELAY_SANDBOX_SCOPE without BELAY_SNAPSHOT_DIR); pass "
            "a snapshot_dir or leave scope unset"
        )

    env = dict(base if base is not None else os.environ)
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    if scope is not None:
        env["BELAY_SANDBOX_SCOPE"] = str(scope)
    if snapshot_dir is not None:
        env["BELAY_SNAPSHOT_DIR"] = str(snapshot_dir)
    return env


__all__ = ["proxy_command", "gated_env"]
