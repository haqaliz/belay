"""Two sessions, one JSON-RPC id: correlation must not let one request evict its twin.

`docs/planning/verify-tool-not-offered/incidental-findings/spec.md` Finding 2. The
dual-server composite (`eval/minting_driver/composite.py:_broadcast`) sends `initialize`
and `tools/list` to EVERY session carrying the SAME JSON-RPC id — one `MonotonicIds()`
counter serves both (`eval/minting_driver/loop.py:99-102`). `merge_session_traces` then
folds those sessions into one trace, renumbering `seq` and **adding no origin tag**:
provenance is destroyed by the merge because none was ever recorded.

`derive_correlation` keys pending requests on `(direction, type(id), id)` with no session
component, and a second request with that key used to OVERWRITE the first pending entry.
The consequences, all three real:

* the first request stays `unanswered` forever — a request that WAS answered, recorded as
  one that was not;
* the first reply is credited to the SECOND request — a pairing that never happened;
* the second reply lands on an already-`answered` entry and is reported
  `duplicate-response`, asserting a non-conforming server where both replies were
  perfectly ordinary.

The module's own docstring already forbids exactly this: *"`duplicate-response` below,
which appends rather than overwrites. Requests are never held waiting for a partner, so a
retried request cannot leak an entry."* An eviction is an overwrite that loses a request,
so this is the module repaired against its own stated contract, not a new policy.

**HONEST LIMIT, stated up front and not softened anywhere.** This CANNOT be validated
against the real merged mint data. The s6 captures no longer exist — they lived under a
worktree since removed, and the holder backup has `s1, s1b, s1p, s2, s3,
live-smoke-claude-cli` and no `s6` (`prd.md` -> Constraints). Every trace below is
CONSTRUCTED here, in `tmp_path`, from bytes this file writes. That is a legitimate test of
the correlation rule; it is **not** a replay of history, and nothing here re-derives,
re-runs or re-edits any published Phase-0 number.

Deterministic and offline: `tmp_path` only, synthetic records, no network, no clock.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from eval.minting_driver.trace_merge import merge_session_traces

from belay.index import derive_correlation
from belay.verify.trajectory import offered_toolset

#: Distinct `t_in` per record so the merge INTERLEAVES the two sessions rather than
#: concatenating them: `_interleave` sorts by `t_in`, ties broken by `(filename, seq)`,
#: so equal stamps would put all of session A before all of session B and the two
#: requests would never be pending at the same time — the collision would not occur.
def _record(kind: str, seq: int, stamp: str, **fields) -> dict:
    record = {"v": 1, "kind": kind, "seq": seq, "t_in": stamp}
    record.update(fields)
    return record


def _frame(direction: str, seq: int, stamp: str, message: dict) -> dict:
    raw = base64.b64encode(json.dumps(message).encode()).decode()
    return _record(
        "frame",
        seq,
        stamp,
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


def _tools_list_request(seq: int, stamp: str, msg_id: int) -> dict:
    return _frame("c2s", seq, stamp, {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list"})


def _tools_list_response(seq: int, stamp: str, msg_id: int, names: tuple[str, ...]) -> dict:
    return _frame(
        "s2c",
        seq,
        stamp,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": [{"name": name} for name in names]},
        },
    )


def _collided_merged_records(tmp_path: Path) -> list[dict]:
    """A merged two-session trace whose `tools/list` broadcast shares ONE id.

    Built through the REAL `merge_session_traces`, so the interleaving, the `seq`
    renumbering and the absence of any session tag are the shipped ones — not a hand-made
    approximation of them. The capture order is request(fs), request(shell),
    response(fs), response(shell): both requests are pending at once, which is the
    condition the eviction needed.
    """
    fs = [
        _tools_list_request(0, "2026-08-12T00:00:00.000000+00:00", 1),
        _tools_list_response(1, "2026-08-12T00:00:02.000000+00:00", 1, ("read_text_file", "edit_file")),
    ]
    shell = [
        _tools_list_request(0, "2026-08-12T00:00:01.000000+00:00", 1),
        _tools_list_response(1, "2026-08-12T00:00:03.000000+00:00", 1, ("run_process",)),
    ]
    _write_trace(tmp_path, "trace-20260812T000000Z-aaaa0000.jsonl", fs)
    _write_trace(tmp_path, "trace-20260812T000000Z-bbbb1111.jsonl", shell)

    merged = merge_session_traces(tmp_path)
    assert merged is not None
    return [json.loads(line) for line in merged.open(encoding="utf-8")]


def _tools_list_entries(index: list[dict]) -> list[dict]:
    return [
        entry
        for entry in index
        if entry["kind"] == "correlation" and entry.get("method") == "tools/list"
    ]


# --- AC-4: both pairs correlate; no eviction, no spurious duplicate-response ------------


def test_a_broadcast_id_does_not_evict_its_twin(tmp_path: Path) -> None:
    """AC-4: two sessions sharing one `tools/list` id correlate BOTH pairs correctly.

    The pairing is FIFO over the pending entries for a key — the merged trace carries no
    session tag, so arrival order is the only evidence there is, and the oldest unanswered
    request is the one a reply answers. Both entries answer; neither is left `unanswered`;
    no `duplicate-response` is invented."""
    records = _collided_merged_records(tmp_path)
    index = derive_correlation(records)

    entries = _tools_list_entries(index)
    assert len(entries) == 2, entries
    assert [e["status"] for e in entries] == ["answered", "answered"], entries
    assert [(e["request_seq"], e["response_seq"]) for e in entries] == [(0, 2), (1, 3)], entries
    assert not [e for e in index if e.get("status") == "duplicate-response"], index


# --- AC-6: `offered_toolset` is right BY CONSTRUCTION, not by not-filtering -------------


def test_offered_toolset_reads_the_union_by_construction(tmp_path: Path) -> None:
    """AC-6: the union of both sessions' tools, and it no longer depends on an accident.

    `offered_toolset` -> `derive_annotations` walks correlation entries with a
    `response_seq`, filtering on `method` and NOT on `status`. On the evicting index the
    second snapshot arrived only via the spurious `duplicate-response` entry (which
    inherits the first request's `method` and `request_seq`) while the evicted entry
    contributed nothing — the right answer reached by a wrong route, and one status filter
    away from silently losing a whole server's toolset.

    Now both snapshots come from two `answered` entries, so the reading is correct by
    construction: asserted here TOGETHER with the structural facts it rests on, because
    the union alone cannot tell the two routes apart."""
    records = _collided_merged_records(tmp_path)

    reading = offered_toolset(records)
    assert reading.names == frozenset({"read_text_file", "edit_file", "run_process"})
    assert reading.stale is False

    # The route, not just the answer: every snapshot came from a properly answered
    # request, so a reader that DID filter on `status` would read the same union.
    entries = _tools_list_entries(derive_correlation(records))
    assert all(e["status"] == "answered" for e in entries), entries
    assert all(e["response_seq"] is not None for e in entries), entries


def test_the_shell_toolset_survives_a_status_filter(tmp_path: Path) -> None:
    """The same property said the other way round: restrict the snapshots to entries whose
    `status` is `answered` — the filter `derive_annotations` does not apply — and the
    command tool is STILL offered. Under the eviction it was not: the shell session's
    entry was the evicted one."""
    records = _collided_merged_records(tmp_path)
    index = derive_correlation(records)

    answered_response_seqs = {
        entry["response_seq"]
        for entry in _tools_list_entries(index)
        if entry["status"] == "answered"
    }
    names = set()
    by_seq = {r["seq"]: r for r in records if r.get("kind") == "frame"}
    for seq in answered_response_seqs:
        message = json.loads(base64.b64decode(by_seq[seq]["raw"]))
        names.update(tool["name"] for tool in message["result"]["tools"])
    assert "run_process" in names, names


# --- the engine-level property, without the merge in the way ----------------------------


def test_fifo_pairing_on_hand_built_records(tmp_path: Path) -> None:
    """The rule stated directly on records: two pending requests sharing a key are
    answered oldest-first. No merge, no eval module — this is what `belay.index`
    guarantees to any caller."""
    records = [
        _frame("c2s", 0, "t0", {"jsonrpc": "2.0", "id": 7, "method": "tools/call"}),
        _frame("c2s", 1, "t1", {"jsonrpc": "2.0", "id": 7, "method": "tools/call"}),
        _frame("s2c", 2, "t2", {"jsonrpc": "2.0", "id": 7, "result": {"n": 1}}),
        _frame("s2c", 3, "t3", {"jsonrpc": "2.0", "id": 7, "result": {"n": 2}}),
    ]
    index = derive_correlation(records)

    assert [(e["request_seq"], e["response_seq"], e["status"]) for e in index] == [
        (0, 2, "answered"),
        (1, 3, "answered"),
    ], index


# --- regressions: the behaviours this must NOT change -----------------------------------


def test_a_second_reply_to_one_request_is_still_a_duplicate_response(tmp_path: Path) -> None:
    """Unchanged: ONE request answered TWICE is still `duplicate-response`, inheriting the
    request's method and `request_seq`. The fix narrows to the case where a SECOND REQUEST
    is still pending; it does not retire the duplicate fact."""
    records = [
        _frame("c2s", 0, "t0", {"jsonrpc": "2.0", "id": 4, "method": "tools/call"}),
        _frame("s2c", 1, "t1", {"jsonrpc": "2.0", "id": 4, "result": {"first": True}}),
        _frame("s2c", 2, "t2", {"jsonrpc": "2.0", "id": 4, "result": {"second": True}}),
    ]
    index = derive_correlation(records)

    (answered,) = [e for e in index if e["status"] == "answered"]
    assert (answered["request_seq"], answered["response_seq"]) == (0, 1)
    (duplicate,) = [e for e in index if e["status"] == "duplicate-response"]
    assert duplicate["method"] == "tools/call"
    assert (duplicate["request_seq"], duplicate["response_seq"]) == (0, 2)


def test_a_reused_id_after_an_answer_still_pairs_with_the_new_request(tmp_path: Path) -> None:
    """Unchanged: an id RETIRED by its answer and then reused pairs with the new request —
    the answered entry is no longer pending, so FIFO cannot hand it a second reply."""
    records = [
        _frame("c2s", 0, "t0", {"jsonrpc": "2.0", "id": 5, "method": "a"}),
        _frame("s2c", 1, "t1", {"jsonrpc": "2.0", "id": 5, "result": {}}),
        _frame("c2s", 2, "t2", {"jsonrpc": "2.0", "id": 5, "method": "b"}),
        _frame("s2c", 3, "t3", {"jsonrpc": "2.0", "id": 5, "result": {}}),
    ]
    index = derive_correlation(records)

    assert [(e["method"], e["request_seq"], e["response_seq"], e["status"]) for e in index] == [
        ("a", 0, 1, "answered"),
        ("b", 2, 3, "answered"),
    ], index


def test_an_unanswered_request_is_still_recorded_unanswered(tmp_path: Path) -> None:
    """Unchanged: nothing is held back waiting for a partner. Two pending requests, ONE
    reply — the older answers, the younger stays honestly `unanswered`."""
    records = [
        _frame("c2s", 0, "t0", {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
        _frame("c2s", 1, "t1", {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
        _frame("s2c", 2, "t2", {"jsonrpc": "2.0", "id": 9, "result": {"tools": []}}),
    ]
    index = derive_correlation(records)

    assert [(e["request_seq"], e["status"]) for e in index] == [
        (0, "answered"),
        (1, "unanswered"),
    ], index
