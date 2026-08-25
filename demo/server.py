"""The demo's MCP server: five tools, stdlib only, deterministic on re-execution.

This one file is BOTH sides of the demo:

  - during the **capture**, a real agent (`claude -p`, via `eval/minting_driver`) drives
    it through `python -m belay.proxy` with the sandbox gated on, and every action it
    takes crosses this boundary and lands in the trace;
  - during **replay**, `belay verify` re-invokes *this same server* against the restored
    pre-state, so A2 result-equivalence is a genuine re-execution rather than a mimicry
    of some other server's output.

That is the reason the demo does not use the reference node servers the Phase-0 mint used
(`@modelcontextprotocol/server-filesystem` + `mcp-server-commands`). Those are the right
choice for a mint that wants real-world fidelity, but they cannot be re-invoked in CI: they
are a gitignored `npm install`, and their `edit_file` answers with a git-style diff that a
stdlib stand-in could only imitate — an imitation that reproduces the recorded reply by
construction, which is a vacuous A2 PASS dressed up as a real one. Owning the server makes
the demo clone-and-run and keeps the A2 PASS meaningful. What it does NOT do is weaken the
verdict: the engine, the trace format, the sandbox and the invariant are untouched, and the
agent on the other side is real.

**Determinism is the contract.** Every reply here is a pure function of the request and the
tree it runs against. Nothing reads a clock, a random source, the network, or the
environment; no reply carries a duration, a temp path, an address, or a traceback. If any
of that leaked in, the recorded reply would not reproduce and A2 would report a spurious
DIVERGED on a trace that is perfectly faithful.

**Paths are relative, and the root arrives as argv.** `python demo/server.py <abs-root>`;
every tool path is resolved against that root and refused if it escapes. Replay rewrites
the in-root argv token to its scratch copy (`belay.replay.relocate.remap_argv`), so the
same recorded command re-executes against the restored pre-state on any machine, and the
replies — which carry only relative paths — stay byte-identical.

**Annotations are declared truthfully**, which is what gives A2's effect-conformance
something to check instead of abstaining. `readOnlyHint: false` on the writers is the
load-bearing one: it says "I mutate", so the write the agent makes conforms to the
contract and A2 PASSes it — correctly. Only the task-scoped A1 invariant
(`no-assertion-weakening` under `tests/`) can call that same write a corrupt success. A
server that lied, or that declared nothing, would collapse that contrast.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "belay-demo", "version": "1"}

#: Where the demo repo keeps its suite, relative to the root. `run_tests` walks this, and
#: it is the same segment the A1 default invariant scopes over.
TESTS_DIR = "tests"

TOOLS = [
    {
        "name": "list_files",
        "title": "List Files",
        "description": (
            "List every file in the repository, as paths relative to the repository "
            "root, sorted."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read_text_file",
        "title": "Read Text File",
        "description": (
            "Read a file as UTF-8 text. `path` is relative to the repository root."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
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
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "edit_file",
        "title": "Edit File",
        "description": (
            "Replace `oldText` with `newText` in the file at `path`. `oldText` must "
            "appear exactly once, verbatim; anything else is an error and nothing is "
            "written."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "oldText": {"type": "string"},
                "newText": {"type": "string"},
            },
            "required": ["path", "oldText", "newText"],
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "run_tests",
        "title": "Run Tests",
        "description": (
            "Run the repository's test suite and report each test's outcome plus a "
            "one-line summary."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        # Truthful, not conservative: the runner executes the repository's own code,
        # which is free to write. Declaring read-only here would be a lie the effect
        # check would eventually catch — and declaring nothing would make it abstain.
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "openWorldHint": False,
        },
    },
]


class ToolError(Exception):
    """A tool-level failure: reported as `isError: true` content, never as a crash."""


# --- the tree ------------------------------------------------------------------------


def _resolve(root: Path, path: str) -> Path:
    """Resolve `path` under `root`, refusing anything that escapes it.

    The refusal is the server's own boundary and is deliberately separate from Belay's
    sandbox: a demo whose server would happily write outside the repo would be a poor
    illustration of a contained agent even though the sandbox would still stop it.
    """
    if os.path.isabs(path):
        raise ToolError(f"path must be relative to the repository root: {path!r}")
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"path escapes the repository root: {path!r}")
    return target


def _relative(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


def _list_files(root: Path) -> str:
    paths = sorted(
        _relative(root, p)
        for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    return "\n".join(paths)


def _read_text_file(root: Path, arguments: dict) -> str:
    target = _resolve(root, arguments["path"])
    if not target.is_file():
        raise ToolError(f"no such file: {arguments['path']!r}")
    return target.read_text(encoding="utf-8")


def _write_file(root: Path, arguments: dict) -> str:
    target = _resolve(root, arguments["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(arguments["content"], encoding="utf-8")
    return f"wrote {_relative(root, target)}"


def _edit_file(root: Path, arguments: dict) -> str:
    target = _resolve(root, arguments["path"])
    if not target.is_file():
        raise ToolError(f"no such file: {arguments['path']!r}")
    before = target.read_text(encoding="utf-8")
    old, new = arguments["oldText"], arguments["newText"]
    occurrences = before.count(old)
    if occurrences != 1:
        raise ToolError(
            f"oldText must appear exactly once in {arguments['path']!r}; "
            f"it appears {occurrences} times"
        )
    target.write_text(before.replace(old, new, 1), encoding="utf-8")
    return f"edited {_relative(root, target)}"


# --- the test runner -------------------------------------------------------------------


def _run_tests(root: Path, _arguments: dict) -> str:
    """Run every `tests/test_*.py` and report outcomes, deterministically.

    A deliberately small in-process runner rather than a `pytest` subprocess. pytest's
    output carries durations, a rootdir line and tracebacks with addresses — none of which
    reproduce byte-for-byte on replay, so a recorded pytest reply would report DIVERGED on
    a faithful trace. This runner emits an outcome per test and a count, and nothing else.

    A failing test is reported by its exception TYPE, never its message: an
    `AssertionError`'s message is built from the failing expression's runtime values and
    would drag reprs (and, for an object, an address) into the reply.
    """
    tests_root = root / TESTS_DIR
    if not tests_root.is_dir():
        raise ToolError(f"no {TESTS_DIR}/ directory in the repository")

    lines: list[str] = []
    passed = failed = 0

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    preexisting = set(sys.modules)
    try:
        for path in sorted(tests_root.rglob("test_*.py")):
            relative = _relative(root, path)
            namespace: dict = {"__name__": path.stem, "__file__": str(path)}
            try:
                exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
            except BaseException as exc:  # a syntax error, a bad import, a module-level raise
                lines.append(f"{relative} ERROR ({type(exc).__name__})")
                failed += 1
                continue
            for name, value in list(namespace.items()):
                if not name.startswith("test_") or not callable(value):
                    continue
                try:
                    value()
                except BaseException as exc:
                    lines.append(f"{relative}::{name} FAILED ({type(exc).__name__})")
                    failed += 1
                else:
                    lines.append(f"{relative}::{name} PASSED")
                    passed += 1
    finally:
        # Leave no import state behind: the next `run_tests` must observe the tree as it
        # is THEN, not a module cached from an earlier edit.
        for name in set(sys.modules) - preexisting:
            del sys.modules[name]
        sys.path.remove(str(root))

    lines.append(f"{passed} passed, {failed} failed")
    return "\n".join(lines)


HANDLERS = {
    "list_files": lambda root, _arguments: _list_files(root),
    "read_text_file": _read_text_file,
    "write_file": _write_file,
    "edit_file": _edit_file,
    "run_tests": _run_tests,
}


# --- the trace-ordering guard ----------------------------------------------------------

#: Generous on purpose: the bound turns a hang into a named failure; it is not a latency
#: expectation.
AWAIT_TIMEOUT = 30.0


def _await_tools_list_recorded(trace_dir: str) -> None:
    """Block until the trace holds the `tools/list` REQUEST this call is answering.

    `belay.proxy._pump` forwards each chunk and observes it afterwards — forwarding must
    never wait on the recorder — so a server that answers fast enough can have its RESPONSE
    recorded before its own REQUEST. An inverted pair does not correlate,
    `derive_annotations` takes no snapshot, and effect-conformance abstains for every turn
    in the run. A real client has a model turn between the two and never hits it; this
    driver sends `tools/list` immediately after `initialize` and can. Synchronising on the
    trace itself — appended with raw `os.write`, so a record is visible the instant it is
    made — is what closes the window without a guessed sleep.
    """
    deadline = time.monotonic() + AWAIT_TIMEOUT
    while time.monotonic() < deadline:
        for path in glob.glob(os.path.join(trace_dir, "*.jsonl")):
            with open(path, "rb") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("kind") != "frame" or record.get("dir") != "c2s":
                            continue
                        message = json.loads(base64.b64decode(record["raw"]))
                    except (KeyError, ValueError):
                        continue  # a partially written final line; the next poll gets it
                    if isinstance(message, dict) and message.get("method") == "tools/list":
                        return
        time.sleep(0.005)
    raise SystemExit(
        f"the trace in {trace_dir!r} never recorded the tools/list request within "
        f"{AWAIT_TIMEOUT}s"
    )


# --- the JSON-RPC loop -----------------------------------------------------------------


def _reply(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode() + b"\n")
    sys.stdout.buffer.flush()


def _tools_call(root: Path, message: dict) -> dict:
    params = message.get("params") or {}
    name = params.get("name")
    handler = HANDLERS.get(name)
    if handler is None:
        return {"content": [{"type": "text", "text": f"no such tool: {name!r}"}], "isError": True}
    try:
        text = handler(root, params.get("arguments") or {})
    except ToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except KeyError as exc:
        return {
            "content": [{"type": "text", "text": f"missing argument: {exc.args[0]!r}"}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": text}], "isError": False}


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit("usage: server.py <absolute-repository-root>")
    root = Path(argv[1]).resolve()

    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method, msg_id = message.get("method"), message.get("id")

        if method == "initialize":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": SERVER_INFO,
                    },
                }
            )
        elif method == "notifications/initialized":
            continue  # a notification: no reply, ever
        elif method == "tools/list":
            trace_dir = os.environ.get("BELAY_TRACE_DIR")
            if trace_dir:
                # Unset means nothing is being captured (replay, or a bare run), and then
                # there is no ordering to protect.
                _await_tools_list_recorded(trace_dir)
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": _tools_call(root, message)})
        elif msg_id is not None:
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )


if __name__ == "__main__":
    main(sys.argv)
