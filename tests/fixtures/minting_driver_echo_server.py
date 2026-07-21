"""A fake MCP server for `StdioMcp` correlation tests (Task 2, minting driver).

For every request it reads (a JSON-RPC object carrying an `id`), it writes THREE
lines before the client can see a matching reply:

1. an unsolicited notification (no `id` at all) — proves a reply-reader is not
   confused by a line that carries no id to match on;
2. a bogus response carrying a WRONG id (`requested id + 1000`) — proves the
   reader keeps consuming lines instead of returning the first response-shaped
   line it sees;
3. the real, correctly-correlated reply `{"id": <requested id>, "result":
   {"echoed": <requested id>}}`.

This lets one fixture cover both "an interleaved notification doesn't break
correlation" and "a mismatched-id response doesn't break correlation" for every
request a test sends it, without per-test fixture variants.

A request with no `id` (a notification from the client) gets no reply at all,
matching JSON-RPC semantics — `StdioMcp.notify` sends exactly this shape.

Stdlib only, deterministic, no network, no sleeps.
"""

import json
import sys


def main() -> None:
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        msg_id = message.get("id")
        if msg_id is None:
            continue  # a notification: no reply, ever

        stray = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
        stdout.write((json.dumps(stray) + "\n").encode("utf-8"))

        bogus = {"jsonrpc": "2.0", "id": msg_id + 1000, "result": {"echoed": "wrong"}}
        stdout.write((json.dumps(bogus) + "\n").encode("utf-8"))

        reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"echoed": msg_id}}
        stdout.write((json.dumps(reply) + "\n").encode("utf-8"))
        stdout.flush()


if __name__ == "__main__":
    main()
