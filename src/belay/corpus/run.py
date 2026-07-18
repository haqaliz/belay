"""C6 Phase 3: `belay corpus run` — re-verify every stored case; regression != skip.

`corpus run` re-verifies every stored case against the live engine and asserts it still
reaches its recorded verdict. The corpus IS the regression suite: a case that no longer
reaches its `expected` verdict is a caught DRIFT in a detector, and the run exits non-zero
so the build breaks.

## The one property that carries this module: a SKIP is not a REGRESSION (and never a pass)

- A **REGRESSION** is a detector change that flipped a verdict — the engine now computes a
  different per-sub-verdict set than the case recorded. This is the signal the corpus exists
  to emit, and it must fail CI.
- A **SKIP** is "THIS box could not evaluate the case" — off the macOS Seatbelt substrate,
  the recorded server was not runnable / did not answer, a backend capability mismatch on
  restore. The case was not evaluated here, so it is neither a pass nor a regression, and a
  non-darwin CI box must not fail the build over a case it structurally cannot replay.

Conflating the two is the quiet failure: a naive "any non-match is a regression" would turn
every non-darwin run RED, and a "SKIP is basically a pass" would let a real regression hide
behind an environment excuse. So SKIP is decided FIRST and only for a closed set of
environment/substrate causes; everything else that differs from `expected` is a REGRESSION.

## Why the comparison pins the per-sub-verdict SET, not the reduced status (D4)

`classify_case` compares the WHOLE recomputed set — `reduced_status` AND every
`(axis, kind, status)` sub-verdict — against the stored `expected`. Comparing only the
reduced status would miss an axis silently regressing while some OTHER axis keeps the turn at
the same reduced status: an A1 invariant detector that stops catching corrupt success on a
turn a diverged A2 still FAILs would read as a MATCH. The corpus pins the set precisely so
that flip is a caught REGRESSION. `test_axis_flip_with_unchanged_reduced_status_is_regression`
is the teeth, captured RED against a reduced-status-only stub.

Zero runtime dependencies: stdlib only. The re-verification is C4/C5's `verify_turn`; the
comparison and classification here are pure data. No model is consulted.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from belay.corpus.case import load_case
from belay.replay.reader import read_trace
from belay.replay.report import REPLAY_DID_NOT_ANSWER, canonical_cause
from belay.snapshot.substrate import UnrestorableCause
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

#: The three outcomes a case re-verification can reach. A SKIP is deliberately a THIRD
#: state, not a shade of MATCH: it means "not evaluated here", and keeping it distinct is
#: what lets the corpus fail CI on a real regression without failing it on every box that
#: lacks the substrate.
MATCH = "MATCH"
REGRESSION = "REGRESSION"
SKIP = "SKIP"

#: The canonical cause buckets that mean "this box could not evaluate the case" — an
#: environment/substrate gap, never a detector change. `verify_turn` stamps a non-replayed
#: turn's TurnVerdict.cause with `report.canonical_cause(engine cause)` (see
#: `verify.turn._unverifiable_verdict`), so this set is expressed in the CANONICAL bucket
#: space that field actually holds, and `classify_case` canonicalises before matching so a
#: raw engine constant (as a hand-built test may carry) is recognised too.
#:
#: Assembled by reading the engine and substrate:
#:  - `report.REPLAY_DID_NOT_ANSWER` is the bucket for `engine.UNANSWERED_TARGET` — the
#:    server was re-invoked but never answered the target (it exited / timed out / could not
#:    spawn). That is "the server is not runnable on THIS box", the server-unavailable gap.
#:  - `UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH` (substrate.py) — the persisted
#:    snapshot needs a backend capability this box's restore substrate lacks (S1). A machine
#:    without the clonefile/APFS substrate the case was captured on lands here (and the
#:    up-front `sys.platform != "darwin"` gate in `run_case` covers the common case of the
#:    whole substrate being absent). This is a per-box capability gap, not a verdict flip.
#: Everything else that leaves a turn UNVERIFIED — a manifest missing from a self-contained
#: case, an unreadable frame — is engine/case corruption, a real divergence from `expected`,
#: and stays a REGRESSION. The set is deliberately narrow.
_SKIP_CAUSES = frozenset(
    {
        REPLAY_DID_NOT_ANSWER,
        UnrestorableCause.UNRESTORABLE_CAPABILITY_MISMATCH.value,
    }
)


@dataclass(frozen=True)
class Divergence:
    """One (axis, kind) whose recomputed status no longer matches what the case recorded.

    `expected_status` / `got_status` are the stored vs recomputed status strings; either is
    `None` when the sub-verdict is present on only one side (a whole axis appeared or
    vanished). The reduced-status divergence is carried with the sentinel kind
    `"reduced_status"` and an empty axis, so a report can name it alongside the sub-verdicts.
    """

    axis: str
    kind: str
    expected_status: Optional[str]
    got_status: Optional[str]


@dataclass(frozen=True)
class CaseResult:
    """One case's re-verification outcome.

    `outcome` is `MATCH` / `REGRESSION` / `SKIP`. `divergences` is populated only for a
    REGRESSION — the diverging `(axis, kind, expected, got)` list. `skip_reason` is populated
    only for a SKIP — the environment/substrate cause that stopped evaluation here.
    """

    case_id: str
    outcome: str
    divergences: list[Divergence] = field(default_factory=list)
    skip_reason: Optional[str] = None


@dataclass(frozen=True)
class CorpusRun:
    """The whole-corpus aggregate: every `CaseResult`, with counts and the exit signal.

    `has_regression` is the exit contract in one place: the run exits non-zero IFF at least
    one case REGRESSED. A run that is all MATCH/SKIP is a clean exit — a pure SKIP is partial
    coverage (say so), never a CI failure.
    """

    results: list[CaseResult] = field(default_factory=list)

    @property
    def matches(self) -> int:
        return sum(1 for r in self.results if r.outcome == MATCH)

    @property
    def regressions(self) -> int:
        return sum(1 for r in self.results if r.outcome == REGRESSION)

    @property
    def skips(self) -> int:
        return sum(1 for r in self.results if r.outcome == SKIP)

    @property
    def has_regression(self) -> bool:
        return self.regressions > 0


def _recomputed_set(recomputed: TurnVerdict) -> dict:
    """The recomputed verdict as the same plain dict shape `corpus add` stored in `expected`."""
    return {
        "reduced_status": recomputed.status.value,
        "sub_verdicts": [
            {"axis": v.axis, "kind": v.kind, "status": v.status.value}
            for v in recomputed.sub_verdicts
        ],
    }


def _divergences(expected: dict, recomputed_set: dict) -> list[Divergence]:
    """Every (axis, kind) — plus the reduced status — whose recomputed status differs.

    Sub-verdicts are matched by `(axis, kind)` so an added/removed axis diverges against
    `None` rather than silently aligning by position. The reduced status is compared too, as
    a sentinel `reduced_status` divergence, so a report can name it. Empty iff the sets are
    identical, which is exactly the MATCH condition.
    """
    divergences: list[Divergence] = []

    exp_reduced = expected.get("reduced_status")
    got_reduced = recomputed_set["reduced_status"]
    if exp_reduced != got_reduced:
        divergences.append(Divergence("", "reduced_status", exp_reduced, got_reduced))

    exp_subs = {(s["axis"], s["kind"]): s["status"] for s in expected.get("sub_verdicts", [])}
    got_subs = {(s["axis"], s["kind"]): s["status"] for s in recomputed_set["sub_verdicts"]}
    for axis, kind in sorted(set(exp_subs) | set(got_subs)):
        exp_status = exp_subs.get((axis, kind))
        got_status = got_subs.get((axis, kind))
        if exp_status != got_status:
            divergences.append(Divergence(axis, kind, exp_status, got_status))

    return divergences


def classify_case(expected: dict, recomputed: TurnVerdict, *, case_id: str = "") -> CaseResult:
    """Compare a recomputed verdict against a case's stored `expected` — SKIP first, then diff.

    1. **SKIP first.** If the recompute could not EVALUATE the case on this box — the turn is
       UNVERIFIED with an environment/substrate cause in `_SKIP_CAUSES` — the case was not
       evaluated here. Return SKIP; it is neither a pass nor a regression.
    2. Else compare the WHOLE recomputed set (reduced status AND every `(axis, kind, status)`)
       against `expected`. Equal -> MATCH. Otherwise -> REGRESSION, naming each divergence.

    Pure: no replay, no server, no model. `case_id` stamps the result for the report; it is
    the one thing `classify_case` cannot read from its two data arguments.
    """
    if recomputed.status is Status.UNVERIFIED:
        cause = canonical_cause(recomputed.cause)
        if cause in _SKIP_CAUSES:
            return CaseResult(case_id=case_id, outcome=SKIP, skip_reason=cause)

    # MATCH is EXACT equality of the whole set — the ordered sub-verdict list too — so nothing
    # can collapse two like-`(axis, kind)` sub-verdicts into a false MATCH. The `(axis, kind)`
    # matching below is for naming the REGRESSION's divergences only, never for deciding it.
    recomputed_set = _recomputed_set(recomputed)
    if recomputed_set == expected:
        return CaseResult(case_id=case_id, outcome=MATCH)
    return CaseResult(
        case_id=case_id,
        outcome=REGRESSION,
        divergences=_divergences(expected, recomputed_set),
    )


def run_case(case_dir: Path) -> CaseResult:
    """Load a case, recompute its target turn by REAL re-verification, and classify it.

    `load_case` runs FIRST and is fail-closed: a corrupt case dir raises here, on every
    platform, before any platform gate — the corpus never silently drops an unreadable case.
    Off darwin the Seatbelt replay substrate is absent, so the case cannot be evaluated at all
    and is a SKIP decided up front, before a server is ever spawned.

    On darwin the turn is recomputed with `verify_turn`, passing `manifest_dir=case_dir`: the
    engine globs `case_dir/*.json`, matches the turn's recorded handle to `manifest.json`
    (case.json carries no `handle` and is skipped), and `load_snapshot` resolves the
    manifest's `tree_path="prestate"` against `case_dir` — so the case replays from itself
    alone. Invariants are rebuilt from the stored policy with `os.fsencode`, mirroring how
    `verify`/`corpus add` built them.
    """
    case = load_case(case_dir)
    if sys.platform != "darwin":
        return CaseResult(
            case_id=case.id,
            outcome=SKIP,
            skip_reason=(
                f"platform {sys.platform!r} is not darwin; the Seatbelt replay substrate is "
                f"macOS-only, so this case cannot be re-verified here"
            ),
        )

    records = read_trace(Path(case_dir) / "trace.jsonl").records
    invariants = [
        Invariant(scope=os.fsencode(d["scope"]), rule=d["rule"]) for d in case.invariants
    ]
    recomputed = verify_turn(
        records,
        case.target_turn_index,
        server_command=case.server_command,
        manifest_dir=Path(case_dir),
        invariants=invariants,
        replays=case.replays,
        timeout=case.timeout,
    )
    return classify_case(case.expected, recomputed, case_id=case.id)


def run_corpus(corpus_dir: Path) -> CorpusRun:
    """Re-verify every case directory under `corpus_dir` and aggregate the outcomes.

    Iterates the immediate subdirectories as case dirs and `run_case`s each. A corrupt case
    dir is fail-closed: `run_case`'s `load_case` raises a named `ValueError`, propagated here
    rather than swallowed, because a corpus that quietly dropped an unreadable case would
    regress against fewer cases than it holds — the exact false-completeness the corpus refuses.
    """
    corpus_dir = Path(corpus_dir)
    results = [run_case(d) for d in sorted(p for p in corpus_dir.iterdir() if p.is_dir())]
    return CorpusRun(results=results)


__all__ = [
    "MATCH",
    "REGRESSION",
    "SKIP",
    "CaseResult",
    "CorpusRun",
    "Divergence",
    "classify_case",
    "run_case",
    "run_corpus",
]
