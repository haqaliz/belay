"""A fake MCP server that takes real time per `tools/call`, and mutates as it goes.

`mutating_server.py` proves the snapshot beats the server to the tree. This one
proves something the gate cannot see from a single turn: that **two turns can be
in flight at once**, which is what a client does by default when it batches
independent tool calls into one block. Claude Code is instructed to; Cursor and
the OpenAI agents SDK do the same.

Two properties make the pipelined case decidable rather than raced:

**It sleeps before it acts.** A server that replied instantly would let the reply
reach the gate before the second call did, and the second turn really would have
begun with nothing outstanding — an honest `present`, and a test whose outcome the
scheduler picks. `SLEEP_S` is far longer than a clone, so while the second
`tools/call` is being gated the first is provably still running.

**Each call leaves a distinct mark, named by the caller.** Turn 2 therefore runs
against a tree that visibly contains turn 1's file, so "turn 2's recorded
pre-state is empty" is a difference a test can see rather than infer.

Replies are built here rather than canned, because the id must match the request:
a pipelining client is exactly the client that can tell two replies apart, and an
id this fixture made up would make the in-flight ledger untestable. Byte-identity
is not this fixture's job (that is `fake_server.py`), so a serialiser is free.
"""

import json
import os
import sys
import time

#: Long enough that turn 1 is unambiguously still executing when turn 2 is gated,
#: and short enough to sit inside the suite's timeouts. The gate's own budget is
#: 200ms for a 400-file clone, so this is an order of magnitude clear of it.
SLEEP_S = 0.4


def main() -> None:
    target_dir = os.environ["BELAY_TEST_TOUCH_DIR"]
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("method") != "tools/call":
            continue

        # The work, before the reply and before the next call is read: this is the
        # window in which a second turn is genuinely concurrent with this one.
        time.sleep(SLEEP_S)
        name = message["params"]["arguments"]["name"]
        with open(os.path.join(target_dir, name), "wb") as handle:
            handle.write(b"touched")
            handle.flush()
            os.fsync(handle.fileno())

        reply = {
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {"content": [{"type": "text", "text": name}]},
        }
        stdout.write(json.dumps(reply).encode("utf-8") + b"\n")
        stdout.flush()


if __name__ == "__main__":
    main()
