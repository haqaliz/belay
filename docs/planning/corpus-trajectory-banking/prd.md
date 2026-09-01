# PRD — corpus-trajectory-banking

**Unit:** `feat/corpus-trajectory-banking/aliz` (bbf, 2026-09-01) · **Phase 3 output**
(prd-interview) · **Source:** `docs/planning/_card/issue.md`, `docs/planning/_card/understanding.md`.

## Problem Statement

The failure corpus cannot hold what C6's contract promises — *"every caught failure becomes
a labeled, replayable case"* — on the trajectory axis, which is the axis that earned the
Phase-0 number. From the shell-toolset mint, **zero of the 23 trajectory FAILs banked**
(`docs/planning/mint-shell-toolset-run/audit-and-publish/AUDIT.md:122-142`), including all
11 hand-audited TPs. `belay corpus score` therefore reads `n/a` on the axis that matters
most, and the audit records the cause and the demand:

> *"Case-id collision: the trajectory ingest targets the same `trace-<instance>-turnN` id
> namespace as the per-turn A2 seam cases … the guard refuses to overwrite (**the guard is
> correct; the id namespace is the gap**) … The trajectory-case id-collision is a follow-up
> defect to fix before any future mint trusts `phase0 run`'s trajectory ingest."*
> — `AUDIT.md:124-142`; also `docs/technical/PHASE0_RESULTS.md:1189-1195`.

The collision is mechanical: both case shapes mint ids from the same
`_safe_case_id(source_trace_id, target_turn_index)` site
(`src/belay/corpus/add.py:122-131, 316`); the trajectory case targets the final turn
(`src/belay/phase0/runner.py:431, 483`), so whenever the final turn itself carries a
per-turn FAIL, the two ids are identical and `CaseExistsError` (`add.py:324-328`) refuses —
correctly. The refusal is bucketed (`runner.py:498-499`), so the trajectory case is lost
silently. The corpus-trajectory plan's own edge-case table promised coexistence:
*"Trajectory FAIL + turn FAILs on one instance → Both cases ingest"*
(`docs/planning/trajectory-success-invariant/corpus-trajectory/plan_20260809.md:134`).

## Goals & Success Metrics

1. **Banking works for the defect shape.** A synthetic mint whose final turn carries BOTH a
   per-turn FAIL and a trajectory FAIL banks both cases, and `belay corpus run` recomputes
   both as MATCH. (The defect shape has no passing test today.)
2. **Score denominators become real.** A banked, human-labeled trajectory case counts into
   `corpus score` precision/recall with a real denominator — proven end-to-end by test, with
   `score()` itself unchanged.
3. **Fail-closed honesty is preserved.** An unrestorable-pre-state trajectory FAIL refuses
   to bank with the named pre-state cause — never a guessed restore, never a drop from the
   instance's disposition or the violation denominator.
4. **Nothing else moves.** No verdict axis, status, or Phase-0 number changes; per-turn case
   ids are byte-identical; the reclassification discipline holds (`11/60 = 18.3%`, `precision
   0.00`, `1/15`, `4/16` stand unedited). The no-backfill fact is stated in the docs.

## User Personas & Scenarios

- **The mint operator** (the owner, next mint). Runs `belay phase0 run` over fresh
  instances; every trajectory FAIL banks as a labeled corrupt-success case, and `corpus
  run`/`corpus score` measure the trajectory axis with real denominators instead of `n/a`.
- **The harness engineer** (regression safety). A detection change that breaks trajectory
  detection now fails `belay corpus run` on a banked trajectory case — the axis's regression
  suite exists for the first time.

## Requirements

### Must-have

- **M1 · Disjoint namespace.** Trajectory case ids mint as `f"{source_trace_id}-trajectory"`
  (the confirmed format), derived and deterministic, never random — disjoint from the
  per-turn `-turnN` namespace by construction (turn indices are integers).
- **M2 · Intra-ingest coexistence.** One instance, trajectory FAIL + final-turn per-turn
  FAIL → both cases bank in the same `_verify_one_trace` invocation; the per-turn loop runs
  first, the trajectory block second, and the second does not collide.
- **M3 · Idempotent recompose.** Re-running the same verify over the same corpus refuses
  both shapes with `CaseExistsError` ("already exists") — the guard behavior is pinned and
  unchanged; no `--overwrite` anywhere. For the trajectory shape the rerun refusal must also
  preserve the stored case **byte-identically, including a human label** (the per-turn side
  already has that pin; the trajectory side gains it in this unit).
- **M4 · Unrestorable stays unbankable.** A trajectory FAIL naming an unrestorable
  pre-state is refused with the pre-state cause (the pre-state check runs before the
  collision check — ordering unchanged); the instance keeps its real disposition and stays
  in `violation_denominator()`.
- **M5 · Score end-to-end.** With `score()` unchanged, a labeled trajectory case (expected
  `reduced_status` FAIL, human label true-positive) yields precision/recall with real
  denominators in a mixed per-turn + trajectory corpus.
- **M6 · Per-turn ids untouched.** `_safe_case_id` behavior for per-turn cases is
  byte-identical; `test_case_id_is_deterministic_from_trace_and_turn` and the
  `CaseExistsError` suite stay green unchanged.

### Should-have

- **S1 · Named-cause surface.** The trajectory banking outcome (`trajectory_addable` /
  `trajectory_unaddable` with cause) continues to reach the ledger/report/CLI exactly as
  today — the fix changes the id, not the accounting.
- **S2 · Docs record corrected.** `corpus-trajectory/spec.md`'s namespace line is corrected
  to the new format; the AUDIT's follow-up line records the closure; `CHANGELOG.md` and
  `docs/STATUS.md` gain the entry with the no-backfill statement.

### Nice-to-have

- None. The unit is deliberately minimal.

## Technical Considerations

- **Capability:** C6 (failure corpus) follow-on slice — the C6 status block's own "every
  caught failure becomes a case" contract, extended to the trajectory shape's real shape.
  Dependencies C1–C6 are built; this unit touches none of the verdict machinery.
- **One minting site.** `add_case` already receives the v4 `trajectory` declaration; the id
  minting becomes shape-aware at `add.py:316` (deriving the namespace from the same input),
  rather than adding an explicit `case_id` override parameter (wider surface, caller-owned
  ids). No new CLI surface, no schema bump (v4 already declares `trajectory`; the id is an
  implementation detail of the corpus dir name).
- **Id consumers.** The plan verifies (grep, not assumption) that no code parses `-turnN`
  out of a case id — `case.json`'s `target_turn_index` is the only source of truth for a
  trajectory case's target turn (`corpus/run.py` recompute reads the stored trace, never
  the id). Current reading: corpus code treats ids as opaque.
- **Verdict impact: none.** No axis (A1/A2/A3), status, or verdict changes; `verify_turn`,
  `verdict.reduce`, and every published number are pinned by existing tests and must stay
  green.
- **Recompute routing is untouched.** Trajectory cases still route through
  `_recompute_trajectory_case` → `_verify_one_trace(ingest=False)` (`corpus/run.py:479-543`);
  MATCH/REGRESSION/STILL_MISSED/MISS_CLOSED transitions unchanged.
- **Test-first.** Acceptance is written as RED tests before code; the two existing
  assertions pinning the old id (`tests/test_corpus_trajectory_ingest.py:214, 375`) are the
  first tests changed, and the diff must show the namespace is the only reason they moved.
- **The no-backfill constraint.** The s6 captures no longer exist on disk
  (`docs/STATUS.md` v0.25.0 entry), so the mint's 11 TPs cannot be re-banked; the value is
  forward-looking. The docs must say this plainly — no implied retroactive precision.

## Risks & Open Questions

- **Effort (feasibility signal):** small unit — one minting-site change (`add.py`), zero
  runner/verify changes expected, ~5 test changes + 2 new tests, 3 doc surfaces, and the
  repo's release step (bump to v0.26.0 per `RELEASING.md`). Planned as one commit per
  aspect; the release commit carries the CHANGELOG dated section.
- **R1..R12 mapping:** none of the register's risks maps cleanly; this unit retires no R-id
  and opens none. It serves moat #2 (the compounding corpus), which the roadmap does not
  register as a numbered risk. The nearest discipline: the honesty rules — every number
  stands unedited; the no-backfill fact is stated, not hidden.
- **Id string ambiguity (resolved):** `-trajectory` suffix confirmed 2026-09-01.
- **Score surface (resolved):** `score()` unchanged; end-to-end proof test only.
- **`corpus run --shell-server` (resolved):** out of scope; recorded NOT-built in
  `STATUS.md` v0.25.0 and untouched by this unit.
- **Hazard:** the id namespace is load-bearing — `test_case_id_is_deterministic_from_trace_and_turn`
  and `test_readd_same_case_id_raises_case_exists` pin the per-turn format; a trace stem
  ending in `-trajectory` would yield a doubled suffix (`-trajectory-trajectory`) — harmless,
  deterministic, and not worth special-casing.
- **Edge:** a per-turn FAIL on a NON-final turn already coexists today
  (`test_mixed_instance_ingests_both_*`, green); the new coexistence is the final-turn
  variant — the only shape the old namespace could not hold.

## Out of Scope

- `belay corpus run --shell-server` CLI flag (named NOT-built; library seam exists).
- Standalone `belay corpus add` trajectory support and any change to per-turn recompute
  (the corpus-trajectory spec's "Out of scope" section — unchanged).
- Backfilling the mint's 11 TPs (impossible: s6 captures no longer exist) and any
  re-adjudication of the 12 unverifiable-by-seam instances.
- C8 (A3), C9 export-back, GHCR publish, N-server routing — the standing named non-goals.
- Any verdict-axis or schema change (no v5).