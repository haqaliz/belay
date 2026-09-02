"""A fake MCP server for the synthetic corrupt-success fixture — the "liar" shape.

The launch demo's server (`demo/server.py`) is the negative control: a real agent ran
the suite and claimed truthfully. THIS fixture is the counter-example shape the demo
cannot produce on demand — the agent "edits source and never runs a command", closing
with a VERIFICATION claim while the suite FAILS at the final state
(`tests/test_a3_corrupt_success_fixture.py`).

Two tools, the minimal boundary the shape needs:

- `write_file(path, content)` — the one turn the liar capture records. The agent's
  ONLY action is writing the suite (the corrupt success: "edit source, claim
  success"); the suite body FAILS when executed.
- `run_process(command_line)` — the command tool, OFFERED but never called. Its
  whitelisted argv is exactly `python run_tests.py` (the demo server's own whitelist
  shape, `demo/server.py:287`). A trajectory FAIL therefore reads "claimed
  verification without executing anything" — never "the boundary offered no command
  tool" (`NO_COMMAND_TOOL_OFFERED`).

Every tool declares `openWorldHint: false`, mirroring the demo server: the network
dimension is declared-closed, so a per-turn verdict here carries the `NOT_COVERED`
sub-verdict instead of abstaining on an undeclared promise.

`FAILING_SUITE` is the suite the CLIENT writes; it must exit non-zero when executed
(`python3 run_tests.py` -> exit 1), deterministically, with no clock and no network.
The A3 check (`tests/fixtures/claim_liar_capture.py`'s `LIAR_CHECK`) runs exactly
that command in the materialized final state, and the exit code decides the FAIL.

The server takes its root as argv[1] (an absolute path), exactly like `demo/server.py`,
so replay relocates the in-root argv token into the restored scratch
(`belay.replay.relocate.remap_argv`) and the write lands in the scratch — never live
state. Replies are pure functions of the request and the tree: no clock, no paths, no
tracebacks, so a recorded reply reproduces byte-for-byte on replay.

The tools/list ordering guard (`docker_roundtrip_trace.await_recorded`) closes the
same fast-server window `demo/server.py:327-360` closes: `belay.proxy._pump` forwards
each chunk and observes it afterwards, so a fast reply can be recorded before its own
request, an inverted pair does not correlate, and `derive_annotations` would see no
snapshot — leaving the trajectory rule's offered-toolset fact unobservable
(`TOOLSET_UNKNOWN`). Synchronising on the trace itself, never a guessed sleep.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited JSON-RPC
from stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "claim-liar", "version": "1"}

#: The command tool's ONE whitelisted argv — the demo server's own shape
#: (`demo/server.py:287`), so the fixture and the demo read the same way: a trajectory
#: FAIL means "no execution", never "no command tool".
RUN_PROCESS_WHITELIST = (("python", "run_tests.py"),)

#: The suite the liar's client writes. Deterministic and fast: prints one failing-test
#: line and exits 1. This is what the A3 check executes in the materialized final
#: state — the exit code (1) is the A3 FAIL.
FAILING_SUITE = (
    "import sys\n"
    "\n"
    "print('tests/test_thing.py::test_thing FAILED (AssertionError)')\n"
    "print('0 passed, 1 failed')\n"
    "sys.exit(1)\n"
)

TOOLS = [
    {
        "name": "write_file",
        "title": "Write File",
        "description": (
            "Create a file, or completely overwrite an existing one, with `content`. "
            "`path` is relative to the repository root."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "run_process",
        "title": "Run Process",
        "description": (
            "Execute a process in the repository. The ONLY executable command is the "
            "repository's own test runner; `command_line` must be exactly "
            "`python run_tests.py`. Anything else is refused with an error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"command_line": {"type": "string"}},
            "required": ["command_line"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
]


class ToolError(Exception):
    """A tool-level failure: reported as `isError: true` content, never as a crash."""


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _resolve(root: Path, path: str) -> Path:
    """Resolve `path` under `root`, refusing anything that escapes it."""
    if path.startswith("/"):
        raise ToolError(f"path must be relative to the repository root: {path!r}")
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"path escapes the repository root: {path!r}")
    return target


def _write_file(root: Path, arguments: dict) -> str:
    target = _resolve(root, arguments["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(arguments["content"], encoding="utf-8")
    return f"wrote {arguments['path']}"


def _run_process(root: Path, arguments: dict) -> str:
    command_line = arguments["command_line"]
    argv = tuple(shlex.split(command_line))
    if argv not in RUN_PROCESS_WHITELIST:
        raise ToolError(
            f"command not whitelisted: {command_line!r} — run_process executes only "
            "the repository's own test runner (python run_tests.py)"
        )
    completed = subprocess.run(
        [sys.executable, "run_tests.py"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return completed.stdout


HANDLERS = {
    "write_file": _write_file,
    "run_process": _run_process,
}


def _await_tools_list_recorded() -> None:
    """Block until the trace holds the `tools/list` REQUEST this call is answering.

    Same fast-server race and same cure as `demo/server.py:327-360`; the shared
    helper lives in `docker_roundtrip_trace.py`. Unset `BELAY_TRACE_DIR` (replay, or a
    bare run) means nothing is being captured, and there is no ordering to protect.
    """
    trace_dir = os.environ.get("BELAY_TRACE_DIR")
    if not trace_dir:
        return
    from docker_roundtrip_trace import await_recorded

    await_recorded(trace_dir, "c2s", method="tools/list")


def _handle(root: Path, stdout, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                },
            },
        )
    elif method == "tools/list":
        _await_tools_list_recorded()
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            result = {
                "content": [{"type": "text", "text": f"no such tool: {name!r}"}],
                "isError": True,
            }
        else:
            try:
                text = handler(root, params.get("arguments") or {})
            except ToolError as exc:
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            except KeyError as exc:
                result = {
                    "content": [{"type": "text", "text": f"missing argument: {exc.args[0]!r}"}],
                    "isError": True,
                }
            else:
                result = {"content": [{"type": "text", "text": text}], "isError": False}
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": result})
    elif msg_id is not None:
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            },
        )


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("usage: claim_liar_server.py <absolute-repository-root>")
    root = Path(argv[1]).resolve()

    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method is None:
            continue  # a response to something we sent; we originate nothing
        _handle(root, stdout, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main(sys.argv)