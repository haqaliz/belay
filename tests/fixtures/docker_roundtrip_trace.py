"""Wait on the TRACE, never on a clock — shared by the in-image roundtrip fixtures.

**Re-scoped 2026-09-05 (`trace-ordering-fix`). Read this first: the guard below no
longer carries the property it was written for, and it is kept because it carries a
second one that no recorder can close.**

What it was written for. `belay.proxy._pump` forwards each chunk and observes it
afterwards, under the comment "forwarding must never wait on the recorder", so both
directions ran ahead of the trace and a fast server could have its RESPONSE recorded
before its own REQUEST — measured on a GitHub `ubuntu-24.04` runner and reproduced 2
times in 20 locally:

    seq 5  frame s2c  (reply to id 2)      <-- the tools/list RESPONSE
    seq 6  frame c2s  tools/list  id 2     <-- its own REQUEST, recorded after

**That is now closed in the recorder** (`belay.trace.TraceWriter`): a response defers
its own record until its request's record exists, bounded and fail-open. So the
server-side wait here is belt-and-braces, not the guarantee.

What it still carries, and what nothing else can. The *client-side* ordering:
`derive_annotations` snapshots a tool's contract from the `tools/list` RESPONSE
recorded BEFORE the call, and only the CLIENT decides when its next request crosses.
A client that fires the call microseconds after reading the reply can still get in
ahead of the reply's record — and the recorder cannot fix that without making the
client's data path wait, which is the one thing it must not do. Real clients do not
hit it (a model turn sits between the reply and the next request); a test harness
does. So the wait stays, and stays on the observable — the trace file is opened
`O_APPEND` and written with raw `os.write`, so a record is visible the instant it is
made — instead of sleeping a guessed interval tuned to one machine.

A timeout here RAISES. A wait that gives up quietly would put the flake back.
"""

import base64
import glob
import json
import os
import time

#: Generous on purpose: the bound turns a hang into a named failure, it does not
#: express an expected latency.
TIMEOUT = 30.0


def _records(trace_dir: str):
    for path in glob.glob(os.path.join(trace_dir, "*.jsonl")):
        with open(path, "rb") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # a partially written final line; the next poll gets it
                if record.get("kind") != "frame":
                    continue
                try:
                    message = json.loads(base64.b64decode(record["raw"]))
                except (KeyError, ValueError):
                    continue
                if isinstance(message, dict):
                    yield record["dir"], message


def _seen(trace_dir: str, direction: str, **fields) -> bool:
    for recorded_dir, message in _records(trace_dir):
        if recorded_dir != direction:
            continue
        if all(message.get(key) == value for key, value in fields.items()):
            return True
    return False


def await_recorded(trace_dir: str, direction: str, **fields) -> None:
    """Block until the trace holds a `direction` frame matching `fields`."""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        if _seen(trace_dir, direction, **fields):
            return
        time.sleep(0.005)
    raise AssertionError(
        f"the trace in {trace_dir!r} never recorded a {direction} frame matching "
        f"{fields!r} within {TIMEOUT}s"
    )
