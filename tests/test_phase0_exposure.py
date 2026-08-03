"""A1 exposure accounting through the ledger: absent survives, because zero is a finding.

Task 1 (`invariants.py`) made the `no-assertion-weakening` content rule write
`expected["exposure"]` — `{"compared": N, "in_scope": M}`, or a partial `{"in_scope": M}`
on the file-budget abstain, or nothing at all on the five early abstains and on every
`read-only` path. This module carries that fact from the per-turn `Verdict` through
`phase0`'s runner into `InstanceRecord`, its JSON, and the run-level `RunLedger`
accessor, with ABSENCE intact throughout.

The one decision every test here protects: `files_compared == 0` is a REAL, MEASURED
finding (the rule was given nothing to judge), and MUST NOT be confused with
`exposure is None` (this ledger — or this instance, or this turn — never recorded
exposure at all, because it predates the field or A1 never ran). Collapsing the two
would let every ledger written before this aspect read as "the detector judged nothing",
fabricating the exact finding this unit exists to establish honestly. This mirrors the
`detector` field's pattern (`ledger.py:65-72, 228-239, 329-332`), NOT `not_covered_turns`'s
(`ledger.py:57-63`, which collapses absent into `{}` and survives only because the report
refuses to claim either reading).
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.phase0.ledger import (
    Disposition,
    InstanceRecord,
    RunLedger,
    _REQUIRED_INSTANCE_FIELDS,
    from_json,
    to_json,
)
from belay.phase0.runner import run_batch
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURED_AT = "2026-08-03T00:00:00+00:00"


# --- helpers -----------------------------------------------------------------------------


def _instance(trace_id: str, disposition: Disposition, **kwargs) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=kwargs.pop("turn_status_counts", {}),
        flagged_turns=kwargs.pop("flagged_turns", []),
        flagged_addable=kwargs.pop("flagged_addable", []),
        flagged_unaddable=kwargs.pop("flagged_unaddable", []),
        unverified_causes=kwargs.pop("unverified_causes", {}),
        error=kwargs.pop("error", None),
        **kwargs,
    )


def _a1_verdict(status: Status, expected: dict) -> Verdict:
    return Verdict("A1", "invariant", status, observed=None, expected=expected, message="m")


def _a2_verdict(status: Status = Status.PASS) -> Verdict:
    return Verdict("A2", "replay", status, observed=None, expected=None, message="m")


# --- (4/5) the absent-vs-zero boundary, on a real old-ledger shape -----------------------


def test_ledger_without_exposure_key_loads_and_reads_unrecorded() -> None:
    """A real old-ledger instance JSON, shaped like `runs/s2.json`, has NO `exposure` key.

    Loading it must never coerce that absence to `0` or `{}` — the ledger predates the
    field entirely, and reading it as "the rule compared zero files" would fabricate a
    finding nobody measured.
    """
    payload = json.loads((FIXTURES / "phase0_ledger_no_exposure.json").read_text())

    ledger = from_json(payload)

    assert len(ledger.instances) == 1
    assert ledger.instances[0].exposure is None


def test_to_json_omits_exposure_when_unrecorded() -> None:
    """`to_json` never writes `"exposure"` at all when it is unrecorded -- asserted on BYTES.

    `null` and absent are indistinguishable after loading back through `from_json`, so this
    test inspects the serialized JSON text directly, not the round-tripped object.
    """
    ledger = RunLedger(instances=[_instance("trace-x", Disposition.VERIFIED_CLEAN)])

    rendered = json.dumps(to_json(ledger))

    assert "exposure" not in rendered


def test_zero_exposure_and_unrecorded_are_distinguishable_after_a_roundtrip() -> None:
    """A real zero (`files_compared: 0`, exposure WAS recorded) survives distinctly from
    `exposure is None` (never recorded) through a full `to_json` / `from_json` round-trip.
    """
    recorded_zero = _instance(
        "trace-recorded-zero",
        Disposition.VERIFIED_CLEAN,
        exposure={"files_compared": 0, "turns_judging": 0, "turns_recorded": 1},
    )
    unrecorded = _instance("trace-unrecorded", Disposition.VERIFIED_CLEAN)
    ledger = RunLedger(instances=[recorded_zero, unrecorded])

    rebuilt = from_json(to_json(ledger))

    by_id = {inst.trace_id: inst for inst in rebuilt.instances}
    assert by_id["trace-recorded-zero"].exposure == {
        "files_compared": 0,
        "turns_judging": 0,
        "turns_recorded": 1,
    }
    assert by_id["trace-unrecorded"].exposure is None


# --- (6) never a required field -----------------------------------------------------------


def test_exposure_is_not_a_required_field() -> None:
    """`exposure` is absent from `_REQUIRED_INSTANCE_FIELDS`, and loading without it is fine."""
    assert "exposure" not in _REQUIRED_INSTANCE_FIELDS

    payload = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "VERIFIED_CLEAN",
                "turn_status_counts": {},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
                # "exposure" deliberately omitted
            }
        ]
    }

    ledger = from_json(payload)

    assert ledger.instances[0].exposure is None


# --- exposure never pollutes turn_status_counts / total_turns() --------------------------


def test_exposure_is_not_in_turn_status_counts_and_total_turns_is_unchanged() -> None:
    """A recorded exposure dict never leaks a key into `turn_status_counts`, and the FAIL
    rate's denominator (`total_turns()`) sums exactly the same as before this field existed.
    """
    inst = _instance(
        "trace-x",
        Disposition.VERIFIED_CLEAN,
        turn_status_counts={"PASS": 3, "FAIL": 1},
        exposure={"files_compared": 5, "turns_judging": 2, "turns_recorded": 4},
    )
    ledger = RunLedger(instances=[inst])

    assert "exposure" not in inst.turn_status_counts
    assert set(inst.turn_status_counts) == {"PASS", "FAIL"}
    assert ledger.total_turns() == 4


# --- runner: the accumulator (`_verify_one_trace`) ----------------------------------------


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
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            writer.observer("c2s")(_call_frame(call_id, tool), False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    return writer.path


def _stem_verifier(canned: dict[str, list[TurnVerdict]]):
    def verifier(records, n, *, server_command, manifest_dir, invariants, replays, timeout):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _noop_ingester(corpus_dir, **kwargs) -> Path:
    return Path(corpus_dir) / "unused-case"


def test_runner_accumulates_exposure_from_a1_subverdicts_across_turns(tmp_path) -> None:
    """Files compared and turns judged are summed PER TURN across the whole instance.

    Turn 0: two A1 sub-verdicts (two scoped invariants, "tests" and "testing"), each
    carrying `{"compared": N, "in_scope": M}` -- both contribute to the SAME turn's tally.
    Turn 1: one A1 PASS with `{"compared": 0, "in_scope": 0}` (nothing in scope) --
    recorded, but does not count toward `turns_judging`.
    Turn 2: no A1 sub-verdict at all (only A2) -- contributes nothing.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    trace_path = _write_trace(trace_dir, "edit_file", 3)

    turn0 = TurnVerdict(
        turn_index=0,
        tool_name="edit_file",
        status=Status.PASS,
        sub_verdicts=[
            _a2_verdict(),
            _a1_verdict(Status.PASS, {"rule": "no-assertion-weakening", "scope": "tests",
                                       "turn": 0, "exposure": {"compared": 2, "in_scope": 2}}),
            _a1_verdict(Status.PASS, {"rule": "no-assertion-weakening", "scope": "testing",
                                       "turn": 0, "exposure": {"compared": 1, "in_scope": 1}}),
        ],
    )
    turn1 = TurnVerdict(
        turn_index=1,
        tool_name="edit_file",
        status=Status.PASS,
        sub_verdicts=[
            _a2_verdict(),
            _a1_verdict(Status.PASS, {"rule": "no-assertion-weakening", "scope": "tests",
                                       "turn": 1, "exposure": {"compared": 0, "in_scope": 0}}),
        ],
    )
    turn2 = TurnVerdict(
        turn_index=2,
        tool_name="edit_file",
        status=Status.PASS,
        sub_verdicts=[_a2_verdict()],
    )
    canned = {trace_path.stem: [turn0, turn1, turn2]}

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier(canned),
        ingester=_noop_ingester,
    )

    inst = ledger.instances[0]
    assert inst.exposure == {"files_compared": 3, "turns_judging": 1, "turns_recorded": 2}


def test_runner_records_no_exposure_when_a1_never_ran(tmp_path) -> None:
    """No turn's sub-verdicts ever carry an `"exposure"` key -> the instance's exposure is
    `None`, never a fabricated `{"files_compared": 0, ...}`.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    trace_path = _write_trace(trace_dir, "read_file", 1)
    canned = {
        trace_path.stem: [
            TurnVerdict(
                turn_index=0,
                tool_name="read_file",
                status=Status.PASS,
                sub_verdicts=[_a2_verdict()],
            )
        ]
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

    assert ledger.instances[0].exposure is None


def test_runner_partial_exposure_dict_without_compared_key_is_recorded_but_contributes_no_files(
    tmp_path,
) -> None:
    """The file-budget abstain's `{"in_scope": M}` (no `compared` key) is a recorded fact
    -- `turns_recorded` counts it -- but must not be coerced into a fabricated `compared`,
    so it contributes zero to `files_compared` and never to `turns_judging`.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    trace_path = _write_trace(trace_dir, "edit_many", 1)
    canned = {
        trace_path.stem: [
            TurnVerdict(
                turn_index=0,
                tool_name="edit_many",
                status=Status.UNVERIFIED,
                sub_verdicts=[
                    _a1_verdict(
                        Status.UNVERIFIED,
                        {
                            "rule": "no-assertion-weakening",
                            "scope": "tests",
                            "turn": 0,
                            "cause": "in-scope-file-budget-exceeded",
                            "exposure": {"in_scope": 600},
                        },
                    ),
                ],
                cause="in-scope-file-budget-exceeded",
            )
        ]
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

    inst = ledger.instances[0]
    assert inst.exposure == {"files_compared": 0, "turns_judging": 0, "turns_recorded": 1}


# --- ERRORED: exposure is unrecorded, never a fabricated zero ----------------------------


def test_errored_instance_reports_unrecorded_never_zero(tmp_path) -> None:
    """A trace that raises before verification even starts ERRORS the instance, and its
    exposure is `None` -- `{"files_compared": 0, ...}` there would assert the detector
    judged nothing, which is not what happened; nothing ran at all.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"
    corrupt_path = trace_dir / "trace-corrupt-broken.jsonl"
    trace_dir.mkdir(parents=True)
    corrupt_path.write_text("not json at all\n", encoding="utf-8")

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=["irrelevant"],
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_stem_verifier({}),
        ingester=_noop_ingester,
    )

    inst = ledger.instances[0]
    assert inst.disposition is Disposition.ERRORED
    assert inst.exposure is None


# --- RunLedger accessor, beside `not_covered_by_kind` -------------------------------------


def test_run_ledger_exposure_summary_merges_recorded_instances_and_counts_them() -> None:
    """`RunLedger.exposure_summary()` sums the per-instance dicts and counts how many
    instances actually recorded one -- instances with `exposure is None` are excluded from
    the sums AND from the count, mirroring the same absent-vs-zero discipline one level up.
    """
    a = _instance(
        "trace-a",
        Disposition.VERIFIED_CLEAN,
        exposure={"files_compared": 3, "turns_judging": 1, "turns_recorded": 2},
    )
    b = _instance(
        "trace-b",
        Disposition.VERIFIED_FLAGGED,
        exposure={"files_compared": 4, "turns_judging": 2, "turns_recorded": 2},
    )
    unrecorded = _instance("trace-c", Disposition.VERIFIED_CLEAN)
    ledger = RunLedger(instances=[a, b, unrecorded])

    summary = ledger.exposure_summary()

    assert summary == {
        "files_compared": 7,
        "turns_judging": 3,
        "turns_recorded": 4,
        "instances_recorded": 2,
    }


def test_run_ledger_exposure_summary_is_none_when_no_instance_recorded_one() -> None:
    """No instance ever recorded exposure -> the run-level summary is `None`, not a
    fabricated all-zero dict.
    """
    ledger = RunLedger(instances=[_instance("trace-a", Disposition.VERIFIED_CLEAN)])

    assert ledger.exposure_summary() is None
