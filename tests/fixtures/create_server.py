"""A fake MCP server that CREATES a file on `tools/call` — the `no-create` cheat fixture.

Sister to `weakening_editor_server.py`, the whole point of the C5 A1 axis: the tool HONESTLY
declares `readOnlyHint: false` (so C4 effect-conformance PASSes the write — the tool announced
it mutates, A2 is CORRECT to pass it), and then does exactly the corrupt thing the truth of
that declaration makes INVISIBLE to A2: it creates `generated/new_file.txt` in its workspace.

Why that combination is the load-bearing shape of the `no-create` fixture:

  - A2 (result + effect) both PASS the creating turn: the fixed reply reproduces
    byte-equivalently on replay, and the write conforms to the declared-false hint.
  - Only the A1 `no-create` invariant grounds on the OBSERVED delta — which contains the
    created path — and FAILs. Same turn, same delta, divergent verdicts: the axes are
    non-redundant, which is the property the per-entry fixtures assert.
  - A server that did NOT really create the file would make `no-create` pass vacuously —
    the anti-vacuity guard in `test_invariant_library_e2e.py` proves the creation is real.

Under replay the cwd is the restored pre-state scratch copy (`client.replay_turn` sets the
server's cwd to it), whose tree does NOT contain `generated/` — so the file appearing is a
real created path in the BTH-1 tree diff.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited JSON-RPC from
stdin; answers `initialize`, `tools/list`, and `tools/call`.
"""

import json
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"

#: The file this server creates, relative to its cwd (the restored pre-state scratch under
#: replay). Its `generated/` prefix is created by the server itself — nothing in the pre-state
#: holds it, so the BTH-1 diff records the path as CREATED, which is what `no-create` FAILs on.
TARGET_PATH = "generated/new_file.txt"

#: The content written. Fixed and deterministic; its exact text does not matter for the
#: invariant (creation is decided by the FieldDiff side markers alone), only that the file
#: really appears.
CREATED_CONTENT = "created by the fixture server\n"

#: The fixed reply text. It matches the recorded reply byte-for-byte, so result-equivalence
#: PASSes and the turn's only divergence is the A1 invariant.
REPLY_TEXT = f"created {TARGET_PATH}"

TOOLS = [
    {
        "name": "create_file",
        "description": "Creates a file. Honestly declares it mutates the workspace.",
        "inputSchema": {"type": "object", "properties": {}},
        # The declared contract C4 grounds on. This tool tells the TRUTH: it declares
        # readOnlyHint:false, so a write is conformant and C4 PASSes it — which is exactly
        # why only the task-scoped A1 invariant can call the creation corrupt.
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
                    "serverInfo": {"name": "create-server", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        # The mutation: create the file under the restored pre-state scratch cwd. Nothing in
        # the pre-state contains `generated/`; mkdir defensively so a bare-scratch cwd would
        # not crash the fixture rather than write.
        target = Path(TARGET_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(CREATED_CONTENT, encoding="utf-8")
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