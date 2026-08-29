"""A fake MCP server whose `tools/list` answer is chosen by an env var.

The probe's contract is three-way — a set of names, an EMPTY set, or `None` —
and the two falsy outcomes are different facts. `conforming_server.py` already
covers "the boundary answers with tools"; nothing covered the two shapes that
must NOT read as an empty answer *or* as a populated one:

- `empty` — a well-formed `result.tools: []`. The boundary answered, and offers
  nothing. The probe must return `set()`, never `None`.
- `no-tools` — a well-formed reply whose `result` carries no `tools` key at all.
  Nothing was read, so the probe must return `None`, never `set()`.

Both are reachable only from a real spawn, which is why they are a fixture and
not a hand-built byte string: a reply the server never sends is a reply the
transport was never asked to carry.

The mode is read from `BELAY_TEST_TOOLSET_MODE`; absent, the server offers two
tools, so a test that forgets to set the variable gets a populated set rather
than an accidental pass on the empty case.

Stdlib only, deterministic, no network, no sleeps.
"""

import json
import os
import sys

PROTOCOL_VERSION = "2025-11-25"

MODE_ENV = "BELAY_TEST_TOOLSET_MODE"

#: The two tools the default mode offers.
TOOL_NAMES = ("alpha", "beta")

TOOLS = [
    {
        "name": name,
        "description": f"the {name} tool",
        "inputSchema": {"type": "object", "properties": {}},
    }
    for name in TOOL_NAMES
]


def _send(stdout, message: dict) -> None:
    stdout.write((json.dumps(message) + "\n").encode("utf-8"))
    stdout.flush()


def _tools_result(mode: str) -> dict:
    if mode == "empty":
        return {"tools": []}
    if mode == "no-tools":
        # A well-formed result that answers the request and carries no tool list.
        return {"capabilities": {"tools": {"listChanged": False}}}
    return {"tools": TOOLS}


def _handle(stdout, mode: str, method: str, msg_id, params: dict) -> None:
    if method == "initialize":
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "toolset-probe", "version": "1"},
                },
            },
        )
    elif method == "tools/list":
        _send(stdout, {"jsonrpc": "2.0", "id": msg_id, "result": _tools_result(mode)})
    elif msg_id is not None:
        # Answer anything else with a proper error rather than staying silent: a
        # hang reports as a timeout and says nothing about the cause.
        _send(
            stdout,
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            },
        )


def main() -> None:
    mode = os.environ.get(MODE_ENV, "")
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        if method is None:
            continue  # a response to something we sent; we originate nothing
        # A notification carries no id and must never be answered.
        _handle(stdout, mode, method, message.get("id"), message.get("params") or {})


if __name__ == "__main__":
    main()
