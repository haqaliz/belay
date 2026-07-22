"""End-to-end R6 false-zero defense on the HARNESS -> `phase0 run` -> report path.

Card acceptance criterion #2: a mint whose captures have ~no verifiable turns must read as
`INSTRUMENT SUSPECT`, NOT as a clean 0% violation rate. This test proves that guard holds
across the *whole* chain the live mint actually walks — the real rename bridge
(`eval/minting_driver/bridge.py`), the real corpus runner (`belay.phase0.runner.run_batch`
with the real `verify_turn` + `add_case`, no fakes), the real scorer
(`belay.corpus.metrics.score`), and the real report (`belay.phase0.report.render_report`) —
not the report renderer in isolation (`test_phase0_report.py` already covers that unit).

## The crux, and why it needs no Seatbelt (so this test is CROSS-PLATFORM, not darwin-gated)

Each instance is a `bridge_capture` of a session that issued tool calls but snapshotted
nothing: a real `trace-*.jsonl` with `tools/call` turns, beside NO `<snapshots>.manifests/`
sibling. `bridge_capture` moves the trace and creates an EMPTY dest manifests dir (its honest
"the gate persisted nothing" branch, `bridge.py:144-149`) — exactly what the false-zero guard
must survive.

`run_batch` then verifies each turn with the REAL `verify_turn`. Confirmed by reading
`belay.replay.engine.replay_turn`: a `tools/call` frame with no `present` state handle (or a
`present` handle whose manifest is absent from the empty manifests dir) returns
`NOT_VERIFIABLE`/`UNVERIFIED` at engine.py:248-290 — every one of those early returns is
BEFORE `guarded_restore`/`_client_replay_turn` (engine.py:297+), the only code that touches
the macOS Seatbelt sandbox. Nothing is ever re-invoked, so no sandbox is needed and this test
runs everywhere, unlike the `present`-handle e2e in `test_phase0_e2e.py`.

Every turn therefore comes back UNVERIFIED, no turn is FAIL, so `add_case` is never called and
each instance is classified `NO_VERIFIABLE_TURNS`. The violation denominator (VERIFIED_CLEAN +
VERIFIED_FLAGGED only) is 0, `instrument_suspect` is True, and `render_report` prints the
`INSTRUMENT SUSPECT` block instead of any violation-rate headline.
"""

from __future__ import annotations

from pathlib import Path

from belay.corpus.metrics import score
from belay.phase0.ledger import Disposition
from belay.phase0.report import instrument_suspect, render_report
from belay.phase0.runner import run_batch
from belay.trace import TraceWriter
from eval.minting_driver.bridge import bridge_capture

CAPTURED_AT = "2026-07-22T00:00:00+00:00"

# `run_batch` forwards this to `verify_turn`, but a manifest-less turn early-returns from
# `replay_turn` before any server is ever spawned (see the module docstring), so this command
# is never executed. Named to make an accidental spawn loud in a traceback rather than silent.
UNUSED_SERVER_COMMAND = ["belay-server-never-spawned-in-this-test"]


def _tools_call_frame(call_id: int) -> bytes:
    import json

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _reply_frame(call_id: int) -> bytes:
    import json

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ).encode()


def _bridged_no_snapshot_instance(inst_root: Path, instance_id: str, batch_dir: Path) -> None:
    """Bridge one gated capture that issued a `tools/call` but snapshotted nothing.

    Builds the FROM layout the gated proxy would leave — a real `TraceWriter` trace with one
    `tools/call` turn (deliberately no `set_state_handle`, mirroring a session the gate never
    snapshotted) and a `snapshot_dir` whose `.manifests` sibling does NOT exist — then runs it
    through the REAL `bridge_capture` into `batch_dir`. The bridge moves the trace and creates
    an empty `trace-<id>.manifests/` dir, the honest NO_VERIFIABLE_TURNS input.
    """
    trace_dir = inst_root / "traces"
    snapshot_dir = inst_root / "snapshots"
    trace_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    # Deliberately NO `inst_root/snapshots.manifests` sibling: the gate persisted nothing.

    writer = TraceWriter.in_directory(trace_dir)
    try:
        writer.observer("c2s")(_tools_call_frame(10), False)
        writer.observer("s2c")(_reply_frame(10), False)
    finally:
        writer.close()

    bridge_capture(
        instance_id=instance_id,
        trace_dir=trace_dir,
        snapshot_dir=snapshot_dir,
        batch_dir=batch_dir,
    )


def test_short_denominator_batch_reports_instrument_suspect_not_zero_percent(tmp_path) -> None:
    """A bridged mint of no-verifiable-turn captures reads INSTRUMENT SUSPECT, never 0%.

    Real bridge -> real `run_batch` (real `verify_turn`/`add_case`) -> real `score` -> real
    `render_report`. Three instances, each a trace WITH a `tools/call` but no restorable
    pre-state, so every turn is UNVERIFIED and every instance is NO_VERIFIABLE_TURNS. The
    published report must therefore say INSTRUMENT SUSPECT and carry NO violation-rate line
    and no `0%` — the exact false-zero card acceptance #2 defends against.
    """
    batch_dir = tmp_path / "batch"
    corpus_dir = tmp_path / "corpus"

    instance_ids = ["django__django-11001", "django__django-11002", "django__django-11003"]
    for instance_id in instance_ids:
        _bridged_no_snapshot_instance(tmp_path / instance_id, instance_id, batch_dir)

    ledger = run_batch(
        batch_dir,
        corpus_dir=corpus_dir,
        server_command=UNUSED_SERVER_COMMAND,
        invariants=(),
        captured_at=CAPTURED_AT,
    )

    # The bridge->runner chain saw every instance, and each is honestly NO_VERIFIABLE_TURNS:
    # the tool call WAS observed (turn_status_counts is non-empty and all UNVERIFIED), not a
    # trace that silently held zero turns.
    assert len(ledger.instances) == len(instance_ids)
    for instance in ledger.instances:
        assert instance.disposition is Disposition.NO_VERIFIABLE_TURNS, instance
        assert instance.turn_status_counts == {"UNVERIFIED": 1}, instance
        assert instance.flagged_turns == [], instance

    # Nothing verifiable -> the violation denominator is empty and the instrument is suspect.
    assert ledger.violation_denominator() == 0
    assert instrument_suspect(ledger) is True

    metrics = score([])  # no FAIL turns -> no ingested cases -> an all-n/a Metrics
    report = render_report(ledger, metrics)

    assert "INSTRUMENT SUSPECT" in report
    # The false-zero teeth: the per-instance violation-rate HEADLINE is suppressed entirely,
    # so no misleading "0% of instances violated" can be read off an empty denominator.
    assert "violation rate =" not in report
    # But the guard is surgical, not a blanket zero-scrub: an honest per-turn FAIL rate with a
    # REAL denominator (0 FAILs across 3 examined turns) still prints, distinguishing "we
    # examined turns and none FAILed" from the suppressed "we had nothing verifiable to rate".
    assert "per-turn FAIL rate = 0/3 = 0.0%" in report
    assert "overall UNVERIFIED turn share = 3/3 = 100.0%" in report
