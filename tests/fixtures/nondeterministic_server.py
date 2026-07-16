"""A fake MCP server whose `tools/call` reply is deliberately NONDETERMINISTIC.

This is the adversary C3's determinism classifier must handle *without* crying
foul. A clock/random/pid-dependent tool diverges legitimately across identical
replays — that is nondeterminism, not a fabricated trace — and C2's sharpest
warning lands here: *"Never let a timestamp diff render as FAIL."* So this server
exists to be replayed N times from the *same* restored pre-state and produce a
*different* answer each time, on purpose.

Which source of divergence it draws on is chosen by `BELAY_TEST_NONDET_SOURCE`:

- ``clock``  — the reply embeds ``time.time_ns()``: a ~19-digit decimal that
  strictly increases across the sequential replays. The `WALL_CLOCK` axis.
- ``random`` — the reply embeds 128 bits of entropy as 32 hex chars (letters and
  all). `random` is seeded from system entropy at interpreter start, so a fresh
  process per replay yields fresh bytes. The `RANDOMNESS` axis.
- ``pid``    — the reply embeds ``os.getpid()``: a small integer that differs
  because each replay is a fresh process. The `RUNNING_PROCESS` axis (process
  identity a filesystem snapshot cannot restore).

Each value is placed alone in the tool result's text so exactly one token varies
across runs — which is what lets the classifier *name* the axis rather than only
noting that something changed. The id is echoed back so the client can match the
reply to its request. Stdlib only, no network, no sleeps.
"""

import json
import os
import random
import sys
import time


def _value() -> str:
    source = os.environ["BELAY_TEST_NONDET_SOURCE"]
    if source == "clock":
        return str(time.time_ns())
    if source == "random":
        return "%032x" % random.getrandbits(128)
    if source == "pid":
        return str(os.getpid())
    raise ValueError(f"unknown BELAY_TEST_NONDET_SOURCE {source!r}")


def main() -> None:
    stdout = sys.stdout.buffer
    for raw_line in sys.stdin.buffer:
        line = raw_line.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("method") != "tools/call":
            # Nothing else is exercised: the replay traces are 2026-shape (no
            # handshake), so the only frame that arrives is the target call.
            continue
        reply = {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "result": {
                "content": [{"type": "text", "text": _value()}],
                "isError": False,
            },
        }
        stdout.write((json.dumps(reply) + "\n").encode("utf-8"))
        stdout.flush()


if __name__ == "__main__":
    main()
