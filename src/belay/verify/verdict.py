"""The Verdict, its four statuses, and the reduction that combines them.

Every verdict Belay emits is a `Verdict` — a fact grounded in something concrete (a state
diff, a violated invariant, an annotation contract), never an opinion. A turn is many
sub-checks, so we need one rule to fold them into a single status, and `reduce` is it:
worst-status-wins.

The ordering is the delicate part, and it is not what you would reach for first.
**UNVERIFIED ranks ABOVE PASS and WARN** (below only FAIL). This is the honesty contract
— "UNVERIFIED is never rendered as PASS" — expressed as the shape of the reduction rather
than a rule bolted on top: a turn with one sub-check we could not verify and one that
passed reduces to UNVERIFIED, because "we could not check this" is a stronger statement
about the turn than "this part looked fine". Rank UNVERIFIED below PASS and a turn you
failed to verify is reported clean; that is the exact false pass this project exists to
prevent, and tests/test_verdict.py guards the ordering against it.

The reduction is **axis-agnostic** on purpose. It reads `status`, never `axis`, so A1 (C5,
invariants) and A3 (C8, claim re-derivation) fold in unchanged. A3's "downgrade only, never
promote" property falls out for free: since A3 emits only WARN/FAIL/UNVERIFIED and worst
wins, an A3 sub-check can lower a turn's status but never lift it. No axis-specific code
lives here, and none should.

Pure data and logic: no model, no network, no re-execution. Those live in the checks that
build Verdicts, not in the Verdict itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Sequence


class Status(str, Enum):
    """The honest verdict statuses. `str` mixin so a Status serializes as its name.

    The first four are the scored statuses — the ones a turn can reduce to, ordered by
    `_RANK` below. `NOT_COVERED` is different in kind and is deliberately listed apart.
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"

    #: **Sub-verdict only.** A dimension Belay structurally cannot observe — not an
    #: abstention but a coverage boundary. UNVERIFIED says "we tried to check this and
    #: could not"; NOT_COVERED says "this was never inside what Belay claims to check",
    #: and folding the second into worst-status-wins would let one unobservable dimension
    #: (a tool's `openWorldHint: false` network promise) permanently sink every turn that
    #: Belay verified perfectly. `reduce` therefore filters it out before ranking, and a
    #: turn's reduced status can never be NOT_COVERED — downstream readers depend on that
    #: (see `reduce`). It is never rendered as PASS: a surface that shows a status must
    #: also show what was outside coverage.
    NOT_COVERED = "NOT_COVERED"


# Worst-status-wins severity. FAIL > UNVERIFIED > WARN > PASS. UNVERIFIED outranking PASS
# and WARN is the load-bearing choice — see the module docstring. Change this and you
# change the honesty contract.
#
# NOT_COVERED carries a rank only so a future caller that ranks a status without filtering
# first raises nothing mysterious — it is never reached through `reduce`, which drops it
# beforehand. The value is a floor, NOT a "loses to everything" ordering that would make
# `reduce([NOT_COVERED])` return it; that shape is precisely the false PASS this status
# must not create, and it is why the filter, not the rank, is the mechanism.
_RANK: dict[Status, int] = {
    Status.NOT_COVERED: -1,
    Status.PASS: 0,
    Status.WARN: 1,
    Status.UNVERIFIED: 2,
    Status.FAIL: 3,
}


@dataclass(frozen=True)
class Verdict:
    """One grounded sub-check result.

    `axis` names the verdict axis ("A1"/"A2"/"A3"); `kind` names the specific check within
    it ("replay", "effect", "invariant", …). `observed` and `expected` carry the concrete
    grounding — a state diff, an annotation contract and the paths it covers, whatever the
    check compared. They are typed permissively because different checks ground differently;
    a reader inspects them knowing which `kind` produced the verdict. `message` is the
    human-readable one-line summary.
    """

    axis: str
    kind: str
    status: Status
    observed: Optional[Any]
    expected: Optional[Any]
    message: str


def reduce(verdicts: Sequence[Verdict]) -> Status:
    """Fold sub-check verdicts into one status by worst-status-wins.

    NOT_COVERED sub-verdicts are dropped BEFORE ranking. They state a coverage boundary,
    not a finding, so they must not lower (or raise) a turn — and this filter, rather than
    a losing rank, is what guarantees the reduced status is never NOT_COVERED. That
    guarantee is load-bearing downstream: `corpus/metrics.py` folds any not-FAIL status
    into a decided non-detection, `corpus/case.py` is fail-closed on unknown reduced
    statuses, and `phase0/ledger.py`'s `total_turns()` sums every value into its
    denominator. A leaked NOT_COVERED would read as a verified clean turn in all three.

    An empty set — including one that is empty only AFTER the filter — reduces to
    UNVERIFIED, not PASS and not NOT_COVERED: a turn with no applicable checks verified
    nothing, and nothing-verified is never a pass.
    """
    scored = [v.status for v in verdicts if v.status is not Status.NOT_COVERED]
    if not scored:
        return Status.UNVERIFIED
    return max(scored, key=lambda s: _RANK[s])
