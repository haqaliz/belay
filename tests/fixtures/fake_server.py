"""Fake MCP server for the byte-level differential test (Task 2).

Replies from CANNED RAW BYTES ONLY — never `json.dumps` at runtime. If this
fixture serialised its replies at runtime, a direct run and a proxied run
would both re-normalise through the same code path and a byte-identity
assertion would prove nothing. The canned bytes below are deliberately
hostile so that any component that parses and re-serialises a message
(instead of forwarding raw bytes) changes the output:

- scrambled key order (params/result appear before method/jsonrpc/id)
- a raw `\\uXXXX` escape for "cafe" (never through json.dumps' own escaping)
- an explicit `"isError":null`
- an unknown top-level field, `"belayFuture":"KEEP"`
- an unsolicited notification emitted before the reply to id 3
- one deliberately NON-CONFORMING frame: REPLY_TOOLS_CALL carries both
  `"params"` and `"method"` on what is otherwise a response object, which
  JSON-RPC 2.0 does not permit (a response carries neither). This is kept
  as-is, not fixed, because the proxy's contract is "forward everything,
  police nothing" — and a response with no `method` is a trap a later
  correlation task must handle correctly.

Reads newline-delimited JSON-RPC from stdin (UTF-8). Stdlib-only,
deterministic, no network, no sleeps.
"""

import json
import sys

REPLY_INITIALIZE = (
    b'{"result":{"protocolVersion":"2025-11-25","capabilities":{},'
    b'"serverInfo":{"name":"fake","version":"1"}},"jsonrpc":"2.0","id":1}\n'
)

REPLY_TOOLS_LIST = (
    b'{"result":{"tools":[{"name":"echo","description":"Echoes the input string",'
    b'"inputSchema":{"type":"object","properties":{"s":{"type":"string"}},'
    b'"required":["s"]}}]},"jsonrpc":"2.0","id":2}\n'
)

NOTIFICATION_TOOLS_CHANGED = b'{"jsonrpc":"2.0","method":"notifications/tools/list_changed"}\n'

REPLY_TOOLS_CALL = (
    b'{"params":{"unexpected":"echo"},'
    b'"result":{"content":[{"type":"text","text":"caf\\u00e9"}],"isError":null},'
    b'"method":"tools/call","jsonrpc":"2.0","id":3,"belayFuture":"KEEP"}\n'
)


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        msg_id = message.get("id")

        if method == "initialize" and msg_id == 1:
            stdout.write(REPLY_INITIALIZE)
            stdout.flush()
        elif method == "notifications/initialized":
            continue  # notification: no reply, ever
        elif method == "tools/list" and msg_id == 2:
            stdout.write(REPLY_TOOLS_LIST)
            stdout.flush()
        elif method == "tools/call" and msg_id == 3:
            # Unsolicited notification interleaved BEFORE the reply, to catch
            # a proxy modelled as strict request/response instead of
            # full-duplex forwarding.
            stdout.write(NOTIFICATION_TOOLS_CHANGED)
            stdout.write(REPLY_TOOLS_CALL)
            stdout.flush()


if __name__ == "__main__":
    main()
