"""Phase-0 batch runner: walk traces, verify each turn, classify the instance disposition.

`run_batch` is the driver Task 1's `RunLedger` and Task 2's report exist to be filled and
rendered by: for each trace file in a directory, verify every `tools/call` turn, ingest the
FAILing ones into the corpus, and fold the outcome into one `InstanceRecord`.

Every test here injects a FAKE verifier (never `verify_turn`, never Seatbelt) — capture,
correlation and `tool_calls` are the only real machinery exercised, and those are pure and
cross-platform. The fake verifier is keyed by the trace's stem (read back off
`manifest_dir`'s name, which `default_manifest_dir_for` derives deterministically from the
trace path), so each written trace can be given its own canned verdict script without
depending on capture order or randomness.

The ingester is faked too, EXCEPT in the last two tests, which drive the REAL
`belay.corpus.add.add_case`. They have to: the property they pin is that a corpus
COLLISION — a case id already on disk — cannot turn its instance into `ERRORED` and so
cannot shrink `violation_denominator()` and fabricate an `INSTRUMENT SUSPECT`, i.e. a fake
PIVOT. That property is a contract BETWEEN two modules (`add_case`'s exception type and
`_verify_one_trace`'s `except ValueError`), and a hand-built `ValueError` from a fake
ingester would assert the contract it is supposed to be testing. Real `add_case` is still
platform-independent here — it composes a case out of a synthetic manifest and a fake
pre-state tree, exactly as `tests/test_corpus_add.py` does, and never restores anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.corpus.add import add_case
from belay.phase0.ledger import Disposition
from belay.phase0.report import instrument_suspect
from belay.phase0.runner import default_manifest_dir_for, run_batch
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

CAPTURED_AT = "2026-07-18T00:00:00+00:00"


# --- synthetic trace + canned-verdict apparatus ---------------------------------------


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


def _verdict(n: int, status: Status, *, cause: str | None = None) -> TurnVerdict:
    """A canned `TurnVerdict`: UNVERIFIED carries a cause, everything else one sub-verdict."""
    if status is Status.UNVERIFIED:
        return TurnVerdict(
            turn_index=n, tool_name="t", status=status, sub_verdicts=[], cause=cause or "unknown"
        )
    return TurnVerdict(
        turn_index=n,
        tool_name="t",
        status=status,
        sub_verdicts=[Verdict("A2", "replay", status, None, None, "canned")],
        cause=None,
    )


def _stem_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier keyed by the trace's stem, read back off `manifest_dir`'s name.

    `default_manifest_dir_for` names the manifest dir `<stem>.manifests`; this fake reverses
    that convention rather than hard-coding a second one, so it stays true to what the real
    seam actually passes through.
    """

    def verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _noop_ingester(corpus_dir, **kwargs) -> Path:
    return Path(corpus_dir) / "unused-case"


# --- (1) four traces, four dispositions, disciplined denominator -----------------------


def test_four_traces_four_dispositions_and_violation_denominator(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"

    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    unverifiable_path = _write_trace(trace_dir, "unverified_tool", 1)
    corrupt_path = trace_dir / "trace-corrupt-broken.jsonl"
    corrupt_path.write_text("not json at all\n", encoding="utf-8")

    canned = {
        fail_path.stem: [_verdict(0, Status.FAIL)],
        clean_path.stem: [_verdict(0, Status.PASS)],
        unverifiable_path.stem: [_verdict(0, Status.UNVERIFIED, cause="timeout")],
    }

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=_noop_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert len(ledger.instances) == 4
    assert by_id[fail_path.stem].disposition is Disposition.VERIFIED_FLAGGED
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN
    assert by_id[unverifiable_path.stem].disposition is Disposition.NO_VERIFIABLE_TURNS
    assert by_id[corrupt_path.stem].disposition is Disposition.ERRORED
    assert by_id[corrupt_path.stem].error is not None
    # ERRORED carries no counts.
    assert by_id[corrupt_path.stem].turn_status_counts == {}
    assert by_id[corrupt_path.stem].flagged_turns == []

    # Only the two VERIFIED_* instances count toward the violation denominator.
    assert ledger.violation_denominator() == 2
    assert ledger.violating_instances() == 1


# --- (2) a FAIL turn whose fake ingester succeeds ---------------------------------------


def test_flagged_turn_ingest_success_is_flagged_addable_and_ingester_called_correctly(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}

    calls: list[dict] = []

    def fake_ingester(corpus_dir_arg, **kwargs) -> Path:
        calls.append(kwargs)
        return Path(corpus_dir_arg) / "case-1"

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=fake_ingester,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.flagged_turns == [0]
    assert inst.flagged_addable == [0]
    assert inst.flagged_unaddable == []

    assert len(calls) == 1
    call = calls[0]
    assert call["human_label"] == "pending"
    assert call["target_turn_index"] == 0
    assert call["source_trace_id"] == fail_path.stem
    assert call["captured_at"] == CAPTURED_AT
    assert call["verdict"].status is Status.FAIL


# --- (3) a FAIL turn whose fake ingester raises ValueError ------------------------------


def test_flagged_turn_ingest_value_error_stays_flagged_and_unaddable_batch_continues(
    tmp_path,
) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    canned = {
        fail_path.stem: [_verdict(0, Status.FAIL)],
        clean_path.stem: [_verdict(0, Status.PASS)],
    }

    def raising_ingester(corpus_dir_arg, **kwargs) -> Path:
        raise ValueError("no restorable pre-state")

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=raising_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    flagged = by_id[fail_path.stem]
    assert flagged.disposition is Disposition.VERIFIED_FLAGGED
    assert flagged.flagged_turns == [0]
    assert flagged.flagged_addable == []
    assert flagged.flagged_unaddable == [{"turn": 0, "cause": "no restorable pre-state"}]

    # Still a violation, even though it could not be ingested as a corpus case.
    assert ledger.violating_instances() == 1
    assert ledger.violation_denominator() == 2

    # The batch continued: the other trace was still processed correctly.
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN


# --- (4) a corrupt trace file never aborts the batch ------------------------------------


def test_corrupt_trace_is_errored_other_traces_still_processed(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    clean_path = _write_trace(trace_dir, "pass_tool", 1)
    corrupt_path = trace_dir / "trace-corrupt-9999.jsonl"
    corrupt_path.write_text("{not valid json\n", encoding="utf-8")

    canned = {clean_path.stem: [_verdict(0, Status.PASS)]}

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=_noop_ingester,
    )

    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert by_id[corrupt_path.stem].disposition is Disposition.ERRORED
    assert isinstance(by_id[corrupt_path.stem].error, str)
    assert by_id[corrupt_path.stem].error
    assert by_id[clean_path.stem].disposition is Disposition.VERIFIED_CLEAN


# --- (5) one PASS + several UNVERIFIED is VERIFIED_CLEAN, causes tallied ---------------


def test_one_pass_and_several_unverified_is_clean_with_causes_tallied(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    path = _write_trace(trace_dir, "mixed_tool", 3)
    canned = {
        path.stem: [
            _verdict(0, Status.PASS),
            _verdict(1, Status.UNVERIFIED, cause="timeout"),
            _verdict(2, Status.UNVERIFIED, cause="timeout"),
        ]
    }

    def failing_ingester(corpus_dir_arg, **kwargs) -> Path:
        raise AssertionError("no FAIL turn exists; ingester must not be called")

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=failing_ingester,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_CLEAN
    assert inst.turn_status_counts == {"PASS": 1, "UNVERIFIED": 2}
    assert inst.unverified_causes == {"timeout": 2}
    assert inst.flagged_turns == []


# --- (6) captured_at passed through verbatim; the runner reads no clock ----------------


def test_captured_at_passed_through_verbatim(tmp_path) -> None:
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    fail_path = _write_trace(trace_dir, "fail_tool", 1)
    canned = {fail_path.stem: [_verdict(0, Status.FAIL)]}

    seen: list[str] = []

    def fake_ingester(corpus_dir_arg, **kwargs) -> Path:
        seen.append(kwargs["captured_at"])
        return Path(corpus_dir_arg) / "case"

    custom_captured_at = "1999-01-01T00:00:00+00:00"
    run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=custom_captured_at,
        verifier=_stem_verifier(canned),
        ingester=fake_ingester,
    )

    # The exact string passed in, byte for byte -- never re-derived, never a clock read.
    assert seen == [custom_captured_at]


# --- a gated trace the REAL add_case can ingest ----------------------------------------
#
# `add_case` needs two things the apparatus above does not produce: a `present`
# `state_handle` on the target `tools/call`, and a persisted snapshot manifest for that
# handle under `default_manifest_dir_for(trace)`. Both are synthetic — a hand-written
# manifest and a fake pre-state tree, the platform-independent fixture
# `tests/test_corpus_add.py` already uses — so these tests exercise case COMPOSITION (pure
# filesystem work) and never Seatbelt or a real restore.

PRESTATE_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)


def _write_gated_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """`_write_trace` plus a per-turn `state_handle`, and the `.manifests` sibling to match.

    Turn `i` carries handle `H{i}`, and every handle gets its OWN fake tree, so turn 0's
    pre-state is a distinct baseline from the target turn's and a case on a non-zero turn
    really writes the `task_manifest.json` / `task_prestate/` pair. Trees live under a
    `<stem>.trees` sibling so two traces in one directory cannot collide.
    """
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            call = _call_frame(call_id, tool)
            writer.set_state_handle({"status": "present", "handle": f"H{i}"}, frame=call)
            writer.observer("c2s")(call, False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    trace_path = writer.path

    manifest_dir = default_manifest_dir_for(trace_path)
    manifest_dir.mkdir(parents=True)
    trees = trace_dir / (trace_path.stem + ".trees")
    for i in range(n_calls):
        tree = trees / f"H{i}"
        (tree / "tests").mkdir(parents=True)
        (tree / "tests" / "test_auth.py").write_text(PRESTATE_BODY, encoding="utf-8")
        (manifest_dir / f"H{i}.json").write_text(
            json.dumps(
                {
                    "handle": f"H{i}",
                    "tree_path": str(tree),
                    "backend": "clonefile",
                    "capabilities": ["dir-mtimes", "hardlinks", "setuid"],
                    "fidelity_gaps": [],
                    "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return trace_path


def _records_of(trace_path: Path) -> list[dict]:
    """The trace's records, read straight off disk (the shape `add_case` takes)."""
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def _run_with_real_ingester(trace_dir: Path, corpus_dir: Path, canned: dict):
    """`run_batch` with the fake stem-keyed verifier and the REAL `add_case` as ingester."""
    return run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=add_case,
    )


# --- (7) a corpus collision does not ERROR the instance ---------------------------------


def test_collision_does_not_error_the_instance(tmp_path) -> None:
    """A case id already on disk costs the CASE, never the instance's verified outcome.

    Before `CaseExistsError`, the collision surfaced as `FileExistsError` — not a
    `ValueError`, so `_verify_one_trace`'s per-turn handler missed it, it escaped to
    `run_batch`'s catch-all, and the WHOLE instance became `ERRORED`: every turn's counts
    discarded and the instance dropped from `violation_denominator()`. The violation was
    real and observed; only the corpus write failed. This pins that separation.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    trace_path = _write_gated_trace(trace_dir, "edit_file", 2)
    canned = {trace_path.stem: [_verdict(0, Status.PASS), _verdict(1, Status.FAIL)]}

    # Pre-seed the corpus with EXACTLY the case the run is about to try to ingest, carrying
    # a human label — the thing a re-add must never be able to overwrite.
    add_case(
        corpus_dir,
        records=_records_of(trace_path),
        target_turn_index=1,
        verdict=_verdict(1, Status.FAIL),
        manifest_dir=default_manifest_dir_for(trace_path),
        server_command=["irrelevant"],
        invariants=[],
        human_label="true-positive",
        replays=3,
        timeout=20.0,
        source_trace_id=trace_path.stem,
        captured_at=CAPTURED_AT,
    )
    case_id = f"{trace_path.stem}-turn1"
    assert (corpus_dir / case_id).is_dir()

    ledger = _run_with_real_ingester(trace_dir, corpus_dir, canned)

    assert len(ledger.instances) == 1
    inst = ledger.instances[0]
    assert inst.disposition is Disposition.VERIFIED_FLAGGED
    assert inst.error is None
    # Fully populated, not the empty counts an ERRORED instance carries.
    assert inst.turn_status_counts == {"PASS": 1, "FAIL": 1}
    assert inst.flagged_turns == [1]
    assert inst.flagged_addable == []
    assert len(inst.flagged_unaddable) == 1, inst.flagged_unaddable
    entry = inst.flagged_unaddable[0]
    assert entry["turn"] == 1
    # The cause names the collision AND the case id, so an operator can act on it.
    assert "already exists" in entry["cause"], entry["cause"]
    assert case_id in entry["cause"], entry["cause"]

    # The denominator is untouched: this instance was verified, and it still counts.
    assert ledger.violation_denominator() == 1
    assert ledger.violating_instances() == 1
    assert ledger.errored_count() == 0
    assert instrument_suspect(ledger) is False


# --- (8) re-running a measurement cannot shrink its own denominator ---------------------


def test_rerun_preserves_denominator_and_violating_set(tmp_path) -> None:
    """Two `run_batch` invocations over the same traces AND the same corpus agree exactly.

    The anti-fake-PIVOT property, end to end. Run 1 ingests the flagged turn; run 2 hits
    every case it already wrote. If a collision could ERROR an instance, run 2's denominator
    would be smaller than run 1's — and a small enough denominator trips
    `instrument_suspect()`, which reads as "the instrument captured nothing", i.e. a PIVOT
    manufactured by nothing but re-running the measurement.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    flagged = _write_gated_trace(trace_dir, "edit_file", 2)
    clean = _write_gated_trace(trace_dir, "read_file", 1)
    canned = {
        flagged.stem: [_verdict(0, Status.PASS), _verdict(1, Status.FAIL)],
        clean.stem: [_verdict(0, Status.PASS)],
    }

    first = _run_with_real_ingester(trace_dir, corpus_dir, canned)
    second = _run_with_real_ingester(trace_dir, corpus_dir, canned)

    assert first.violation_denominator() == 2
    assert second.violation_denominator() == first.violation_denominator()
    assert first.violating_instances() == 1
    assert second.violating_instances() == first.violating_instances()
    assert instrument_suspect(first) is False
    assert instrument_suspect(second) is False

    # Nothing else about the measurement moved either: same instances, same dispositions,
    # same per-turn counts, no errors on either pass.
    def shape(ledger):
        return [
            (inst.trace_id, inst.disposition, inst.turn_status_counts, inst.flagged_turns)
            for inst in ledger.instances
        ]

    assert shape(second) == shape(first)
    assert [inst.error for inst in second.instances] == [None, None]

    # The ONE honest difference: run 1 stored the case, run 2 reported it as already stored.
    by_id_first = {inst.trace_id: inst for inst in first.instances}
    by_id_second = {inst.trace_id: inst for inst in second.instances}
    assert by_id_first[flagged.stem].flagged_addable == [1]
    assert by_id_first[flagged.stem].flagged_unaddable == []
    assert by_id_second[flagged.stem].flagged_addable == []
    assert len(by_id_second[flagged.stem].flagged_unaddable) == 1
    assert "already exists" in by_id_second[flagged.stem].flagged_unaddable[0]["cause"]
