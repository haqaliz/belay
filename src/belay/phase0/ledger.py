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

from dataclasses import dataclass, field
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

#: `not_covered_turns` is deliberately NOT in `_REQUIRED_INSTANCE_FIELDS`. It is
#: optional-with-default so every ledger written before coverage was recorded still loads
#: — a fail-closed requirement here would turn "this ledger predates the field" into a
#: corrupt-ledger error. An absent field means "coverage was not recorded", which the
#: report says in those words rather than rendering an unearned "nothing was outside
#: coverage".
_DEFAULT_NOT_COVERED: dict[str, int] = {}

#: `detector` is deliberately NOT a required ledger field, for the same reason
#: `not_covered_turns` is not: it is optional-with-default so every ledger written before
#: the detector was recorded still loads. Fail-closed here would turn "this ledger predates
#: the field" into a corrupt-ledger error, and it is true of all four ledgers in `runs/` —
#: the exact captures this field exists to disambiguate. Defaulting to the CURRENT detector
#: would be worse still: it would print today's rule's name over yesterday's verdicts. The
#: honest third answer is `None`, which every surface renders as the word "unrecorded".
_DEFAULT_DETECTOR = None

#: `exposure` follows `detector`'s pattern, NOT `not_covered_turns`'s — and the two must
#: never be confused. `not_covered_turns` defaults an absent key to `{}` (`ledger.py`
#: below), which COLLAPSES "never recorded" into "recorded as empty"; that is survivable
#: only because the report's prose refuses to claim either reading. It is NOT survivable
#: here: `files_compared == 0` is a real, material finding — the A1 content rule ran and
#: reached zero comparisons — while an absent `exposure` key means NO fact was recorded at
#: all. That absence has several causes and this field distinguishes none of them: a ledger
#: written before exposure accounting (every ledger in `runs/`), an ERRORED instance
#: (`runner.py`), a run with no content rule in force, or an instance whose turns never
#: replayed. Defaulting the absence to a zeroed dict would fabricate the former from any of
#: the latter. So there is deliberately no `_DEFAULT_EXPOSURE` sentinel dict:
#: `_instance_from_json` reads `raw.get("exposure")` and lets a missing key resolve to the
#: dataclass field's own `None` default, exactly as `detector` does for the whole ledger.


@dataclass(frozen=True)
class DetectorIdentity:
    """WHAT PRODUCED A LEDGER: the A1 rules and scopes in force, plus a code identity.

    A ledger is a fraction and its verdicts came from a detector; without this, a ledger
    written by the REPLACED `tests/` read-only rule reads identically to one written by
    today's `no-assertion-weakening`, and a reader re-deriving a published number cannot
    tell a current result from a stale one.

    `rules` is `(scope, rule)` pairs in the order the run applied them, a TUPLE so the
    identity stays hashable and frozen like everything else here. `scope` is a `str`
    because `Invariant.scope` is raw path BYTES: the caller decodes with `os.fsdecode`
    (the encoding `belay.corpus.add` already stores), which is lossless — `os.fsencode`
    recovers the original bytes even when they are not UTF-8.

    `version` is a free-form code identity and is **caller-injected ONLY**. This module
    must not read git, the environment, or a clock: `belay.phase0` is a deterministic
    path, and a library that derived its own version string would make the same ledger
    serialize differently on two boxes.
    """

    rules: tuple[tuple[str, str], ...]
    version: Optional[str] = None


@dataclass(frozen=True)
class InstanceRecord:
    """One corpus instance's verification outcome.

    `turn_status_counts` keys are `belay.verify.verdict.Status` names. `flagged_turns` are
    the turn indices whose reduced verdict was FAIL; `flagged_addable` is the subset
    successfully ingested as corpus cases, and `flagged_unaddable` records why the rest
    could not be (each `{"turn": int, "cause": str}`). `unverified_causes` buckets this
    instance's UNVERIFIED turns by canonical cause. `error` carries the failure message
    when `disposition is ERRORED`, and is `None` otherwise.

    `not_covered_turns` is THE COVERAGE BOUNDARY, persisted. It maps a sub-verdict `kind`
    (e.g. `"effect:network"`) to the number of this instance's turns that carried a
    `NOT_COVERED` sub-verdict of that kind. It exists because `belay phase0 report` is a
    pure re-render of stored JSON: a coverage statement that were merely computed at
    verification time could never reach that surface, and a status rendered without its
    coverage boundary is precisely the false-PASS this status was introduced to prevent.
    It is PER-INSTANCE because the report renders per-instance facts and a run-level
    aggregate derives from per-instance data, never the other way round. It is counted
    per TURN, not per sub-verdict, so `n/total_turns` reads as a fraction of turns.

    Note it is NOT part of `turn_status_counts`: a turn's reduced status can never be
    NOT_COVERED (`verdict.reduce` drops it), so this is a second, orthogonal tally, and
    `total_turns()` — which sums `turn_status_counts` blindly — stays correct.

    `exposure` is how many files the A1 content rule (`no-assertion-weakening`) actually
    judged, summed from the `expected["exposure"]` fact each A1 sub-verdict may carry
    (`invariants.py`'s `_evaluate_content_rule`). It is `None` — UNRECORDED — whenever no
    turn ever carried that key: a ledger from before this aspect, an instance whose only
    declared invariant is `read-only` (which has no exposure concept), or an instance with
    no declared invariants at all. It is a `dict` — `{"files_compared": int,
    "turns_judging": int, "turns_recorded": int}` — the moment even ONE turn recorded the
    fact, and `files_compared` can legitimately be `0` in that dict (nothing was in scope
    to judge). `None` and `{"files_compared": 0, ...}` are DIFFERENT claims and must never
    be conflated — see `_DEFAULT_DETECTOR`'s comment for why this follows `detector`'s
    pattern rather than `not_covered_turns`'s. Also NOT part of `turn_status_counts`, for
    the identical reason `not_covered_turns` is not.
    """

    trace_id: str
    disposition: Disposition
    turn_status_counts: dict[str, int]
    flagged_turns: list[int]
    flagged_addable: list[int]
    flagged_unaddable: list[dict]
    unverified_causes: dict[str, int]
    error: Optional[str]
    not_covered_turns: dict[str, int] = field(default_factory=dict)
    exposure: Optional[dict] = None
    #: The instance-level A1 trajectory verdict (`suite-before-success-claim`), held as a
    #: serialized summary `{"status": <name>, "cause": <named abstain or None>,
    #: "evidence_count": int}`. `None` — UNRECORDED — whenever the rule was not declared
    #: for the run, exactly `exposure`'s absent-never-zero pattern: an absent `trajectory`
    #: means NO verdict was recorded at all, and must never be read as (or rendered as)
    #: "the trajectory was clean". Serialized additively (`_instance_to_json` omits the
    #: key when `None`), so old ledgers re-render byte-identically.
    trajectory: Optional[dict] = None


@dataclass(frozen=True)
class RunLedger:
    """The whole Phase-0 run: every instance's outcome, plus derived-on-the-fly counts.

    Nothing here is stored pre-aggregated — every method below recomputes from
    `instances` each call, so a count can never drift out of sync with the records that
    back it.
    """

    instances: list[InstanceRecord]
    detector: Optional[DetectorIdentity] = None

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

    def not_covered_by_kind(self) -> dict[str, int]:
        """`not_covered_turns` merged across every instance, summed per sub-verdict kind.

        The run-level coverage boundary, derived (like every other count here) from the
        per-instance records rather than stored twice. An empty dict means no instance
        RECORDED a coverage boundary — which includes a ledger written before the field
        existed, and must therefore never be rendered as "nothing was outside coverage".
        """
        merged: dict[str, int] = {}
        for inst in self.instances:
            for kind, count in inst.not_covered_turns.items():
                merged[kind] = merged.get(kind, 0) + count
        return merged

    def unverified_by_cause(self) -> dict[str, int]:
        """`unverified_causes` merged across every instance, summed per bucket."""
        merged: dict[str, int] = {}
        for inst in self.instances:
            for cause, count in inst.unverified_causes.items():
                merged[cause] = merged.get(cause, 0) + count
        return merged


def _instance_to_json(inst: InstanceRecord) -> dict:
    """One `InstanceRecord` as a plain JSON-able dict (disposition rendered as its name).

    `"exposure"` is OMITTED ENTIRELY when unrecorded — mirroring `to_json`'s treatment of
    the ledger-level `"detector"` key, and for the identical reason: writing
    `"exposure": null` would rewrite every pre-existing ledger's bytes on its next
    re-render for no information gained, and would put a `null` where the honest answer is
    that the key never existed. `"trajectory"` follows the identical rule: an unrecorded
    instance-level verdict stays absent, never `null` and never a fabricated clean.
    """
    payload = {
        "trace_id": inst.trace_id,
        "disposition": inst.disposition.name,
        "turn_status_counts": dict(inst.turn_status_counts),
        "flagged_turns": list(inst.flagged_turns),
        "flagged_addable": list(inst.flagged_addable),
        "flagged_unaddable": [dict(entry) for entry in inst.flagged_unaddable],
        "unverified_causes": dict(inst.unverified_causes),
        "error": inst.error,
        "not_covered_turns": dict(inst.not_covered_turns),
    }
    if inst.exposure is not None:
        payload["exposure"] = dict(inst.exposure)
    if inst.trajectory is not None:
        payload["trajectory"] = dict(inst.trajectory)
    return payload


def _detector_to_json(detector: DetectorIdentity) -> dict:
    """One `DetectorIdentity` as a plain JSON-able dict.

    `rules` becomes a list of `{"scope": ..., "rule": ...}` objects — the same shape
    `belay.corpus.add` stores for the invariants a case was judged under — rather than
    bare pairs, so a reader of the raw JSON can tell which half is which.
    """
    return {
        "rules": [{"scope": scope, "rule": rule} for scope, rule in detector.rules],
        "version": detector.version,
    }


def to_json(ledger: RunLedger) -> dict:
    """`ledger` as a plain JSON-able dict.

    The `"detector"` key is OMITTED ENTIRELY when the detector is unrecorded — see
    `_DEFAULT_DETECTOR`. Emitting `"detector": null` would rewrite every ledger written
    before this field existed on its next re-render, for no information gained: absent and
    null say the same thing, and absent is what those ledgers already say.
    """
    payload: dict = {"instances": [_instance_to_json(inst) for inst in ledger.instances]}
    if ledger.detector is not None:
        payload["detector"] = _detector_to_json(ledger.detector)
    return payload


def _instance_from_json(raw: object) -> InstanceRecord:
    """Rebuild one `InstanceRecord` from JSON, or raise a named `ValueError`."""
    if not isinstance(raw, dict):
        raise ValueError(f"instance record must be a JSON object, got {type(raw).__name__}")

    # `field_name`, not `field`: `dataclasses.field` is imported at module scope now.
    for field_name in _REQUIRED_INSTANCE_FIELDS:
        if field_name not in raw:
            raise ValueError(f"instance record is missing required field {field_name!r}")

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
        # Optional-with-default, ON PURPOSE — see `_DEFAULT_NOT_COVERED`. Every other
        # field here is fail-closed; this one must not be, or every ledger written before
        # the coverage boundary was recorded becomes unreadable.
        not_covered_turns=dict(raw.get("not_covered_turns", _DEFAULT_NOT_COVERED)),
        # `raw.get("exposure")`, deliberately with NO default dict — see the comment beside
        # `_DEFAULT_DETECTOR`. A missing key resolves to `None` (unrecorded); a present key
        # is copied defensively, exactly as `not_covered_turns` is, so the loaded record
        # never aliases the caller's payload dict.
        exposure=(
            dict(raw["exposure"]) if isinstance(raw.get("exposure"), dict) else raw.get("exposure")
        ),
        # `trajectory` follows `exposure` exactly: absent means unrecorded (the rule was
        # not declared for the run, or the ledger predates the field) and resolves to
        # `None` — never a fabricated zero or clean verdict. A present dict is copied
        # defensively like every other dict field.
        trajectory=(
            dict(raw["trajectory"])
            if isinstance(raw.get("trajectory"), dict)
            else raw.get("trajectory")
        ),
    )


def _detector_from_json(raw: object) -> DetectorIdentity:
    """Rebuild one `DetectorIdentity` from JSON, or raise a named `ValueError`.

    Fail-closed on everything INSIDE the object. Only the object's ABSENCE is tolerated
    (see `_DEFAULT_DETECTOR`): a ledger that names its detector and names it malformed is
    corrupt, and silently reading it as unrecorded would hide a real defect behind the
    same word that back-compat uses.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"ledger field 'detector' must be a JSON object, got {type(raw).__name__}")

    if "rules" not in raw:
        raise ValueError("ledger field 'detector' is missing required field 'rules'")

    raw_rules = raw["rules"]
    if not isinstance(raw_rules, list):
        raise ValueError(
            f"detector field 'rules' must be a list, got {type(raw_rules).__name__}"
        )

    rules = []
    for entry in raw_rules:
        if not isinstance(entry, dict) or "scope" not in entry or "rule" not in entry:
            raise ValueError(
                "each detector rule must be a JSON object with 'scope' and 'rule'; "
                f"got {entry!r}"
            )
        rules.append((entry["scope"], entry["rule"]))

    return DetectorIdentity(rules=tuple(rules), version=raw.get("version"))


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

    # Optional-with-default, ON PURPOSE — see `_DEFAULT_DETECTOR`. An absent key means the
    # ledger predates the field (every ledger in `runs/` does), NOT that it is corrupt.
    raw_detector = data.get("detector", _DEFAULT_DETECTOR)
    detector = None if raw_detector is None else _detector_from_json(raw_detector)

    return RunLedger(
        instances=[_instance_from_json(item) for item in raw_instances],
        detector=detector,
    )


__all__ = [
    "DetectorIdentity",
    "Disposition",
    "InstanceRecord",
    "RunLedger",
    "to_json",
    "from_json",
]
