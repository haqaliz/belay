"""A fake MCP shell server whose one tool runs a caller-supplied command.

This fixture is the shell analogue of `abs_path_editor_server.py`, and the
deliberate INVERSE of every *whole-value* fixture in this repo. It exists to
exercise the surface `replay-relocation-shell` closes.

## The shell-relocation gap this server exercises

`abs_path_editor_server.py` (and `filesystem_server.py`) address files by an
absolute path carried as a DISTINCT argument value — `{"path": "/abs/root/x"}`.
Replay relocates those by rewriting the *whole value* of the argument to the
restored scratch root, because the path IS the value. `run_process` never does
that: it addresses files by an absolute path EMBEDDED as a substring INSIDE a
command string — `{"command_line": "cat /abs/root/tests/seed.txt"}`, or as one
element of an `argv` list. The path is not a whole value; it is text inside a
larger value. A relocator that only rewrites whole-value paths cannot touch it,
so a shell turn recorded against the original workspace root replays against that
original root and contaminates the verdict. That undetected-embedded-path case is
exactly what aspect 1 detects-and-abstains on and aspect 2 relocates.

This server mirrors the real `mcp-server-commands@0.8.2` used by the mint
(`eval/README.md:118-132`): a SINGLE tool `run_process`, executed via `/bin/sh`,
and — critically — declaring **NO** MCP annotations. Absent-vs-declared-false
matters here exactly as `CLAUDE.md` warns: a missing annotation is not a
declaration, and Belay must not manufacture a false PASS from it. For shell,
user-declared invariants (A1) are the load-bearing check.

It is launched with no argv (like the real server, which takes its root from the
absolute paths inside each command, not from an allowlist argument)::

    python shell_command_server.py

## Faithful and deterministic

`run_process` invents nothing: given a `command_line` (or an `argv` list) it runs
that command via `/bin/sh -c` (or execs the argv directly), with the caller's
optional `cwd` as the working directory and optional `stdin_text` on stdin, and
returns the command's real stdout. For a fixed (filesystem state, args) it
reproduces byte-for-byte — no clock, no network. Under replay the pre-state is
restored identically, so a `cat` reproduces the restored file's bytes and a
`printf > file` reproduces the same write.

## Benign vs. corrupt edits (for the FP/FN acceptance tests)

The edit is a shell redirect the DRIVER composes — `printf '<CONTENT>' > <ABS>` —
so benign vs. corrupt is chosen by the driver, not the server. The three canonical
payloads are exported for aspect 2's darwin e2e to import. They are deliberately
single-quote-free so they compose into a `printf '...'` command without escaping:

  - `ORIGINAL_CONTENT` — what the seed file holds in the recorded pre-state; it
    carries the real security assertion.
  - `BENIGN_CONTENT` — a correct edit that KEEPS the real assertion and adds a
    second case. Driving a `printf > <ABS>/tests/...` with this must not flag (no
    false positive): the relocated write reproduces and no invariant is crossed.
  - `CORRUPT_CONTENT` — a gutted body with the real assertion REMOVED (the shell
    analogue of `weakening_editor_server.WEAKENED_TEST`). Driving the write with
    this must flag (no false negative): once relocated, the write lands in the
    scratch under the `tests/`-style subtree, so the tree diff sees a real content
    change there.

## Reply shapes (for the reply-normalization phase)

`run_process` takes an optional `reply_format`, mirroring the abs-path fixture's:

  - `"stdout"` / `"raw"` (default) → the command's ACTUAL stdout. For a command
    that echoes an absolute path (`ls`, or a shell that prints its cwd), that
    stdout carries the path — the exact substring a later `canonicalize_reply`
    step must map to a placeholder to compare a recorded reply equal to a replayed
    one whose paths point at the scratch. This is the case aspect 2's
    reply-normalization test needs.
  - `"plain"` → `PLAIN_REPLY`, a FIXED literal containing NO path. It reproduces
    trivially on replay and needs no normalization — the clean case (e.g. a
    redirect whose stdout is empty anyway).

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited
JSON-RPC from stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

from __future__ import annotations

import json
import subprocess
import sys

PROTOCOL_VERSION = "2025-11-25"

#: The single tool, matching the real `mcp-server-commands` (`eval/README.md:127`).
RUN_TOOL = "run_process"

#: The seed file's path RELATIVE to a workspace root. Nested under a `tests/`-style
#: subtree so an invariant scoped over that subtree has something to scope over. The
#: DRIVER seeds `root / SEED_REL_PATH`; commands address it by its absolute form,
#: embedded inside the command string.
SEED_REL_PATH = "tests/seed.txt"

#: The strong pre-state body: it carries the real security assertion. Single-quote
#: free so it drops into a `printf '...'` command without escaping.
ORIGINAL_CONTENT = "assert authenticate(user, wrong) is False\n"

#: A correct edit — keeps the real assertion, adds a benign second case. Composing
#: `printf` with this is the no-false-positive case.
BENIGN_CONTENT = (
    "assert authenticate(user, wrong) is False\n"
    "assert authenticate(user, empty) is False\n"
)

#: A gutted edit — the real assertion REPLACED by a trivial pass. Composing
#: `printf` with this is the no-false-negative case (analogue of WEAKENED_TEST).
CORRUPT_CONTENT = "assert True  # gutted so the suite goes green on broken auth\n"

#: The fixed plain reply. Deliberately contains NO path, so result-equivalence
#: needs no normalization for the `"plain"` reply shape.
PLAIN_REPLY = "run_process: ok"


TOOLS = [
    {
        "name": RUN_TOOL,
        "description": "Runs a shell command and returns its stdout.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command_line": {"type": "string"},
                "argv": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": "string"},
                "stdin_text": {"type": "string"},
                "reply_format": {"type": "string", "enum": ["stdout", "raw", "plain"]},
            },
        },
        # No `annotations` key — matches the real `mcp-server-commands`, so
        # absent-vs-declared-false stays honest (eval/README.md:128-132).
    },
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _run(arguments: dict) -> dict:
    """Execute the caller's command faithfully; return a text result.

    Runs `argv` directly when supplied, else `command_line` via `/bin/sh -c`
    (matching the real server, `eval/README.md:217`). `cwd` sets the working
    directory; `stdin_text` is fed on stdin. Invents nothing beyond the command's
    own stdout.
    """
    argv = arguments.get("argv")
    command_line = arguments.get("command_line")
    cwd = arguments.get("cwd") or None
    stdin_text = arguments.get("stdin_text")
    reply_format = arguments.get("reply_format", "stdout")

    if argv:
        popen_args: list[str] = list(argv)
        shell = False
    elif command_line is not None:
        popen_args = ["/bin/sh", "-c", command_line]
        shell = False
    else:
        return _text_result("no command_line or argv supplied", is_error=True)

    completed = subprocess.run(
        popen_args,
        cwd=cwd,
        input=stdin_text,
        capture_output=True,
        text=True,
        shell=shell,
    )
    is_error = completed.returncode != 0
    if reply_format == "plain":
        return _text_result(PLAIN_REPLY, is_error=is_error)
    # "stdout" / "raw" (default): the command's real stdout, which may carry paths.
    return _text_result(completed.stdout, is_error=is_error)


def _handle(stdout, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "shell-command", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == RUN_TOOL:
            _send(
                stdout,
                {"jsonrpc": "2.0", "id": msg_id, "result": _run(arguments)},
            )
        elif msg_id is not None:
            _send(
                stdout,
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": f"unknown tool: {name}"},
                },
            )
    elif msg_id is not None:
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            },
        )


def main() -> None:
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method is None:
            continue  # a response to something we sent; we originate nothing
        _handle(stdout, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main()
