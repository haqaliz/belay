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

## Independence: how many DISTINCT findings the true positives represent

The Phase-0 gate reads "≥3 **independent** hand-audited TPs", so the raw `tp` count is the
wrong number to publish against it: seven flags of one mis-annotated tool are one finding
observed seven times, not seven findings. Two counts are reported, because the permissive and
strict readings of "independent" genuinely disagree, and a single unlabeled number invites
quoting whichever flatters. Each must be rendered WITH the rule that produced it — the same
discipline that makes the coverage line travel beside a `PASS`.

    independent_tp        distinct `root_cause["key"]` among TPs — the human's own
                          adjudication of what went wrong, one key per cause.
    independent_tp_strict the PRE-REGISTERED gloss: a set of TPs is ONE finding unless they
                          differ in BOTH instance and tool. Group TPs by
                          (`provenance["source_trace_id"]`, `target_tool`); the count is the
                          number of groups only when both dimensions actually vary. If every
                          TP shares one tool, the strict count is 1 regardless of how many
                          instances appear — "three flags from one mis-annotated tool count
                          as one finding". `None` (n/a) when any TP has no `target_tool`:
                          the tool dimension is unevaluable, and both 0 and a group count
                          computed as though the absent tool were a value would be guesses.

Both read HUMAN-supplied fields only. Deriving a cause from `expected`/`sub_verdicts` would
make independence a function of the engine's own output — honesty rule 1's label-trap, one
level up: the engine would decide how many distinct things it had found.

Every ambiguity here resolves DOWNWARD. Only confusion-matrix TPs participate (an FP's or a
`pending` case's root cause is a note about a case the matrix already excluded or scored
against us), and a TP carrying no `root_cause` at all contributes no key — `corpus label`
requires one for a `true-positive`, so that gap is a hand-edited case, and undercounting
findings is the direction that cannot clear a gate it should not clear.

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

    The two independence counts summarize the SAME `tp` cases under two different, named
    grouping rules (see the module docstring). `independent_tp` is always a real integer —
    0 TPs is 0 findings, a fact rather than an absence. `independent_tp_strict` is
    additionally `None` when a TP records no `target_tool`, because the tool dimension the
    strict rule turns on cannot be evaluated. Neither count is ever a fraction of `tp`, and
    neither may be rendered without its rule beside it.
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
    #: Both default so that a caller constructing a `Metrics` by hand (the report renderers'
    #: fixtures) keeps working; `score` ALWAYS passes both explicitly, so no computed metric
    #: ever inherits a default. The defaults are the honest empty answer — no TPs is 0
    #: findings, and an unevaluated strict rule is n/a rather than 0.
    independent_tp: int = 0  # distinct root_cause["key"] among TPs
    independent_tp_strict: Optional[int] = None  # None == n/a (a TP has no target_tool)


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    """`numerator/denominator`, or `None` when the denominator is 0.

    The `None` is the honest "n/a": a rate with no cases under it is undefined, and the one
    thing it must never become is 1.0 (a perfect score conjured from an empty denominator).
    """
    return numerator / denominator if denominator else None


def _independent_tp(true_positives: list[Case]) -> int:
    """The number of distinct `root_cause["key"]` among `true_positives`.

    A TP with no `root_cause` contributes no key: `corpus label` requires one to record a
    `true-positive`, so an absent cause means a hand-edited case, and inventing a key for it
    (say, one per case) would count an unadjudicated case as its own finding.
    """
    return len(
        {case.root_cause["key"] for case in true_positives if case.root_cause is not None}
    )


def _independent_tp_strict(true_positives: list[Case]) -> Optional[int]:
    """The strict, pre-registered count: one finding unless BOTH instance and tool vary.

    Group the TPs by (`provenance["source_trace_id"]`, `target_tool`) and return the number
    of groups ONLY when both dimensions actually vary across the corpus; otherwise the whole
    set is a single finding. This is the gloss "three flags from one mis-annotated tool count
    as one finding", and it is deliberately the harsher of the two readings — the permissive
    group count is the flattering number, and the gate is not to be cleared by one tool
    behaving one way across many captures.

    `None` when any TP lacks a `target_tool`: the dimension the rule turns on is unevaluable
    for that case, and both available numbers would be guesses — 0 understates it to "no
    findings", while grouping as though the absent tool were a value overstates it.
    """
    if not true_positives:
        return 0
    if any(case.target_tool is None for case in true_positives):
        return None
    instances = {case.provenance.get("source_trace_id") for case in true_positives}
    tools = {case.target_tool for case in true_positives}
    if len(instances) == 1 or len(tools) == 1:
        return 1
    return len(
        {(case.provenance.get("source_trace_id"), case.target_tool) for case in true_positives}
    )


def score(cases: list[Case]) -> Metrics:
    """Score `cases` into precision/recall/coverage and the two independence counts.

    Pure: reads `case.expected["reduced_status"]` and `case.human_label` for the confusion
    matrix, plus — for TPs only — the human-supplied `root_cause["key"]`, `target_tool` and
    `provenance["source_trace_id"]`. No replay, no server, no clock, no disk. The order of
    exclusion is deliberate — a case with no adjudicable label is set aside FIRST (its verdict
    is irrelevant without ground truth to score it against), then among adjudicable cases an
    UNVERIFIED verdict is set aside as undecided, and only a decisive verdict on an
    adjudicable label enters the confusion matrix.
    """
    tp = fp = fn = tn = 0
    unverified = pending = unverifiable = 0
    # The independence counts group exactly the cases the matrix counted TP — nothing that was
    # excluded, and nothing the engine decided on its own — so they are collected here rather
    # than re-derived from a second pass over `cases` with its own, driftable, notion of TP.
    true_positives: list[Case] = []

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
            true_positives.append(case)
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
        independent_tp=_independent_tp(true_positives),
        independent_tp_strict=_independent_tp_strict(true_positives),
    )


__all__ = ["Metrics", "score"]
