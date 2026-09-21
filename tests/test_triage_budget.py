"""C10 aspect `budget` tests: the pure replay-budget decision machinery.

`decide_replays` is the pure slice of the triage capability: given one calibrated
suspicion score per turn (a `TriageScore`, or `None` when the seam abstained), decide
*which* turns get the expensive replay, behind two budget knobs:

- **threshold**: replay every turn whose score >= threshold (higher score = more
  likely to hide a violation, so the suspicious turns are the ones that earn a replay).
- **top-N**: replay exactly the N highest-score turns, ties broken by lowest turn
  index first.

With both knobs the rules are a **union** — a turn is replayed if either rule spares
it. With neither knob (shadow mode) every turn is replayed and every score recorded
alongside. This module only *orders and samples*: it never emits a verdict — a turn
the budget skips is the surfaces aspect's to render UNVERIFIED-by-budget, never PASS.

The honesty contract the decision machinery encodes is **fail-open on abstention**: a
turn whose triage call returned `None` is always replayed, never skipped, and never
consumes the top-N budget — a broken triage command must never shrink the replay
budget. All-abstain (every score `None`) is therefore full replay under any knob.

The skip cause: the surfaces aspect stamps a skipped turn with the verbatim cause
`"skipped by the triage budget"` (see `triage_budget`'s module docstring), and
`belay.replay.report.canonical_cause` maps it to the `TRIAGE_SKIPPED_BY_BUDGET`
bucket. The closed-vocabulary guard here fails if a future edit drops that
registration — mirroring `tests/test_interop_attach.py::test_replayed_cause_vocabulary_is_closed`.
"""

from __future__ import annotations


def _score(*pairs: float) -> list:
    """A per-turn fixture: `pairs` are `(score, confidence)` in turn order."""
    from belay.verify.triage import TriageScore

    return [TriageScore(score=score, confidence=confidence) for score, confidence in pairs]


# --- threshold: replay every turn at or above the bar -------------------------------------


def test_threshold_replays_exactly_the_turns_at_or_above() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.1, 0.9), (0.5, 0.8), (0.9, 0.7), (0.5, 0.6))
    assert decide_replays(scores, threshold=0.5) == frozenset({1, 2, 3})
    assert decide_replays(scores, threshold=0.51) == frozenset({2})


# --- top-N: replay exactly the N highest-score turns, ties by lowest index -----------------


def test_top_n_replays_exactly_the_n_highest_score_turns() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.1, 0.9), (0.9, 0.8), (0.5, 0.7), (0.7, 0.6))
    assert decide_replays(scores, top_n=2) == frozenset({1, 3})
    assert decide_replays(scores, top_n=1) == frozenset({1})


def test_top_n_ties_break_by_lowest_turn_index_first() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.8, 0.9), (0.8, 0.8), (0.4, 0.7))
    assert decide_replays(scores, top_n=1) == frozenset({0})  # 0.8 @0 and @1: lowest index wins
    assert decide_replays(scores, top_n=2) == frozenset({0, 1})


# --- union: either knob may spare a turn ---------------------------------------------------


def test_both_knobs_union_a_turn_replays_if_either_rule_spares_it() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.9, 0.9), (0.8, 0.8), (0.7, 0.7), (0.2, 0.6), (0.1, 0.5))
    threshold_spared = decide_replays(scores, threshold=0.5)  # {0, 1, 2}
    top_n_spared = decide_replays(scores, top_n=2)  # {0, 1}
    combined = decide_replays(scores, threshold=0.5, top_n=2)
    assert combined == threshold_spared | top_n_spared == frozenset({0, 1, 2})
    assert combined != threshold_spared & top_n_spared  # turn 2 spared by threshold alone


# --- shadow mode: no knobs ⇒ replay everything, scores recorded ----------------------------


def test_shadow_mode_no_knobs_replays_everything_and_records_scores() -> None:
    from belay.verify.triage_budget import decide_replays, shadow_mode

    scores = _score((0.9, 0.9), (0.2, 0.8), (0.5, 0.7))
    assert decide_replays(scores) == frozenset({0, 1, 2})
    observed = shadow_mode(scores)
    assert observed.replay_indices == frozenset({0, 1, 2})
    assert observed.scores == tuple(scores)


# --- fail-open on abstention: a turn the seam could not score is never skipped -------------


def test_all_abstain_replays_everything_fail_open() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = [None, None, None]
    assert decide_replays(scores) == frozenset({0, 1, 2})
    assert decide_replays(scores, threshold=0.9) == frozenset({0, 1, 2})
    assert decide_replays(scores, top_n=1) == frozenset({0, 1, 2})


def test_abstained_turn_is_never_skipped_and_consumes_no_top_n_budget() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = [None, *_score((0.9, 0.9), (0.1, 0.8), (0.8, 0.7))]
    assert decide_replays(scores, threshold=0.85) == frozenset({0, 1})
    # top_n=2 selects {1, 3} on score, and the abstained turn 0 replays regardless
    # (fail-open) without eating one of the two budget slots.
    assert decide_replays(scores, top_n=2) == frozenset({0, 1, 3})


# --- edge shapes ---------------------------------------------------------------------------


def test_empty_turn_list() -> None:
    from belay.verify.triage_budget import decide_replays, shadow_mode

    assert decide_replays([]) == frozenset()
    assert decide_replays([], threshold=0.5) == frozenset()
    assert decide_replays([], top_n=3) == frozenset()
    observed = shadow_mode([])
    assert observed.replay_indices == frozenset()
    assert observed.scores == ()


def test_top_n_larger_than_turn_count_replays_everything() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.9, 0.9), (0.1, 0.8))
    assert decide_replays(scores, top_n=10) == frozenset({0, 1})


def test_threshold_zero_and_one() -> None:
    from belay.verify.triage_budget import decide_replays

    scores = _score((0.0, 0.9), (0.5, 0.8), (1.0, 0.7))
    assert decide_replays(scores, threshold=0.0) == frozenset({0, 1, 2})
    assert decide_replays(scores, threshold=1.0) == frozenset({2})


# --- the skip cause: registered in the closed vocabulary, rendered by canonical_cause -------


def test_triage_skip_cause_constant_is_registered_and_renders() -> None:
    from belay.replay.report import TRIAGE_SKIPPED_BY_BUDGET, canonical_cause

    assert isinstance(TRIAGE_SKIPPED_BY_BUDGET, str)
    assert TRIAGE_SKIPPED_BY_BUDGET.strip()
    label = canonical_cause(TRIAGE_SKIPPED_BY_BUDGET)
    assert label == TRIAGE_SKIPPED_BY_BUDGET
    assert label != "unrestorable (no recorded cause)"  # never the causeless catch-all


def test_triage_cause_vocabulary_is_closed() -> None:
    """Every `TRIAGE_*` cause constant declared in `report` must be registered as a
    `_PREFIX_LABELS` label. If a future edit adds a `TRIAGE_*` bucket and does not
    register it, `canonical_cause` can never reach it — the bucket exists, renders on
    no surface's breakdown, and stays permanently empty (G4-unmet). Fail loudly.
    """
    from belay.replay import report as report_module
    from belay.replay.report import TRIAGE_SKIPPED_BY_BUDGET

    declared = {
        value
        for name, value in vars(report_module).items()
        if name.startswith("TRIAGE_") and isinstance(value, str)
    }
    registered = {label for _prefix, label in report_module._PREFIX_LABELS}

    assert TRIAGE_SKIPPED_BY_BUDGET in declared
    assert declared <= registered, (
        "a TRIAGE_* cause constant is declared but not registered as a _PREFIX_LABELS "
        "label -- canonical_cause can never reach it",
        sorted(declared - registered),
    )