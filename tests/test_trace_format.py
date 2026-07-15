"""The trace format: what the proxy recorded, and what it may claim about it.

These tests hold the line on the two properties everything downstream depends
on. **Losslessness**: the recorded bytes are the bytes, recoverable exactly, for
frames that are not even valid UTF-8. **Honesty**: the trace never asserts more
than the proxy observed — no fabricated canonical form for a frame that has
none, no timing dressed up as server-side, and no silent gap where observation
died.

The data path is deliberately out of scope here; `test_differential.py` owns
byte-transparency and stays the only thing that proves it.
"""

from __future__ import annotations

import base64
import json
import os
import stat
import sys
import threading
from pathlib import Path

from conftest import CLIENT_LINES, FIXTURE, run_over_pipes

from belay.proxy import BoundedPeek, _pump
from belay.trace import TraceWriter

NONUTF8_FIXTURE = Path(__file__).parent / "fixtures" / "nonutf8_server.py"


def proxy_cmd(server: Path) -> list[str]:
    return [sys.executable, "-m", "belay.proxy", sys.executable, str(server)]


def run_traced(tmp_path: Path, name: str, server: Path = FIXTURE) -> list[dict]:
    """Run the scripted client through the proxy and return the trace records."""
    trace_dir = tmp_path / name
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    run_over_pipes(proxy_cmd(server), env=env)
    return read_trace(trace_dir)


def read_trace(trace_dir: Path) -> list[dict]:
    traces = sorted(trace_dir.glob("*.jsonl"))
    assert len(traces) == 1, f"expected exactly one trace file, found {traces!r}"
    lines = traces[0].read_bytes().split(b"\n")
    return [json.loads(line) for line in lines if line]


def frames(records: list[dict], direction: str | None = None) -> list[dict]:
    return [
        r
        for r in records
        if r["kind"] == "frame" and (direction is None or r["dir"] == direction)
    ]


def test_hashes_are_stable_across_two_identical_runs(tmp_path):
    first = frames(run_traced(tmp_path, "first"))
    second = frames(run_traced(tmp_path, "second"))

    # Anti-vacuity: two empty runs would agree on everything and prove nothing.
    assert first, "no frames captured - this comparison would pass vacuously"

    def content(records):
        return [(r["dir"], r["hash_raw"], r["hash_canonical"]) for r in records]

    assert content(first) == content(second)

    # The counterpart: the runs really were separate in time, so the equality
    # above is evidence that timing stays out of the hashed content rather
    # than evidence that we compared a run to itself.
    assert [r["t_in"] for r in first] != [r["t_in"] for r in second]


def test_raw_bytes_round_trip_exactly(tmp_path):
    direct_lines = run_over_pipes([sys.executable, str(FIXTURE)])
    assert direct_lines, "fixture emitted nothing - this comparison would be vacuous"

    captured = [base64.b64decode(r["raw"]) for r in frames(run_traced(tmp_path, "t"), "s2c")]

    assert captured == direct_lines
    assert b"\n".join(captured) + b"\n" == b"\n".join(direct_lines) + b"\n"


def test_non_utf8_frame_round_trips_with_no_canonical_hash(tmp_path):
    captured = frames(run_traced(tmp_path, "t", server=NONUTF8_FIXTURE), "s2c")
    raws = [base64.b64decode(r["raw"]) for r in captured]

    assert b'{"jsonrpc":"2.0","id":1,"result":{"text":"\xff\xfe"}}' in raws

    undecodable = captured[raws.index(b'{"jsonrpc":"2.0","id":1,"result":{"text":"\xff\xfe"}}')]
    assert undecodable["hash_canonical"] is None
    assert undecodable["canonical_form"] is None
    assert undecodable["hash_raw"].startswith("sha256:")

    # The writer survived it: the next frame is still captured, and it is a
    # frame that DOES have a canonical form, so "null" above is a finding about
    # those bytes and not the writer having given up.
    assert captured[-1]["hash_canonical"] is not None


def test_every_schema_field_survives_the_round_trip(tmp_path):
    for record in frames(run_traced(tmp_path, "t")):
        assert record["v"] == 1
        assert record["kind"] == "frame"
        assert isinstance(record["seq"], int)
        assert record["dir"] in ("c2s", "s2c")
        assert isinstance(record["raw"], str)
        assert record["hash_raw"].startswith("sha256:")
        assert record["hash_canonical"].startswith("sha256:")
        assert record["canonical_form"] == "belay/jcs-v1"
        assert record["t_in"].endswith("+00:00")
        assert record["observation_point"] == "proxy"
        assert record["truncated"] is False
        assert record["state_handle"] == {"status": "absent"}


def test_trace_file_is_owner_only(tmp_path):
    trace_dir = tmp_path / "trace"
    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)
    run_over_pipes(proxy_cmd(FIXTURE), env=env)

    (trace,) = list(trace_dir.glob("*.jsonl"))
    assert stat.S_IMODE(trace.stat().st_mode) == 0o600
    assert stat.S_IMODE(trace_dir.stat().st_mode) == 0o700


def test_both_directions_are_captured_with_gapless_seq(tmp_path):
    records = run_traced(tmp_path, "t")

    assert [base64.b64decode(r["raw"]) for r in frames(records, "c2s")] == CLIENT_LINES
    assert frames(records, "s2c"), "no server->client frames captured"

    # Capture order, allocated once across both directions: no gaps, no repeats.
    assert [r["seq"] for r in records] == list(range(len(records)))


def test_no_trace_is_written_when_the_env_var_is_unset(tmp_path):
    env = os.environ.copy()
    env.pop("BELAY_TRACE_DIR", None)
    env["PWD"] = str(tmp_path)

    run_over_pipes(proxy_cmd(FIXTURE), env=env)

    assert list(tmp_path.rglob("*.jsonl")) == []


def test_observer_failure_is_recorded_as_a_named_cause(tmp_path):
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        writer.capture_error("s2c", ValueError("disk on fire"))
    finally:
        writer.close()

    (record,) = read_trace(tmp_path / "trace")
    assert record["kind"] == "capture_error"
    assert record["dir"] == "s2c"
    assert "ValueError" in record["cause"]
    assert "disk on fire" in record["cause"]


def test_concurrent_directions_never_tear_a_line_or_repeat_a_seq(tmp_path):
    """Both pumps are real threads writing one file; this is that seam.

    Honest about its own strength: this is a regression guard, NOT proof that
    the writer's lock is load-bearing. Removing the lock was tried, and the GIL
    makes the unsynchronised version pass this too — the read-then-increment
    race is real but not reachable on demand from Python. What this does catch
    is a refactor that breaks the contract structurally: per-thread buffering, a
    second fd, a short write, a seq allocated outside the append.
    """
    writer = TraceWriter.in_directory(tmp_path / "trace")
    per_direction = 500

    def hammer(direction: str) -> None:
        observe = writer.observer(direction)
        for i in range(per_direction):
            observe(b'{"i":%d}' % i, False)

    threads = [threading.Thread(target=hammer, args=(d,)) for d in ("c2s", "s2c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    writer.close()

    records = read_trace(tmp_path / "trace")  # parses every line: catches tearing
    assert len(records) == 2 * per_direction
    assert sorted(r["seq"] for r in records) == list(range(2 * per_direction))


def test_forwarding_survives_an_observer_that_raises_and_the_cause_is_named():
    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    payload = b'{"a":1}\n{"b":2}\n'
    os.write(src_w, payload)
    os.close(src_w)

    causes: list[BaseException] = []

    def explode(frame: bytes, truncated: bool) -> None:
        raise ValueError("boom")

    _pump(src_r, dst_w, BoundedPeek(explode), causes.append)
    os.close(dst_w)

    # Forwarding is unaffected: every byte still made it through, in order.
    assert os.read(dst_r, 4096) == payload
    # And observation did not just stop being mentioned. It stopped, once,
    # with a cause someone can act on.
    assert len(causes) == 1
    assert isinstance(causes[0], ValueError)
