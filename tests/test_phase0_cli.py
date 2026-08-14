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
import os
from pathlib import Path

from belay import __version__ as belay_version, cli
from belay.phase0.ledger import Disposition, from_json
from belay.trace import TraceWriter
from belay.verify.invariants import default_invariants
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


# --- (6) the ledger a run writes says WHICH detector produced it -----------------------


def test_phase0_run_records_the_detector_in_force(tmp_path, capsys, monkeypatch) -> None:
    """The ledger a run writes records the A1 rules that were actually in force.

    Without this the run's own output is the thing that cannot be dated: the four ledgers
    in `runs/` were produced by the REPLACED `tests/` read-only rule and read identically
    to one produced by today's `no-assertion-weakening`. The identity comes from the
    invariants the run resolved — not from a re-resolution, which could name a different
    policy than the one that decided the verdicts.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    ledger_path = tmp_path / "ledger.json"

    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})

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

    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    assert ledger.detector is not None
    assert ledger.detector.rules == tuple(
        (os.fsdecode(inv.scope), inv.rule) for inv in default_invariants()
    )
    # The RULES are recorded, so the report never says the detector itself is unrecorded.
    assert "detector: unrecorded" not in out, out
    assert "no-assertion-weakening" in out, out
    # And the CODE VERSION is recorded too. It was not, deliberately: `belay.__version__`
    # was a hardcoded `0.0.0` that had drifted from the real release, and stamping a version
    # known to be wrong is worse than recording none. `belay.__version__` now reads the
    # installed distribution, so there is a true answer to record.
    assert ledger.detector.version == belay_version
    assert ledger.detector.version != "0.0.0"
    assert "code version: unrecorded" not in out, out


def test_phase0_run_with_no_default_invariants_records_an_empty_detector(
    tmp_path, capsys, monkeypatch
) -> None:
    """`--no-default-invariants` records a detector with NO rules — recorded, not absent.

    "A1 was disabled for this run" and "nobody wrote down what A1 was" are different
    claims about the same 0% violation rate, and only one of them is a reason to distrust
    the number. Collapsing an empty rule list to `None` would render the first as the
    second.
    """
    trace_dir = tmp_path / "traces"
    ledger_path = tmp_path / "ledger.json"

    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--no-default-invariants",
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out

    ledger = from_json(json.loads(ledger_path.read_text(encoding="utf-8")))
    assert ledger.detector is not None
    assert ledger.detector.rules == ()
    assert "detector: unrecorded" not in out, out
    assert "A1 was disabled" in out, out


# --- (7) the `--shell-server` flag: one quoted string, shlex-split at the boundary -----


def _recording_run_batch(monkeypatch, seen: dict) -> None:
    """Wrap the REAL `run_batch` so the CLI->run_batch param path can be observed.

    The verifier/ingester seams stay patched as every test here patches them (no
    Seatbelt), so the run completes end to end; this only records the kwargs the CLI
    handed over.
    """
    import belay.phase0.runner as phase0_runner

    real_run_batch = phase0_runner.run_batch

    def recording_run_batch(*args, **kwargs):
        seen["shell_server_command"] = kwargs.get("shell_server_command", "<absent>")
        return real_run_batch(*args, **kwargs)

    monkeypatch.setattr(phase0_runner, "run_batch", recording_run_batch)


def test_phase0_run_shell_server_flag_reaches_run_batch(tmp_path, capsys, monkeypatch) -> None:
    """`--shell-server "node /abs/shell.js"` arrives at `run_batch` as the shlex-split list.

    The flag is a SINGLE string (argparse cannot host a second nargs=REMAINDER), so the
    split happens at the CLI boundary; `run_batch` receives the same list it would from
    the library API. The run still completes end to end over the patched seams.
    """
    trace_dir = tmp_path / "traces"
    ledger_path = tmp_path / "ledger.json"

    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})
    seen: dict = {}
    _recording_run_batch(monkeypatch, seen)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--shell-server", "node /abs/eval/servers/node_modules/mcp-server-commands/build/index.js",
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert seen["shell_server_command"] == [
        "node",
        "/abs/eval/servers/node_modules/mcp-server-commands/build/index.js",
    ]


def test_phase0_run_without_shell_server_flag_passes_none(tmp_path, capsys, monkeypatch) -> None:
    """Absent `--shell-server` -> `shell_server_command=None` -> today's behavior.

    The kwarg is present-but-None so the call site is explicit: a run with no shell axis
    is indistinguishable from one before the flag existed.
    """
    trace_dir = tmp_path / "traces"
    ledger_path = tmp_path / "ledger.json"

    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    _patch_seam(monkeypatch, {clean_path.stem: [_verdict(0, Status.PASS)]})
    seen: dict = {}
    _recording_run_batch(monkeypatch, seen)

    rc = cli.main(
        [
            "phase0", "run", str(trace_dir),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--server", "irrelevant",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert seen["shell_server_command"] is None
