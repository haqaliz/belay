"""The pure decision table: is the new capture a REGRESSION of its banked baseline?

The gate compares TWO captures of the same run, which legitimately differ in shape —
so unlike `corpus run`'s exact-equality rule, this is a per-dimension TRANSITION
table, decided explicitly, never by a bare rank comparison. It is pure: plain dicts
in (the `baseline.json` expected set shape and the same `belay.verify.json`
builders' recomputed shape), a `GateComparison` out, no I/O, no replay, no server.

## The table

- **REGRESSION (exit 1):** a dimension that was PASS/WARN moves to FAIL — per turn
  ordinal (common ordinals only), the trajectory status (PASS -> FAIL; the engine's
  trajectory emits no WARN), the claim when the baseline DECLARED one (A3 never
  PASSes, so the stored side is WARN/FAIL/UNVERIFIED, and WARN -> FAIL is the only
  failing claim transition), and a NEW turn beyond the baseline's count that FAILs
  (acceptance 1's "new failing turn").
- **Named, reported, NEVER fail (exit 0):** every other changed transition —
  PASS/WARN -> UNVERIFIED (coverage loss, R7 discipline), any transition INTO WARN,
  any -> PASS, UNVERIFIED -> anything (an abstention becoming a failure is a fix,
  never a regression of a passing dimension), FAIL -> anything (still failing is
  not newly failing), a declared-but-absent claim, plus the SHAPE rows (turn-count
  shrink, tool rename, new non-failing turns) and the DRIFT rows (stored expected
  vs the baseline's own re-verification — engine-change evidence, named, never a
  failure).
- **SKIP (exit 2, rendered UNVERIFIED + named cause):** the baseline could not be
  re-verified HERE — its re-verification turned UNVERIFIED with a cause in the
  unrestorable vocabulary (`BASELINE_UNRESTORABLE`) or with the cross-substrate
  `UNRESTORABLE_CAPABILITY_MISMATCH` (`BASELINE_CAPABILITY_MISMATCH`, the corpus
  precedent). A skip produces NO comparison at all: no divergences, no shape, no
  drift — never a false clean, never a false regression.

The statuses travel as the verify builders' strings (`PASS`/`WARN`/`FAIL`/
`UNVERIFIED`); `None` marks a dimension present on only one side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

#: The named SKIP causes. Rendered as the gate's outcome cause on a preflight exit.
BASELINE_UNRESTORABLE = "BASELINE_UNRESTORABLE"
BASELINE_CAPABILITY_MISMATCH = "BASELINE_CAPABILITY_MISMATCH"

#: The exit reasons. `clean` = comparison ran and nothing regressed; `regression` =
#: at least one transition FAILed a dimension the baseline held PASS/WARN on;
#: `preflight` = the comparison could not run (skip_reason names why).
CLEAN = "clean"
REGRESSION = "regression"
PREFLIGHT = "preflight"

#: The cross-substrate cause, named once: the ONLY unrestorable cause the gate
#: distinguishes (the corpus precedent), because the operator's fix is a different
#: one — re-bank on this substrate — than a general restore failure.
_CAPABILITY_MISMATCH = "UNRESTORABLE_CAPABILITY_MISMATCH"
#: Every other cause in the unrestorable vocabulary (all `UnrestorableCause` values
#: and the gate's non-member `UNRESTORABLE_SNAPSHOT_FAILED`) share this prefix; the
#: absent-handle bucket ("unrestorable (no recorded cause)") does NOT match it, so
#: a snapshot-less baseline re-verifies as UNVERIFIED-without-skip, exactly as
#: `corpus run` treats an un-snapshotted turn.
_UNRESTORABLE_PREFIX = "UNRESTORABLE_"

#: The transitions that FAIL the gate. Decided by the table, never by ranking:
#: only a PASS/WARN dimension moving to FAIL regresses — an abstention becoming a
#: failure is a FIX, and FAIL staying FAIL is not newly failing.
_PASS_WARN_TO_FAIL = frozenset({"PASS", "WARN"})


@dataclass(frozen=True)
class Divergence:
    """One per-dimension transition, named with its expected->got.

    `dimension` names the compared thing (`"turn 3 (echo)"`, `"trajectory"`,
    `"claim"`); `expected`/`got` are the status strings, either `None` when the
    dimension exists on only one side. `regression` is True exactly for the
    transitions in the REGRESSION class — a divergence list with any True row is
    the gate's exit-1 condition, and a False row is a named, reported, never-failing
    change.
    """

    dimension: str
    expected: Optional[str]
    got: Optional[str]
    regression: bool


@dataclass(frozen=True)
class ShapeRow:
    """One named shape divergence: turn-count, tool rename, or a new non-failing turn.

    `kind` is one of `missing-turn` (the capture did LESS — a previously-recorded
    ordinal is absent), `tool-rename` (the same ordinal's tool name changed), and
    `new-turn` (a turn beyond the baseline's count that PASSed/WARNed/abstained).
    Shape rows are report-only, never a gate failure — verdict-worsening decides,
    and a run that did less is a shape change the operator sees, not a regression.
    """

    kind: str
    dimension: str
    expected: Optional[str]
    got: Optional[str]


@dataclass(frozen=True)
class GateComparison:
    """The whole comparison: one computation, two renderers.

    `divergences` are the per-dimension transitions on the CAPTURE side (regression
    and named rows together, each carrying its own `regression` flag); `shape` the
    shape rows; `drift` the stored-expected-vs-baseline-re-verification rows, which
    are ALWAYS non-failing by construction. `exit_reason` is `clean`/`regression`/
    `preflight`; `skip_reason` is set exactly when `exit_reason` is `preflight`.
    An empty comparison — no rows at all — is clean.
    """

    description: str
    divergences: list[Divergence] = field(default_factory=list)
    shape: list[ShapeRow] = field(default_factory=list)
    drift: list[Divergence] = field(default_factory=list)
    exit_reason: str = CLEAN
    skip_reason: Optional[str] = None


def _turn_map(turns: Sequence[dict]) -> dict[int, dict]:
    return {turn["ordinal"]: turn for turn in turns}


def _turn_dimension(expected: Optional[dict], recomputed: Optional[dict], n: int) -> str:
    tool = "?"
    if recomputed is not None and isinstance(recomputed.get("tool"), str):
        tool = recomputed["tool"]
    elif expected is not None and isinstance(expected.get("tool"), str):
        tool = expected["tool"]
    return f"turn {n} ({tool})"


def _turn_transition(expected: Optional[dict], recomputed: Optional[dict], n: int) -> Optional[Divergence]:
    """One common ordinal's reduced-status transition, or `None` when it is equality.

    The ONLY failing turn transition is PASS/WARN -> FAIL. Everything else that
    changed is named with `regression=False` — including PASS -> UNVERIFIED (the R7
    coverage-loss abstention) and UNVERIFIED -> FAIL (a fix, never a regression).
    """
    if expected is None or recomputed is None:
        return None
    exp_status = expected.get("status")
    got_status = recomputed.get("status")
    if exp_status == got_status:
        return None
    regression = exp_status in _PASS_WARN_TO_FAIL and got_status == "FAIL"
    return Divergence(
        _turn_dimension(expected, recomputed, n),
        exp_status,
        got_status,
        regression,
    )


def shape_divergences(expected_turns: Sequence[dict], recomputed_turns: Sequence[dict]) -> list[ShapeRow]:
    """The shape rows: tool renames, missing turns (shrink), new non-failing turns.

    A new turn that FAILs is NOT a shape row — `compare_verdict_sets` carries it as
    a REGRESSION divergence, because a new failure is acceptance 1's "new failing
    turn", never a report-only note.
    """
    rows: list[ShapeRow] = []
    expected_map = _turn_map(expected_turns)
    recomputed_map = _turn_map(recomputed_turns)
    for n in sorted(set(expected_map) | set(recomputed_map)):
        expected = expected_map.get(n)
        recomputed = recomputed_map.get(n)
        if expected is None:
            if recomputed is not None and recomputed.get("status") != "FAIL":
                rows.append(
                    ShapeRow(
                        "new-turn",
                        _turn_dimension(None, recomputed, n),
                        None,
                        recomputed.get("status"),
                    )
                )
            continue
        if recomputed is None:
            rows.append(
                ShapeRow(
                    "missing-turn",
                    _turn_dimension(expected, None, n),
                    expected.get("status"),
                    None,
                )
            )
            continue
        if expected.get("tool") != recomputed.get("tool"):
            rows.append(
                ShapeRow(
                    "tool-rename",
                    f"turn {n}",
                    expected.get("tool"),
                    recomputed.get("tool"),
                )
            )
    return rows


def compare_verdict_sets(
    expected_turns: Sequence[dict],
    recomputed_turns: Sequence[dict],
) -> tuple[list[Divergence], list[ShapeRow]]:
    """The per-turn half of the table: divergences on common ordinals + new-turn FAILs.

    Returns `(divergences, shape)`: every common-ordinal status change (regression
    and named rows), every new turn beyond the baseline's count that FAILs (a
    regression row with `expected=None`), and the shape rows (tool renames, missing
    turns, new non-failing turns). Equality on a common ordinal produces nothing.
    """
    divergences: list[Divergence] = []
    expected_map = _turn_map(expected_turns)
    recomputed_map = _turn_map(recomputed_turns)
    for n in sorted(set(expected_map) & set(recomputed_map)):
        row = _turn_transition(expected_map[n], recomputed_map[n], n)
        if row is not None:
            divergences.append(row)
    for n in sorted(set(recomputed_map) - set(expected_map)):
        turn = recomputed_map[n]
        if turn.get("status") == "FAIL":
            divergences.append(
                Divergence(_turn_dimension(None, turn, n), None, "FAIL", True)
            )
    return divergences, shape_divergences(expected_turns, recomputed_turns)


def compare_trajectory(expected: Optional[dict], recomputed: Optional[dict]) -> Optional[Divergence]:
    """The instance-level trajectory transition, or `None` on equality/absence.

    The trajectory emits PASS/FAIL/UNVERIFIED (never WARN), so the ONLY failing
    transition is PASS -> FAIL; a stored FAIL staying FAIL, a FAIL improving to
    PASS, and an abstention becoming a failure are all named, never failing.
    """
    exp_status = expected.get("status") if expected is not None else None
    got_status = recomputed.get("status") if recomputed is not None else None
    if exp_status == got_status:
        return None
    regression = exp_status == "PASS" and got_status == "FAIL"
    return Divergence("trajectory", exp_status, got_status, regression)


def compare_claim(expected: Optional[dict], recomputed: Optional[dict]) -> Optional[Divergence]:
    """The A3 claim transition — compared ONLY when the baseline DECLARED one.

    A3 never PASSes, so the stored side is WARN/FAIL/UNVERIFIED, and WARN -> FAIL is
    the only failing transition; a stored FAIL on both sides is equality (never a
    regression), a stored FAIL -> UNVERIFIED is reported not failing, and a
    declared-but-absent claim (no author at check time) is named with `got=None`,
    never a fail. An undeclared baseline claim means the dimension is absent on
    both sides of the comparison, whatever the capture carries.
    """
    if expected is None:
        return None
    exp_status = expected.get("status")
    got_status = recomputed.get("status") if recomputed is not None else None
    if exp_status == got_status:
        return None
    regression = exp_status in _PASS_WARN_TO_FAIL and got_status == "FAIL"
    return Divergence("claim", exp_status, got_status, regression)


def _baseline_skip(baseline_recomputed: dict) -> Optional[str]:
    """The SKIP decision over the baseline's own re-verification, or `None`.

    Any UNVERIFIED turn whose cause is in the unrestorable vocabulary means the
    baseline's pre-state cannot be restored on THIS box — the comparison target is
    not grounded on the current engine, so the whole comparison abstains with a
    named cause. The capability mismatch is the more specific diagnosis and names
    a different operator fix (re-bank on this substrate), so it outranks the
    general unrestorable bucket. Absent-handle abstentions carry the bucket
    "unrestorable (no recorded cause)" — no `UNRESTORABLE_` prefix — and are NOT a
    skip: a snapshot-less baseline re-verifies as UNVERIFIED on both sides.
    """
    capability = False
    unrestorable = False
    for turn in baseline_recomputed.get("turns", []):
        if turn.get("status") != "UNVERIFIED":
            continue
        cause = turn.get("cause")
        if not isinstance(cause, str):
            continue
        if cause == _CAPABILITY_MISMATCH:
            capability = True
        elif cause.startswith(_UNRESTORABLE_PREFIX):
            unrestorable = True
    if capability:
        return BASELINE_CAPABILITY_MISMATCH
    if unrestorable:
        return BASELINE_UNRESTORABLE
    return None


def _drift_rows(expected: dict, baseline_recomputed: dict) -> list[Divergence]:
    """Stored expected vs the baseline's re-verification — every difference, never a failure.

    These are the engine-change rows: the same dimensions as the capture comparison,
    but every changed transition is reported (PASS -> FAIL included — it is evidence
    the ENGINE changed, which is exactly what drift exists to surface) and none of
    them can ever fail the gate.
    """
    rows: list[Divergence] = []
    expected_turns = _turn_map(expected.get("turns", []))
    recomputed_turns = _turn_map(baseline_recomputed.get("turns", []))
    for n in sorted(set(expected_turns) & set(recomputed_turns)):
        exp_turn = expected_turns[n]
        got_turn = recomputed_turns[n]
        if exp_turn.get("status") != got_turn.get("status"):
            rows.append(
                Divergence(
                    _turn_dimension(exp_turn, got_turn, n),
                    exp_turn.get("status"),
                    got_turn.get("status"),
                    False,
                )
            )
    exp_traj = expected.get("trajectory")
    got_traj = baseline_recomputed.get("trajectory")
    exp_status = exp_traj.get("status") if exp_traj is not None else None
    got_status = got_traj.get("status") if got_traj is not None else None
    if exp_status != got_status:
        rows.append(Divergence("trajectory", exp_status, got_status, False))
    if expected.get("claim") is not None:
        exp_claim = expected["claim"].get("status")
        got_claim = baseline_recomputed.get("claim")
        got_claim_status = got_claim.get("status") if got_claim is not None else None
        if exp_claim != got_claim_status:
            rows.append(Divergence("claim", exp_claim, got_claim_status, False))
    return rows


def compare(
    description: str,
    expected: dict,
    recomputed: dict,
    *,
    baseline_recomputed: Optional[dict] = None,
) -> GateComparison:
    """The whole decision table: one capture-vs-baseline comparison.

    SKIP first: when `baseline_recomputed` shows the baseline cannot be re-verified
    on this box, the comparison abstains entirely (preflight + named skip_reason,
    zero rows) — never a false clean, never a false regression. Otherwise the
    capture side is compared against the STORED expected set (`divergences` +
    `shape`), the baseline's re-verification against the stored set (`drift`, never
    failing), and `exit_reason` is `regression` IFF at least one divergence is in
    the REGRESSION class. Pure: plain dicts in, one `GateComparison` out.
    """
    skip = _baseline_skip(baseline_recomputed) if baseline_recomputed is not None else None
    if skip is not None:
        return GateComparison(
            description=description,
            exit_reason=PREFLIGHT,
            skip_reason=skip,
        )

    divergences, shape = compare_verdict_sets(
        expected.get("turns", []), recomputed.get("turns", [])
    )

    trajectory_row = compare_trajectory(expected.get("trajectory"), recomputed.get("trajectory"))
    if trajectory_row is not None:
        divergences.append(trajectory_row)

    claim_row = compare_claim(expected.get("claim"), recomputed.get("claim"))
    if claim_row is not None:
        divergences.append(claim_row)

    drift: list[Divergence] = []
    if baseline_recomputed is not None:
        drift = _drift_rows(expected, baseline_recomputed)

    exit_reason = REGRESSION if any(row.regression for row in divergences) else CLEAN
    return GateComparison(
        description=description,
        divergences=divergences,
        shape=shape,
        drift=drift,
        exit_reason=exit_reason,
    )


__all__ = [
    "BASELINE_CAPABILITY_MISMATCH",
    "BASELINE_UNRESTORABLE",
    "CLEAN",
    "PREFLIGHT",
    "REGRESSION",
    "Divergence",
    "GateComparison",
    "ShapeRow",
    "compare",
    "compare_claim",
    "compare_trajectory",
    "compare_verdict_sets",
    "shape_divergences",
]