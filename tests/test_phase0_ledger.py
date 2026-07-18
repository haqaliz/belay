"""Phase-0 run ledger: dispositions + denominator-disciplined counts.

The Phase-0 corpus run needs one honest number: the violation rate. That rate is a
fraction, and a fraction is only honest if its denominator is disciplined — instances
that never produced a verifiable turn, or that errored outright, must not silently
inflate (or deflate) either the numerator or the denominator. This module is pure data:
`Disposition` (mirroring `belay.verify.verdict.Status`'s `str`-mixin so it serializes as
its name), `InstanceRecord` (one corpus instance's outcome), and `RunLedger` (the whole
run, with derived-not-stored counts so they cannot drift out of sync with the records).

This file is written FIRST, before `src/belay/phase0/ledger.py` exists, per strict TDD.
"""

from __future__ import annotations

import pytest

from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger, from_json, to_json


def _instance(
    trace_id: str,
    disposition: Disposition,
    *,
    turn_status_counts: dict | None = None,
    flagged_turns: list | None = None,
    flagged_addable: list | None = None,
    flagged_unaddable: list | None = None,
    unverified_causes: dict | None = None,
    error: str | None = None,
) -> InstanceRecord:
    return InstanceRecord(
        trace_id=trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts or {},
        flagged_turns=flagged_turns or [],
        flagged_addable=flagged_addable or [],
        flagged_unaddable=flagged_unaddable or [],
        unverified_causes=unverified_causes or {},
        error=error,
    )


def _mixed_ledger() -> RunLedger:
    """One instance of each of the four dispositions, with populated counts."""
    clean = _instance(
        "trace-clean",
        Disposition.VERIFIED_CLEAN,
        turn_status_counts={"PASS": 3, "FAIL": 0, "WARN": 0, "UNVERIFIED": 1},
        unverified_causes={"no-restorable-prestate": 1},
    )
    flagged = _instance(
        "trace-flagged",
        Disposition.VERIFIED_FLAGGED,
        turn_status_counts={"PASS": 1, "FAIL": 2, "WARN": 0, "UNVERIFIED": 0},
        flagged_turns=[1, 3],
        flagged_addable=[1],
        flagged_unaddable=[{"turn": 3, "cause": "no-restorable-prestate"}],
        unverified_causes={},
    )
    no_verifiable = _instance(
        "trace-no-verifiable",
        Disposition.NO_VERIFIABLE_TURNS,
        turn_status_counts={"PASS": 0, "FAIL": 0, "WARN": 0, "UNVERIFIED": 0},
    )
    errored = _instance(
        "trace-errored",
        Disposition.ERRORED,
        error="sandbox snapshot restore failed: disk full",
    )
    return RunLedger(instances=[clean, flagged, no_verifiable, errored])


def test_disposition_has_exactly_four_members() -> None:
    """`Disposition` has exactly the four named members, no more, no fewer."""
    names = {member.name for member in Disposition}
    assert names == {
        "VERIFIED_CLEAN",
        "VERIFIED_FLAGGED",
        "NO_VERIFIABLE_TURNS",
        "ERRORED",
    }


def test_disposition_serializes_as_its_name() -> None:
    """`Disposition` is a `str` mixin, like `Status`: it serializes as its member name."""
    assert Disposition.VERIFIED_FLAGGED == "VERIFIED_FLAGGED"
    assert str(Disposition.VERIFIED_FLAGGED.value) == "VERIFIED_FLAGGED"
    assert isinstance(Disposition.VERIFIED_FLAGGED, str)


def test_denominator_and_counts_across_the_four_dispositions() -> None:
    """(1) violation_denominator/violating_instances/no_verifiable_count/errored_count."""
    ledger = _mixed_ledger()

    # Denominator excludes NO_VERIFIABLE_TURNS and ERRORED: only CLEAN + FLAGGED count.
    assert ledger.violation_denominator() == 2
    assert ledger.violating_instances() == 1
    assert ledger.no_verifiable_count() == 1
    assert ledger.errored_count() == 1


def test_total_turns_and_fail_turns_sum_across_instances() -> None:
    """(2) `total_turns()`/`fail_turns()` sum `turn_status_counts` across all instances."""
    ledger = _mixed_ledger()

    # clean: 3+0+0+1=4, flagged: 1+2+0+0=3, no_verifiable: 0, errored: 0 (empty dict)
    assert ledger.total_turns() == 7
    # FAIL counts: clean=0, flagged=2, no_verifiable=0, errored=0
    assert ledger.fail_turns() == 2


def test_unverified_by_cause_merges_across_instances() -> None:
    """(3) `unverified_by_cause()` sums per-bucket counts across every instance."""
    a = _instance(
        "trace-a",
        Disposition.VERIFIED_CLEAN,
        unverified_causes={"no-restorable-prestate": 2, "timeout": 1},
    )
    b = _instance(
        "trace-b",
        Disposition.VERIFIED_FLAGGED,
        unverified_causes={"no-restorable-prestate": 1, "sandbox-unsupported": 5},
    )
    ledger = RunLedger(instances=[a, b])

    assert ledger.unverified_by_cause() == {
        "no-restorable-prestate": 3,
        "timeout": 1,
        "sandbox-unsupported": 5,
    }


def test_json_round_trip_is_identity() -> None:
    """(4) `from_json(to_json(ledger)) == ledger` for a ledger covering every field."""
    ledger = _mixed_ledger()

    payload = to_json(ledger)
    rebuilt = from_json(payload)

    assert rebuilt == ledger


def test_to_json_renders_disposition_as_plain_string_name() -> None:
    """`to_json` output is JSON-able: dispositions appear as their bare string name."""
    ledger = _mixed_ledger()
    payload = to_json(ledger)

    rendered = [inst["disposition"] for inst in payload["instances"]]
    assert rendered == [
        "VERIFIED_CLEAN",
        "VERIFIED_FLAGGED",
        "NO_VERIFIABLE_TURNS",
        "ERRORED",
    ]
    assert all(isinstance(d, str) for d in rendered)


def test_from_json_rejects_unknown_disposition() -> None:
    """(5) An unknown disposition string raises a named `ValueError`, never a silent default."""
    payload = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "TOTALLY_MADE_UP",
                "turn_status_counts": {},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
            }
        ]
    }

    with pytest.raises(ValueError, match="TOTALLY_MADE_UP"):
        from_json(payload)


def test_from_json_rejects_missing_required_field() -> None:
    """(5) A missing required field raises a named `ValueError`, never a silent default."""
    payload = {
        "instances": [
            {
                "trace_id": "trace-x",
                "disposition": "VERIFIED_CLEAN",
                # "turn_status_counts" deliberately omitted
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
            }
        ]
    }

    with pytest.raises(ValueError, match="turn_status_counts"):
        from_json(payload)


def test_from_json_rejects_missing_instances_key() -> None:
    """A payload with no `instances` key at all is also a named `ValueError`."""
    with pytest.raises(ValueError, match="instances"):
        from_json({})
