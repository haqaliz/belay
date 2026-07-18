"""`belay phase0 run` / `belay phase0 report` — the CLI over the Task-3 batch runner.

`run_batch` (Task 3) verifies every trace in a directory and folds the outcome into a
`RunLedger` (Task 1); `render_report` (Task 2) turns that ledger plus a scored corpus into
the human-readable violation-rate report. This is the CLI wiring: `phase0 run` drives
`run_batch`, persists the ledger as JSON, scores the corpus, and prints the report;
`phase0 report` re-renders that same report from a saved ledger with no replay at all.

Every test here monkeypatches `belay.phase0.runner.verify_turn` / `.add_case` — the module
attributes `run_batch`'s `verifier`/`ingester` seam is meant to be pointed at — so no
Seatbelt and no real replay ever runs. `cli.py` must look those symbols up off the
`belay.phase0.runner` module AT CALL TIME (not bind them as its own import-time default),
or a monkeypatch here would silently do nothing and every test would instead invoke the
real engine.

Load-bearing: test 5 (`phase0 run` exits 0 with violations present) is the whole point of
"measurement, not a gate" — the opposite exit code here would be exactly the false-failure
mode the brief calls out by name.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay import cli
from belay.phase0.ledger import Disposition, from_json
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


# --- synthetic trace + canned-verdict apparatus (mirrors tests/test_phase0_runner.py) ---


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


def _noop_ingester(corpus_dir, **kwargs) -> Path:
    return Path(corpus_dir) / "unused-case"


def _patch_seam(monkeypatch, canned: dict[str, list[TurnVerdict]], ingester=_noop_ingester) -> None:
    """Point `belay.phase0.runner`'s verifier/ingester seam at fakes, no Seatbelt involved."""
    import belay.phase0.runner as phase0_runner

    monkeypatch.setattr(phase0_runner, "verify_turn", _stem_verifier(canned))
    monkeypatch.setattr(phase0_runner, "add_case", ingester)


# --- (1) `phase0 run`: writes a round-tripping ledger, prints the report, exit 0 --------


def test_phase0_run_writes_ledger_and_prints_report(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    ledger_path = tmp_path / "ledger.json"

    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    canned = {
        fail_path.stem: [_verdict(0, Status.FAIL)],
        clean_path.stem: [_verdict(0, Status.PASS)],
    }
    _patch_seam(monkeypatch, canned)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(corpus_dir),
            "--ledger", str(ledger_path),
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out

    # The ledger file round-trips through from_json.
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger = from_json(data)
    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert by_id[fail_path.stem].disposition is Disposition.VERIFIED_FLAGGED
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN

    # The printed report carries the violation-rate denominator (never the bare instrument
    # -suspect case here, since one instance was actually verified clean).
    assert "violation rate = 1/2" in out, out
    assert "VERIFIED_FLAGGED: 1" in out, out
    assert "VERIFIED_CLEAN: 1" in out, out


# --- (2) a malformed --invariants file is fail-closed: exit 2 --------------------------


def test_phase0_run_malformed_invariants_file_is_fail_closed(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    ledger_path = tmp_path / "ledger.json"
    inv_file = tmp_path / "bad.json"
    inv_file.write_text("{ not valid json", encoding="utf-8")

    def unreachable_verifier(*args, **kwargs):
        raise AssertionError("run_batch must never be reached with a malformed --invariants file")

    _patch_seam(monkeypatch, {}, ingester=unreachable_verifier)
    import belay.phase0.runner as phase0_runner
    monkeypatch.setattr(phase0_runner, "verify_turn", unreachable_verifier)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--ledger", str(ledger_path),
            "--invariants", str(inv_file),
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert not ledger_path.exists()


# --- (3) a missing trace-dir is fail-closed: exit 2 ------------------------------------


def test_phase0_run_missing_trace_dir_is_fail_closed(tmp_path, capsys) -> None:
    missing = tmp_path / "does-not-exist"
    ledger_path = tmp_path / "ledger.json"

    rc = cli.main(
        ["phase0", "run", str(missing), "--ledger", str(ledger_path), "--server", "irrelevant"]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
    assert not ledger_path.exists()


# --- (4) `phase0 report` re-renders deterministically; a bad ledger is fail-closed -----


def test_phase0_report_rerenders_the_same_report_as_run(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    ledger_path = tmp_path / "ledger.json"

    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}
    _patch_seam(monkeypatch, canned)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(corpus_dir),
            "--ledger", str(ledger_path),
            "--server", "irrelevant",
        ]
    )
    run_out = capsys.readouterr().out
    assert rc == 0, run_out

    rc2 = cli.main(["phase0", "report", str(ledger_path), "--corpus-dir", str(corpus_dir)])
    report_out = capsys.readouterr().out
    assert rc2 == 0, report_out

    assert report_out == run_out, (report_out, run_out)


def test_phase0_report_missing_ledger_is_fail_closed(tmp_path, capsys) -> None:
    missing = tmp_path / "no-such-ledger.json"

    rc = cli.main(["phase0", "report", str(missing)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out


def test_phase0_report_corrupt_ledger_is_fail_closed(tmp_path, capsys) -> None:
    corrupt = tmp_path / "corrupt-ledger.json"
    corrupt.write_text("{ not valid json", encoding="utf-8")

    rc = cli.main(["phase0", "report", str(corrupt)])
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out


# --- (5) `phase0 run` exits 0 EVEN WITH violations present: measurement, not a gate ----


def test_phase0_run_exits_zero_with_violations_present(tmp_path, capsys, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    ledger_path = tmp_path / "ledger.json"

    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}
    _patch_seam(monkeypatch, canned)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(corpus_dir),
            "--ledger", str(ledger_path),
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out

    # A ledger FULL of flagged violations still exits 0 — this is a measurement, not a gate.
    assert rc == 0, out
    assert "violation rate = 1/1" in out, out

    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger = from_json(data)
    assert ledger.violating_instances() == 1
