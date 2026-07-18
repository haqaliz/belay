"""The Phase-0 run ledger: one instance's disposition, and the run's derived counts.

Running the failure corpus at scale produces one instance outcome per traced task, and
the headline number Phase-0 exists to publish — the violation rate — is a fraction. A
fraction is only honest if its denominator is disciplined: an instance that produced no
verifiable turn, or that errored before verification could run at all, must not silently
inflate or deflate either side of that fraction. `Disposition` names the four possible
outcomes; `InstanceRecord` is one instance's outcome; `RunLedger` is the whole run, with
every aggregate computed on the fly from `instances` rather than stored, so a count can
never drift out of sync with the records it summarizes.

`Disposition` mirrors `belay.verify.verdict.Status`: a `str` mixin so it serializes as its
member name, never a bare int or a custom code. Serialization here mirrors the fail-closed
discipline of `belay.corpus.case.load_case`: `from_json` never silently defaults an
unknown disposition or a missing field — it raises a named `ValueError`, because a ledger
that loaded wrong would misreport the very number this module exists to get right.

Pure and deterministic: no clock, no network, no randomness, no filesystem here. Those
belong to whatever later phase populates a `RunLedger` by actually verifying traces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Disposition(str, Enum):
    """How one Phase-0 instance resolved. `str` mixin so it serializes as its name."""

    VERIFIED_CLEAN = "VERIFIED_CLEAN"
    VERIFIED_FLAGGED = "VERIFIED_FLAGGED"
    NO_VERIFIABLE_TURNS = "NO_VERIFIABLE_TURNS"
    ERRORED = "ERRORED"


#: The two dispositions that count toward the violation-rate denominator: an instance
#: that was actually verified, whether or not it turned up a flagged turn. Excludes
#: NO_VERIFIABLE_TURNS (nothing to verify) and ERRORED (verification never completed).
_DENOMINATOR_DISPOSITIONS = frozenset({Disposition.VERIFIED_CLEAN, Disposition.VERIFIED_FLAGGED})

#: `InstanceRecord` fields that MUST be present when loading from JSON. `error` is
#: included: it is always present, `None` when the disposition is not ERRORED, so its
#: absence is as much a malformed record as an absent `trace_id`.
_REQUIRED_INSTANCE_FIELDS = (
    "trace_id",
    "disposition",
    "turn_status_counts",
    "flagged_turns",
    "flagged_addable",
    "flagged_unaddable",
    "unverified_causes",
    "error",
)


@dataclass(frozen=True)
class InstanceRecord:
    """One corpus instance's verification outcome.

    `turn_status_counts` keys are `belay.verify.verdict.Status` names. `flagged_turns` are
    the turn indices whose reduced verdict was FAIL; `flagged_addable` is the subset
    successfully ingested as corpus cases, and `flagged_unaddable` records why the rest
    could not be (each `{"turn": int, "cause": str}`). `unverified_causes` buckets this
    instance's UNVERIFIED turns by canonical cause. `error` carries the failure message
    when `disposition is ERRORED`, and is `None` otherwise.
    """

    trace_id: str
    disposition: Disposition
    turn_status_counts: dict[str, int]
    flagged_turns: list[int]
    flagged_addable: list[int]
    flagged_unaddable: list[dict]
    unverified_causes: dict[str, int]
    error: Optional[str]


@dataclass(frozen=True)
class RunLedger:
    """The whole Phase-0 run: every instance's outcome, plus derived-on-the-fly counts.

    Nothing here is stored pre-aggregated — every method below recomputes from
    `instances` each call, so a count can never drift out of sync with the records that
    back it.
    """

    instances: list[InstanceRecord]

    def violation_denominator(self) -> int:
        """Instances whose disposition is VERIFIED_CLEAN or VERIFIED_FLAGGED."""
        return sum(1 for inst in self.instances if inst.disposition in _DENOMINATOR_DISPOSITIONS)

    def violating_instances(self) -> int:
        """Instances whose disposition is VERIFIED_FLAGGED."""
        return sum(1 for inst in self.instances if inst.disposition is Disposition.VERIFIED_FLAGGED)

    def no_verifiable_count(self) -> int:
        """Instances whose disposition is NO_VERIFIABLE_TURNS."""
        return sum(1 for inst in self.instances if inst.disposition is Disposition.NO_VERIFIABLE_TURNS)

    def errored_count(self) -> int:
        """Instances whose disposition is ERRORED."""
        return sum(1 for inst in self.instances if inst.disposition is Disposition.ERRORED)

    def total_turns(self) -> int:
        """Sum of every `turn_status_counts` value, across all instances."""
        return sum(
            count
            for inst in self.instances
            for count in inst.turn_status_counts.values()
        )

    def fail_turns(self) -> int:
        """Sum of the `"FAIL"` count across all instances."""
        return sum(inst.turn_status_counts.get("FAIL", 0) for inst in self.instances)

    def unverified_by_cause(self) -> dict[str, int]:
        """`unverified_causes` merged across every instance, summed per bucket."""
        merged: dict[str, int] = {}
        for inst in self.instances:
            for cause, count in inst.unverified_causes.items():
                merged[cause] = merged.get(cause, 0) + count
        return merged


def _instance_to_json(inst: InstanceRecord) -> dict:
    """One `InstanceRecord` as a plain JSON-able dict (disposition rendered as its name)."""
    return {
        "trace_id": inst.trace_id,
        "disposition": inst.disposition.name,
        "turn_status_counts": dict(inst.turn_status_counts),
        "flagged_turns": list(inst.flagged_turns),
        "flagged_addable": list(inst.flagged_addable),
        "flagged_unaddable": [dict(entry) for entry in inst.flagged_unaddable],
        "unverified_causes": dict(inst.unverified_causes),
        "error": inst.error,
    }


def to_json(ledger: RunLedger) -> dict:
    """`ledger` as a plain JSON-able dict."""
    return {"instances": [_instance_to_json(inst) for inst in ledger.instances]}


def _instance_from_json(raw: object) -> InstanceRecord:
    """Rebuild one `InstanceRecord` from JSON, or raise a named `ValueError`."""
    if not isinstance(raw, dict):
        raise ValueError(f"instance record must be a JSON object, got {type(raw).__name__}")

    for field in _REQUIRED_INSTANCE_FIELDS:
        if field not in raw:
            raise ValueError(f"instance record is missing required field {field!r}")

    disposition_name = raw["disposition"]
    try:
        disposition = Disposition[disposition_name]
    except KeyError:
        known = ", ".join(member.name for member in Disposition)
        raise ValueError(
            f"instance record field 'disposition' is {disposition_name!r}; "
            f"must be one of: {known}"
        ) from None

    return InstanceRecord(
        trace_id=raw["trace_id"],
        disposition=disposition,
        turn_status_counts=dict(raw["turn_status_counts"]),
        flagged_turns=list(raw["flagged_turns"]),
        flagged_addable=list(raw["flagged_addable"]),
        flagged_unaddable=[dict(entry) for entry in raw["flagged_unaddable"]],
        unverified_causes=dict(raw["unverified_causes"]),
        error=raw["error"],
    )


def from_json(data: dict) -> RunLedger:
    """Rebuild a `RunLedger` from JSON, FAIL-CLOSED: never silently defaults a bad field.

    Raises a named `ValueError` for a non-dict payload, a missing `instances` key, a
    non-list `instances`, or any malformed instance record (missing field or unknown
    disposition). Round-trips: `from_json(to_json(ledger)) == ledger`.
    """
    if not isinstance(data, dict):
        raise ValueError(f"ledger data must be a JSON object, got {type(data).__name__}")

    if "instances" not in data:
        raise ValueError("ledger data is missing required field 'instances'")

    raw_instances = data["instances"]
    if not isinstance(raw_instances, list):
        raise ValueError(
            f"ledger field 'instances' must be a list, got {type(raw_instances).__name__}"
        )

    return RunLedger(instances=[_instance_from_json(item) for item in raw_instances])


__all__ = [
    "Disposition",
    "InstanceRecord",
    "RunLedger",
    "to_json",
    "from_json",
]
