"""A spec-conforming MCP server, for the real-SDK compatibility test.

**Why this exists alongside `fake_server.py`, rather than replacing it.** The two
fixtures are adversaries of each other and both are load-bearing:

- `fake_server.py` replies from canned hostile bytes and includes a deliberately
  NON-CONFORMING frame (a response carrying `params` and `method`). That is what
  makes the byte-level differential meaningful — a proxy that parses and re-emits
  changes those bytes and gets caught. A real SDK client **rejects** that frame,
  by design and correctly.
- this one is boringly correct, so a real SDK client can actually complete a
  handshake through the proxy. It proves compatibility, and proves nothing about
  byte-transparency: it is conforming enough that a re-serialising proxy would
  sail through it unnoticed.

Neither fixture can do the other's job. Using only this one would quietly retire
the differential's teeth; using only that one makes a real client impossible.

Stdlib only, deterministic, no network, no sleeps. Reads newline-delimited
JSON-RPC from stdin, writes it to stdout. Serialising at runtime is fine *here*
precisely because nothing in this test compares bytes.
"""

import json
import sys

PROTOCOL_VERSION = "2025-11-25"

TOOLS = [
    {
        "name": "echo",
        "description": "Echoes the input string",
        "inputSchema": {
            "type": "object",
            "properties": {"s": {"type": "string"}},
            "required": ["s"],
        },
    }
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _result(stdout, msg_id, result: dict) -> None:
    _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": result})


def _handle(stdout, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _result(
            stdout,
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "conforming", "version": "1"},
            },
        )
    elif method == "tools/list":
        _result(stdout, msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        arguments = params.get("arguments") or {}
        _result(
            stdout,
            msg_id,
            {
                "content": [{"type": "text", "text": str(arguments.get("s", ""))}],
                "isError": False,
            },
        )
    elif method == "ping":
        _result(stdout, msg_id, {})
    elif msg_id is not None:
        # A request we do not implement gets a proper JSON-RPC error. Staying
        # silent would hang the client on a request it is entitled to an answer
        # to, and a hang is a much worse test failure than a rejection: it
        # reports as a timeout and says nothing about the cause.
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
        # A notification carries no id and must never be answered — including
        # `notifications/initialized`, which falls through to here and is dropped.
        _handle(stdout, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main()
