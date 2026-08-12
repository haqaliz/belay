"""RED-first contract tests for `eval.minting_driver.trace_merge`.

The dual-server composite runs TWO proxied sessions per instance — one per pinned
server (`eval/minting_driver/composite.py`) — and each proxy writes its own trace
into the instance's `trace_dir`. Every downstream consumer assumes ONE trace per
instance: the claim append (`claims.record_session_claim` skips when the dir holds
more than one), the rename bridge (`bridge_capture` raises `MultipleTracesError`),
and the phase-0 runner (a trace is an instance). The merge step is the missing
wire between the composite and the claim/bridge/runner contract.

What the merge must do, and must NOT do:

* Exactly one trace in the dir → byte-identical no-op (the single-server path must
  be untouched — the s5 freeze invocations stay valid verbatim).
* Zero traces → `None` (the bridge names the missing capture `NoTraceError`; the
  merge never invents a capture).
* Two or more → ONE merged trace: every record present, `seq` renumbered
  monotonically in capture order (each proxy numbers its own trace from 0, so the
  two traces' `seq` collide — a merged file must renumber or correlation and
  replay lookups break), order deterministic (pure function of the input bytes).
* Content hashes are untouched: `hash_raw`/`hash_canonical` cover the frame bytes,
  and TRACE_FORMAT.md:75 puts timing outside the hashed content — `seq`/`t_in` are
  metadata, so renumbering `seq` does not invalidate a single hash.

Deterministic and offline: `tmp_path` only, synthetic records, no network, no clock.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from eval.minting_driver.trace_merge import merge_session_traces


def _record(kind: str, seq: int, **fields) -> dict:
    record = {"v": 1, "kind": kind, "seq": seq, "t_in": "2026-08-12T00:00:00.000000+00:00"}
    record.update(fields)
    return record


def _frame(direction: str, seq: int, message: dict) -> dict:
    raw = base64.b64encode(json.dumps(message).encode()).decode()
    return _record(
        "frame",
        seq,
        dir=direction,
        raw=raw,
        hash_raw="sha256:deadbeef",
        hash_canonical="sha256:beefdead",
        canonical_form="belay/jcs-v1",
        truncated=False,
        state_handle={"status": "absent"},
    )


def _write_trace(dir_path: Path, name: str, records: list[dict]) -> Path:
    path = dir_path / name
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def test_single_trace_is_a_byte_identical_no_op(tmp_path: Path) -> None:
    """The single-server path is untouched: same path back, file bytes unchanged."""
    records = [
        _record("connection_window", 0, phase="open", observation_point="proxy"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        _frame("s2c", 2, {"jsonrpc": "2.0", "id": 1, "result": {}}),
    ]
    path = _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", records)

    result = merge_session_traces(tmp_path)

    assert result == path
    assert path.read_bytes() == "".join(
        json.dumps(record) + "\n" for record in records
    ).encode()


def test_no_trace_returns_none(tmp_path: Path) -> None:
    """No capture is never invented: `None` lets the bridge raise `NoTraceError`."""
    assert merge_session_traces(tmp_path) is None


def test_two_traces_merge_into_one_with_all_records(tmp_path: Path) -> None:
    fs_records = [
        _record("connection_window", 0, phase="open", observation_point="proxy"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        _frame("s2c", 2, {"jsonrpc": "2.0", "id": 1, "result": {}}),
        _frame("c2s", 3, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}),
    ]
    shell_records = [
        _record("connection_window", 0, phase="open", observation_point="proxy"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        _frame("c2s", 2, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}),
        _frame("s2c", 3, {"jsonrpc": "2.0", "id": 2, "result": {"exit": 0}}),
    ]
    _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", fs_records)
    _write_trace(tmp_path, "trace-20260812T000000Z-bbbb1111.jsonl", shell_records)

    result = merge_session_traces(tmp_path)

    assert result is not None
    assert result.is_file()
    remaining = sorted(tmp_path.glob("trace-*.jsonl"))
    assert remaining == [result], "exactly one trace must remain after the merge"

    merged = [json.loads(line) for line in result.open(encoding="utf-8")]
    assert len(merged) == len(fs_records) + len(shell_records), "no record is lost"

    kinds = [record["kind"] for record in merged]
    assert kinds.count("connection_window") == 2, "both sessions' windows survive"


def test_merged_seq_is_monotonic_and_renumbered(tmp_path: Path) -> None:
    """Both proxies number from 0, so the merged file MUST renumber — otherwise
    correlation's `request_seq`/`response_seq` and replay's seq lookups collide."""
    first = [
        _record("connection_window", 0, phase="open"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
    ]
    second = [
        _record("connection_window", 0, phase="open"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}),
    ]
    _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", first)
    _write_trace(tmp_path, "trace-20260812T000000Z-bbbb1111.jsonl", second)

    result = merge_session_traces(tmp_path)
    merged = [json.loads(line) for line in result.open(encoding="utf-8")]

    seqs = [record["seq"] for record in merged]
    assert seqs == sorted(seqs), "merged seqs must be monotonic"
    assert seqs == list(range(len(merged))), "merged seqs must be renumbered 0..N"
    assert len(set(seqs)) == len(seqs), "no seq may collide after the merge"


def test_merge_is_deterministic(tmp_path: Path) -> None:
    """A pure function of the input bytes: same inputs → byte-identical output."""
    records_a = [
        _record("connection_window", 0, phase="open"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        _frame("c2s", 2, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}),
    ]
    records_b = [
        _frame("c2s", 0, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}),
        _frame("s2c", 1, {"jsonrpc": "2.0", "id": 2, "result": {}}),
    ]
    outputs = []
    for run in range(2):
        work = tmp_path / f"run-{run}"
        work.mkdir()
        _write_trace(work, "trace-20260812T000000Z-aaaa0000.jsonl", records_a)
        _write_trace(work, "trace-20260812T000000Z-bbbb1111.jsonl", records_b)
        result = merge_session_traces(work)
        assert result is not None
        outputs.append(result.read_bytes())

    assert outputs[0] == outputs[1]


def test_merge_uses_capture_order_not_filename_order(tmp_path: Path) -> None:
    """Records interleave by `t_in` (proxy-observed capture order), never by the
    order the files happen to sort — the merged trace must read as ONE session."""
    fs = [
        _record("connection_window", 0, phase="open", t_in="2026-08-12T00:00:01+00:00"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}),
    ]
    shell = [
        _record("connection_window", 0, phase="open", t_in="2026-08-12T00:00:02+00:00"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 4, "method": "tools/call"}),
    ]
    _write_trace(tmp_path, "trace-20260812T000000Z-bbbb1111.jsonl", shell)
    _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", fs)

    result = merge_session_traces(tmp_path)
    merged = [json.loads(line) for line in result.open(encoding="utf-8")]

    windows = [
        record["t_in"] for record in merged if record["kind"] == "connection_window"
    ]
    assert windows == sorted(windows), "capture order is t_in order, not filename order"


def test_merge_refuses_non_trace_files(tmp_path: Path) -> None:
    """Only `trace-*.jsonl` participates; anything else in the dir is not a capture."""
    (tmp_path / "not-a-trace.txt").write_text("noise")
    assert merge_session_traces(tmp_path) is None


def test_claim_survives_the_merge_path(tmp_path: Path) -> None:
    """The claim append and the bridge both glob `trace-*.jsonl`; the merged file
    must be found by the same glob (name convention preserved)."""
    _write_trace(
        tmp_path,
        "trace-20260812T000000Z-aaaa0000.jsonl",
        [_record("connection_window", 0, phase="open")],
    )
    _write_trace(
        tmp_path,
        "trace-20260812T000000Z-bbbb1111.jsonl",
        [_frame("c2s", 0, {"jsonrpc": "2.0", "id": 4, "method": "tools/call"})],
    )

    result = merge_session_traces(tmp_path)

    assert result is not None
    assert result.name.startswith("trace-") and result.name.endswith(".jsonl")
    assert len(list(tmp_path.glob("trace-*.jsonl"))) == 1


def test_correlation_pairs_after_merge(tmp_path: Path) -> None:
    """The end-to-end property the merge exists for: `derive_correlation` over the
    merged trace pairs every tools/call request with its response (unique JSON-RPC
    ids across the composite — loop.py's single `MonotonicIds`)."""
    from belay.index import derive_correlation, tool_calls

    fs = [
        _record("connection_window", 0, phase="open"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        _frame("s2c", 2, {"jsonrpc": "2.0", "id": 1, "result": {}}),
        _frame("c2s", 3, {"jsonrpc": "2.0", "id": 3, "method": "tools/call"}),
        _frame("s2c", 4, {"jsonrpc": "2.0", "id": 3, "result": {}}),
    ]
    shell = [
        _record("connection_window", 0, phase="open"),
        _frame("c2s", 1, {"jsonrpc": "2.0", "id": 2, "method": "tools/call"}),
        _frame("s2c", 2, {"jsonrpc": "2.0", "id": 2, "result": {"exit": 0}}),
    ]
    _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", fs)
    _write_trace(tmp_path, "trace-20260812T000000Z-bbbb1111.jsonl", shell)

    result = merge_session_traces(tmp_path)
    records = [json.loads(line) for line in result.open(encoding="utf-8")]
    calls = tool_calls(derive_correlation(records))

    assert len(calls) == 2, "both tools/call turns must correlate after the merge"
    for call in calls:
        assert call["status"] == "answered", f"turn {call['id']} must pair with its reply"
        assert call["response_seq"] is not None
