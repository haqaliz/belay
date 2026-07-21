"""A fake MCP server that logs heavily to stderr before replying (Task 2 fix).

For every request it reads, it first writes a large volume to stderr — well
past a typical OS pipe buffer (64KB on Linux and modern macOS) — THEN writes
the correctly-correlated JSON-RPC reply to stdout. If nothing on the client
side is draining the server's stderr pipe, this write blocks once the pipe
fills, so the server never gets around to writing its stdout reply — and a
transport that only reads stdout sees that as a `ReplyTimeout` against a
server that is, in fact, healthy and eventually would have replied.

This is deliberately NOT a hang: given a drained stderr, the server replies
almost immediately. It reproduces exactly the pipe-buffer deadlock described
in the Task 2 review, without ever being a true hang like
`minting_driver_hang_server.py`.

Stdlib only, deterministic, no network, no sleeps.
"""

import json
import sys

# Comfortably past a 64KB OS pipe buffer; still fast to generate and write.
_STDERR_CHUNK = b"x" * 8192
_STDERR_TOTAL_BYTES = 512 * 1024  # 512KB, in 8KB chunks


def _flood_stderr() -> None:
    stderr = sys.stderr.buffer
    written = 0
    while written < _STDERR_TOTAL_BYTES:
        stderr.write(_STDERR_CHUNK)
        written += len(_STDERR_CHUNK)
    stderr.flush()


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

        # Log noisily BEFORE replying — this is the write that blocks if the
        # client never drains stderr.
        _flood_stderr()

        reply = {"jsonrpc": "2.0", "id": msg_id, "result": {"echoed": msg_id}}
        stdout.write((json.dumps(reply) + "\n").encode("utf-8"))
        stdout.flush()

        # And more noise AFTER replying, so a second request on the same
        # transport also has to contend with a still-filling stderr pipe.
        _flood_stderr()


if __name__ == "__main__":
    main()
