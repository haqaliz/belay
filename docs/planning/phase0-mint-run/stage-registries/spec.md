# Spec — `stage-registries`

**Aspect of:** `phase0-mint-run` · **PRD:** `docs/planning/phase0-mint-run/prd.md`
**Date:** 2026-08-09

## Problem slice

The driver preserves registry order (`batch.py:325` iterates records as loaded), and
`selected.json` appends the 3 controls **last** (`draw_mint_set.py:122`) — so the PRD's
"controls FIRST, always" (req. 2) is a registry property, not a driver property. The funded
mint needs committed registries for stage 1 (one control) and stage 2 (3 controls + 7 real,
controls at the head). The third control (`control__requests-read-then-write`) has **never**
been driven live — stage 2 is its first coverage.

## In scope

1. **`eval/instances/stage4a.json`** — 1 record: `control__flask-read-only`, header naming
   the stage and provenance.
2. **`eval/instances/stage4.json`** — 10 records: the 3 controls at the head, then 7 real
   instances, all from `selected.json`; header mirroring the `stage2.json` provenance shape
   (`source_pool`, `stage`, composition, `controls` expectations).
3. **The 7-real selection rule, decided and stated:** the first 7 real records of
   `selected.json` (small-repo block first: flask, requests, pylint, pytest, sphinx) that
   were **never captured in s2/s3** — fresh instances only, preserving repo spread. The
   excluded set is the banked list in `docs/technical/PHASE0_RESULTS.md` (the 15 named
   instances, incl. the 12 s3 + 9 s2 union).
4. A small deterministic generator script `eval/scripts/build_stage4_registry.py` (offline,
   no network) that reads `selected.json` + the excluded set and emits both registries
   byte-stably, plus a unit test asserting the shape contract.

## Out of scope

- Re-drawing or re-seeding the pool — `selected.json` (seed `20260723`) is untouched.
- Any change to the driver, `registry.py`, or `selected.json` itself.
- A separate stage-3 registry — stage 3 is `selected.json` verbatim (controls in-batch,
  `phase0-live-mint/prd.md` must-have 15).

## Acceptance criteria (test-first)

1. Test (RED first) on the generator: for both output files — `instances[0:3]` are the 3
   controls in `CONTROL_RECORDS` order; exactly 7 real records follow; every record exists
   in `selected.json` with byte-identical fields; none of the 7 real is in the excluded
   set; the header carries `source_pool`, `stage`, `seed: 20260723`, and `controls` with
   `CONTROL_EXPECTATIONS`.
2. `load_registry` accepts both files (round-trip via the shipped loader).
3. Re-running the generator produces byte-identical files (determinism).
4. `uv run pytest` stays green at the baseline + new tests.

## Dependencies & sequencing

Second aspect — blocked by nothing; blocks the `mint-run` stage-2 freeze (the frozen
invocation names `stage4.json`). The excluded-set list is read from `PHASE0_RESULTS.md`'s
banked-instances table — if the list is ambiguous, the script takes it as an explicit
committed literal, never inferred.

## Open questions / risks

- If fewer than 7 fresh small-repo instances exist, top up from django/sympy in
  `selected.json` order and state the composition in the header — the generator asserts
  ≥7 exist or fails loud.
- Registry choice is a fixed artifact once committed: the frozen stage-2 invocation and the
  registry must land in the **same commit** as the freeze, so the git history proves what
  was actually driven.
