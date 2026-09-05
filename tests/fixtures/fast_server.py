"""An MCP server that answers instantly and waits on nothing. The race, on purpose.

The sibling fixtures for the in-image roundtrip (`docker_roundtrip_server.py`,
`docker_roundtrip_client.py`) synchronise on the TRACE before they speak, because the
proxy forwards a chunk and records it afterwards and a fast server could otherwise have
its RESPONSE recorded before its own REQUEST. This fixture is the opposite by design: it
removes that guard so the ordering guarantee is tested rather than avoided.

**Measured with this fixture, on the engine before the fix (2026-09-05, this machine,
22 request/response pairs per run):** two 20-run stresses gave 15/20 and 12/20 runs
holding at least one broken correlation — 46 and 60 broken correlation records. Two
stresses after the fix: 20/20 and 20/20 clean, 0 broken records. A stochastic race, so
the numbers are what was observed, not a rate.

Nothing here reads a clock, a random source, the network or the environment: the whole
point is that the only variable is the recorder's ordering. `readOnlyHint` is declared
truthfully — the tool touches nothing — so the run also carries an annotation snapshot to
assert on, which is the coverage the inverted pair used to destroy.
"""

import json
import sys

TOOL = {
    "name": "peek",
    "description": "Returns a fixed string and touches nothing.",
    "inputSchema": {"type": "object", "properties": {}},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
}


def _reply(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message).encode() + b"\n")
    sys.stdout.buffer.flush()


def main() -> None:
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
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "fast", "version": "1"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue  # a notification: no reply, ever
        elif method == "tools/list":
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": [TOOL]}})
        elif method == "tools/call":
            _reply(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": "ok"}],
                        "isError": False,
                    },
                }
            )


if __name__ == "__main__":
    main()
