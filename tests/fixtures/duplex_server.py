"""A server that originates its own request with `id:1`, colliding with the client's.

MCP is full-duplex: a server may originate requests (sampling, elicitation,
roots) at any time. Its ids live in **its own namespace** and legitimately start
at 1 — the same place the client's start. So `id:1` exists twice in one session,
meaning two different things, and a correlation table keyed on the bare id
cross-wires them: it can answer "what did the client's initialize return?" with
the reply to a sampling request, or vice versa.

That collision is not a rare edge; it is the default for any server that speaks
first. This fixture makes it reachable end-to-end, driven by the same
`CLIENT_LINES` as every other test:

- the scripted client sends `initialize` with `id:1` (c2s)
- this server originates `sampling/createMessage` with `id:1` (s2c)
- this server replies to the client's `initialize`, `id:1` (s2c)

The scripted client never answers `sampling/createMessage`, which is the second
fact under test: an unanswered request is **legal** — cancellation is racy by
design — and must be recorded as unanswered rather than leaked or waited on.

Replies are CANNED RAW BYTES ONLY, for the same reason as `fake_server.py`: a
fixture that serialised at runtime would re-normalise through the same code path
as the thing it is testing.

Kept separate from `fake_server.py`, which is the differential gate's control and
must not acquire new behaviour.
"""

import json
import sys

# Server-originated. `id:1` in the SERVER's id space - unrelated to the client's
# `id:1`, and deliberately sent before the initialize reply so that a
# correlation keyed on the bare id meets the collision before the disambiguating
# response arrives.
SERVER_REQUEST_SAMPLING = (
    b'{"jsonrpc":"2.0","id":1,"method":"sampling/createMessage",'
    b'"params":{"messages":[],"maxTokens":1}}\n'
)

REPLY_INITIALIZE = (
    b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25","capabilities":{},'
    b'"serverInfo":{"name":"duplex","version":"1"}}}\n'
)

REPLY_TOOLS_LIST = b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}\n'

REPLY_TOOLS_CALL = (
    b'{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"ok"}]}}\n'
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
            stdout.write(SERVER_REQUEST_SAMPLING)
            stdout.write(REPLY_INITIALIZE)
            stdout.flush()
        elif method == "tools/list" and msg_id == 2:
            stdout.write(REPLY_TOOLS_LIST)
            stdout.flush()
        elif method == "tools/call" and msg_id == 3:
            stdout.write(REPLY_TOOLS_CALL)
            stdout.flush()


if __name__ == "__main__":
    main()
