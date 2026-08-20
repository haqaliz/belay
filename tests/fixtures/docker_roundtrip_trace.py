"""Wait on the TRACE, never on a clock — shared by the in-image roundtrip fixtures.

`belay.proxy._pump` forwards each chunk and observes it afterwards, under the
comment "forwarding must never wait on the recorder": transparency is the proxy's
whole contract, so both directions run ahead of the trace. The consequence is a
real ordering race that a fast client and a fast server can lose — measured, on a
GitHub `ubuntu-24.04` runner and reproduced 2 times in 20 locally:

    seq 5  frame s2c  (reply to id 2)      <-- the tools/list RESPONSE
    seq 6  frame c2s  tools/list  id 2     <-- its own REQUEST, recorded after

`derive_correlation` pairs a request with a LATER response, so an inverted pair
does not correlate; `derive_annotations` then has no `tools/list` snapshot, and the
turn's effect-conformance abstains with "no tools/list response was captured before
this call". A truthful abstention about a trace that really is out of order — the
engine is not wrong here, the trace is.

Real clients do not hit this: a model turn sits between the reply and the next
request. A test harness firing microseconds apart does. So the fixtures synchronise
on the observable — the trace file is opened `O_APPEND` and written with raw
`os.write`, so a record is visible the instant it is made — instead of sleeping a
guessed interval that would be tuned to one machine and go quiet on a faster one.

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
