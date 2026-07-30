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

import json
import os

import pytest

from belay.phase0.ledger import (
    DetectorIdentity,
    Disposition,
    InstanceRecord,
    RunLedger,
    from_json,
    to_json,
)


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


# --- Detector identity: what produced this ledger, or an honest "unrecorded" -----------


def test_detector_identity_round_trips() -> None:
    """A recorded detector survives `to_json`/`from_json` exactly — rules, scopes, version.

    The four ledgers in `runs/` were produced by the REPLACED `tests/` read-only rule and
    are indistinguishable, by reading them, from one produced by today's
    `no-assertion-weakening`. A ledger about to re-derive a published number must state
    what decided its verdicts, and a round-trip that dropped or reordered a rule would put
    a different detector's name on the same number.
    """
    detector = DetectorIdentity(
        rules=(("tests", "no-assertion-weakening"), ("testing", "no-assertion-weakening")),
        version="belay 0.10.0",
    )
    ledger = RunLedger(instances=_mixed_ledger().instances, detector=detector)

    rebuilt = from_json(to_json(ledger))

    assert rebuilt == ledger
    assert rebuilt.detector is not None
    assert rebuilt.detector.rules == (
        ("tests", "no-assertion-weakening"),
        ("testing", "no-assertion-weakening"),
    )
    assert rebuilt.detector.version == "belay 0.10.0"


def test_detector_identity_round_trips_a_non_utf8_scope() -> None:
    """A scope whose raw bytes are not UTF-8 round-trips LOSSLESSLY, never mangled.

    `Invariant.scope` is raw path BYTES on purpose (`invariants.py:106-115`), so the
    identity must carry `os.fsdecode`'s surrogate-escaped form — the same encoding
    `corpus/add.py:351` stores — and `os.fsencode` must recover the original bytes. A
    replacement-character round-trip would silently rename the scope a verdict was
    decided under.
    """
    scope = os.fsdecode(b"tests/\xff")
    ledger = RunLedger(
        instances=[],
        detector=DetectorIdentity(rules=((scope, "read-only"),), version=None),
    )

    payload = json.loads(json.dumps(to_json(ledger)))
    rebuilt = from_json(payload)

    assert rebuilt.detector is not None
    assert os.fsencode(rebuilt.detector.rules[0][0]) == b"tests/\xff"


def test_ledger_without_detector_loads_as_unrecorded() -> None:
    """A ledger with NO detector key loads fine, and reads as unrecorded — not as corrupt.

    FAIL-CLOSED WOULD BE WRONG HERE. Every field in `_REQUIRED_INSTANCE_FIELDS` is
    fail-closed because its absence means the record is malformed. `detector` is the
    opposite case, and it is exactly `not_covered_turns`' case (`ledger.py:57-63`): its
    absence means "this ledger predates the field", which is true of all four ledgers in
    `runs/`. Rejecting them would make the banked captures unreadable by the very command
    that must re-render them; defaulting them to the CURRENT detector would put today's
    rule's name on yesterday's verdicts. `None` — rendered as `unrecorded` — is the only
    honest third answer.

    The payload below is shaped like a real `runs/s2.json` instance: the nine existing
    fields, no detector key.
    """
    payload = {
        "instances": [
            {
                "trace_id": "trace-pytest-dev__pytest-5227",
                "disposition": "VERIFIED_CLEAN",
                "turn_status_counts": {"PASS": 20, "FAIL": 0, "WARN": 0, "UNVERIFIED": 0},
                "flagged_turns": [],
                "flagged_addable": [],
                "flagged_unaddable": [],
                "unverified_causes": {},
                "error": None,
                "not_covered_turns": {"effect:network": 20},
            }
        ]
    }

    ledger = from_json(payload)

    assert ledger.detector is None
    assert len(ledger.instances) == 1
    assert ledger.instances[0].disposition is Disposition.VERIFIED_CLEAN


def test_to_json_omits_the_detector_key_when_unrecorded() -> None:
    """An unrecorded detector emits NO key at all, so an existing ledger round-trips as-is.

    Writing `"detector": null` would rewrite every banked ledger's bytes on the next
    re-render for no information gained; absent and null mean the same thing here, and
    absent is what the four ledgers in `runs/` already say.
    """
    payload = to_json(RunLedger(instances=[]))

    assert "detector" not in payload
