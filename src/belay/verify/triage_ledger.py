"""Aspect `ledger-command` — the pure re-render of the calibration measurement.

`belay triage-ledger <verify-json>` turns ONE stored `belay verify --json`
document into the C10 calibration ledger: the per-turn triage scores paired with
the execution-grounded reduced verdict, then the reliability curve (confidence
deciles vs the observed violation rate), the ECE, and the decision-relevant sweep
— at each candidate threshold, how many true violations would have been skipped
and how much of the replay budget saved. A PURE RE-RENDER: no replay, no
re-verification, no clock read — the same document re-renders byte-identically.

## The mapping (the honesty contract, stated here once)

- `triage.scores` rows join to `turns` records by `ordinal`. A score row whose
  ordinal matches no turn is a corrupt document — fail-closed (`ValueError`),
  never silently dropped.
- The violation column is the per-turn reduced FAIL (WARN folded with PASS, the
  corpus precedent — `corpus/metrics.py`). UNVERIFIED turns are EXCLUDED from the
  column — there is no verdict to calibrate against — and counted;
  `"skipped": true` rows (the budgeted-mode marker) are excluded the same way and
  counted; abstentions (turns with no score row) are absent, and the unscored
  count is stated whenever nonzero, so `turns_total == decided + excluded` always
  holds. The counts appear in the render.
- A document with NO `triage` section is a refusal, not a ledger: the run never
  ran triage, so there is nothing to measure — named error, exit 2.
- A zero-denominator column refuses a rate: the named `NO_DECIDED_ROWS` refusal
  renders with NO rates and exits 0 — a measurement refused, never a fabricated
  0% (the R6 false-zero defense, the `phase0 report` INSTRUMENT SUSPECT shape).
- Deterministic: no clock, no randomness, no filesystem beyond the input read,
  no network, no model — the zero-LLM guard scans this directory, and the
  arithmetic lives in `belay.verify.calibration` (stdlib only).

The text and `--json` renderers are "one computation, two renderers": both derive
from the SAME ledger objects. JSON float values are the raw arithmetic results
(never rounded), so a fixture with binary-exact values pins them exactly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from belay.verify.calibration import (
    LedgerRow,
    ReliabilityBin,
    ece,
    reliability_curve,
    threshold_sweep,
    top_n_sweep,
)

#: The ledger document's schema version (its own, independent of the verify doc's).
SCHEMA = 1

#: The pinned candidate thresholds for the sweep — the nine decile boundaries.
#: A row is "skipped" by a threshold budget when `score < threshold`; threshold
#: 0.0 would skip nothing and threshold 1.0 would skip everything, so neither is
#: a candidate.
SWEEP_THRESHOLDS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)

#: The pinned top-N budgets for the sweep (N lowest-score rows skipped, ties by
#: lowest ordinal, mirroring the budget aspect).
SWEEP_NS: tuple[int, ...] = (1, 2, 3, 4, 5)

#: The named refusal for a zero-denominator column (the INSTRUMENT SUSPECT shape).
NO_DECIDED_ROWS = "NO_DECIDED_ROWS"


class NoTriageSectionError(ValueError):
    """The document never ran triage: `triage` is absent, so a ledger over it
    would be a fabrication. Named so the surface can say exactly that."""


@dataclass(frozen=True)
class Ledger:
    """One verify document's calibration ledger: the decided rows plus the
    exclusion counts, so the renderers never re-read the document.

    `rows` holds ONLY decided turns (FAIL/PASS/WARN), joined from `triage.scores`
    by ordinal. `excluded_unscored` is `turns_total - decided - unverified -
    skipped` — the turns with no score row at all (abstentions/out-of-scope),
    stated so `turns_total == decided + unverified + skipped + unscored` always
    holds.
    """

    trace: Optional[str]
    rows: tuple[LedgerRow, ...]
    turns_total: int
    excluded_unverified: int
    excluded_skipped: int
    excluded_unscored: int

    @property
    def turns_decided(self) -> int:
        return len(self.rows)


def rows_from_document(doc: dict) -> Ledger:
    """The document -> ledger mapping: join `triage.scores` to `turns` by ordinal.

    FAIL -> `violated=True`; PASS/WARN -> `violated=False`; UNVERIFIED -> excluded
    and counted; `"skipped": true` rows -> excluded and counted (no verdict — the
    budget skipped them, so there is nothing to calibrate against); turns with no
    score row -> absent (counted as unscored). Raises `NoTriageSectionError` when
    `triage` is absent and `ValueError` on any corrupt shape — a silently smaller
    ledger would read as a correct one.
    """
    triage = doc.get("triage")
    if triage is None:
        raise NoTriageSectionError(
            "the verify document carries no triage section — a ledger over a run "
            "that never ran triage would be a fabrication"
        )
    turns = doc.get("turns")
    scores = triage.get("scores")
    if not isinstance(turns, list) or not isinstance(scores, list):
        raise ValueError(
            "the verify document must carry a `turns` list and a `triage.scores` list"
        )

    by_ordinal: dict[Any, dict] = {}
    for turn in turns:
        if not isinstance(turn, dict) or "ordinal" not in turn:
            raise ValueError("a turn record must carry an ordinal")
        by_ordinal[turn["ordinal"]] = turn

    rows: list[LedgerRow] = []
    excluded_unverified = 0
    excluded_skipped = 0
    for entry in scores:
        if (
            not isinstance(entry, dict)
            or "ordinal" not in entry
            or "score" not in entry
            or "confidence" not in entry
        ):
            raise ValueError(
                "a triage score row must carry ordinal, score and confidence: "
                f"{entry!r}"
            )
        ordinal = entry["ordinal"]
        turn = by_ordinal.get(ordinal)
        if turn is None:
            raise ValueError(
                f"triage score row ordinal {ordinal} matches no turn record"
            )
        if entry.get("skipped") is True:
            excluded_skipped += 1
            continue
        status = turn.get("status")
        if status == "FAIL":
            rows.append(LedgerRow(ordinal, entry["score"], entry["confidence"], True))
        elif status in ("PASS", "WARN"):
            rows.append(LedgerRow(ordinal, entry["score"], entry["confidence"], False))
        elif status == "UNVERIFIED":
            excluded_unverified += 1
        else:
            raise ValueError(
                f"turn {ordinal} carries an unclassifiable status {status!r}"
            )

    turns_total = len(turns)
    unscored = (
        turns_total - len(rows) - excluded_unverified - excluded_skipped
    )
    if unscored < 0:
        raise ValueError(
            "more triage score rows than turn records — corrupt document"
        )
    return Ledger(
        trace=doc.get("trace"),
        rows=tuple(rows),
        turns_total=turns_total,
        excluded_unverified=excluded_unverified,
        excluded_skipped=excluded_skipped,
        excluded_unscored=unscored,
    )


# --- the renderers (one computation, two renderers) ------------------------------------


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """`numerator/denominator`, or `None` when the denominator is 0.

    Copies `belay.phase0.report._ratio`'s discipline exactly: `None` is the honest
    "n/a" for an empty denominator, never a silently-clean 0.0. A rate with no
    cases under it is undefined; the one thing it must never become is a perfect
    score conjured from an empty denominator.
    """
    return numerator / denominator if denominator else None


def _format_rate(rate: Optional[float]) -> str:
    """`rate` as a percentage string, or `"n/a"` when `rate` is `None`."""
    if rate is None:
        return "n/a"
    return f"{rate:.1%}"


def _violations(rows: Sequence[LedgerRow]) -> int:
    return sum(1 for row in rows if row.violated)


def _excluded_parts(ledger: Ledger) -> list[str]:
    """The human exclusion breakdown: UNVERIFIED and skipped always, unscored
    only when nonzero (the text render; the JSON always carries all three)."""
    parts = [
        f"{ledger.excluded_unverified} UNVERIFIED",
        f"{ledger.excluded_skipped} skipped",
    ]
    if ledger.excluded_unscored:
        parts.append(f"{ledger.excluded_unscored} unscored")
    return parts


def _excluded_count(ledger: Ledger) -> int:
    return (
        ledger.excluded_unverified
        + ledger.excluded_skipped
        + ledger.excluded_unscored
    )


def _bin_label(bin_: ReliabilityBin) -> str:
    """`[lo-hi)` for every decile, `[lo-hi]` for the last — the 1.0-inclusive
    edge rendered distinctly. Edges use the raw float repr (`0.0`, never `0`)."""
    if bin_.hi == 1.0:
        return f"[{bin_.lo}-{bin_.hi}]"
    return f"[{bin_.lo}-{bin_.hi})"


def _bin_detail(bin_: ReliabilityBin) -> str:
    """One bin's rendered content: `no data` for an empty bin (never a
    fabricated 0.0 rate), else n, mean confidence, and the observed rate."""
    if bin_.no_data:
        return "no data"
    return (
        f"n={bin_.n}, mean conf {bin_.mean_confidence}, "
        f"rate {_format_rate(bin_.observed_rate)}"
    )


def _skipped_count(rows: Sequence[LedgerRow], threshold: float) -> int:
    """The raw skipped count for one threshold candidate — recomputed from the
    rows (not derived from `budget_saved`, which is a ratio and could be lossy)."""
    return sum(1 for row in rows if row.score < threshold)


def _refusal_cause(ledger: Ledger) -> str:
    """The named refusal's cause sentence, shared verbatim by both renderers."""
    return (
        f"{ledger.turns_total} turns, 0 decided, {_excluded_count(ledger)} "
        f"excluded ({', '.join(_excluded_parts(ledger))}); no calibration "
        "measurement rendered over a zero-denominator column"
    )


def _refusal_doc(ledger: Ledger) -> dict:
    """The machine refusal document: the named refusal, the counts, NO rates."""
    return {
        "schema": SCHEMA,
        "trace": ledger.trace,
        "refusal": NO_DECIDED_ROWS,
        "cause": _refusal_cause(ledger),
        "turns_total": ledger.turns_total,
        "turns_decided": 0,
        "excluded": {
            "unverified": ledger.excluded_unverified,
            "skipped": ledger.excluded_skipped,
            "unscored": ledger.excluded_unscored,
        },
    }


def render_text(ledger: Ledger) -> str:
    """The human ledger: denominator, exclusion counts, violation rate, ECE, the
    reliability curve (no-data bins included), the threshold sweep, and the top-N
    sweep. The zero-denominator case renders the named refusal with NO rates.
    Deterministic: the same ledger renders the same bytes on every box.
    """
    if not ledger.turns_decided:
        return f"belay triage ledger: {NO_DECIDED_ROWS} — {_refusal_cause(ledger)}"

    rows = ledger.rows
    total = ledger.turns_decided
    lines = [
        f"belay triage ledger: {ledger.trace or '(none)'}",
        (
            f"turns: {ledger.turns_total} total, {total} decided, "
            f"{_excluded_count(ledger)} excluded ({', '.join(_excluded_parts(ledger))})"
        ),
        (
            f"violations: {_violations(rows)}/{total} = "
            f"{_format_rate(_ratio(_violations(rows), total))}"
        ),
        f"ece: {ece(rows):g}",
        "reliability:",
    ]
    lines.extend(
        f"  {_bin_label(bin_)}: {_bin_detail(bin_)}"
        for bin_ in reliability_curve(rows)
    )
    lines.append("threshold sweep (skipped = score < threshold):")
    lines.extend(
        f"  {point.threshold:g}: skipped {_skipped_count(rows, point.threshold)}/{total} "
        f"({_format_rate(_ratio(_skipped_count(rows, point.threshold), total))}), "
        f"violations skipped {point.violations_skipped}"
        for point in threshold_sweep(rows, SWEEP_THRESHOLDS)
    )
    lines.append("top-N sweep (N lowest scores skipped, ties by lowest ordinal):")
    lines.extend(
        f"  {point.n}: skipped {min(point.n, total)}/{total} "
        f"({_format_rate(_ratio(min(point.n, total), total))}), "
        f"violations skipped {point.violations_skipped}"
        for point in top_n_sweep(rows, SWEEP_NS)
    )
    return "\n".join(lines)


def render_json(ledger: Ledger) -> str:
    """The machine ledger, as ONE JSON document with the pinned key order. The
    zero-denominator case emits the refusal document — the named refusal, the
    counts, NO rates. Float values are raw arithmetic results (never rounded).
    Deterministic: the same ledger emits the same bytes on every box.
    """
    if not ledger.turns_decided:
        return json.dumps(_refusal_doc(ledger))

    rows = ledger.rows
    total = ledger.turns_decided
    doc = {
        "schema": SCHEMA,
        "trace": ledger.trace,
        "turns_total": ledger.turns_total,
        "turns_decided": total,
        "excluded": {
            "unverified": ledger.excluded_unverified,
            "skipped": ledger.excluded_skipped,
            "unscored": ledger.excluded_unscored,
        },
        "violations": _violations(rows),
        "violation_rate": _ratio(_violations(rows), total),
        "reliability": [
            {
                "bin": _bin_label(bin_),
                "n": bin_.n,
                "mean_confidence": bin_.mean_confidence,
                "observed_rate": bin_.observed_rate,
                "no_data": bin_.no_data,
            }
            for bin_ in reliability_curve(rows)
        ],
        "ece": ece(rows),
        "threshold_sweep": [
            {
                "threshold": point.threshold,
                "skipped": _skipped_count(rows, point.threshold),
                "violations_skipped": point.violations_skipped,
                "budget_saved": point.budget_saved,
            }
            for point in threshold_sweep(rows, SWEEP_THRESHOLDS)
        ],
        "top_n_sweep": [
            {
                "n": point.n,
                "skipped": min(point.n, total),
                "violations_skipped": point.violations_skipped,
                "budget_saved": point.budget_saved,
            }
            for point in top_n_sweep(rows, SWEEP_NS)
        ],
    }
    return json.dumps(doc)


__all__ = [
    "NO_DECIDED_ROWS",
    "SCHEMA",
    "SWEEP_NS",
    "SWEEP_THRESHOLDS",
    "Ledger",
    "NoTriageSectionError",
    "render_json",
    "render_text",
    "rows_from_document",
]