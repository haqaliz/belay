# Aspect spec — corpus-trajectory

**Feature:** `trajectory-success-invariant` · **Aspect:** `corpus-trajectory` (third, after `trajectory-rule`) ·
**Date:** 2026-08-09

## Problem slice

Every caught failure must become a labeled, replayable corpus case (moat #2; C6's standing
rule: "a capability that catches nothing new does not ship"). Trajectory violations are
**instance-level** verdicts, but the corpus is turn-shaped (`case.json` expected verdict on a
target turn; `corpus run` recomputes via `verify_turn`). This aspect closes the gap: flags
from `suite-before-success-claim` become corrupt-success cases, and `corpus run` can
recompute their instance-level verdict so the regression-suite property holds for this rule.

## In scope

1. **Ingestion.** When an instance-level trajectory verdict is FAIL, `phase0 run` ingests a
   corrupt-success case exactly as it ingests flagged turns (`runner.py:320-339`): kind
   `corrupt-success`, rule `suite-before-success-claim`, target turn = the instance's final
   turn, violating evidence = the verdict's evidence list. The case's `trace.jsonl` already
   carries the whole trajectory **including the claim record** (aspect 1), so the case is
   self-contained.
2. **Case schema.** The stored `expected` must express the **instance-level** verdict without
   breaking the turn-level validation (`case.py:126-127`, `_KNOWN_STATUSES`, fail-closed
   validation). Design: the trajectory case stores its expected verdict under an optional
   instance-level field (or a distinct marker), schema-versioned — decide in the build with
   the existing v3/v4 discipline (never a silent field; old readers must not misread).
3. **`corpus run` recompute.** A case whose stored `invariants` include
   `suite-before-success-claim` is re-verified by the **instance-level path** over its own
   `trace.jsonl` (the case holds the full trajectory — no new data needed), not by
   `verify_turn`. `MATCH`/`REGRESSION` semantics carry over; `STILL_MISSED`/`MISS_CLOSED`
   (recorded-miss) interplay must be checked: can a recorded-miss case close against an
   instance-level verdict? (No real banked miss exists — the capability, not the result,
   must stay sound.)
4. **No regression on banked cases.** The 7 FP cases store only the old defaults
   (`corpus/run.py:429-431`) and are structurally untouched — pinned by test. New cases
   added by `phase0 run` now carry both rules in their stored invariants; the ordered
   sub-verdict exact-equality rule must be audited for the instance-level field's interplay
   (a trajectory sub-verdict is not a per-turn sub-verdict; `_divergences`'s `(axis, kind)`
   dict keying must not hide it — see `run.py:261-284`).
5. **Acceptance tests** (deterministic, no network, in CI): (a) a trajectory FAIL ingests a
   case with kind `corrupt-success`, rule `suite-before-success-claim`, target turn = final
   turn, claim record present in the stored trace; (b) `corpus run` on that case recomputes
   the same instance-level verdict → MATCH; (c) a deliberately regressed rule (e.g. the
   classifier flipped) fails `corpus run` naming the case; (d) the 7 banked FP cases remain
   MATCH with the new rule in the default set; (e) round-trip stability: a trajectory case
   replays to the same verdict on a second run.

## Out of scope

- Precision/recall claims on real data — no real trajectory case exists until a mint runs
  under the rule; adjudication is the owner-confirmed human protocol, not this aspect.
- Backfilling claims (aspect 1 boundary); classifier calibration; `belay corpus add`
  standalone trajectory support (bulk ingest from `phase0 run` is the required path;
  standalone add is a follow-up if demand shows).
- Any change to how per-turn cases are recomputed.

## Dependencies & sequencing

Depends on aspects 1 (claim kind) and 2 (instance-level verdicts + runner integration).

## Open questions / risks

- **Instance-level vs turn-level case shape:** the case format is turn-centric; an
  instance-level expected verdict must be represented without corrupting
  `verify_turn`-based recompute for ordinary cases. The build decides the field shape under
  the schema-versioning discipline.
- **Recorded-miss interplay:** declare-first protocol vs instance-level verdicts — confirm
  `recorded_miss` semantics compose (the capability must stay sound; no real miss exists to
  validate against).
- **Exact-equality audit:** adding an instance-level verdict field must not silently change
  MATCH semantics for per-turn cases.
