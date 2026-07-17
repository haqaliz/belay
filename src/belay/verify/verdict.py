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
    """The four honest verdict statuses. `str` mixin so a Status serializes as its name."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


# Worst-status-wins severity. FAIL > UNVERIFIED > WARN > PASS. UNVERIFIED outranking PASS
# and WARN is the load-bearing choice — see the module docstring. Change this and you
# change the honesty contract.
_RANK: dict[Status, int] = {
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

    An empty set reduces to UNVERIFIED, not PASS: a turn with no applicable checks verified
    nothing, and nothing-verified is never a pass.
    """
    if not verdicts:
        return Status.UNVERIFIED
    return max((v.status for v in verdicts), key=lambda s: _RANK[s])
