"""C10 aspect `budget` — pure decision machinery: which turns earn the expensive replay.

Given one calibrated suspicion score per turn (a `TriageScore`, or `None` when the
triage seam abstained), `decide_replays` returns the exact set of turn indices to
replay, behind two budget knobs:

- **threshold**: replay every turn whose `score >= threshold`. Higher score = more
  likely to hide a violation, so the suspicious turns are the ones that earn a replay.
- **top-N**: replay exactly the N highest-score turns, ties broken by lowest turn
  index first.

With both knobs the rules are a **union**: a turn is replayed if either rule spares
it. With neither knob the run is **shadow mode**: every turn is replayed and every
score recorded alongside (`shadow_mode`), which is the safe default whenever a triage
command is configured — nothing is skipped until the calibration ledger earns a
tighter budget.

## The honesty contract (stated here once, like the seam's)

- **This module never emits a verdict.** It orders and samples the replay queue and
  nothing else: `PASS`/`WARN`/`FAIL`/`UNVERIFIED` stay with replay and execution.
- **A skipped turn is UNVERIFIED-by-budget, never PASS.** The caller (the surfaces
  aspect) renders every index *not* in the returned set as UNVERIFIED with the named
  cause below. This module never renders a status, so it can never manufacture a PASS
  for a turn it chose to skip.
- **Fail-open on abstention.** A turn whose triage call returned `None` is always
  replayed, never skipped, and never consumes the top-N budget — a broken or
  abstaining triage command must never shrink the replay budget. All-abstain
  (every score `None`) is therefore full replay under any knob combination.

## The exact skip-cause string (the surfaces aspect quotes this verbatim)

The surfaces aspect stamps a skipped turn with the raw cause:

    "skipped by the triage budget"

`belay.replay.report.canonical_cause` maps that verbatim string to the
`TRIAGE_SKIPPED_BY_BUDGET` bucket via its `_PREFIX_LABELS` entry, so every surface
that reports turns renders the named bucket and never the causeless
`"unrestorable (no recorded cause)"` catch-all. The registration is pinned by a
closed-vocabulary guard test (`tests/test_triage_budget.py`).

Stdlib only (dataclasses, typing). Pure functions — no subprocess, no I/O, no verdict
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from belay.verify.triage import TriageScore

#: The verbatim cause string the surfaces aspect stamps on a turn the budget skipped.
#: Registered in `belay.replay.report._PREFIX_LABELS` as the `TRIAGE_SKIPPED_BY_BUDGET`
#: bucket — see the module docstring; the surfaces aspect quotes this exact value.
SKIPPED_BY_BUDGET_CAUSE = "skipped by the triage budget"


@dataclass(frozen=True)
class ShadowModeResult:
    """What shadow mode observes: every turn replayed, every score recorded alongside.

    `replay_indices` is always the full turn set (nothing is skipped); `scores` is a
    faithful copy of the per-turn scores so the caller can carry them into the
    calibration ledger that this slice ships for and no further.
    """

    replay_indices: frozenset[int]
    scores: tuple[Optional[TriageScore], ...]


def decide_replays(
    scores: Sequence[Optional[TriageScore]],
    *,
    threshold: Optional[float] = None,
    top_n: Optional[int] = None,
) -> frozenset[int]:
    """The turn indices to replay, given one per-turn triage score (index = turn).

    `threshold` replays every turn whose `score >= threshold`; `top_n` replays exactly
    the N highest-score turns (ties broken by lowest turn index first). With both
    knobs the result is the **union** — a turn is replayed if either rule spares it.
    With neither knob every turn is replayed (shadow mode). A turn whose triage call
    returned `None` is always replayed — fail-open, and it never consumes a top-N
    budget slot.

    This is pure sampling: the returned set says nothing about verdicts. An index not
    in the set is the caller's to render UNVERIFIED-by-budget, never PASS.
    """
    if threshold is None and top_n is None:
        return frozenset(range(len(scores)))

    replay: set[int] = set()

    if threshold is not None:
        for index, score in enumerate(scores):
            # An abstention is fail-open: it can never push a turn off the replay path.
            if score is None or score.score >= threshold:
                replay.add(index)

    if top_n is not None:
        scored = [(index, score.score) for index, score in enumerate(scores) if score is not None]
        ranked = sorted(scored, key=lambda pair: (-pair[1], pair[0]))  # score desc, index asc
        replay.update(index for index, _score in ranked[:top_n])
        # Abstentions do not compete for a budget slot and are never skipped.
        replay.update(index for index, score in enumerate(scores) if score is None)

    return frozenset(replay)


def shadow_mode(scores: Sequence[Optional[TriageScore]]) -> ShadowModeResult:
    """Shadow mode: every turn replayed, every score recorded alongside — never a skip.

    The safe default whenever a triage command is configured: nothing is skipped until
    the calibration ledger earns a tighter budget, so this slice saves no cost and
    claims none. `replay_indices` is the full turn set by construction.
    """
    return ShadowModeResult(
        replay_indices=frozenset(range(len(scores))),
        scores=tuple(scores),
    )


__all__ = [
    "SKIPPED_BY_BUDGET_CAUSE",
    "ShadowModeResult",
    "decide_replays",
    "shadow_mode",
]