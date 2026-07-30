"""Many stage ledgers, one population: the dedup rule, and both denominators.

A Phase-0 run produces one `RunLedger` per invocation, and the banked data is **24
captures over 17 distinct trace ids** — one instance minted three times, five minted
twice. `RunLedger.instances` is a bare list that every aggregate is computed over, so
concatenating two stage ledgers double-counts every shared `trace_id`: the same instance
would enter the violation denominator twice, inflating the denominator and deflating the
rate, silently. This module is the merge that does not.

Two facts decide the design, and getting either wrong corrupts the number:

**A `trace_id` is NOT unique across stages.** It is the trace file's stem, so the `s2` and
`s3` captures of `pallets__flask-4992` share the id `trace-pallets__flask-4992` while being
genuinely different observations with different turn counts (17 vs 20). Therefore a
CAPTURE is `(label, trace_id)` and an INSTANCE is `trace_id`, and every input ledger
carries a **caller-supplied** stage label. Without labels, keying on `trace_id` alone would
DROP one of two real observations — losing verified turns rather than double-counting them.

**No merged `InstanceRecord` is ever synthesized.** Collapsing two captures into one record
would have to merge their `turn_status_counts`, and summing those counts one instance's
turns twice while the instance itself counts once, which makes `total_turns()` and the
per-turn FAIL rate meaningless. So capture-level records stay the ground truth:

- per-**turn** statistics are computed over **captures** — every one of those turns really
  was verified;
- per-**instance** statistics come from an `InstanceView` over the captures of one id.

Pure and deterministic: stdlib only, no filesystem, no clock, no network, no randomness.
Same labeled ledgers in -> the same population out, in any order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from belay.phase0.ledger import (
    _DENOMINATOR_DISPOSITIONS,
    DetectorIdentity,
    Disposition,
    InstanceRecord,
    RunLedger,
)

# `_DENOMINATOR_DISPOSITIONS` is imported rather than restated. It is private to the
# package, not to the module, and the alternative — writing the denominator rule down a
# second time — is how two definitions of "counted" drift apart. This module must answer
# the denominator question exactly as `RunLedger.violation_denominator()` does, one capture
# at a time.


@dataclass(frozen=True)
class LabeledLedger:
    """One input ledger plus the stage `label` that distinguishes its captures.

    The label is **caller-supplied and mandatory**: nothing inside a `RunLedger` names the
    run that produced it, and two stages of the same instance are indistinguishable without
    it. `s1`, `s2`, `s3` in the banked data.
    """

    label: str
    ledger: RunLedger


@dataclass(frozen=True)
class Capture:
    """One instance's outcome IN ONE STAGE — the ground-truth unit of this module.

    Identified by `(label, trace_id)`, never by `trace_id` alone. The wrapped
    `InstanceRecord` is untouched: no field of it is ever merged, summed, or rewritten.
    """

    label: str
    record: InstanceRecord

    @property
    def trace_id(self) -> str:
        return self.record.trace_id

    @property
    def disposition(self) -> Disposition:
        return self.record.disposition

    @property
    def key(self) -> tuple[str, str]:
        """`(label, trace_id)` — the capture's identity. See the module docstring."""
        return (self.label, self.record.trace_id)


@dataclass(frozen=True)
class InstanceView:
    """Every capture of ONE `trace_id`, and the reduction over them.

    A VIEW, deliberately not a record: it computes answers from its captures on each call
    and stores no merged counts, so nothing here can drift out of sync with the captures
    that back it — the same discipline `RunLedger` applies to its own instances.
    """

    trace_id: str
    captures: tuple[Capture, ...]

    def is_violating(self) -> bool:
        """True iff ANY capture flagged — worst-verdict-wins on the violation question.

        Conservative in the direction of not HIDING a violation, and the direction is the
        point: a run that flagged an instance observed something real, and a second run
        that came back clean does not un-observe it. The cost is that this can inflate the
        rate, which is why every disagreeing instance is named in the report rather than
        being reduced silently.
        """
        return any(c.disposition is Disposition.VERIFIED_FLAGGED for c in self.captures)

    def in_denominator(self) -> bool:
        """True iff ANY capture was actually verified (VERIFIED_CLEAN or VERIFIED_FLAGGED).

        "Worst" is defined over the VIOLATION question, not over badness: a capture that
        ERRORED is not evidence of a violation, and it is not evidence of cleanliness
        either — it is no evidence at all. So an instance that errored in one stage and
        verified clean in another is IN the denominator on the strength of the stage that
        actually ran, and NOT violating. An instance that errored in every stage was never
        verified and stays OUT, exactly as `RunLedger.violation_denominator()` excludes it.
        """
        return any(c.disposition in _DENOMINATOR_DISPOSITIONS for c in self.captures)

    def answering_captures(self) -> tuple[Capture, ...]:
        """The captures that ANSWER the violation question, i.e. CLEAN or FLAGGED.

        NO_VERIFIABLE_TURNS and ERRORED captures are excluded: they abstain. A disagreement
        is two different ANSWERS, never an answer beside an abstention.
        """
        return tuple(c for c in self.captures if c.disposition in _DENOMINATOR_DISPOSITIONS)

    def disagrees(self) -> bool:
        """True iff this instance's captures give BOTH answers to the violation question.

        Abstentions (ERRORED, NO_VERIFIABLE_TURNS) do not create a disagreement — silence
        does not contradict a verdict.
        """
        answers = {c.disposition for c in self.answering_captures()}
        return len(answers) > 1


@dataclass(frozen=True)
class Population:
    """The captures of many stage ledgers, with an instance-level view over them.

    Holds capture-level records only. `detectors` records which detector produced each
    labeled ledger, so a population report can state it per stage: a merged number over
    ledgers written by different detectors is a different claim from one written by a
    single detector, and an unrecorded detector must stay visible as `unrecorded` on this
    surface too — merging ledgers is exactly where a stale one would otherwise disappear.
    """

    captures: tuple[Capture, ...]
    detectors: tuple[tuple[str, Optional[DetectorIdentity]], ...] = ()

    @staticmethod
    def from_labeled(labeled: Iterable[LabeledLedger]) -> "Population":
        """Build a population from labeled ledgers, or raise a named `ValueError`.

        Fail-closed on duplicate identity, in both directions, because both are input
        defects that a merge would otherwise paper over:

        - the **same label twice** — two ledgers claiming to be the same stage is a
          duplicated input, not two observations;
        - the **same `trace_id` twice inside one label** — one stage verifying one instance
          twice is a malformed ledger, not two stages.

        Captures are sorted by `(trace_id, label)`, so merging in either order yields an
        EQUAL population and therefore a byte-identical report.
        """
        labeled = list(labeled)

        seen_labels: set[str] = set()
        captures: list[Capture] = []
        detectors: list[tuple[str, Optional[DetectorIdentity]]] = []
        for entry in labeled:
            if entry.label in seen_labels:
                raise ValueError(
                    f"duplicate ledger label {entry.label!r}: two ledgers cannot be the same "
                    "stage; label them distinctly or drop the duplicate input"
                )
            seen_labels.add(entry.label)
            detectors.append((entry.label, entry.ledger.detector))

            seen_ids: set[str] = set()
            for record in entry.ledger.instances:
                if record.trace_id in seen_ids:
                    raise ValueError(
                        f"ledger {entry.label!r} records trace_id {record.trace_id!r} twice: "
                        "one stage cannot hold two captures of one instance"
                    )
                seen_ids.add(record.trace_id)
                captures.append(Capture(label=entry.label, record=record))

        return Population(
            captures=tuple(sorted(captures, key=lambda c: (c.trace_id, c.label))),
            detectors=tuple(sorted(detectors, key=lambda pair: pair[0])),
        )

    # --- counts over CAPTURES -----------------------------------------------------------

    def capture_count(self) -> int:
        """How many captures this population holds — the alongside denominator."""
        return len(self.captures)

    def total_turns(self) -> int:
        """Every turn of every capture. Over CAPTURES on purpose: they were all verified."""
        return sum(
            count for c in self.captures for count in c.record.turn_status_counts.values()
        )

    def capture_denominator(self) -> int:
        """Captures that were actually verified — the ALONGSIDE denominator.

        The same rule `RunLedger.violation_denominator()` applies, one capture at a time
        and without any dedup: an instance captured in two stages counts TWICE here. That
        is not a competing answer to the headline, it is a different question — "of the
        verification runs we performed, how many flagged?" — and printing it unlabeled
        beside the per-instance rate is the confusion this pair of lines exists to prevent.
        """
        return sum(1 for c in self.captures if c.disposition in _DENOMINATOR_DISPOSITIONS)

    def violating_captures(self) -> tuple[tuple[str, str], ...]:
        """`(label, trace_id)` for every capture that flagged — no dedup, by design."""
        return tuple(
            c.key for c in self.captures if c.disposition is Disposition.VERIFIED_FLAGGED
        )

    # --- the instance-level VIEW --------------------------------------------------------

    def instances(self) -> tuple[InstanceView, ...]:
        """One `InstanceView` per distinct `trace_id`, ordered by that id."""
        by_id: dict[str, list[Capture]] = {}
        for capture in self.captures:
            by_id.setdefault(capture.trace_id, []).append(capture)
        return tuple(
            InstanceView(trace_id=trace_id, captures=tuple(by_id[trace_id]))
            for trace_id in sorted(by_id)
        )

    def instance_count(self) -> int:
        """Distinct `trace_id`s — one instance minted in three stages counts ONCE."""
        return len({capture.trace_id for capture in self.captures})

    def instance_denominator(self) -> int:
        """Instances with at least one capture that was actually verified."""
        return sum(1 for view in self.instances() if view.in_denominator())

    def violating_instances(self) -> tuple[str, ...]:
        """The `trace_id`s of every violating instance, ordered.

        Returns the IDS, not a count — deliberately unlike `RunLedger.violating_instances()`,
        which returns an int. A reduction over several captures has to be auditable, and a
        bare number is not: naming them is what lets a reader check the worst-verdict-wins
        rule against the captures it reduced.
        """
        return tuple(view.trace_id for view in self.instances() if view.is_violating())

    def disagreements(self) -> tuple[InstanceView, ...]:
        """Instances whose captures give different answers to the violation question."""
        return tuple(view for view in self.instances() if view.disagrees())


__all__ = [
    "Capture",
    "InstanceView",
    "LabeledLedger",
    "Population",
]
