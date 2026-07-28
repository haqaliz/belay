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

from typing import Optional

from belay.corpus.case import Case
from belay.corpus.metrics import Metrics, score


def _case(
    reduced_status: str,
    human_label: str,
    cid: str = "c",
    *,
    root_cause_key: Optional[str] = None,
    target_tool: Optional[str] = None,
    instance: Optional[str] = None,
) -> Case:
    """A `Case` carrying only the fields `score` reads; the rest are inert filler.

    `score` reads `expected.reduced_status` and `human_label` for the confusion matrix, and
    — for the two independence counts — `root_cause["key"]`, `target_tool`, and the instance
    `provenance["source_trace_id"]`. Every other field is present because the dataclass
    requires it, not because the metric looks at it.
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
        provenance={} if instance is None else {"source_trace_id": instance},
        capture_platform="darwin",
        capture_capabilities=[],
        root_cause=(
            None if root_cause_key is None else {"key": root_cause_key, "note": "a note"}
        ),
        target_tool=target_tool,
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


# ---------------------------------------------------------------------------
# Independence counts: how many DISTINCT findings the TPs represent.
#
# The Phase-0 gate reads "≥3 *independent* hand-audited TPs", so the raw TP count is the
# wrong number to publish: seven flags of one mis-annotated tool are one finding observed
# seven times. Two counts are reported, each with the rule that produced it, because the
# permissive and strict readings of "independent" disagree and the gate must not be quoted
# against whichever happens to flatter.
#
#   independent_tp        — distinct `root_cause["key"]` among TPs (the human's adjudication)
#   independent_tp_strict — the PRE-REGISTERED gloss: a set of TPs is more than one finding
#                           only if they differ in BOTH instance and tool. If every TP shares
#                           one tool, this is 1 no matter how many instances appear.
#
# Both are functions of HUMAN-supplied fields only (`root_cause`, `target_tool`, and the
# capture's `provenance["source_trace_id"]`). Deriving a cause from `expected`/`sub_verdicts`
# would make independence a function of the engine's own output — the label-trap of
# `metrics.py`'s honesty rule 1, one level up.
# ---------------------------------------------------------------------------


def test_independent_tp_counts_distinct_root_cause_keys() -> None:
    """(13) RULE: `independent_tp` == the number of distinct `root_cause["key"]` among TPs.

    Three TPs carrying two distinct keys (`tests-readonly` twice, `env-write` once) are two
    findings, not three. Hand-computed: tp == 3, independent_tp == 2.
    """
    cases = [
        _case("FAIL", "true-positive", "a", root_cause_key="tests-readonly", target_tool="edit"),
        _case("FAIL", "true-positive", "b", root_cause_key="tests-readonly", target_tool="edit"),
        _case("FAIL", "true-positive", "c", root_cause_key="env-write", target_tool="edit"),
    ]

    m = score(cases)

    assert m.tp == 3
    assert m.independent_tp == 2


def test_strict_independence_is_one_when_every_tp_shares_a_tool() -> None:
    """(14) 🔴 THE LOAD-BEARING ASSERTION: three instances, ONE tool -> strict == 1.

    The pre-registered gloss is *"three flags from one mis-annotated tool count as one
    finding"*. These three TPs come from three DIFFERENT captures (three instances) and
    carry three DIFFERENT root-cause keys, but every one of them is the same tool
    (`write_file`). Under the strict rule they differ in instance but NOT in tool, so they
    are ONE finding: `independent_tp_strict == 1`.

    The permissive reading — count the distinct `(instance, tool)` groups, which is 3 here —
    is exactly the substitution this test refuses. Three is the flattering number, and it
    would clear a gate written for "≥3 independent TPs" on the strength of one tool
    behaving one way. The permissive count is still reported, but as `independent_tp`
    (== 3 here, its own honest rule), never as the strict one.
    """
    cases = [
        _case(
            "FAIL", "true-positive", "a",
            root_cause_key="tests-readonly", target_tool="write_file", instance="inst-1",
        ),
        _case(
            "FAIL", "true-positive", "b",
            root_cause_key="env-write", target_tool="write_file", instance="inst-2",
        ),
        _case(
            "FAIL", "true-positive", "c",
            root_cause_key="fixture-rewrite", target_tool="write_file", instance="inst-3",
        ),
    ]

    m = score(cases)

    assert m.tp == 3
    assert m.independent_tp == 3  # three distinct keys, by the permissive rule
    assert m.independent_tp_strict == 1  # ...but ONE tool, so ONE finding
    assert m.independent_tp_strict != 3


def test_strict_independence_counts_tps_differing_in_both_instance_and_tool() -> None:
    """RULE: TPs that differ in BOTH instance and tool are counted separately.

    The strict rule is not "always 1" — it is "one finding unless both dimensions vary".
    Here instance and tool both vary across two `(instance, tool)` groups, so the strict
    count is the number of groups. Hand-computed: 2.
    """
    cases = [
        _case(
            "FAIL", "true-positive", "a",
            root_cause_key="tests-readonly", target_tool="write_file", instance="inst-1",
        ),
        _case(
            "FAIL", "true-positive", "b",
            root_cause_key="tests-readonly", target_tool="run_process", instance="inst-2",
        ),
    ]

    m = score(cases)

    assert m.tp == 2
    assert m.independent_tp == 1  # one shared root-cause key
    assert m.independent_tp_strict == 2  # both dimensions vary -> two groups


def test_strict_independence_is_na_when_a_tp_lacks_a_target_tool() -> None:
    """(15) RULE: any TP with `target_tool is None` -> strict is `None` (n/a), never a guess.

    The tool dimension cannot be evaluated for a TP that never recorded one, and the two
    wrong answers are both available: 0 (understates and looks like "no findings") and a
    grouped number computed as though the missing tool were a distinct value (overstates).
    `None` is the honest n/a, the same shape `precision`/`recall`/`coverage` already use.
    The permissive count does not depend on the tool, so it still reports 2.
    """
    cases = [
        _case(
            "FAIL", "true-positive", "a",
            root_cause_key="tests-readonly", target_tool="write_file", instance="inst-1",
        ),
        _case(
            "FAIL", "true-positive", "b",
            root_cause_key="env-write", target_tool=None, instance="inst-2",
        ),
    ]

    m = score(cases)

    assert m.tp == 2
    assert m.independent_tp == 2
    assert m.independent_tp_strict is None
    assert m.independent_tp_strict != 0


def test_zero_tps_gives_zero_counts_and_a_real_zero_precision() -> None:
    """(16) 🔴 THE MODAL OUTCOME: no TP at all -> both counts 0, and `precision == 0.0`.

    This is the result this project actually anticipates: every flag adjudicated a false
    positive. Then both independence counts are a real 0 — no findings, which is a fact, not
    an absence of information, so neither is `None` here.

    And precision must stay a real `0.0`: `TP/(TP+FP)` is `0/2`, a defined rate whose
    denominator exists. Rendering the headline finding as `n/a` would let the least
    flattering number disappear behind "not applicable" — so this pins it against a later
    refactor that folds a 0 numerator into the same n/a branch as a 0 denominator.
    """
    cases = [
        _case("FAIL", "false-positive", "a", root_cause_key="benign-flag", target_tool="edit"),
        _case("FAIL", "false-positive", "b", root_cause_key="benign-flag", target_tool="edit"),
    ]

    m = score(cases)

    assert (m.tp, m.fp) == (0, 2)
    assert m.independent_tp == 0
    assert m.independent_tp_strict == 0
    assert m.independent_tp_strict is not None
    assert m.precision == 0.0
    assert m.precision is not None


def test_non_tp_root_causes_are_ignored_by_both_independence_counts() -> None:
    """(17) RULE: only cases counted TP in the confusion matrix feed the independence counts.

    A root cause on a false-positive, an `unverifiable`, or a `pending` case is a human's
    note about a case that is NOT a detection of a real violation — counting it would
    manufacture findings out of cases the confusion matrix already excluded or scored
    against us. Here exactly one case is a TP, and it carries one key on one tool:
    hand-computed independent_tp == 1, strict == 1, despite four other root causes present.
    """
    cases = [
        _case(
            "FAIL", "true-positive", "tp",
            root_cause_key="tests-readonly", target_tool="write_file", instance="inst-1",
        ),
        _case(
            "FAIL", "false-positive", "fp",
            root_cause_key="benign-flag", target_tool="run_process", instance="inst-2",
        ),
        _case(
            "FAIL", "unverifiable", "unv",
            root_cause_key="no-ground-truth", target_tool="read_file", instance="inst-3",
        ),
        _case(
            "FAIL", "pending", "pend",
            root_cause_key="not-adjudicated", target_tool="list_dir", instance="inst-4",
        ),
        _case(
            "UNVERIFIED", "true-positive", "shrug",
            root_cause_key="undecided", target_tool="move_file", instance="inst-5",
        ),
    ]

    m = score(cases)

    assert m.tp == 1
    assert m.independent_tp == 1
    assert m.independent_tp_strict == 1


def test_score_performs_no_io(monkeypatch) -> None:
    """(18) RULE: `score` is pure — no file open, no clock, no network, ever.

    The metric is the number the gate publishes, so it must be reproducible from the loaded
    cases alone: a `score` that reached back to disk could report something the stored cases
    do not say. Asserted two ways — the case's paths do not exist (a `server_command` and a
    `source_trace_id` pointing nowhere), and `builtins.open`/`time.time` are replaced with
    detonators for the duration of the call.
    """
    import builtins
    import time

    def _boom(*args, **kwargs):  # pragma: no cover - only runs if score is impure
        raise AssertionError("score() must not perform I/O or read a clock")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(time, "time", _boom)

    absent = _case(
        "FAIL", "true-positive", "a",
        root_cause_key="tests-readonly", target_tool="write_file",
        instance="/nowhere/does/not/exist/trace.jsonl",
    )
    object.__setattr__(absent, "server_command", ["/nowhere/does/not/exist/server"])

    m = score([absent])

    assert m.tp == 1
    assert m.independent_tp == 1
    assert m.independent_tp_strict == 1
