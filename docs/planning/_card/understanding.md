# Understanding — corpus-trajectory-banking

**Worktree:** `feat/corpus-trajectory-banking` · **Source:** `docs/planning/_card/issue.md` (inline brief, belay-next pick 2026-08-31).

## What the work is really asking

Make the failure corpus able to hold what C6's contract promises: **every caught failure
becomes a labeled, replayable case** (`CAPABILITY_ROADMAP.md`, C6). The trajectory axis —
the one that earned the Phase-0 number (11/60 = 18.3%, trajectory-axis only) — produced
**zero banked cases** from the shell-toolset mint: the ingest collides with the per-turn
A2 namespace and the guard refuses. `corpus score` reads `n/a` on the axis that matters
most, and the AUDIT demands the fix "before any future mint trusts `phase0 run`'s
trajectory ingest" (`mint-shell-toolset-run/audit-and-publish/AUDIT.md:141-142`).

## The defect, mechanically (code-grounded)

- Every case id is minted at one site: `_safe_case_id(source_trace_id, target_turn_index)`
  → `f"{source_trace_id}-turn{n}"` (`src/belay/corpus/add.py:122-131`, minted at
  `add.py:316` inside `add_case`).
- The per-turn loop (`src/belay/phase0/runner.py:396-416`) and the trajectory block
  (`runner.py:418-499`) both call the same `ingester`; the trajectory case targets
  `final_turn = len(calls) - 1` (`runner.py:431`, `483`).
- When the final turn itself FAILs (per-turn A2), the per-turn loop banks
  `trace-<instance>-turn<final>` first; the trajectory block then mints the **identical
  id**; `CaseExistsError` (`add.py:324-328`) refuses — the guard is correct, the
  **namespace is the gap** (`AUDIT.md:131`). The refusal is bucketed, never propagated
  (`runner.py:498-499`), so nothing crashes — the trajectory case is just silently lost
  to `trajectory_unaddable`.
- In the mint's real shape, the per-turn cases were banked by the *first* verify pass; the
  trajectory ingest in the same run collided with them.
- The plan's own edge-case table promised coexistence: "Trajectory FAIL + turn FAILs on
  one instance → Both cases ingest" (`trajectory-success-invariant/corpus-trajectory/
  plan_20260809.md:134`). The code fails that promise whenever the turn FAIL is the final
  turn. No test exercised that shape (existing mixed test uses failing turn 1 ≠ final
  turn 2, and the collision test pins only the *rerun* collision).

## The fix surface

The trajectory case's **id namespace only**. The guard, the fail-closed pre-state checks,
the v4 schema, and the recompute routing are all correct and stay.

- **Id:** trajectory cases mint `f"{source_trace_id}-trajectory"` instead of
  `f"{source_trace_id}-turn{final}"`. Still derived, never random; still idempotent on
  recompose (a rerun refuses with `CaseExistsError`, exactly as today — that behavior is
  pinned and stays). `turnN` (N an int) can never collide with `trajectory`, so the two
  shapes are namespace-disjoint by construction.
- **Shape-awareness at one site:** `add_case` already receives the `trajectory` declaration
  (the v4 field); the id minting derives the namespace from the same input. No new CLI
  surface, no `--overwrite`, no new parameter, no change to per-turn ids
  (`test_case_id_is_deterministic_from_trace_and_turn` stays green unchanged).
- **Intra-ingest coexistence** (the plan's row 134): trajectory FAIL + final-turn FAIL on
  one instance → both cases bank, both recompute MATCH.
- **Unrestorable pre-state** (5 mint instances) stays unbankable: the pre-state check runs
  before the collision check by deliberate ordering (`add.py:303-314`), fail-closed, named
  cause. This is a negative test, not a casualty.

## Acceptance mapping (from the handoff)

1. Synthetic mint: trajectory FAIL + final-turn per-turn FAIL on one instance → both cases
   bank, `corpus run` → MATCH on both (RED first — the defect shape).
2. `corpus score` with labeled trajectory cases → precision/recall with **real
   denominators** (no `n/a` once labels exist). `score()` already reads only
   `expected.reduced_status` + `human_label`; a trajectory case's expected carries
   `reduced_status == "FAIL"` (`runner.py:464-478`), so no metrics change is expected —
   the test proves the pipeline end-to-end. Open question for the PRD: should the score
   report name the trajectory-shape count, or is the single precision/recall enough?
3. Unrestorable-pre-state trajectory FAIL → refuses to bank with the named pre-state
   cause; the instance disposition and denominator are untouched.
4. No verdict axis/status/number moves; docs state plainly: s6 captures are gone, nothing
   is backfilled, value is forward-looking (`docs/STATUS.md` v0.25.0 entry).

## Strategic-constraint check (CLAUDE.md)

- Harness only: corpus machinery, zero LLM. ✓
- Deepens moat #2 (compounding corpus); the deterministic spine is untouched. ✓
- UNVERIFIED-never-PASS: untouched; the pre-state abstention stays fail-closed. ✓
- Test-first: acceptance as RED tests before code. ✓

## Verdict-axis placement

None. This unit changes no verdict, axis, or status — it changes which **corpus case ids**
a FAIL's disposition can reach. A1/A2/A3 all untouched; `verify_turn`, `verdict.reduce`,
and every published number are pinned unchanged by existing tests.

## Open questions for the PRD

1. **Id string:** `-trajectory` suffix (proposal) vs `-trajectory-turn<final>` (more
   verbose, keeps the target turn visible in the id). The case already stores
   `target_turn_index`; the suffix is decoration.
2. **Score output:** name the trajectory-shape count in `corpus score` output (a `should`),
   or prove the end-to-end pipeline with no CLI change (a `must`-minimum)?
3. **Docs surface:** which docs carry the no-backfill statement — `corpus-trajectory/spec.md`
   (correct the namespace line), the AUDIT's follow-up line (close it), `CHANGELOG.md`
   (repo convention — check the format), `docs/STATUS.md` (append entry per convention)?
4. **The `_safe_case_id` signature:** shape-aware minting inside `add_case` (proposal) vs an
   explicit `case_id` override parameter (wider surface, caller-owned ids).
5. **`corpus run --shell-server`** (recorded NOT-built, `STATUS.md` v0.25.0): out of scope
   for this unit — the trajectory recompute already accepts the shell command at library
   level (`run.py:547`), and the CLI flag is a separate, named non-goal. Confirm in the PRD.

## Hazards

- `tests/test_corpus_trajectory_ingest.py` pins the old id in two assertions
  (`-turn1` at :214, `[turn1, turn2]` at :375) — these are the RED tests to change first,
  and the diff must show the namespace change is the only reason they moved.
- `test_rerun_trajectory_collision_never_errors_the_instance` pins the rerun-refusal
  behavior, not the id string — must stay green with the new id.
- The corpus-trajectory spec's "Out of scope" section forbids changing per-turn recompute —
  this unit touches per-turn **ids**? No — it must not; the per-turn minting is untouched.