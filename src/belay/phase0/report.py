"""The Phase-0 report: the violation rate, rendered with its honesty guards as teeth.

`RunLedger` (Task 1) carries the raw disposition counts; this module turns those counts
plus a scored `belay.corpus.metrics.Metrics` into the human-readable "number" Phase-0
exists to publish. Two guards make that number honest rather than merely convenient:

1. **The instrument-suspect guard (R6, the false-zero defense).** A run whose traces
   captured ~no verifiable turns is NOT a clean 0% violation rate — it is an instrument
   failure. `instrument_suspect` detects that condition, and `render_report` refuses to
   print a violation-rate headline at all when it is True: it prints a loud
   "INSTRUMENT SUSPECT" block instead. Silently printing "0%" here would read as "we
   checked and nothing was wrong", when the truth is "we checked nothing".
2. **The 0-denominator guard.** Mirrors `belay.corpus.metrics._ratio`'s discipline: a
   0 denominator renders as `None`/"n/a", never a bare `0%` and never a conjured `1.0`
   (100%). Every rate this module prints carries its denominator alongside it.

Pure and deterministic: stdlib only, no filesystem, no clock, no randomness. Same
`(ledger, metrics)` in -> the same string out, always.
"""

from __future__ import annotations

from typing import Optional

from belay.corpus.metrics import Metrics
from belay.phase0.ledger import Disposition, RunLedger

_DISPOSITION_ORDER = (
    Disposition.VERIFIED_CLEAN,
    Disposition.VERIFIED_FLAGGED,
    Disposition.NO_VERIFIABLE_TURNS,
    Disposition.ERRORED,
)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """`numerator/denominator`, or `None` when the denominator is 0.

    Copies `belay.corpus.metrics._ratio`'s discipline exactly: `None` is the honest
    "n/a" for an empty denominator, never a silently-clean `0.0` and never a conjured
    `1.0`. Kept local (not imported) because this module's rates are a different axis
    from the corpus's precision/recall, even though the rule is identical.
    """
    return numerator / denominator if denominator else None


def _format_rate(rate: Optional[float]) -> str:
    """`rate` as a percentage string, or `"n/a"` when `rate` is `None`."""
    if rate is None:
        return "n/a"
    return f"{rate:.1%}"


def violation_rate(ledger: RunLedger) -> Optional[float]:
    """`violating_instances() / violation_denominator()`, or `None` if the denominator is 0.

    The denominator is disciplined by `RunLedger.violation_denominator()`: it counts
    only VERIFIED_CLEAN + VERIFIED_FLAGGED instances, excluding NO_VERIFIABLE_TURNS and
    ERRORED. A `None` result means "nothing verifiable to compute a rate from" — never
    read this as a 0% violation rate.
    """
    return _ratio(ledger.violating_instances(), ledger.violation_denominator())


def instrument_suspect(ledger: RunLedger, *, threshold: float = 1.0) -> bool:
    """True when the run's traces captured ~no verifiable turns (the R6 false-zero guard).

    Concretely, True when EITHER:
    - `violation_denominator() == 0` and the ledger has at least one instance (every
      instance was NO_VERIFIABLE_TURNS and/or ERRORED — nothing was ever verified), OR
    - `(no_verifiable_count() + errored_count()) >= threshold * len(instances)`, with
      `threshold` defaulting to 1.0 (every single instance failed to yield a verifiable
      turn).

    An EMPTY ledger (no instances at all) is NOT suspect: there is nothing to be
    suspicious about when no instances were even attempted, so this returns False in
    that case rather than True. "The instrument never ran" and "the instrument ran and
    caught nothing" are different claims; this function speaks only to the latter.
    """
    total = len(ledger.instances)
    if total == 0:
        return False

    if ledger.violation_denominator() == 0:
        return True

    return (ledger.no_verifiable_count() + ledger.errored_count()) >= threshold * total


#: What an unrecorded detector must SAY. A ledger that does not record its detector is
#: indistinguishable, by reading it, from one written by today's rule — and every ledger in
#: `runs/` is one, produced by the REPLACED `tests/` read-only rule. Printing nothing here
#: reads as "the current detector, obviously"; printing the current detector would be a
#: fabrication. The only honest rendering names the gap and says what follows from it.
_UNRECORDED_DETECTOR_CLAUSE = (
    "unrecorded — this ledger does not record which A1 rules produced it, so "
    "the numbers below MUST NOT be assumed current"
)

_UNRECORDED_DETECTOR = f"detector: {_UNRECORDED_DETECTOR_CLAUSE}"


def _detector_section(ledger: RunLedger) -> list[str]:
    """Which detector produced this ledger, or the honest `unrecorded`.

    Placed FIRST in the report because it qualifies everything after it: a violation rate
    is a statement about a detector applied to a population, and a reader who learns which
    detector only after reading the number has already read the number as current.

    Read back from the ledger, never computed here — `belay phase0 report` is a pure
    re-render, so an identity that only existed at verification time could not reach that
    surface, which is the same reason `not_covered_turns` is persisted.
    """
    detector = ledger.detector
    if detector is None:
        return [_UNRECORDED_DETECTOR]

    lines = [f"detector: {len(detector.rules)} A1 rule(s) in force"]
    for scope, rule in detector.rules:
        # Scope and rule on ONE line: a detector is the PAIR. `tests`+`read-only` and
        # `tests`+`no-assertion-weakening` are different detectors over the same scope.
        lines.append(f"  scope {scope!r}: {rule}")
    if not detector.rules:
        lines.append("  (none — A1 was disabled for this run; no invariant was enforced)")
    version = detector.version if detector.version is not None else "unrecorded"
    lines.append(f"  code version: {version}")
    return lines


def _disposition_breakdown(ledger: RunLedger) -> str:
    """One line per disposition, in a fixed order, plus the total instance count."""
    counts = {
        disposition: sum(1 for inst in ledger.instances if inst.disposition is disposition)
        for disposition in _DISPOSITION_ORDER
    }
    lines = [f"run size: {len(ledger.instances)} instances"]
    for disposition in _DISPOSITION_ORDER:
        lines.append(f"  {disposition.name}: {counts[disposition]}")
    return "\n".join(lines)


#: Human wording for each sub-verdict `kind` that can be NOT_COVERED. A kind with no entry
#: is still rendered, under its own name — a new coverage boundary must never be silently
#: dropped from this section for want of a phrase.
_COVERAGE_PROSE = {
    "effect:network": (
        "network egress is NOT observed, so openWorldHint conformance is NOT_COVERED"
    ),
}


def _coverage_section(ledger: RunLedger) -> list[str]:
    """The coverage boundary, read back from the ledger's stored `not_covered_turns`.

    Nothing here is computed from verdicts: `belay phase0 report` re-renders a ledger file
    and never replays anything, so a coverage statement that only existed at verification
    time could not reach that surface — and a rate rendered without its coverage boundary
    is the exact misreading (`PASS` == "the network was checked") this status exists to
    prevent. `render_report` places this section OUTSIDE the INSTRUMENT SUSPECT branch:
    the headline can be suppressed, the limits of what Belay looked at cannot.

    An empty tally says so in those words. It must never read as "nothing was outside
    coverage", because a ledger written before this field existed is indistinguishable
    from one that recorded no boundary.
    """
    by_kind = ledger.not_covered_by_kind()
    total = ledger.total_turns()
    lines = [
        "coverage (NOT_COVERED — dimensions Belay does not observe; never a PASS, "
        "and outside every rate in this report):"
    ]
    if not by_kind:
        lines.append(
            "  no NOT_COVERED dimension recorded in this ledger — a ledger written "
            "before coverage was recorded reads the same way; this is NOT a claim that "
            "everything was inside coverage"
        )
        return lines
    for kind in sorted(by_kind):
        prose = _COVERAGE_PROSE.get(kind, "outside what Belay observes")
        lines.append(f"  {kind}: NOT observed for {by_kind[kind]}/{total} turn(s) — {prose}")
    return lines


def render_report(ledger: RunLedger, metrics: Metrics) -> str:
    """Render the human-readable Phase-0 report, in this fixed order:

    0. THE DETECTOR that produced this ledger — its A1 rules with their scopes and its
       code version — or the word `unrecorded` with what follows from it. First, because
       it qualifies every number below: the same captures under a different rule are a
       different number, and a reader who learns the detector after the rate has already
       read the rate as current.
    1. Run size + disposition breakdown.
    2. THE HEADLINE: if `instrument_suspect(ledger)`, a loud "INSTRUMENT SUSPECT" block
       and NO violation-rate percentage headline at all. Otherwise, the violation rate
       with its denominator always visible (`n/a` if that denominator is 0, never a bare
       `0%` or `100%`).
    2b. THE COVERAGE BOUNDARY, rendered from the ledger's stored `not_covered_turns` —
       deliberately placed OUTSIDE the `instrument_suspect` branch above, which suppresses
       the headline. A rate can be suppressed; what Belay does not observe never can, or a
       reader sees a status with no statement of its limits. It is read back from the
       ledger, never computed here, so `belay phase0 report` (a pure re-render) shows it.
    3. Per-turn FAIL rate (`fail_turns()/total_turns()`), same n/a discipline.
    4. UNVERIFIED rate by named cause (`unverified_by_cause()`), one line per bucket,
       plus the overall UNVERIFIED turn share.
    5. FP-rate from the labeled corpus, rendered as its fraction `FP/(TP+FP) = pct`
       (FP-rate = 1 - precision = FP/(TP+FP)), or `n/a` when `metrics.precision is None`
       (TP+FP == 0) — never a fabricated 0.0/1.0.
    6. Flagged-but-unaddable note: total count across instances, labeled as counted
       violations that are not replayable corpus cases.

    Deterministic: no clock, no randomness, no network, no filesystem.
    """
    lines = _detector_section(ledger) + ["", _disposition_breakdown(ledger), ""]

    if instrument_suspect(ledger):
        lines.append(
            "INSTRUMENT SUSPECT: traces captured ~no verifiable turns; this is "
            "UNVERIFIED-of-the-experiment, NOT a zero-percent violation rate"
        )
    else:
        rate = violation_rate(ledger)
        lines.append(
            f"violation rate = {ledger.violating_instances()}/"
            f"{ledger.violation_denominator()} = {_format_rate(rate)}"
        )
    lines.append("")

    lines.extend(_coverage_section(ledger))
    lines.append("")

    fail_rate = _ratio(ledger.fail_turns(), ledger.total_turns())
    lines.append(
        f"per-turn FAIL rate = {ledger.fail_turns()}/{ledger.total_turns()} = "
        f"{_format_rate(fail_rate)}"
    )
    lines.append("")

    by_cause = ledger.unverified_by_cause()
    total_unverified = sum(by_cause.values())
    lines.append("UNVERIFIED by cause:")
    for cause in sorted(by_cause):
        lines.append(f"  {cause}: {by_cause[cause]}")
    unverified_share = _ratio(total_unverified, ledger.total_turns())
    lines.append(
        f"  overall UNVERIFIED turn share = {total_unverified}/{ledger.total_turns()} = "
        f"{_format_rate(unverified_share)}"
    )
    lines.append("")

    if metrics.precision is None:
        fp_fraction = "n/a"
    else:
        fp_denominator = metrics.tp + metrics.fp
        fp_fraction = f"{metrics.fp}/{fp_denominator} = {_format_rate(metrics.fp / fp_denominator)}"
    lines.append(
        f"FP-rate (false-positive rate, labeled corpus, UNVERIFIED excluded) = {fp_fraction}"
    )
    lines.append("")

    flagged_unaddable_total = sum(len(inst.flagged_unaddable) for inst in ledger.instances)
    lines.append(
        f"flagged-but-unaddable: {flagged_unaddable_total} "
        "(counted as violations, not replayable corpus cases)"
    )

    return "\n".join(lines)


# --- the POPULATION report: many stage ledgers, one number ----------------------------

#: The dedup rule, stated in the output rather than only in a docstring. A merged number is
#: only auditable if the reduction that produced it is on the page: a reader who cannot see
#: that one `trace_id` captured in three stages counted ONCE cannot check the denominator,
#: and a denominator nobody can check is the defect this whole unit exists to end.
_DEDUP_RULE = (
    "dedup rule: a CAPTURE is (stage label, trace_id); an INSTANCE is a trace_id. An "
    "instance is\n"
    "  VIOLATING iff ANY of its captures flagged (worst-verdict-wins), and IN THE "
    "DENOMINATOR iff\n"
    "  ANY of its captures is VERIFIED_CLEAN or VERIFIED_FLAGGED — a capture that ERRORED "
    "is NOT\n"
    "  evidence of a violation, and an instance that ERRORED in every stage was never "
    "verified."
)


def _population_detector_section(population) -> list[str]:
    """Which detector produced each input ledger, by stage label.

    Merging is precisely where a stale detector would disappear: a population can mix a
    ledger written by the REPLACED `tests/` read-only rule with one written by today's
    `no-assertion-weakening`, and the merged rate would then be a number no single detector
    ever produced. So the identity is stated PER STAGE — one unrecorded ledger among four
    recorded ones has to stay visible as unrecorded, not be averaged into silence.
    """
    lines = ["detector by stage (what produced each input ledger):"]
    if not population.detectors:
        lines.append("  (no input ledger — nothing produced this population)")
        return lines
    for label, detector in population.detectors:
        if detector is None:
            lines.append(f"  {label}: {_UNRECORDED_DETECTOR_CLAUSE}")
            continue
        lines.append(f"  {label}: {len(detector.rules)} A1 rule(s) in force")
        for scope, rule in detector.rules:
            # Scope and rule on ONE line: a detector is the PAIR, exactly as in the
            # single-ledger report above.
            lines.append(f"    scope {scope!r}: {rule}")
        if not detector.rules:
            lines.append("    (none — A1 was disabled for this run; no invariant was enforced)")
        version = detector.version if detector.version is not None else "unrecorded"
        lines.append(f"    code version: {version}")
    return lines


def _disagreement_section(population) -> list[str]:
    """Every instance whose captures disagree, NAMED with each capture's outcome.

    Worst-verdict-wins can inflate the rate, and that is only acceptable because the
    reduction is auditable. "None" is a result and is printed in words: an empty section
    would read as though the question had never been asked.
    """
    disagreements = population.disagreements()
    if not disagreements:
        return [
            "disagreements: none — no disagreement between any instance's captures on the "
            "violation question"
        ]
    lines = [
        "disagreements (one instance, captures that differ on the violation question): "
        f"{len(disagreements)}"
    ]
    for view in disagreements:
        outcomes = ", ".join(
            f"{capture.label}={capture.disposition.name}" for capture in view.captures
        )
        lines.append(
            f"  {view.trace_id}: {outcomes} -> counted "
            f"{'VIOLATING' if view.is_violating() else 'NOT violating'} by worst-verdict-wins"
        )
    return lines


#: What a FLAGGED control means HERE, spelled out in the output rather than left to docs.
#: The meaning is context-dependent and nothing in the data encodes the context: in a FRESH
#: MINT a failing control says the instrument was broken while capturing, and it VOIDS the
#: mint. Re-verifying captures that are already banked, there is no mint in flight to void —
#: the control is known-clean by construction, so a flag on it is the detector firing on
#: known-good behaviour, i.e. a PRECISION signal, which is exactly what this measurement is
#: for. Printing "void" here would fabricate one, and a fabricated void reads as a PIVOT the
#: data never supported.
_FAILING_CONTROL_MEANING = (
    "    a control is known-clean BY CONSTRUCTION, so a flagged control is the detector "
    "firing on\n"
    "    known-good behaviour: a DETECTOR FALSE POSITIVE, and a precision signal — which is "
    "what\n"
    "    this measurement is for. This is NOT a mint-void condition. Voiding belongs to a "
    "FRESH\n"
    "    MINT, where a failing control means the instrument was broken WHILE CAPTURING;\n"
    "    in a re-verification of already-banked captures there is no mint in flight to void."
)

#: What "no controls" must SAY. An omitted block reads as "controls ran and were fine";
#: "no control is in this population" is a different and weaker statement, and Stage 3 —
#: which captured zero of its three controls — is exactly the run that makes the difference
#: matter. The absence has to be legible, not inferred from a silence.
_NO_CONTROLS = (
    "controls: none — no instance id in this population matches the 'control__' convention.\n"
    "  That is NOT the same as controls having run and come back clean: this population "
    "contains\n"
    "  no control at all, so it carries no evidence either way about the instrument."
)


def _controls_section(population) -> list[str]:
    """The controls, partitioned out of the headline and reported with their own counts."""
    controls = population.controls()
    views = controls.instances()
    if not views:
        return [_NO_CONTROLS]

    lines = [
        f"controls: {len(views)} control instance(s) over {controls.capture_count()} "
        "capture(s) — EXCLUDED from the headline rate and its denominator"
    ]
    lines.append(
        "  ids treated as controls (by the 'control__' instance-id convention — a naming "
        "convention,"
    )
    lines.append("  not a guarantee, so they are named here rather than only counted):")
    for view in views:
        outcomes = ", ".join(
            f"{capture.label}={capture.disposition.name}" for capture in view.captures
        )
        suffix = " -> DETECTOR FALSE POSITIVE" if view.is_violating() else ""
        lines.append(f"    {view.trace_id}: {outcomes}{suffix}")

    if population.failing_controls():
        lines.append(_FAILING_CONTROL_MEANING)
    return lines


def render_population_report(population) -> str:
    """Render the Phase-0 report for a MERGED population, in this fixed order:

    0. THE DETECTOR per stage label, or `unrecorded` — first, for the same reason it comes
       first in `render_report`: it qualifies every number below, and a merge is where a
       stale detector would otherwise vanish into an average.
    1. THE DEDUP RULE, in the output. A merged denominator that a reader cannot reconstruct
       is not auditable.
    2. Population size: captures, instances and turns, each with the noun it counts.
    3. THE HEADLINE, per INSTANCE — a `trace_id` captured in several stages counts ONCE.
    4. ALONGSIDE, per CAPTURE — the same instance counts TWICE, and the line says it is not
       the headline. Both carry their denominator, and a 0 denominator is `n/a`, never a
       bare `0%` and never a conjured `100%`.
    5. DISAGREEMENTS, named, or the words "no disagreement".
    6. CONTROLS, in their own block with their own counts and their ids named — or the
       words "controls: none", never an omitted block. Steps 2-5 are computed over
       `population.measured()`, i.e. with the controls partitioned OUT: a control is a
       known-answer instance run to check the instrument, and it is clean by construction,
       so folding it into the headline drags the rate toward zero by exactly the number of
       controls that ran. A FLAGGED control is labeled a DETECTOR FALSE POSITIVE and the
       block states that this is NOT a mint-void condition here.

    Takes no `Metrics`: the corpus FP-rate is scored over a corpus directory, not over a
    population of ledgers, and pairing it with a merged rate would imply the two share a
    denominator. `render_report`'s single-ledger contract is untouched by this function.

    Deterministic: no clock, no randomness, no network, no filesystem.
    """
    lines = _population_detector_section(population) + ["", _DEDUP_RULE, ""]

    # EVERY number below is over the MEASURED population — controls partitioned out. A
    # control is a known-answer instance run to check the instrument, not a task the agent
    # was measured on, and because controls are clean by construction, folding them in
    # drags the rate toward zero by exactly the number of controls that ran.
    measured = population.measured()

    lines.append(
        f"population size: {measured.capture_count()} capture(s) over "
        f"{measured.instance_count()} instance(s), {measured.total_turns()} turn(s)"
        + (" — controls excluded, see below" if population.control_ids() else "")
    )

    instance_numerator = len(measured.violating_instances())
    instance_denominator = measured.instance_denominator()
    lines.append(
        "HEADLINE violation rate, per INSTANCE (a trace_id captured in several stages "
        f"counts ONCE) = {instance_numerator}/{instance_denominator} = "
        f"{_format_rate(_ratio(instance_numerator, instance_denominator))}"
    )

    capture_numerator = len(measured.violating_captures())
    capture_denominator = measured.capture_denominator()
    lines.append(
        "alongside, per CAPTURE (an instance captured in two stages counts TWICE; NOT the "
        f"headline) = {capture_numerator}/{capture_denominator} = "
        f"{_format_rate(_ratio(capture_numerator, capture_denominator))}"
    )
    lines.append("")

    # Over the MEASURED population, because this section exists to explain the HEADLINE's
    # reduction. No control outcome is lost by that: the controls block below lists every
    # capture of every control by name and stage.
    lines.extend(_disagreement_section(measured))
    lines.append("")

    lines.extend(_controls_section(population))

    return "\n".join(lines)


__all__ = [
    "violation_rate",
    "instrument_suspect",
    "render_report",
    "render_population_report",
]
