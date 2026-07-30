"""`belay phase0 run --no-ingest` — a pure measurement that writes nothing, and says so.

Re-verifying already-captured runs sometimes wants the number WITHOUT touching the corpus:
`--no-ingest` suppresses every corpus WRITE while changing no verdict and no count. The
honesty requirement is the whole point of the flag, and it is the second test below: with
ingestion off, `flagged_addable` is empty for a reason that has nothing to do with
addability, so an unlabelled empty list would read as "nothing could be added". A
measurement that silently wrote nothing must not look like a measurement that found
nothing — the report must distinguish *not attempted* from *attempted and failed*.

This lives in its own file rather than in `tests/test_phase0_cli.py` because that file was
being edited in parallel when the flag landed; the apparatus below is deliberately a copy
of that file's (which itself mirrors `tests/test_phase0_runner.py`), for the same reason
those two already duplicate it — a synthetic trace plus a canned verdict keyed by trace
stem, so no Seatbelt and no real replay ever runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay import cli
from belay.phase0.ledger import from_json
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


# --- synthetic trace + canned-verdict apparatus (mirrors tests/test_phase0_cli.py) ------


def _call_frame(call_id: int, tool: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    ).encode()


def _reply_frame(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ).encode()


def _write_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """Write one `trace-*.jsonl` of `n_calls` `tools/call` turns for `tool`, via the real writer."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            writer.observer("c2s")(_call_frame(call_id, tool), False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    return writer.path


def _verdict(n: int, status: Status) -> TurnVerdict:
    return TurnVerdict(
        turn_index=n,
        tool_name="t",
        status=status,
        sub_verdicts=[Verdict("A2", "replay", status, None, None, "canned")],
        cause=None,
    )


def _stem_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier keyed by the trace's stem, read back off `manifest_dir`'s name."""

    def verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _patch_seam(monkeypatch, canned: dict[str, list[TurnVerdict]], ingester) -> None:
    """Point `belay.phase0.runner`'s verifier/ingester seam at fakes, no Seatbelt involved."""
    import belay.phase0.runner as phase0_runner

    monkeypatch.setattr(phase0_runner, "verify_turn", _stem_verifier(canned))
    monkeypatch.setattr(phase0_runner, "add_case", ingester)


def _dir_writing_ingester(corpus_dir, *, source_trace_id, target_turn_index, **kwargs) -> Path:
    """A stand-in for `add_case` that WRITES: it creates the case directory it returns.

    Deliberately does not write `case.json`, so `_load_scored_cases`' `*/case.json` glob
    still scores an empty corpus and the CLI's exit code stays about the flag under test
    rather than about a synthetic case failing to load.
    """
    case_dir = Path(corpus_dir) / f"{source_trace_id}-turn{target_turn_index}"
    case_dir.mkdir(parents=True)
    (case_dir / "trace.jsonl").write_text("", encoding="utf-8")
    return case_dir


def _unaddable_ingester(corpus_dir, **kwargs) -> Path:
    """The real `add_case`'s "this turn could not be added" shape: a `ValueError`."""
    raise ValueError("no restorable pre-state for this turn")


def _case_dirs(corpus_dir: Path) -> list[str]:
    """Every case directory name under `corpus_dir`; `[]` when the directory is absent."""
    if not corpus_dir.is_dir():
        return []
    return sorted(p.name for p in corpus_dir.iterdir() if p.is_dir())


def _run(trace_dir: Path, corpus_dir: Path, ledger_path: Path, *extra: str) -> int:
    return cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(corpus_dir),
            "--ledger", str(ledger_path),
            *extra,
            "--server", "irrelevant",
        ]
    )


def _instance(ledger_path: Path):
    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    assert len(ledger.instances) == 1, ledger.instances
    return ledger.instances[0]


# --- (1) the flag writes no case directory, and changes no count -----------------------


def test_no_ingest_writes_no_case_dirs(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    fail_path = _write_trace(trace_dir, "fail_tool", 3)
    canned = {
        fail_path.stem: [
            _verdict(0, Status.FAIL),
            _verdict(1, Status.PASS),
            _verdict(2, Status.FAIL),
        ]
    }
    _patch_seam(monkeypatch, canned, ingester=_dir_writing_ingester)

    ingesting_corpus = tmp_path / "corpus-ingesting"
    ingesting_ledger = tmp_path / "ingesting.json"
    rc = _run(trace_dir, ingesting_corpus, ingesting_ledger)
    out = capsys.readouterr().out
    assert rc == 0, out
    # The fixture is only meaningful if the ingesting run really does write.
    assert _case_dirs(ingesting_corpus) == [
        f"{fail_path.stem}-turn0",
        f"{fail_path.stem}-turn2",
    ], _case_dirs(ingesting_corpus)

    quiet_corpus = tmp_path / "corpus-quiet"
    quiet_ledger = tmp_path / "quiet.json"
    rc = _run(trace_dir, quiet_corpus, quiet_ledger, "--no-ingest")
    out = capsys.readouterr().out
    assert rc == 0, out

    assert _case_dirs(quiet_corpus) == [], _case_dirs(quiet_corpus)

    ingesting = _instance(ingesting_ledger)
    quiet = _instance(quiet_ledger)
    assert quiet.flagged_turns == ingesting.flagged_turns == [0, 2]
    assert quiet.turn_status_counts == ingesting.turn_status_counts
    assert quiet.disposition is ingesting.disposition


# --- (2) THE HONESTY TEST: the report states that ingestion was disabled ---------------


def test_no_ingest_is_stated_in_the_report(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}
    _patch_seam(monkeypatch, canned, ingester=_dir_writing_ingester)

    rc = _run(trace_dir, tmp_path / "corpus-quiet", tmp_path / "quiet.json", "--no-ingest")
    quiet_out = capsys.readouterr().out
    assert rc == 0, quiet_out

    # An empty flagged-addable list must be labeled NOT ATTEMPTED, or it reads as
    # "nothing could be added" — the exact misreading the flag would otherwise create.
    assert "--no-ingest" in quiet_out, quiet_out
    assert "NOT ATTEMPTED" in quiet_out, quiet_out
    # The flagged turn is still reported: the flag suppresses writes, never detection.
    assert "violation rate = 1/1" in quiet_out, quiet_out

    rc = _run(trace_dir, tmp_path / "corpus-ingesting", tmp_path / "ingesting.json")
    ingesting_out = capsys.readouterr().out
    assert rc == 0, ingesting_out

    # And the line is conditional: an ingesting run must not claim ingestion was disabled.
    assert "--no-ingest" not in ingesting_out, ingesting_out
    assert "NOT ATTEMPTED" not in ingesting_out, ingesting_out


# --- (3) a skipped turn is not an unaddable turn ---------------------------------------


def test_no_ingest_does_not_populate_flagged_unaddable(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}
    _patch_seam(monkeypatch, canned, ingester=_unaddable_ingester)

    ingesting_ledger = tmp_path / "ingesting.json"
    rc = _run(trace_dir, tmp_path / "corpus-ingesting", ingesting_ledger)
    out = capsys.readouterr().out
    assert rc == 0, out
    # The fixture is only meaningful if an ATTEMPTED ingest really does bucket as unaddable.
    ingesting = _instance(ingesting_ledger)
    assert [entry["turn"] for entry in ingesting.flagged_unaddable] == [0]

    quiet_ledger = tmp_path / "quiet.json"
    rc = _run(trace_dir, tmp_path / "corpus-quiet", quiet_ledger, "--no-ingest")
    out = capsys.readouterr().out
    assert rc == 0, out

    quiet = _instance(quiet_ledger)
    # Never attempted is not "attempted and failed": the turn keeps its real FAIL and its
    # place in the numerator, and appears in NEITHER ingest bucket.
    assert quiet.flagged_unaddable == []
    assert quiet.flagged_addable == []
    assert quiet.flagged_turns == [0]
