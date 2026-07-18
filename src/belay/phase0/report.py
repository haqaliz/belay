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


def render_report(ledger: RunLedger, metrics: Metrics) -> str:
    """Render the human-readable Phase-0 report, in this fixed order:

    1. Run size + disposition breakdown.
    2. THE HEADLINE: if `instrument_suspect(ledger)`, a loud "INSTRUMENT SUSPECT" block
       and NO violation-rate percentage headline at all. Otherwise, the violation rate
       with its denominator always visible (`n/a` if that denominator is 0, never a bare
       `0%` or `100%`).
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
    lines = [_disposition_breakdown(ledger), ""]

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


__all__ = ["violation_rate", "instrument_suspect", "render_report"]
