"""The post-close claim record: how a success claim gets into a closed trace.

The trajectory rule needs the agent's final claim to judge, but the proxy
records only what crossed the wire, and the claim never does — the minting
driver parses `Done` and the loop returns on it without it ever crossing the
proxy. `append_claim_record` is the format's answer: one well-formed `claim`
record appended to a closed trace by the driver.

These tests pin the spec's acceptance criteria 1-4: the envelope continues
the capture's `seq` sequence, the `text` key is absent (never `""`) when there
is nothing to say, a malformed or absent trace raises a named error instead of
failing silently, and repeated appends stay strictly increasing.

Traces are built through the real `TraceWriter` wherever the writer could
produce the file — a hand-built envelope would only test the fabricator's idea
of the format. Only the invalid inputs are hand-crafted, because a real writer
can never produce them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.trace import TraceClaimError, TraceWriter, append_claim_record


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
