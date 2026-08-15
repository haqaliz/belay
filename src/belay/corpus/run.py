"""C6 Phase 3: `belay corpus run` — re-verify every stored case; regression != skip.

`corpus run` re-verifies every stored case against the live engine and asserts it still
reaches its recorded verdict. The corpus IS the regression suite: a case that no longer
reaches its `expected` verdict is a caught DRIFT in a detector, and the run exits non-zero
so the build breaks — **unless the case DECLARES that its stored verdict records a MISS AND
the divergence is exactly the one exempted transition**, where the direction is inverted and
reaching `expected` is the thing that is not agreement. The declaration exempts that ONE
transition, never the case: every other divergence on a declared case still breaks the build.
Read the next section before quoting a green run.

## What a GREEN run means, and what it does NOT

Read this before quoting a green run as evidence of anything. The meaning has moved twice
already — it once certified that Belay still MIS-FIRES identically, then that the A1 rule
still reaches PASS on turns a human adjudicated false positives — and both times the record
had to be corrected afterwards. So it is stated here rather than left to be inferred:

    a green `corpus run` means "no case REGRESSED". That is the whole claim.

It is literally `CorpusRun.has_regression`, and nothing else. In particular it does **NOT**
mean *"the engine catches everything in the corpus"*, and it does **NOT** mean *"every
recorded miss is still recorded as missed"* — a green run coexists with BOTH of the two
declared-miss outcomes, in opposite directions:

- `STILL_MISSED` — known, DECLARED blindness: a violation a human adjudicated real that the
  engine does not detect. It is green, and that is deliberate — a known-open miss is not a
  DRIFT, and failing the build on it would leave CI permanently red over a state the corpus
  exists to record. That is also exactly why `STILL_MISSED` is its own outcome rather than a
  `MATCH`: `MATCH` would certify blindness AS AGREEMENT, and a reader would take the green
  for coverage it does not have.
- `MISS_CLOSED` — a recorded miss the sharpened detector now CATCHES. Also green, because CI
  must not go red for a fix. In such a run a recorded miss is precisely NOT still missed,
  which is why the green cannot carry that clause either.

A green run is therefore a statement about **drift**, not about **coverage** and not about
what is still missed. Whatever else a reader wants from a run has to be read off the outcome
COUNTS, which is why they are printed and why the `STILL_MISSED` count also qualifies the
sign-off line; `belay corpus score`, against human labels, is where detection is measured.

## The one property that carries this module: a SKIP is not a REGRESSION (and never a pass)

- A **REGRESSION** is a detector change that flipped a verdict — the engine now computes a
  different per-sub-verdict set than the case recorded. This is the signal the corpus exists
  to emit, and it must fail CI. (The one exception is a case that DECLARES a recorded miss
  and whose flip is exactly the miss closing; see below. Every other flip, declared or not,
  is a REGRESSION.)
- A **SKIP** is "THIS box could not evaluate the case" — on a box with no sandbox backend
  (neither Seatbelt on darwin nor Landlock+seccomp on linux), the recorded server was not
  runnable / did not answer, a backend capability mismatch on restore (the cross-substrate
  case: banked on clonefile/APFS, replayed on copy-fidelity). The case was not evaluated
  here, so it is neither a pass nor a regression, and a box without the substrate must not
  fail the build over a case it structurally cannot replay.

Conflating the two is the quiet failure: a naive "any non-match is a regression" would turn
every run on a bare box RED, and a "SKIP is basically a pass" would let a real regression hide
behind an environment excuse. So SKIP is decided FIRST and only for a closed set of
environment/substrate causes; everything else that differs from `expected` is a REGRESSION —
again unless the case declares a recorded miss AND the difference is exactly the one exempted
transition, which is `MISS_CLOSED` and exits 0.

## A case older than the `task_prestate` format is a REGRESSION, and that is correct

Case format v2 bundles turn 0's pre-state (`task_manifest.json` + `task_prestate/`), which
is the baseline `no-assertion-weakening` is judged against. A case written before v2 whose
target turn is NOT 0 carries no such manifest, so the rule reaches UNVERIFIED with a named
cause, and a stored `expected` recording an A1 FAIL no longer matches: the case classifies
**REGRESSION** and the run exits non-zero.

**Do not add a new SKIP cause to quiet that.** A SKIP means "THIS box could not evaluate the
case" — an environment gap that differs between machines. A missing task pre-state is a
**case-format** gap, identical on every box, and filing it as SKIP would let a real detector
regression hide behind it. There is no migration tool: the upgrade path for a stale case is
to **re-add** it, and the REGRESSION is exactly what tells the operator to.

(A pre-v2 case whose target turn IS 0 evaluates normally — its one manifest genuinely IS
turn 0's, so the baseline is present and nothing degrades.)

## A case that DECLARES a recorded miss is classified in the opposite direction

`belay phase0 run` ingests FLAGGED turns and nothing else, so a violation the detector MISSES
never becomes a case by the bulk path. (`belay corpus add` enforces no such precondition —
pointing it at a turn the detector verified clean is how one gets in at all.) A case may
therefore DECLARE (`case.recorded_miss`) that its stored `expected` is a verdict the engine
produced but a human adjudicated a MISS — its `expected.reduced_status` is the CLEAN verdict,
and the clean verdict is the defect.

Comparing such a case against `expected` alone inverts both directions:

- the engine still misses it -> the sets are EQUAL -> `MATCH`, i.e. the regression suite
  certifies blindness AS AGREEMENT.
- the detector is sharpened and now CATCHES it -> the sets DIFFER -> `REGRESSION`, exit 1,
  i.e. **CI goes red for a fix**.

So a declared case reaches `STILL_MISSED` (equal sets — the known state, exit 0, but never
called agreement, and never counted as a MATCH) or `MISS_CLOSED` (the ONE exempted
transition: the reduced status AND the A1 `invariant` sub-verdict BOTH moving PASS -> FAIL
and nothing else diverging). **The escape exempts exactly one transition, not the case.** An
A2 divergence, a move to `WARN`, a move to `UNVERIFIED` without a `_SKIP_CAUSES` cause, an A1
flip the reduced status did not follow — every one of them is still a `REGRESSION`, because a
blanket "a declared case never regresses" would make each banked miss a hole in the suite.
And the exemption is decided the same way every other outcome here is — by CONSTRUCTING the
one patched expectation and demanding EXACT equality, never by inspecting a diff (see
`_closes_the_miss`), so the declaration cannot buy an escape from the exact-equality rule of
the next section either.

`classify_case` reads the DECLARATION and the verdicts, never `human_label`: `corpus score`
scores that field independently, and coupling regression detection to it would mean
relabelling a case silently moved the regression suite.

## A case that carries the schema-v4 `trajectory` declaration is INSTANCE-LEVEL

A trajectory case (`corpus-trajectory`) declares its expected verdict whole-trajectory —
`suite-before-success-claim` judged the run, not any turn — so no single `verify_turn` can
re-derive it, and `run_case` routes it through the INSTANCE path instead
(`_recompute_trajectory_case`): the whole stored trace is re-verified with
`_verify_one_trace` (`ingest=False`, the case's own `invariants`/`server_command`,
`manifest_dir=case_dir`), and the recomputed trajectory STATUS is compared against the
declared status (`_classify_trajectory_case`). MATCH/REGRESSION/STILL_MISSED/MISS_CLOSED
carry over on that one dimension — an instance-level miss closes exactly when the
declared-clean trajectory status recomputes PASS -> FAIL, mirroring `_closes_the_miss`'s
transition on the turn-level A1 axis. Per-turn cases are untouched; the two shapes coexist
in one corpus and each classifies on its own contract.

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

from belay.corpus.add import add_case
from belay.corpus.case import Case, load_case
from belay.phase0.runner import _verify_one_trace
from belay.replay.reader import read_trace
from belay.replay.report import REPLAY_DID_NOT_ANSWER, canonical_cause
from belay.snapshot.substrate import UnrestorableCause
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

#: The outcomes a case re-verification can reach. A SKIP is deliberately a THIRD state, not
#: a shade of MATCH: it means "not evaluated here", and keeping it distinct is what lets the
#: corpus fail CI on a real regression without failing it on every box that lacks the
#: substrate.
MATCH = "MATCH"
REGRESSION = "REGRESSION"
SKIP = "SKIP"

#: The two outcomes a case that DECLARES a recorded miss can reach instead (see the section
#: above). Both exit 0; neither is ever reachable without the declaration.
STILL_MISSED = "STILL_MISSED"
MISS_CLOSED = "MISS_CLOSED"

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
#:    without the clonefile/APFS substrate a case was captured on lands here — the
#:    cross-substrate consequence (darwin-banked case on linux, and the mirror), and the
#:    up-front `sys.platform` gate in `run_case` covers the common case of the WHOLE
#:    substrate being absent (no darwin/linux backend at all). This is a per-box capability
#:    gap, not a verdict flip.
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

    `outcome` is `MATCH` / `REGRESSION` / `SKIP` / `STILL_MISSED` / `MISS_CLOSED`.
    `divergences` is populated for a REGRESSION and for a MISS_CLOSED — the diverging
    `(axis, kind, expected, got)` list, which for a MISS_CLOSED names the very transition
    that closed the miss. `skip_reason` is populated only for a SKIP — the
    environment/substrate cause that stopped evaluation here.
    """

    case_id: str
    outcome: str
    divergences: list[Divergence] = field(default_factory=list)
    skip_reason: Optional[str] = None


@dataclass(frozen=True)
class CorpusRun:
    """The whole-corpus aggregate: every `CaseResult`, with counts and the exit signal.

    `has_regression` is the exit contract in one place: the run exits non-zero IFF at least
    one case REGRESSED. A run with no REGRESSION is a clean exit — a pure SKIP is partial
    coverage (say so), never a CI failure, and neither `STILL_MISSED` (a known-open miss) nor
    `MISS_CLOSED` (a miss a fix just closed) may exit CI non-zero. The counts are kept
    separate rather than folded into `matches`: a miss is not agreement.
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
    def still_missed(self) -> int:
        return sum(1 for r in self.results if r.outcome == STILL_MISSED)

    @property
    def miss_closed(self) -> int:
        return sum(1 for r in self.results if r.outcome == MISS_CLOSED)

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


#: The A1 sub-verdict the exempted transition is about. A miss closes when the invariant axis
#: — the ONLY axis that can catch a corrupt success — starts FAILing on a case it passed.
_A1_INVARIANT = ("A1", "invariant")


def _closes_the_miss(expected: dict, recomputed_set: dict) -> bool:
    """True IFF the recompute is `expected` with EXACTLY the miss-closing transition applied.

    The ONE transition a `recorded_miss` declaration exempts from REGRESSION: the reduced
    status and the A1 `invariant` sub-verdict, BOTH moving PASS -> FAIL. That is the detector
    the corpus banked a miss against having been sharpened until it catches the case — the
    change the corpus exists to drive, so it must not break the build.

    **Decided by CONSTRUCTION, then EXACT EQUALITY** — never by inspecting a diff. This
    module's whole comparison rule is exact equality of the recomputed set, ordered
    sub-verdict list included (see `classify_case`); a rule phrased over `_divergences` would
    silently inherit that helper's `(axis, kind)` keying and accept three shapes exact
    equality rejects: a REORDERED sub-verdict list, a DUPLICATED A1 sub-verdict, and — worst —
    two CONTRADICTORY A1 entries where the last one wins in the dict. Those are exactly what
    the exact-equality rule exists to prevent, so the declaration must not buy an escape from
    it. Instead: patch `expected` with the one transition and demand the recompute equal the
    patch, byte for byte.

    The two guards are what make it a TRANSITION rather than a destination. The stored verdict
    must have been PASS overall, and EVERY A1 `invariant` sub-verdict it carried must have
    been PASS — so an A1 sub-verdict that materialises where the case recorded none
    (`None -> FAIL`, not `PASS -> FAIL`) is a structural change to the axis set and stays a
    REGRESSION, and a stored WARN can never be patched to FAIL and exempted.

    **EVERY entry, not SOME entry.** A policy may declare more than one invariant, so a turn
    can carry more than one `("A1", "invariant")` sub-verdict, and `patched` forces all of
    them to FAIL. A guard asking only whether SOME entry was PASS would let a second entry at
    WARN ride the exemption — the same "anything -> FAIL" widening, reintroduced one entry
    over. All-or-nothing on the A1 axis is also the right reading of the transition: the
    legitimate close is "the invariant axis moved PASS -> FAIL and nothing else did", so two
    invariants moving together is a close, and one of two moving is not.

    `patched` is built FROM `expected` (`{**expected, ...}`), not from the two top-level keys
    `_recomputed_set` produces, and that one token is what keeps the two directions symmetric.
    STILL_MISSED compares `expected` WHOLE, so a stored `expected` carrying an UNKNOWN extra
    top-level key can never reach it; building the patch from the two known keys would have
    let that same case reach MISS_CLOSED — the exempting outcome reachable, the non-exempting
    one structurally not. Carrying the unknown key into `patched` makes equality fail and the
    case a REGRESSION, which is strictly NARROWER than the alternative and asserts no schema
    that `case.py` owns.
    """
    if expected.get("reduced_status") != "PASS":
        return False
    subs = expected.get("sub_verdicts", [])
    a1 = [s for s in subs if (s["axis"], s["kind"]) == _A1_INVARIANT]
    if not a1 or any(s["status"] != "PASS" for s in a1):
        return False

    patched = {
        **expected,
        "reduced_status": "FAIL",
        "sub_verdicts": [
            {**s, "status": "FAIL"} if (s["axis"], s["kind"]) == _A1_INVARIANT else s
            for s in subs
        ],
    }
    return recomputed_set == patched


#: The (axis, kind) of an INSTANCE-LEVEL divergence. A trajectory verdict is not a
#: per-turn sub-verdict: `_divergences`'s `(axis, kind)` dict keying matches recomputed
#: sub-verdicts against the stored `expected`, and an instance-level mismatch must be
#: reported by name on its own dimension — never collapsed into (or hidden among) the
#: turn-shaped keys.
_TRAJECTORY_DIVERGENCE = ("trajectory", "status")


def _trajectory_divergence(expected_status: Optional[str], got_status: Optional[str]) -> Divergence:
    """One instance-level mismatch, named on the trajectory dimension.

    `expected_status` / `got_status` are the stored vs recomputed trajectory STATUS;
    either is `None` when one side carried no verdict at all (a declaration with no
    rule to recompute it).
    """
    return Divergence(_TRAJECTORY_DIVERGENCE[0], _TRAJECTORY_DIVERGENCE[1],
                      expected_status, got_status)


def _classify_trajectory_case(
    expected: dict,
    recomputed_status: Optional[str],
    *,
    case_id: str,
    recorded_miss: Optional[dict],
) -> CaseResult:
    """Classify an instance-level recompute against a trajectory case's expected verdict.

    A trajectory case's contract is the INSTANCE-LEVEL status (`case.trajectory.status`),
    not any turn's `expected` set — the per-turn shape on the case is the final turn's
    proxy record, and `corpus run` re-derives the whole-trajectory verdict or nothing.
    Status equality is therefore the MATCH condition, decided on that one dimension:

    - equal -> MATCH, or **STILL_MISSED** when the case declares a recorded miss (equal
      there means the engine is still blind on the instance level, which is not agreement
      — the same inversion `classify_case` applies to turn-shaped cases).
    - otherwise -> REGRESSION, named on the trajectory dimension — unless the case
      declares a recorded miss AND the recompute is the ONE exempted instance-level
      transition, the declared-clean trajectory status moving PASS -> FAIL, which is
      **MISS_CLOSED**: the whole-dimension verdict the miss was banked against flipped
      to a catch, and a closed miss must not break the build.

    `recorded_miss` is the DECLARATION, passed in by `run_case` from the loaded case;
    `None` is an undeclared case. Pure: no replay, no server, no model.
    """
    expected_status = expected["status"]
    declared = recorded_miss is not None

    if recomputed_status == expected_status:
        return CaseResult(case_id=case_id, outcome=STILL_MISSED if declared else MATCH)

    divergence = [_trajectory_divergence(expected_status, recomputed_status)]
    if declared and expected_status == "PASS" and recomputed_status == "FAIL":
        return CaseResult(case_id=case_id, outcome=MISS_CLOSED, divergences=divergence)
    return CaseResult(case_id=case_id, outcome=REGRESSION, divergences=divergence)


def classify_case(
    expected: dict,
    recomputed: TurnVerdict,
    *,
    case_id: str = "",
    recorded_miss: Optional[dict] = None,
) -> CaseResult:
    """Compare a recomputed verdict against a case's stored `expected` — SKIP first, then diff.

    1. **SKIP first.** If the recompute could not EVALUATE the case on this box — the turn is
       UNVERIFIED with an environment/substrate cause in `_SKIP_CAUSES` — the case was not
       evaluated here. Return SKIP; it is neither a pass nor a regression. This outranks the
       declaration: a recorded miss is identical on every box, an environment gap is not.
    2. Else compare the WHOLE recomputed set (reduced status AND every `(axis, kind, status)`)
       against `expected`. Equal -> MATCH, or **STILL_MISSED** if the case declares a recorded
       miss (equal sets there mean the engine is still blind, which is not agreement).
    3. Otherwise -> REGRESSION, naming each divergence — unless the case declares a recorded
       miss AND the recompute equals `expected` with exactly the miss-closing transition
       applied (`_closes_the_miss`, itself an exact-equality test), which is **MISS_CLOSED**:
       the detector was sharpened and now catches the banked miss.

    `recorded_miss` is the DECLARATION, passed in by `run_case` from the loaded case; `None`
    (the default) is an undeclared case, whose classification is byte-for-byte what it was
    before the two new outcomes existed. This function never reads `human_label` — the labels
    `corpus score` scores stay independent of what the regression suite decides.

    Pure: no replay, no server, no model. `case_id` stamps the result for the report; it is
    the one thing `classify_case` cannot read from its data arguments.
    """
    if recomputed.status is Status.UNVERIFIED:
        cause = canonical_cause(recomputed.cause)
        if cause in _SKIP_CAUSES:
            return CaseResult(case_id=case_id, outcome=SKIP, skip_reason=cause)

    declared = recorded_miss is not None

    # EVERY outcome is decided by EXACT equality of the whole set — the ordered sub-verdict
    # list too — so nothing can collapse two like-`(axis, kind)` sub-verdicts into a false
    # MATCH, and nothing can collapse them into a false MISS_CLOSED either (`_closes_the_miss`
    # compares against a CONSTRUCTED expectation, not against a diff). The `(axis, kind)`
    # matching below is for NAMING the divergences only, never for deciding an outcome.
    recomputed_set = _recomputed_set(recomputed)
    if recomputed_set == expected:
        return CaseResult(case_id=case_id, outcome=STILL_MISSED if declared else MATCH)

    divergences = _divergences(expected, recomputed_set)
    if declared and _closes_the_miss(expected, recomputed_set):
        return CaseResult(case_id=case_id, outcome=MISS_CLOSED, divergences=divergences)
    return CaseResult(case_id=case_id, outcome=REGRESSION, divergences=divergences)


def _recompute_trajectory_case(case_dir: Path, case: Case, expected: dict) -> CaseResult:
    """Recompute an INSTANCE-LEVEL case through the instance path, and classify it.

    A trajectory case's expected verdict is whole-trajectory, so no single `verify_turn`
    can re-derive it. The whole stored trace is re-verified through the SAME instance
    machinery `phase0 run` verifies with (`_verify_one_trace`, `ingest=False` — the
    corpus is never written, and the ingester is unreachable): the case is
    self-contained, so `manifest_dir=case_dir` (the engine globs `case_dir/*.json` and
    matches the turns' recorded handles to the bundled manifests exactly as the per-turn
    path does), and the stored `invariants`/`server_command`/`replays`/`timeout` are
    passed through. The recomputed instance-level verdict's STATUS is compared against
    the expected status (`expected` is `case.trajectory`, already narrowed to a dict by
    the caller) by `_classify_trajectory_case`.

    `ingest=False` is what makes this a pure re-verification: `_verify_one_trace` skips
    the ingest loop wholesale, so a re-run over the case can never collide with it or
    write anything.
    """
    invariants = [
        Invariant(scope=os.fsencode(d["scope"]), rule=d["rule"]) for d in case.invariants
    ]
    instance = _verify_one_trace(
        Path(case_dir) / "trace.jsonl",
        source_trace_id=case.id,
        corpus_dir=case_dir,
        server_command=case.server_command,
        invariants=invariants,
        captured_at=case.provenance.get("captured_at", ""),
        replays=case.replays,
        timeout=case.timeout,
        manifest_dir_for=lambda _trace_path: Path(case_dir),
        verifier=verify_turn,
        ingester=add_case,
        ingest=False,
    )
    recomputed = instance.trajectory
    recomputed_status = recomputed.get("status") if recomputed is not None else None
    return _classify_trajectory_case(
        expected,
        recomputed_status,
        case_id=case.id,
        recorded_miss=case.recorded_miss,
    )


def run_case(case_dir: Path) -> CaseResult:
    """Load a case, recompute its target turn by REAL re-verification, and classify it.

    `load_case` runs FIRST and is fail-closed: a corrupt case dir raises here, on every
    platform, before any platform gate — the corpus never silently drops an unreadable case.
    On a platform with NO sandbox backend (neither darwin nor linux) the case cannot be
    evaluated at all and is a SKIP decided up front, before a server is ever spawned.

    A case carrying the schema-v4 `trajectory` declaration is an INSTANCE-LEVEL case:
    it is recomputed through the instance path (`_recompute_trajectory_case`) — the
    per-turn `verify_turn` below cannot re-derive a whole-trajectory verdict, and a
    trajectory case sent down it would regress against a final turn's verdict that is
    not its contract. Every other case takes the per-turn path below, byte-for-byte.

    On darwin AND linux the turn is recomputed with `verify_turn`, passing
    `manifest_dir=case_dir`: the engine globs `case_dir/*.json`, matches the turn's
    recorded handle to `manifest.json` (case.json carries no `handle` and is skipped),
    and `load_snapshot` resolves the manifest's `tree_path="prestate"` against
    `case_dir` — so the case replays from itself alone. A case banked on the OTHER
    substrate (clonefile/APFS on darwin, copy-fidelity on linux) refuses at restore
    with `UNRESTORABLE_CAPABILITY_MISMATCH`, which `classify_case` maps to SKIP with
    the named cause — the cross-substrate consequence, stated in README. Invariants
    are rebuilt from the stored policy with `os.fsencode`, mirroring how
    `verify`/`corpus add` built them.
    """
    case = load_case(case_dir)
    if sys.platform != "darwin" and not sys.platform.startswith("linux"):
        return CaseResult(
            case_id=case.id,
            outcome=SKIP,
            skip_reason=(
                f"platform {sys.platform!r} has no sandbox backend; the Seatbelt "
                f"(darwin) and Landlock+seccomp (linux) replay substrates are both "
                f"absent, so this case cannot be re-verified here"
            ),
        )

    if case.trajectory is not None:
        return _recompute_trajectory_case(case_dir, case, case.trajectory)

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
    return classify_case(
        case.expected, recomputed, case_id=case.id, recorded_miss=case.recorded_miss
    )


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
    "MISS_CLOSED",
    "REGRESSION",
    "SKIP",
    "STILL_MISSED",
    "CaseResult",
    "CorpusRun",
    "Divergence",
    "classify_case",
    "run_case",
    "run_corpus",
]
