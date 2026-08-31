# Spec — case-id-namespace

**Aspect of:** `corpus-trajectory-banking` · `docs/planning/corpus-trajectory-banking/prd.md`
(requirements M1, M2, M3, M6, S1).

## Problem slice

The trajectory case id collides with the per-turn namespace. The fix is the trajectory
case's **id minting only**: the guard, the fail-closed pre-state checks, the v4 schema, the
`ValueError`/bucketing contract, and the recompute routing are all correct and stay.

## In scope

- `_safe_case_id` / `add_case` become shape-aware at the single minting site
  (`src/belay/corpus/add.py:316`): a case carrying the v4 `trajectory` declaration mints
  `f"{source_trace_id}-trajectory"`; a per-turn case mints `f"{source_trace_id}-turn{n}"`
  exactly as today. No new parameter, no CLI surface.
- The trajectory ingest path (`src/belay/phase0/runner.py:418-499`) passes through
  unchanged — the namespace derives from the declaration it already passes.
- `CaseExistsError` behavior for both shapes is preserved: rerun over the same corpus
  refuses, bucketed into `flagged_unaddable` / `trajectory_unaddable`, never overwrites,
  never errors the instance, never moves the disposition or denominator.

## Out of scope

- Per-turn id format (byte-identical).
- `corpus add`/`corpus run`/`score` behavior.
- Any schema change (no v5); the id is a corpus-dir implementation detail.

## Acceptance (RED first)

1. `test_trajectory_fail_ingests_a_corrupt_success_case` — the pinned id assertion changes
   `[f"{stem}-turn1"]` → `[f"{stem}-trajectory"]`; `target_turn_index` and the
   `trajectory` declaration are unchanged.
2. `test_mixed_instance_ingests_both_the_turn_case_and_the_trajectory_case` — final-turn
   variant added: failing final turn + trajectory FAIL in one run → case names are
   `[f"{stem}-turn<final>", f"{stem}-trajectory"]` (the defect shape; RED before the fix).
3. `test_rerun_trajectory_collision_never_errors_the_instance` stays green — rerun refusal
   with the new id, "already exists" cause, `trajectory_addable is False`; extended to
   assert the stored trajectory case survives **byte-identically including a human label**
   (the per-turn analogue `test_readd_leaves_existing_case_byte_identical` is the model).
4. `test_case_id_is_deterministic_from_trace_and_turn` and the `CaseExistsError` suite stay
   green byte-for-byte.
5. The ledger/report surfaces render the trajectory banking outcome identically (no new
   field; S1).

## Dependencies & sequencing

First aspect. Touches `add.py` + `runner.py` (no runner change expected) + the ingest
tests. Runs darwin + Linux (no platform gate).

## Open questions

None — PRD decisions lock the format (`-trajectory` suffix), the surface (no new
parameter), and the guard (unchanged).