# Aspect — `mint-registry`

**Grade: deterministic.** Pure, offline, no spend. Gates the live run.

## Problem slice

A mint drives a **registry**, not a pool. This aspect builds the registry for a run whose
instance supply is nearly exhausted, and records that exhaustion honestly rather than
hiding it behind a draw that no longer means what it used to.

**Measured** (pool minus the union of every committed registry's real ids):

```
pool reals ................. 166
union of registry reals .... 137
FRESH (never driven) ........ 30   →  django 23, sympy 7
```

`eval/minting_driver/selection.py:3-24` records the reason the stratified draw exists:
*~83% of the eligible pool is django+sympy, so a uniform draw of 50 would publish a
django/sympy rate as an agent rate.* **The residue is ~100% django+sympy.** The draw's
own purpose cannot be served by what is left — and the correct response is to *state*
that, not to simulate stratification that no longer exists.

This is why Q1 decided **no violation rate is published** from this run.

## In scope

1. **A registry generator** in the committed pattern (`eval/scripts/build_*_registries.py`)
   producing the stage registries for this run from `pool.json` minus the observed/driven
   set, plus controls.
2. **Stage structure per Rule A** (`phase0-mint-run/prd.md:73-79`), sized for n≈12 (Q2):
   - **stage 1** — 1 control probe (instrument check before any real spend)
   - **stage 2** — controls **first**, then the real instances
   - Stage 3's ≥50 denominator is **not attempted**; the registry must make that explicit.
3. **Controls** from `eval/instances/controls.py`: CTL-1/2/3 plus **CTL-4**
   (`control__flask-verify-with-command`), the positive control, which only produces
   evidence under `--toolset filesystem+shell` and gives the trajectory axis its PASS side
   — the gap named as caveat (4) on the 18.3% result.
4. **Seed discipline.** A seed is only evidence if chosen before the draw was inspected.
   Any seed change appends to `SEED_HISTORY` with a reason; an empty history is the claim
   "drawn once" (`draw_mint_set.py:16-23`).
5. **A recorded provenance header** stating the pool composition beside the counts —
   honesty property 5 (`phase0-live-mint/prd.md:310-317`): *"The instance-pool composition
   is published beside the number."*

## Out of scope

- **Re-driving already-banked instances.** `CaseExistsError` is fail-closed with no
  `--overwrite` (`corpus/add.py:364-368`), and `observed.json` exists precisely so a
  banked instance cannot inflate a denominator twice.
- Widening the eligibility filters to manufacture more instances. The three filters
  (`fetch_swebench_pool.py:24-38`) are pinned; the instruction is to **record a
  discrepancy, never tune the rule**.
- Any network fetch. `fetch_swebench_pool.py` is the only network-touching script and is
  human-run; `pool.json` is committed.
- Publishing a rate (Q1).

## Acceptance criteria (RED before GREEN)

| # | Criterion |
|---|---|
| B1 | The generator is **pure and offline** — no network, no clock, no ambient randomness; a local `random.Random(seed)` only, candidates sorted by `instance_id` before any shuffle |
| B2 | Re-running with an unchanged pool rewrites **byte-identical** output — `git status` staying clean *is* the reproducibility check (`draw_mint_set.py:137-142`) |
| B3 | Every drawn real instance is in `pool.json` and in **none** of the committed registries (the measured 30) |
| B4 | **Zero overlap with already-banked corpus case ids** — no drawn instance can collide on `trace-<instance>-*` |
| B5 | Controls are carried by the `is_control` **field**, never a naming convention on the id (`registry.py:18-20`) |
| B6 | CTL-4 is present and the registry records that it requires `--toolset filesystem+shell` |
| B7 | The registry **loads through the stock loader** (`registry.py:98-200`) with no error — fail-closed on blank/missing/duplicate |
| B8 | The provenance header records: pool size, driven size, fresh size, **per-repo composition**, seed, and an explicit statement that **n < 50 and this is not a gate run** |
| B9 | `SEED_HISTORY` is present; empty = "drawn once", or carries a reason per entry |
| B10 | A short-pool condition **raises** rather than drawing short — a short draw is a short denominator (`selection.py:54-60`) |
| B11 | Full suite green; baseline **2540 passed / 25 skipped / 12 deselected** |

## Dependencies & sequencing

- Depends on: nothing. Parallel with `a3-author`.
- Blocks: `mint-run`.

## Risks

| Risk | Note |
|---|---|
| **The draw cannot stratify** — ~100% django+sympy | Not fixable. Handled by *stating* it (B8) and by Q1's no-rate decision. The failure mode to avoid is publishing a number that looks comparable to 18.3% |
| n≈12 is too small to produce any trajectory FAIL | Real. A run that banks nothing is a **recorded result** — the same rule as R-A. Stage gating caps the cost |
| Drawn instances overlap prior *registries* but were never actually driven | B3 uses registry membership, which is conservative (a registry entry may never have been driven). Prefer the conservative set — it cannot collide |
| Controls trip D-3 and void the run | CTL-2/3 carry the anti-D-3 steering sentence (`controls.py:111-114`), which *lowers* the probability, never guarantees. Pre-registered and accepted |

## Open questions

- **Exact n.** Q2 says ≈12. Stage 2 in the precedent was 3 controls + 7 real; the gate run
  used 4 controls + 7 real. Matching the precedent (4 controls + ~8 real) keeps the shape
  comparable without claiming the denominator. Decide at plan time.
- **Should the remaining 30 be exhausted in one run or preserved?** Once driven, they are
  gone from the fresh pool forever — there is no more supply behind them. Preserving some
  keeps a future option open; spending all 30 maximizes this run's chance of catching
  something. **Lean: do not exhaust** — draw n≈12 and leave the rest, since a future unit
  may need a fresh population and none can be manufactured.
