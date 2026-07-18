"""C6 Phase 4: the precision / recall / coverage metric, scored against HUMAN labels.

This is the number the Phase-0 gate publishes, and its whole value is that it cannot be
gamed by the engine grading its own homework. Two honesty properties carry the file, each
pinned by a test watched failing against the exact stub it defends against:

1. `test_pending_and_unverifiable_labels_are_excluded_not_scored` — THE LABEL-TRAP. A
   `pending` or `unverifiable` case has no human ground truth, so it is EXCLUDED from
   precision/recall and counted only in the excluded tallies. A "count every FAIL verdict
   as a true positive" stub inflates precision to 1.0 by substituting the engine's own
   verdict for a human label; this test FAILs that stub. The engine's verdict can never
   stand in for a human's.

2. `test_unverified_verdict_is_excluded_from_pr_and_lowers_coverage` — UNVERIFIED EXCLUDED.
   A case whose engine verdict is UNVERIFIED is NOT folded into PASS/FN (that would render
   "I could not check this" as "I checked and cleared it" — the UNVERIFIED-as-PASS the whole
   project forbids) and NOT counted as a positive. It is excluded from P/R and appears on
   the coverage line. A "UNVERIFIED counts as PASS" stub is FAILed by this test.

Every test is pure: it builds `Case` objects in memory with a chosen `expected.reduced_status`
and `human_label` and calls `score`. No replay, no server, no clock — runs everywhere.

Ground-truth semantics (verdict-INDEPENDENT):
  true-positive  -> BAD  (a genuine violation is present)
  false-positive -> GOOD (clean, not a violation)
  unverifiable   -> no ground truth, excluded
  pending        -> not yet adjudicated, excluded
Positive = the engine emitted FAIL. WARN is folded in with PASS as a non-detection.
"""

from __future__ import annotations

from belay.corpus.case import Case
from belay.corpus.metrics import Metrics, score


def _case(reduced_status: str, human_label: str, cid: str = "c") -> Case:
    """A `Case` carrying only the two fields `score` reads; the rest are inert filler.

    `score` is a pure function of `expected.reduced_status` and `human_label`; every other
    field is present because the dataclass requires it, not because the metric looks at it.
    """
    return Case(
        id=cid,
        target_turn_index=0,
        expected={"reduced_status": reduced_status, "sub_verdicts": []},
        human_label=human_label,
        invariants=[],
        server_command=["server"],
        replays=1,
        timeout=1.0,
        provenance={},
        capture_platform="darwin",
        capture_capabilities=[],
    )


def test_hand_computed_confusion_matrix_and_rates() -> None:
    """(a) A fixture with one of each cell + an UNVERIFIED + a pending -> exact hand values.

    Corpus, and the cell each case lands in:
      FAIL + true-positive   -> TP   (flagged, truly BAD)
      FAIL + false-positive  -> FP   (flagged, actually GOOD)
      PASS + true-positive   -> FN   (missed a truly BAD run)
      PASS + false-positive  -> TN   (cleared a GOOD run)
      UNVERIFIED + true-pos  -> excluded from P/R, adjudicable -> lowers coverage
      PASS + pending         -> excluded (no ground truth)

    By hand:
      tp=1 fp=1 fn=1 tn=1  |  unverified=1  pending=1  unverifiable=0  total=6
      precision = 1/(1+1) = 0.5
      recall    = 1/(1+1) = 0.5
      adjudicable = tp+fp+fn+tn+unverified = 5
      coverage  = (tp+fp+fn+tn)/adjudicable = 4/5 = 0.8
    """
    cases = [
        _case("FAIL", "true-positive", "tp"),
        _case("FAIL", "false-positive", "fp"),
        _case("PASS", "true-positive", "fn"),
        _case("PASS", "false-positive", "tn"),
        _case("UNVERIFIED", "true-positive", "unv"),
        _case("PASS", "pending", "pend"),
    ]

    m = score(cases)

    assert isinstance(m, Metrics)
    assert (m.tp, m.fp, m.fn, m.tn) == (1, 1, 1, 1)
    assert m.unverified == 1
    assert m.pending == 1
    assert m.unverifiable == 0
    assert m.total == 6
    assert m.precision == 0.5
    assert m.recall == 0.5
    assert m.coverage == 0.8


def test_pending_and_unverifiable_labels_are_excluded_not_scored() -> None:
    """(b) 🔴 THE LABEL-TRAP: pending/unverifiable labels never enter precision/recall.

    A corpus of ALL FAIL verdicts whose labels are only `pending`/`unverifiable` has NO
    adjudicable ground truth. The honest result is empty: tp=fp=fn=tn=0, precision/recall
    n/a (None). The "count every FAIL as a TP" fraud reports precision 1.0 here — this test
    refutes exactly that stub. The engine's own FAIL can never be counted as a human's
    true-positive.
    """
    cases = [
        _case("FAIL", "pending", "a"),
        _case("FAIL", "pending", "b"),
        _case("FAIL", "unverifiable", "c"),
    ]

    m = score(cases)

    # None of these three is a scored detection.
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 0)
    assert m.pending == 2
    assert m.unverifiable == 1
    # Precision must be n/a (no TP+FP), never the fabricated 1.0 the count-every-FAIL stub prints.
    assert m.precision is None
    assert m.precision != 1.0
    assert m.recall is None
    # No adjudicable case -> coverage is n/a, not a perfect-looking 1.0.
    assert m.coverage is None


def test_unverified_verdict_is_excluded_from_pr_and_lowers_coverage() -> None:
    """(c) 🔴 UNVERIFIED EXCLUDED: an UNVERIFIED verdict is neither PASS/FN nor a positive.

    A single UNVERIFIED-verdict, true-positive-label case: the engine could not decide, and
    the label says the run was genuinely BAD. The honest scoring counts it NOWHERE in the
    confusion matrix — not a FN (which is what a "UNVERIFIED==PASS" stub would produce, since
    PASS+BAD is a miss), not a TP. It lands in the `unverified` tally and drags coverage to
    0 (no case was decided). recall must be n/a, NOT 0.0 and NOT 1.0.
    """
    cases = [_case("UNVERIFIED", "true-positive", "shrug")]

    m = score(cases)

    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 0)
    assert m.unverified == 1
    # The UNVERIFIED==PASS stub would make this a FN (PASS on a BAD run) -> fn == 1. Refuse it.
    assert m.fn == 0
    # recall has no TP and no FN -> n/a, the honest answer; never 0.0, never 1.0.
    assert m.recall is None
    # The one adjudicable case was not decided -> coverage 0.0 (0 decided / 1 adjudicable).
    assert m.coverage == 0.0


def test_zero_denominator_recall_is_na_never_one() -> None:
    """(d) 0-DENOMINATOR: an all-FAIL, all-true-positive corpus has precision but no recall.

    Every case is flagged (FAIL) and truly BAD -> all TP, no FN, no FP. precision = TP/TP =
    1.0 is real. recall = TP/(TP+FN) has TP but FN=0, so the denominator is TP itself and
    recall is 1.0 — wait, that HAS a denominator. To force recall's 0-denominator we need no
    TP and no FN: a corpus of only FP+TN. Do both, and assert the n/a is n/a, never 1.0/0.0.
    """
    # All flagged, all genuinely BAD: precision defined and perfect, recall defined (TP>0).
    flagged_bad = [_case("FAIL", "true-positive", f"tp{i}") for i in range(3)]
    m1 = score(flagged_bad)
    assert (m1.tp, m1.fp, m1.fn, m1.tn) == (3, 0, 0, 0)
    assert m1.precision == 1.0
    assert m1.recall == 1.0  # TP=3, FN=0 -> 3/3, a real 1.0 (denominator is TP)

    # No TP and no FN at all -> recall's denominator is 0 -> n/a, asserted NOT 1.0, NOT 0.
    no_positives = [
        _case("FAIL", "false-positive", "fp"),  # FP
        _case("PASS", "false-positive", "tn"),  # TN
    ]
    m2 = score(no_positives)
    assert (m2.tp, m2.fp, m2.fn, m2.tn) == (0, 1, 0, 1)
    assert m2.recall is None
    assert m2.recall != 1.0
    assert m2.recall != 0.0
    # precision here also has no TP+FP? It has FP=1 -> TP/(TP+FP)=0/1=0.0, a real 0.
    assert m2.precision == 0.0


def test_coverage_reported_alongside_precision_and_recall() -> None:
    """(e) COVERAGE: 4 adjudicable cases, 1 UNVERIFIED -> coverage 3/4, returned WITH P/R.

    The metric must never expose precision/recall without coverage beside them — a corpus
    can look perfect on the cases it decided while shrugging on everything else. `score`
    returns all three from one call.
    """
    cases = [
        _case("FAIL", "true-positive", "a"),  # TP, decided
        _case("PASS", "false-positive", "b"),  # TN, decided
        _case("FAIL", "false-positive", "c"),  # FP, decided
        _case("UNVERIFIED", "true-positive", "d"),  # adjudicable but undecided
    ]

    m = score(cases)

    assert m.coverage == 0.75  # 3 decided / 4 adjudicable
    # P and R are returned from the SAME object, alongside coverage.
    assert m.precision is not None
    assert m.recall is not None
    assert m.coverage is not None


def test_empty_corpus_is_all_na_never_perfect() -> None:
    """An empty corpus scores to all-n/a, never a vacuous 1.0 on any axis."""
    m = score([])
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 0)
    assert m.total == 0
    assert m.precision is None
    assert m.recall is None
    assert m.coverage is None
