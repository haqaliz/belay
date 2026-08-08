"""The post-close claim record: how a success claim gets into a closed trace.

The trajectory rule needs the agent's final claim to judge, but the proxy
records only what crossed the wire, and the claim never does — the minting
driver parses `Done` and the loop returns on it without it ever crossing the
proxy. `append_claim_record` is the format's answer: one well-formed `claim`
record appended to a closed trace by the driver.

These tests pin the spec's acceptance criteria 1-6. Criteria 1-4 cover the
helper itself: the envelope continues the capture's `seq` sequence, the `text`
key is absent (never `""`) when there is nothing to say, a malformed or absent
trace raises a named error instead of failing silently, and repeated appends
stay strictly increasing. Criteria 5-6 pin the tolerance the readers and the
replay machinery already have: a `claim` is a non-frame record, so it must not
change any derived record, gap, or verdict — the indexer skips it
(`index.py:110`) and replay never gathers or reads it. The existing code is
already inert to the record, so these are contract pins, not bug fixes: they
pass because the format's unknown-kind rule was written before the claim kind
existed.

Traces are built through the real `TraceWriter` wherever the writer could
produce the file — a hand-built envelope would only test the fabricator's idea
of the format. Only the invalid inputs are hand-crafted, because a real writer
can never produce them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.index import derive_correlation, tool_calls
from belay.replay.engine import EQUAL, REPLAYED, replay_turn
from belay.replay.persist import persist_snapshot
from belay.replay.reader import read_trace
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceClaimError, TraceWriter, append_claim_record

CONFORMING = Path(__file__).parent / "fixtures" / "conforming_server.py"
CONFORMING_CMD = [sys.executable, str(CONFORMING)]


def closed_trace(tmp_path: Path, n_frames: int = 2) -> tuple[Path, int]:
    """Write a real, closed trace with `n_frames` frames; return (path, last seq)."""
    writer = TraceWriter.in_directory(tmp_path / "trace")
    try:
        for i in range(n_frames):
            writer.observer("c2s")(
                b'{"jsonrpc":"2.0","id":%d,"method":"tools/call"}' % i, False
            )
    finally:
        writer.close()
    records = [json.loads(line) for line in writer.path.read_text().splitlines() if line]
    assert records, "no records written - the envelope checks would pass vacuously"
    return writer.path, records[-1]["seq"]


def records_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_claim_envelope_continues_the_capture_sequence(tmp_path):
    path, last_seq = closed_trace(tmp_path)

    returned = append_claim_record(path, text="the suite passed")

    records = records_of(path)
    claim = records[-1]
    assert claim["v"] == 1
    assert claim["kind"] == "claim"
    assert claim["seq"] == last_seq + 1
    assert returned == claim["seq"]
    assert claim["t_in"].endswith("+00:00")
    assert claim["observation_point"] == "session"
    assert claim["text"] == "the suite passed"
    # The claim is the last record: nothing may land after it.
    assert claim is records[-1]


def test_text_key_is_absent_when_there_is_no_text(tmp_path):
    path, _ = closed_trace(tmp_path)

    append_claim_record(path)
    append_claim_record(path, text="")
    append_claim_record(path, text="   \t ")

    claims = [r for r in records_of(path) if r["kind"] == "claim"]
    assert len(claims) == 3
    assert all("text" not in claim for claim in claims)


def test_missing_file_raises_named_error(tmp_path):
    with pytest.raises(TraceClaimError):
        append_claim_record(tmp_path / "no-such-trace.jsonl")


def test_empty_file_raises_named_error(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_file_with_no_record_lines_raises_named_error(tmp_path):
    path = tmp_path / "blank.jsonl"
    path.write_text("\n\n")

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_unparseable_last_line_raises_named_error(tmp_path):
    path = tmp_path / "junk.jsonl"
    path.write_text('{"v":1,"kind":"frame","seq":0}\nthis is not json\n')

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_last_line_that_is_not_a_record_raises_named_error(tmp_path):
    path = tmp_path / "list.jsonl"
    path.write_text('{"v":1,"kind":"frame","seq":0}\n[1, 2]\n')

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_last_line_without_seq_raises_named_error(tmp_path):
    path = tmp_path / "noseq.jsonl"
    path.write_text('{"v":1,"kind":"frame"}\n')

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_non_integer_seq_raises_named_error(tmp_path):
    path = tmp_path / "strseq.jsonl"
    path.write_text('{"v":1,"kind":"frame","seq":"zero"}\n')

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_negative_seq_raises_named_error(tmp_path):
    path = tmp_path / "negseq.jsonl"
    path.write_text('{"v":1,"kind":"frame","seq":-1}\n')

    with pytest.raises(TraceClaimError):
        append_claim_record(path)


def test_two_appends_yield_strictly_increasing_seq(tmp_path):
    path, last_seq = closed_trace(tmp_path)

    first = append_claim_record(path, text="one")
    second = append_claim_record(path, text="two")

    assert first == last_seq + 1
    assert second == first + 1

    seqs = [r["seq"] for r in records_of(path)]
    assert seqs == list(range(len(seqs))), "seq must stay gapless and duplicate-free"


# --- Acceptance 5-6: the readers and replay are inert to the claim record -----
#
# The claim kind exists so the trajectory rule has something to judge. The rule
# must judge it A1-style, but the ENGINE must not notice it: the indexer derives
# from frames only (`index.py:110`), and replay selects turns from that index and
# re-reads frames only. These are contract pins — the code was already tolerant,
# and these tests exist so that a reader that one day starts reacting to the claim
# kind fails loudly instead of quietly changing every verdict.


def _trace_with_path(tmp_path: Path, name: str, frames: list[tuple]) -> tuple[Path, list[dict]]:
    """Build a real trace via `TraceWriter`; return (path, records).

    Each frame is `(direction, raw_bytes, state_handle_or_None)`; a handle is
    pinned to that exact frame via `set_state_handle(..., frame=...)`, exactly as
    the replay tests build their traces.
    """
    writer = TraceWriter.in_directory(tmp_path / name)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted((tmp_path / name).glob("*.jsonl"))[0]
    return path, records_of(path)


def _without_timing(records: list[dict]) -> list[dict]:
    """The records with `t_in` stripped, for cross-trace comparison.

    `t_in` is wall-clock by design (it never enters any hash — two identical
    runs may record different times), so two separately-built traces differ in
    it. What must be identical is everything else: kind, seq, payload, envelope.
    """
    return [{k: v for k, v in record.items() if k != "t_in"} for record in records]


def _snapshot_manifest(tmp_path: Path, name: str, contents: dict[str, str]) -> tuple[Path, dict]:
    """A workspace with `contents`, snapshotted and persisted; returns the manifest
    directory and the `present` state handle naming that snapshot."""
    work = tmp_path / f"{name}-work"
    work.mkdir()
    for filename, text in contents.items():
        (work / filename).write_text(text)
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / "m.json")
    return manifest_dir, present_handle(snap)


def _initialize(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": version,
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        }
    ).encode()


def _initialize_reply(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": version,
                "capabilities": {},
                "serverInfo": {"name": "x", "version": "1"},
            },
        }
    ).encode()


def _echo_call(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"s": text}},
        }
    ).encode()


def _echo_reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'

# A handshake + one echoed `tools/call`: exercises request/response correlation,
# the notification skip, and both directions of frame.
_INDEX_FRAMES = [
    ("c2s", _initialize("2025-11-25"), None),
    ("s2c", _initialize_reply("2025-11-25"), None),
    ("c2s", INITIALIZED, None),
    ("c2s", _echo_call(2, "hi"), None),
    ("s2c", _echo_reply(2, "hi"), None),
]


def test_claim_record_changes_no_derived_record(tmp_path):
    """Acceptance 5: the same trace, with a claim record appended, derives identically.

    Both the raw reader path (`read_trace(...).records` — the phase0 consumer path)
    and the derived index (`derive_correlation` + `tool_calls`) must be unchanged,
    with or without claim `text`. The claim is a non-frame record: the indexer
    skips it (`index.py:110`), so no `index_gap`, no correlation entry, no derived
    record may appear or move.
    """
    plain_path, _ = _trace_with_path(tmp_path, "plain", _INDEX_FRAMES)
    with_text_path, _ = _trace_with_path(tmp_path, "with-text", _INDEX_FRAMES)
    without_text_path, _ = _trace_with_path(tmp_path, "without-text", _INDEX_FRAMES)

    append_claim_record(with_text_path, text="the suite passed")
    append_claim_record(without_text_path)

    # Anti-vacuity: the appends really landed, and the plain trace indexes to
    # something — "identical" over two empty derivations would prove nothing.
    assert any(r["kind"] == "claim" for r in records_of(with_text_path))
    assert any(r["kind"] == "claim" for r in records_of(without_text_path))
    assert "text" in records_of(with_text_path)[-1]
    assert "text" not in records_of(without_text_path)[-1]

    plain_records = read_trace(plain_path).records
    plain_index = derive_correlation(plain_records)
    plain_calls = tool_calls(plain_index)
    assert plain_calls, "the fixture indexes to no tool call — the comparison would be vacuous"

    for claim_path in (with_text_path, without_text_path):
        records = read_trace(claim_path).records
        assert _without_timing(records) == _without_timing(plain_records), (
            "the reader returned different records for the claim trace"
        )

        index = derive_correlation(records)
        assert index == plain_index, "the claim record changed a derived correlation record"
        assert [g for g in index if g["kind"] == "index_gap"] == [
            g for g in plain_index if g["kind"] == "index_gap"
        ], "the claim record introduced or moved an index_gap"
        assert tool_calls(index) == plain_calls, "the claim record changed the tools/call index"


def test_claim_record_is_a_recorded_skip_in_the_trace_reader(tmp_path):
    """The reader's unknown-kind rule: a `claim` is skipped, and the skip is recorded.

    `claim` is not one of the `KINDS` the reader accepts (`trace.py:53-61`), so the
    reader records one `Skip` naming it — never a silent drop, never a fatal error.
    The understood records are byte-for-byte the claim-free trace's.
    """
    plain_path, _ = _trace_with_path(tmp_path, "plain", _INDEX_FRAMES)
    claim_path, _ = _trace_with_path(tmp_path, "claim", _INDEX_FRAMES)
    append_claim_record(claim_path, text="the suite passed")

    plain_read = read_trace(plain_path)
    claim_read = read_trace(claim_path)

    assert _without_timing(claim_read.records) == _without_timing(plain_read.records)
    assert len(claim_read.skips) == 1, "the claim must be one recorded skip, never a drop"
    assert claim_read.skips[0].kind == "claim"


@pytest.mark.skipif(
    sys.platform != "darwin", reason="replay re-invokes inside the macOS Seatbelt sandbox"
)
def test_claim_record_does_not_change_the_replayed_turn(tmp_path):
    """Acceptance 6: replaying a turn of a claim-bearing trace reproduces the same
    observations as the same trace without the record.

    A real replay: the pre-state is snapshotted and persisted, the turn is
    re-invoked against a fresh `conforming_server`, and the reply and workspace
    delta are captured. The claim record must not enter the turn-selection path
    (`tool_calls` over the correlation index), the frame table (`_frames_by_seq`),
    the handshake gather, or the version resolution — so every observation field
    is identical, the replay still succeeds (REPLAYED, EQUAL — the positive
    control that this rig really re-invokes), and only the ephemeral scratch
    workspace path may differ.
    """
    manifest_dir, handle = _snapshot_manifest(tmp_path, "inert", {"keep.txt": "x"})
    frames = [
        ("c2s", _initialize("2025-11-25"), None),
        ("s2c", _initialize_reply("2025-11-25"), None),
        ("c2s", INITIALIZED, None),
        ("c2s", _echo_call(2, "hi"), handle),
        ("s2c", _echo_reply(2, "hi"), None),
    ]
    plain_path, _ = _trace_with_path(tmp_path, "plain", frames)
    claim_path, _ = _trace_with_path(tmp_path, "claim", frames)
    append_claim_record(claim_path, text="the suite passed")

    plain = replay_turn(
        read_trace(plain_path).records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir
    )
    claimed = replay_turn(
        read_trace(claim_path).records, 0, server_command=CONFORMING_CMD, manifest_dir=manifest_dir
    )

    # Positive control: both replays really ran and agreed with the recording.
    assert plain.status == REPLAYED, f"the plain trace must replay: {plain}"
    assert claimed.status == REPLAYED, f"the claim record broke the replay: {claimed}"
    assert claimed.result_equivalence == EQUAL == plain.result_equivalence

    # The deterministic observations — everything except the ephemeral scratch
    # workspace path and the outcomes that name it.
    for field in (
        "status",
        "cause",
        "reinvoked",
        "delta",
        "result_equivalence",
        "recorded_reply",
        "replayed_reply",
        "recorded_version",
        "replayed_version",
        "version_drift",
    ):
        assert getattr(claimed, field) == getattr(plain, field), (
            f"the claim record changed the replay observation {field!r}: "
            f"{getattr(plain, field)!r} -> {getattr(claimed, field)!r}"
        )
