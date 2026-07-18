"""Precision / recall / coverage of the corpus, scored against HUMAN labels — the number
the Phase-0 gate publishes, and the one metric here designed so the engine cannot grade
its own homework.

`corpus run` (Phase 3) asks "does each stored verdict still reproduce?". THIS asks the
different, load-bearing question: "how well do the engine's stored verdicts match the human
ground truth?". It is a PURE function of two fields per case — `expected.reduced_status`
(the engine's reduced verdict) and `human_label` (the human's adjudication) — and consults
nothing else: no replay, no server, no clock. It runs everywhere.

## The two honesty rules that are the entire point

The naive version of this metric is a fraud, and there are two specific ways to write the
fraud. This module refuses both, and a test watches each refusal fail against its stub.

1. **A human label can never be the engine's own verdict (the label-trap).** Ground truth
   is `human_label`, adjudicated by a person, *independent of what the engine decided*. A
   case whose label is `pending` (not yet adjudicated) or `unverifiable` (no ground truth to
   be had) is EXCLUDED from precision/recall entirely — it lands only in the excluded
   tallies. The tempting fraud counts every FAIL verdict as a true positive, which makes
   precision 1.0 by construction: the engine flagged it, so the engine is right. That is the
   100%-precision-by-construction lie, and excluding unadjudicated labels is what refuses it.

2. **UNVERIFIED is excluded, never folded into PASS.** A case whose *engine verdict* is
   UNVERIFIED means "I could not decide". Folding it into PASS/FN treats "I could not check
   this" as "I checked and cleared it" — the UNVERIFIED-rendered-as-PASS the whole project
   forbids; folding it into a positive fabricates a detection. So an UNVERIFIED verdict is
   excluded from the confusion matrix (neither numerator nor denominator of P/R) and instead
   lowers COVERAGE — the fraction of adjudicable cases the engine actually DECIDED.

## The labels and the confusion matrix

`human_label` is read as verdict-INDEPENDENT ground truth about the run:

    true-positive  -> BAD  (a genuine violation is present)
    false-positive -> GOOD (clean, not a violation)
    unverifiable   -> no ground truth  -> EXCLUDED
    pending        -> not yet adjudicated -> EXCLUDED

Positive = the engine emitted **FAIL** (a detection). Over cases with a DECISIVE verdict
{FAIL, PASS} AND an ADJUDICABLE label {BAD, GOOD}:

    |                | label BAD (true-positive) | label GOOD (false-positive) |
    | verdict FAIL   | TP                        | FP                          |
    | verdict PASS   | FN                        | TN                          |

    precision = TP / (TP + FP)   # of what was flagged, how much was truly BAD
    recall    = TP / (TP + FN)   # of what was truly BAD, how much was caught
    coverage  = decided / adjudicable
              = (TP+FP+FN+TN) / (TP+FP+FN+TN + unverified-among-adjudicable)

A 0 denominator is `None` ("n/a"), NEVER 1.0 and never 0/0: an all-FAIL corpus has no FN, so
recall is honestly n/a. **Precision/recall are meaningless without coverage beside them** — a
metric can look perfect while the engine shrugged on everything else — so `score` returns all
three from one call and the CLI prints them together.

**WARN** is folded in with PASS as a non-detection (positive is FAIL alone). It is rare in
A1/A2 today; treating it as a decided non-detection keeps it out of the UNVERIFIED shrug it is
not, rather than silently dropping it.

This mirrors `belay.replay.report`'s discipline: "not-verifiable is NOT unverified" — kept off
the numerator and reported on its own line. Same honesty, different axis.

Zero runtime dependencies: stdlib `dataclasses` and the `Case` dataclass. No model, no I/O
beyond the list the caller passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from belay.corpus.case import Case

#: The two labels that carry adjudicable ground truth. A label outside this set
#: (`pending`, `unverifiable`) has no usable ground truth and is excluded from P/R.
_BAD = "true-positive"
_GOOD = "false-positive"


@dataclass(frozen=True)
class Metrics:
    """The scored corpus: the confusion matrix, the three rates, and the excluded tallies.

    `precision`/`recall`/`coverage` are `None` when their denominator is 0 — "n/a", never a
    vacuous 1.0. `unverified` counts adjudicable-label cases the engine did NOT decide
    (verdict UNVERIFIED); those are the cases that lower coverage. `pending`/`unverifiable`
    count cases with no adjudicable label. Every case falls in exactly one bucket, so
    `tp+fp+fn+tn + unverified + pending + unverifiable == total`.
    """

    tp: int
    fp: int
    fn: int
    tn: int
    precision: Optional[float]  # None == n/a (TP+FP == 0)
    recall: Optional[float]  # None == n/a (TP+FN == 0)
    coverage: Optional[float]  # None == n/a (no adjudicable case)
    unverified: int  # engine verdict UNVERIFIED, adjudicable label — excluded from P/R
    pending: int  # label pending — no ground truth, excluded
    unverifiable: int  # label unverifiable — no ground truth, excluded
    total: int


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """`numerator/denominator`, or `None` when the denominator is 0.

    The `None` is the honest "n/a": a rate with no cases under it is undefined, and the one
    thing it must never become is 1.0 (a perfect score conjured from an empty denominator).
    """
    return numerator / denominator if denominator else None


def score(cases: list[Case]) -> Metrics:
    """Score `cases` into precision/recall/coverage against their human labels.

    Pure: reads only `case.expected["reduced_status"]` and `case.human_label`. The order of
    exclusion is deliberate — a case with no adjudicable label is set aside FIRST (its verdict
    is irrelevant without ground truth to score it against), then among adjudicable cases an
    UNVERIFIED verdict is set aside as undecided, and only a decisive verdict on an
    adjudicable label enters the confusion matrix.
    """
    tp = fp = fn = tn = 0
    unverified = pending = unverifiable = 0

    for case in cases:
        label = case.human_label
        # Label exclusion first: without human ground truth there is nothing to score, whatever
        # the engine decided. Counting a FAIL here as a true positive is the label-trap.
        if label == "pending":
            pending += 1
            continue
        if label not in (_BAD, _GOOD):
            # `unverifiable` — the only remaining non-adjudicable label (case.py's loader
            # rejects any other value, so this cannot silently swallow an unknown one).
            unverifiable += 1
            continue

        verdict = case.expected["reduced_status"]
        # UNVERIFIED is excluded from P/R and lowers coverage — never folded into PASS/FN,
        # which would render "could not check" as "checked and cleared".
        if verdict == "UNVERIFIED":
            unverified += 1
            continue

        is_bad = label == _BAD
        positive = verdict == "FAIL"  # positive == a detection; PASS and WARN are non-detections
        if positive and is_bad:
            tp += 1
        elif positive:
            fp += 1
        elif is_bad:
            fn += 1
        else:
            tn += 1

    decided = tp + fp + fn + tn
    adjudicable = decided + unverified
    return Metrics(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=_ratio(tp, tp + fp),
        recall=_ratio(tp, tp + fn),
        coverage=_ratio(decided, adjudicable),
        unverified=unverified,
        pending=pending,
        unverifiable=unverifiable,
        total=len(cases),
    )


__all__ = ["Metrics", "score"]
