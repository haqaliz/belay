"""A fake MCP server that MUTATES the scope the instant a `tools/call` arrives.

This fixture exists to make the turn gate's central claim falsifiable. The gate
must snapshot a turn's pre-state *before* the `tools/call` reaches the server; an
after-the-fact snapshot is a race that captures whatever the server has already
done, and a "pre-state" that includes the mutation is worthless — worse than
worthless, because everything downstream would still call it grounded.

So the mutation is the **first** thing this server does on receiving the call,
before it replies. If the snapshot were taken anywhere after the frame is
forwarded, it would be racing this write with the whole cost of a tree walk and a
clone against it, and would capture `MUTATED`.

The path to clobber comes from `BELAY_TEST_MUTATE_PATH`. Replies are canned raw
bytes for the same reason `fake_server.py` gives: a fixture that serialises at
runtime cannot be used in a byte-identity comparison.
"""

import json
import os
import sys

PRE_STATE = b"pre-state"
MUTATED = b"MUTATED"

REPLY_INITIALIZE = (
    b'{"result":{"protocolVersion":"2025-11-25","capabilities":{},'
    b'"serverInfo":{"name":"mutating","version":"1"}},"jsonrpc":"2.0","id":1}\n'
)

REPLY_TOOLS_LIST = (
    b'{"result":{"tools":[{"name":"clobber","inputSchema":{"type":"object"}}]},'
    b'"jsonrpc":"2.0","id":2}\n'
)

REPLY_TOOLS_CALL = b'{"result":{"content":[{"type":"text","text":"clobbered"}]},"jsonrpc":"2.0","id":3}\n'


def main() -> None:
    target = os.environ["BELAY_TEST_MUTATE_PATH"]
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")

        if method == "tools/call":
            # First, before the reply: this is the mutation the snapshot must
            # have already outrun.
            with open(target, "wb") as handle:
                handle.write(MUTATED)
                handle.flush()
                os.fsync(handle.fileno())
            stdout.write(REPLY_TOOLS_CALL)
            stdout.flush()
        elif method == "initialize":
            stdout.write(REPLY_INITIALIZE)
            stdout.flush()
        elif method == "tools/list":
            stdout.write(REPLY_TOOLS_LIST)
            stdout.flush()


if __name__ == "__main__":
    main()
