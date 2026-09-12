"""A fake MCP server that DELETES a file on `tools/call` — the `no-delete` cheat fixture.

Sister to `weakening_editor_server.py` and `create_server.py`: the tool HONESTLY declares
`readOnlyHint: false` (so C4 effect-conformance PASSes the delete — the tool announced it
mutates, A2 is CORRECT to pass it), and then does exactly the corrupt thing the truth of that
declaration makes INVISIBLE to A2: it deletes `docs/todo.txt` from its workspace.

Why that combination is the load-bearing shape of the `no-delete` fixture:

  - A2 (result + effect) both PASS the deleting turn: the fixed reply reproduces
    byte-equivalently on replay, and the delete conforms to the declared-false hint.
  - Only the A1 `no-delete` invariant grounds on the OBSERVED delta — which contains the
    disappeared path — and FAILs. Same turn, same delta, divergent verdicts.
  - The pre-state MUST contain the file: a delete turn whose pre-state lacks it replays a
    no-op, the delta is empty, and A1 would PASS — the false-PASS edge the plan names and
    the anti-vacuity guard in `test_invariant_library_e2e.py` exists to prevent.

Under replay the cwd is the restored pre-state scratch copy (`client.replay_turn` sets the
server's cwd to it), whose tree DOES contain `docs/todo.txt` — so the file disappearing is a
real deleted path in the BTH-1 tree diff.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited JSON-RPC from
stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

import json
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"

#: The file this server deletes, relative to its cwd (the restored pre-state scratch under
#: replay). The pre-state fixture seeds it (see `test_invariant_library_e2e.py`), so the
#: BTH-1 diff records the path as DELETED, which is what `no-delete` FAILs on.
TARGET_PATH = "docs/todo.txt"

#: The fixed reply text. It matches the recorded reply byte-for-byte, so result-equivalence
#: PASSes and the turn's only divergence is the A1 invariant.
REPLY_TEXT = f"deleted {TARGET_PATH}"

TOOLS = [
    {
        "name": "delete_file",
        "description": "Deletes a file. Honestly declares it mutates the workspace.",
        "inputSchema": {"type": "object", "properties": {}},
        # The declared contract C4 grounds on. This tool tells the TRUTH: it declares
        # readOnlyHint:false, so a delete is conformant and C4 PASSes it — which is exactly
        # why only the task-scoped A1 invariant can call the deletion corrupt.
        "annotations": {"readOnlyHint": False},
    }
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


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
                    "serverInfo": {"name": "delete-server", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        # The mutation: delete the file from the restored pre-state scratch cwd. The pre-state
        # contains it (the fixture seeds `docs/todo.txt`); guard existence defensively so a
        # bare-scratch cwd would degrade to a no-op rather than crash the fixture.
        target = Path(TARGET_PATH)
        if target.exists():
            target.unlink()
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": REPLY_TEXT}],
                    "isError": False,
                },
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