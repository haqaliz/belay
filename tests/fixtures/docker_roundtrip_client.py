"""A sequenced stdio client: one request at a time, each reply read before the next.

Used only by `tests/test_docker_inimage.py`, to drive `python -m belay.proxy` in
front of `docker_roundtrip_server.py` and leave a captured trace behind.

Sequencing is the whole reason this exists rather than a `printf | proxy` pipeline.
Belay derives a tool's annotations from the `tools/list` RESPONSE that was captured
BEFORE the call — that ordering is what makes the derivation a fact about what the
client had been told, not a guess. Push all four frames at once and the server's
`tools/list` reply lands in the trace *after* the `tools/call` request, so the turn
comes back `readOnlyHint` not-declared and effect-conformance abstains: a green-
looking run that verified strictly less. Measured, not theorised — it is what the
first draft of the roundtrip did.

Usage: `docker_roundtrip_client.py <server-script> <write-target>`.
"""

import json
import subprocess
import sys


def main() -> int:
    server, target = sys.argv[1], sys.argv[2]
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
