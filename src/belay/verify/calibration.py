"""Aspect `calibration-math` — the pure measurement behind the calibration ledger.

The ledger's job is to answer *"does the triage model's confidence predict a real
violation?"* with numbers, and this module is the arithmetic those numbers rest on:
the reliability curve (confidence deciles vs observed violation rate), the expected
calibration error over those bins, and the decision-relevant sweep — at each
candidate threshold, how many true violations would have been skipped and how much
budget saved.

## The honesty contract (stated here once)

- **The measurement is over the turns actually replayed.** A `LedgerRow` pairs a
  triage `score`/`confidence` with a decided, execution-grounded verdict
  (`violated`). Rows for turns that were never replayed, or whose verdict was
  UNVERIFIED, are the CALLER's to exclude before this module sees them — the caller
  refuses, never this module (`EmptyRowsError`).
- **Calibrated ≠ caused.** A well-calibrated curve says the confidence predicts the
  observed violation rate on THESE replayed turns. It says nothing about turns that
  were not replayed, and nothing causal.
- **A rate with no cases under it is None, never 1.0.** Empty decile bins render
  `"no data"` (`observed_rate`/`mean_confidence` None, `no_data` True) and a
  0-denominator `budget_saved` is None — the one thing a rate must never become is a
  perfect score conjured from an empty denominator (the `corpus/metrics.py:149-155`
  discipline, copied).

Pure functions, stdlib only (dataclasses, typing): no clock, no randomness, no
filesystem, no network, no model — the same rows yield the same output on every box.
The zero-LLM guard scans this directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

#: The pinned equal-width decile edges on confidence [0, 1] — [0.0-0.1) ... [0.9-1.0].
#: The last bin is inclusive at exactly 1.0; everything else is half-open. Pinned at
#: the review gate: do not "improve" the binning without flagging it.
DECILE_EDGES: tuple[tuple[float, float], ...] = (
    (0.0, 0.1),
    (0.1, 0.2),
    (0.2, 0.3),
    (0.3, 0.4),
    (0.4, 0.5),
    (0.5, 0.6),
    (0.6, 0.7),
    (0.7, 0.8),
    (0.8, 0.9),
    (0.9, 1.0),
)


class EmptyRowsError(ValueError):
    """An empty row set was handed to a measurement that needs at least one row.

    The caller refuses BEFORE computing: an ECE over no turns is not 0.0 (that is a
    fabricated perfect score) and a curve over no turns is not ten empty bins — it is
    a refusal. Sweeps tolerate the empty set (their rates return None, see
    `_ratio`); `ece` and `reliability_curve` raise this.
    """


@dataclass(frozen=True)
class LedgerRow:
    """One replayed turn: its triage `score`/`confidence` and the decided verdict.

    `ordinal` is the turn's position in the verify document — the ledger-command
    aspect pairs `triage.scores` rows with `turns` verdicts on it. `violated` is the
    reduced FAIL verdict (WARN folded with PASS, UNVERIFIED excluded by the caller).
    """

    ordinal: int
    score: float
    confidence: float
    violated: bool


@dataclass(frozen=True)
class ReliabilityBin:
    """One decile of the reliability curve.

    `no_data` is the "no data" marker: an empty bin has `n` 0 and both
    `mean_confidence` and `observed_rate` None — never a fabricated 0.0 rate.
    """

    lo: float
    hi: float
    n: int
    mean_confidence: Optional[float]
    observed_rate: Optional[float]
    no_data: bool


@dataclass(frozen=True)
class ThresholdSweepPoint:
    """At one candidate threshold: violations-skipped and budget-saved.

    `violations_skipped` = violated rows with `score < threshold`; `budget_saved` =
    skipped rows / total (None when the row set is empty — 0-denominator, never 1.0).
    """

    threshold: float
    violations_skipped: int
    budget_saved: Optional[float]


@dataclass(frozen=True)
class TopNSweepPoint:
    """At one top-N budget: violations-skipped and budget-saved.

    The N lowest-score rows are the ones a top-N budget would skip, ties broken by
    lowest ordinal first (mirroring the budget aspect). `budget_saved` = skipped /
    total (None when the row set is empty — 0-denominator, never 1.0).
    """

    n: int
    violations_skipped: int
    budget_saved: Optional[float]


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """`numerator/denominator`, or `None` when the denominator is 0.

    The `None` is the honest "n/a": a rate with no cases under it is undefined, and
    the one thing it must never become is 1.0 (a perfect score conjured from an
    empty denominator) — the `corpus/metrics.py:149-155` discipline, copied.
    """
    return numerator / denominator if denominator else None


def reliability_curve(rows: Sequence[LedgerRow]) -> list[ReliabilityBin]:
    """The reliability curve: per decile, n, mean confidence, and observed rate.

    Ten equal-width decile bins on confidence [0, 1] (`DECILE_EDGES`), returned in
    ascending order — deterministic iteration, no clock, no randomness. An empty bin
    renders `"no data"` (rate None, never 0); a real zero rate (rows present, none
    violated) renders 0.0. Raises `EmptyRowsError` on an empty row set.
    """
    if not rows:
        raise EmptyRowsError(
            "reliability_curve refuses an empty row set: a curve over no turns is "
            "a fabricated zero, not a measurement"
        )
    confidences: list[list[float]] = [[] for _ in DECILE_EDGES]
    violated: list[list[bool]] = [[] for _ in DECILE_EDGES]
    for row in rows:
        index = min(int(row.confidence * 10), 9)
        confidences[index].append(row.confidence)
        violated[index].append(row.violated)
    bins: list[ReliabilityBin] = []
    for index, (lo, hi) in enumerate(DECILE_EDGES):
        n = len(confidences[index])
        if n == 0:
            bins.append(ReliabilityBin(lo, hi, 0, None, None, True))
        else:
            mean_confidence = sum(confidences[index]) / n
            observed_rate = sum(violated[index]) / n
            bins.append(ReliabilityBin(lo, hi, n, mean_confidence, observed_rate, False))
    return bins


def ece(rows: Sequence[LedgerRow]) -> float:
    """Expected calibration error: sum over non-empty bins of
    `(n_bin/N x |rate_bin - conf_bin|)`.

    Bins with no rows contribute nothing — there is no rate to compare against a
    confidence. Raises `EmptyRowsError` on an empty row set: 0.0 for no turns would
    be a fabricated perfect calibration.
    """
    if not rows:
        raise EmptyRowsError(
            "ece refuses an empty row set: 0.0 over no turns is a fabricated "
            "perfect calibration, not a measurement"
        )
    total = len(rows)
    return sum(
        (bin_.n / total) * abs(bin_.observed_rate - bin_.mean_confidence)
        for bin_ in reliability_curve(rows)
        if not bin_.no_data
    )


def threshold_sweep(
    rows: Sequence[LedgerRow], candidates: Sequence[float]
) -> list[ThresholdSweepPoint]:
    """Per candidate threshold: violations-skipped and budget-saved.

    A row is "skipped" by a threshold budget when its `score < threshold`;
    `violations_skipped` counts the skipped rows whose verdict was `violated`; and
    `budget_saved` is skipped / total — the honest answer to "what would this
    threshold have cost". An empty row set yields `budget_saved` None (0-denominator,
    never 1.0). Deterministic: points follow the candidate order given.
    """
    total = len(rows)
    points: list[ThresholdSweepPoint] = []
    for threshold in candidates:
        skipped = [row for row in rows if row.score < threshold]
        violations_skipped = sum(1 for row in skipped if row.violated)
        points.append(
            ThresholdSweepPoint(
                threshold, violations_skipped, _ratio(len(skipped), total)
            )
        )
    return points


def top_n_sweep(
    rows: Sequence[LedgerRow], ns: Sequence[int]
) -> list[TopNSweepPoint]:
    """Per top-N budget: violations-skipped and budget-saved.

    A top-N budget skips the N lowest-score rows, ties broken by lowest ordinal
    first (mirroring the budget aspect); `violations_skipped` counts the skipped
    rows whose verdict was `violated`; `budget_saved` is N/total. An empty row set
    yields `budget_saved` None (0-denominator, never 1.0). Deterministic: points
    follow the `ns` order given.
    """
    total = len(rows)
    ranked = sorted(
        enumerate(rows), key=lambda pair: (pair[1].score, pair[0])
    )  # score asc, ordinal asc
    points: list[TopNSweepPoint] = []
    for n in ns:
        selected = ranked[:n]
        violations_skipped = sum(1 for _index, row in selected if row.violated)
        points.append(
            TopNSweepPoint(n, violations_skipped, _ratio(len(selected), total))
        )
    return points


__all__ = [
    "DECILE_EDGES",
    "EmptyRowsError",
    "LedgerRow",
    "ReliabilityBin",
    "ThresholdSweepPoint",
    "TopNSweepPoint",
    "ece",
    "reliability_curve",
    "threshold_sweep",
    "top_n_sweep",
]