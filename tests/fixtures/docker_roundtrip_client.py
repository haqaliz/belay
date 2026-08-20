"""A sequenced stdio client that waits for the RECORDER, not just for the reply.

Used only by `tests/test_docker_inimage.py`, to drive `python -m belay.proxy` in
front of `docker_roundtrip_server.py` and leave a captured trace behind.

Two orderings matter here and they are not the same ordering.

**Request/response sequencing.** Belay derives a tool's annotations from the
`tools/list` RESPONSE recorded BEFORE the call — that is what makes the derivation
a fact about what the client had been told rather than a guess. Push all four
frames at once and the reply lands in the trace after the `tools/call` request, so
the turn comes back `readOnlyHint` not-declared and effect-conformance abstains: a
green-looking run that verified strictly less. Measured, not theorised — it is what
the first draft did.

**Forwarding runs AHEAD of recording, deliberately.** Reading a reply does NOT
establish that the reply was RECORDED — see `docker_roundtrip_trace.py`, which
carries the measurement and the reasoning. So before sending the call, this client
waits until the `tools/list` reply is in the trace: the annotation snapshot must
precede the call's own frame, or effect-conformance abstains. The server holds up
its half of the same ordering.

Usage: `docker_roundtrip_client.py <server-script> <write-target>`.
"""

import json
import os
import subprocess
import sys

from docker_roundtrip_trace import await_recorded


def main() -> int:
    server, target = sys.argv[1], sys.argv[2]
    trace_dir = os.environ["BELAY_TRACE_DIR"]
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", sys.executable, server],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    def send(message: dict, expect_reply: bool = True) -> None:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        proc.stdin.flush()
        if not expect_reply:
            return
        line = proc.stdout.readline()
        assert line, f"the proxy closed without answering {message.get('method')!r}"

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "docker-roundtrip", "version": "1"},
            },
        }
    )
    send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    # The reply is in hand; the point is that it is also in the TRACE, because that
    # is what the annotation derivation reads.
    await_recorded(trace_dir, "s2c", id=2)
    send(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "write_note", "arguments": {"path": target}},
        }
    )

    assert proc.stdin is not None
    proc.stdin.close()
    return proc.wait(timeout=60)


if __name__ == "__main__":
    sys.exit(main())
