"""The recorder never writes a response before the request it answers.

`belay.proxy._pump` forwards a chunk and observes it afterwards — *"forwarding must
never wait on the recorder"* — so the two directions both run ahead of the trace and a
fast server can have its RESPONSE recorded before its own REQUEST. `derive_correlation`
pairs a request with a **later** response only, so an inverted pair breaks in two
(`response-without-request` + `unanswered`), `derive_annotations` then has no
`tools/list` snapshot to take, and effect-conformance abstains for the whole run. Honest
— UNVERIFIED, never a false PASS — and a real coverage-loss path for any fast local
server.

This module pins the fix, which lives in the recorder and nowhere else: an s2c response
defers its own record until its request's record is on disk, bounded and fail-open.

Two grades of evidence, kept apart on purpose:

* the **unit** tests below drive `TraceWriter` directly and are deterministic — the
  deferral either happens or the response lands immediately, and there is no interleaving
  to be lucky about;
* the **integration** test drives the real proxy in front of a server that answers
  instantly (`tests/fixtures/fast_server.py`) and is a *stress* guard. It is stochastic
  by nature, so it is quoted as what was measured rather than as a rate. On the engine
  **before** the fix, 2026-09-05, this machine: two 20-run stresses of this exact
  fixture and driver gave **15/20 and 12/20 runs holding at least one broken
  correlation** (46 and 60 broken correlation records). **After: 20/20 and 20/20 clean,
  0 broken records.**
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import read_trace

from belay.annotations import derive_annotations
from belay.index import classify, derive_correlation
from belay.trace import TraceClosed, TraceWriter

FAST_SERVER = Path(__file__).parent / "fixtures" / "fast_server.py"

#: How many `tools/call` roundtrips the integration guard drives. Each one is an
#: independent race, so N is the number of chances the guard gets, not a duration.
N_CALLS = 20


def frame(message: dict | list) -> bytes:
    """A frame as the recorder sees one: the bytes, without the newline."""
    return json.dumps(message).encode()


def request_frame(id_: object, method: str = "tools/list") -> bytes:
    return frame({"jsonrpc": "2.0", "id": id_, "method": method})


def response_frame(id_: object, text: str = "ok") -> bytes:
    return frame(
        {
            "jsonrpc": "2.0",
            "id": id_,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    )


def seq_of(records: list[dict], needle: bytes) -> int:
    """The `seq` of the one frame record whose raw bytes are `needle`."""
    import base64

    hits = [
        record["seq"]
        for record in records
        if record.get("kind") == "frame"
        and base64.b64decode(record["raw"]) == needle
    ]
    assert len(hits) == 1, f"expected exactly one record of {needle!r}, found {hits!r}"
    return hits[0]


def record_in_thread(writer: TraceWriter, direction: str, raw: bytes, truncated=False):
    """Observe `raw` on `direction` from another thread; return (thread, done, box)."""
    done = threading.Event()
    box: list[BaseException] = []

    def run() -> None:
        try:
            writer.observer(direction)(raw, truncated)
        except BaseException as exc:  # the test asserts on what was raised
            box.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, done, box


# --- the guarantee ------------------------------------------------------------------


def test_a_response_waits_for_its_request_and_then_records_after_it(tmp_path):
    """The defect, closed: the response cannot land while its request is unrecorded.

    Deterministic in both directions. On the unfixed engine the response records
    immediately and `done` is set within microseconds, so the negative wait below fails
    without depending on any interleaving; on the fixed engine the response cannot land
    until the c2s record exists, which this test is the one thing able to cause.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    call, reply = request_frame(2), response_frame(2)
    thread, done, box = record_in_thread(writer, "s2c", reply)
    try:
        assert not done.wait(0.25), (
            "the response recorded before its request: an inverted pair does not "
            "correlate, so the annotation snapshot is never taken and "
            "effect-conformance abstains for the whole run"
        )
        writer.observer("c2s")(call, False)
        assert done.wait(10), "the response never recorded after its request did"
    finally:
        thread.join(timeout=10)
        writer.close()
    assert not box, box

    records = read_trace(tmp_path / "trace")
    assert seq_of(records, call) < seq_of(records, reply)
    correlations = [
        entry
        for entry in derive_correlation(records)
        if entry["kind"] == "correlation"
    ]
    assert [entry["status"] for entry in correlations] == ["answered"]


def test_a_response_whose_request_is_already_recorded_never_waits(tmp_path):
    """The overwhelmingly common case pays nothing.

    A 30-second deadline with a sub-second assertion: if the ordinary path waited at
    all, this would sit on that deadline rather than pass.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=30.0)
    try:
        writer.observer("c2s")(request_frame(2), False)
        started = time.monotonic()
        writer.observer("s2c")(response_frame(2), False)
        assert time.monotonic() - started < 1.0
    finally:
        writer.close()


def test_an_orphan_response_records_anyway_after_the_deadline(tmp_path):
    """Fail-open, and honestly out of order — never a hang, never a fabricated pair.

    A response whose request never crosses is legal (a non-conforming server, or a
    proxy attached mid-connection). The record still lands, and the readers name what
    they see: `response-without-request`, exactly as they do today.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=0.05)
    try:
        started = time.monotonic()
        writer.observer("s2c")(response_frame(7), False)
        waited = time.monotonic() - started
    finally:
        writer.close()

    assert 0.05 <= waited < 5.0, waited
    records = read_trace(tmp_path / "trace")
    correlations = [
        entry
        for entry in derive_correlation(records)
        if entry["kind"] == "correlation"
    ]
    assert [entry["status"] for entry in correlations] == ["response-without-request"]


def test_closing_the_writer_releases_a_parked_response(tmp_path):
    """Shutdown is never held by a deferral longer than the close it is racing.

    The refusal that follows is the writer's existing contract, unchanged: an
    observation outside the connection window is a named `TraceClosed`, not a bad fd.
    The proxy's capture gate stops observation before close, so this is unreachable
    through it — which is exactly why the writer states it rather than assuming it.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=30.0)
    thread, done, box = record_in_thread(writer, "s2c", response_frame(4))
    assert not done.wait(0.25)

    started = time.monotonic()
    writer.close()
    assert done.wait(10), "close() left the deferral parked on its full deadline"
    assert time.monotonic() - started < 5.0
    thread.join(timeout=10)

    assert len(box) == 1 and isinstance(box[0], TraceClosed), box


# --- what must never wait -----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, truncated, why",
    [
        (
            frame({"jsonrpc": "2.0", "id": 1, "method": "sampling/createMessage"}),
            False,
            "a server-originated REQUEST answers nothing and lives in the server's "
            "own id space",
        ),
        (
            frame({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}),
            False,
            "a notification carries no id, so no request could be waited for",
        ),
        (
            frame([{"jsonrpc": "2.0", "id": 1, "result": {}}]),
            False,
            "a JSON-RPC batch is a shape the reader names rather than pairs; "
            "guessing at one here would pair on a key the reader never builds",
        ),
        (b'{"jsonrpc":"2.0","id":1,"result":', False, "an unparseable frame"),
        (
            b"\xff\xfe not utf-8 at all",
            False,
            "bytes that are not a message at all — the frames the proxy exists to "
            "carry intact",
        ),
        (
            frame({"jsonrpc": "2.0", "id": [1], "result": {}}),
            False,
            "a container id is illegal and unhashable; there is no key to wait on",
        ),
        (
            response_frame(3),
            True,
            "a truncated frame is a fragment, and half a message read as if it were "
            "the message is worse than an acknowledged gap",
        ),
    ],
)
def test_these_s2c_frames_never_wait(tmp_path, raw, truncated, why):
    """M3: a frame waits only when it is provably a response to a client request.

    The deadline is 30 s and the assertion is sub-second, so a frame that waited by
    mistake fails here rather than merely running slowly.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=30.0)
    try:
        started = time.monotonic()
        writer.observer("s2c")(raw, truncated)
        assert time.monotonic() - started < 1.0, why
    finally:
        writer.close()


def test_a_response_travelling_c2s_never_waits(tmp_path):
    """The client's own reply to a server request travels c2s and answers nothing here.

    Only s2c responses defer: a c2s frame is never waited on, or the two directions
    could wait on each other.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=30.0)
    try:
        started = time.monotonic()
        writer.observer("c2s")(response_frame(11), False)
        assert time.monotonic() - started < 1.0
    finally:
        writer.close()


# --- the mechanism's own properties -------------------------------------------------


def test_a_second_reply_to_an_answered_request_does_not_stall(tmp_path):
    """The index is monotone, and this is the case that decides it.

    A non-conforming server answering twice is `duplicate-response` to the reader — a
    named, handled fact. Draining a key once its response was recorded would make the
    second reply wait out the whole deadline for a request that was recorded long ago.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace", request_wait=30.0)
    try:
        writer.observer("c2s")(request_frame(2), False)
        writer.observer("s2c")(response_frame(2, "first"), False)
        started = time.monotonic()
        writer.observer("s2c")(response_frame(2, "second"), False)
        assert time.monotonic() - started < 1.0
    finally:
        writer.close()

    statuses = sorted(
        entry["status"]
        for entry in derive_correlation(read_trace(tmp_path / "trace"))
        if entry["kind"] == "correlation"
    )
    assert statuses == ["answered", "duplicate-response"]


def test_the_request_index_does_not_grow_with_the_run(tmp_path, monkeypatch):
    """S2: bounded memory. The oldest keys are dropped, never the newest."""
    monkeypatch.setattr("belay.trace._REQUEST_INDEX_MAX", 8)
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for id_ in range(50):
            writer.observer("c2s")(request_frame(id_), False)
        # The private index is the thing under test; there is no public surface for
        # it, and inventing one would be a wider change than the fix.
        assert len(writer._recorded_requests) == 8
        started = time.monotonic()
        writer.observer("s2c")(response_frame(49), False)
        assert time.monotonic() - started < 1.0, "the newest keys were evicted"
    finally:
        writer.close()


@pytest.mark.parametrize(
    "message",
    [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "no"}},
        # A response a non-conforming server also stamped `method` on. One exists in
        # this repo's own fixtures, and `result`-first is the only reading that gets
        # it right.
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "result": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": None, "method": "tools/list"},
        {"jsonrpc": "2.0"},
        {"id": 1},
    ],
)
def test_the_recorder_classifies_exactly_as_the_reader_does(message):
    """M3: the recorder's structural classification is the reader's, pinned.

    Re-implemented in `belay.trace` rather than imported from `belay.index`: the
    recorder must not depend on a derivation that reads what it writes. This test is
    what makes "identical" a fact rather than an intention — a drift here is how the
    recorder would start waiting on a key the reader never builds.
    """
    from belay.trace import _classify

    assert _classify(message) == classify(message)


# --- end to end, through the real proxy ---------------------------------------------


def _drive_fast_server(trace_dir: Path) -> None:
    """Drive `fast_server.py` behind the real proxy, one frame at a time.

    Sequenced rather than batched: pushing every frame at once gives the c2s recorder
    a whole chunk of head start, which is the interleaving the race does NOT live in.
    One request, one reply, N times is the shape that measured 15/20 broken.
    """
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    proc = subprocess.Popen(
        [sys.executable, "-m", "belay.proxy", sys.executable, str(FAST_SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    def send(message: dict, expect_reply: bool = True) -> None:
        proc.stdin.write(json.dumps(message).encode() + b"\n")
        proc.stdin.flush()
        if expect_reply:
            assert proc.stdout.readline(), (
                f"the proxy closed without answering {message.get('method')!r}"
            )

    send(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "fast", "version": "1"},
            },
        }
    )
    send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    for offset in range(N_CALLS):
        send(
            {
                "jsonrpc": "2.0",
                "id": 3 + offset,
                "method": "tools/call",
                "params": {"name": "peek", "arguments": {}},
            }
        )
    proc.stdin.close()
    assert proc.wait(timeout=60) == 0


def test_a_fast_server_roundtrip_correlates_every_pair_and_keeps_its_snapshot(tmp_path):
    """The defect's own shape, end to end: 22 pairs against a server that never waits.

    The assertion is deliberately the defect's shape — every pair correlates, and the
    `tools/list` snapshot survives — and NOT snapshot-liveness for the call that
    follows. That second property is client-side by construction (only the client
    decides when its next request crosses) and stays guarded by the fixtures that
    guard it today; the engine's guarantee is request-before-response, nothing more.
    """
    trace_dir = tmp_path / "trace"
    _drive_fast_server(trace_dir)
    records = read_trace(trace_dir)

    derived = derive_correlation(records)
    correlations = [entry for entry in derived if entry["kind"] == "correlation"]
    gaps = [entry for entry in derived if entry["kind"] == "index_gap"]

    # Anti-vacuity, first: a fixture that emitted nothing would make every assertion
    # below pass by comparing empty to empty, which is the corrupt success this repo
    # exists to catch — inside its own suite. An INVERTED pair yields two entries for
    # one exchange, so this floor cannot hide one; the exact count is asserted after
    # the diagnosis below, which names what went wrong.
    assert len(correlations) >= N_CALLS + 2, correlations
    assert not gaps, gaps

    broken = [entry for entry in correlations if entry["status"] != "answered"]
    assert not broken, (
        "a response was recorded before its request; the pair broke in two and the "
        f"run lost its annotation coverage:\n  {broken!r}"
    )
    assert len(correlations) == N_CALLS + 2, correlations
    assert all(
        entry["request_seq"] < entry["response_seq"] for entry in correlations
    ), correlations

    snapshots = [
        entry
        for entry in derive_annotations(records)
        if entry["kind"] == "annotation_snapshot"
    ]
    assert len(snapshots) == 1, snapshots
    tools = snapshots[0]["tools"]
    assert [tool["name"] for tool in tools] == ["peek"]
    assert tools[0]["annotations"]["readOnlyHint"]["state"] == "declared-true", tools
