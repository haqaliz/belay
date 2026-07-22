# Aspect spec — `mint-execution`

**Parent PRD:** `docs/planning/phase0-live-mint/prd.md` (must-haves 14, 15; should-have 17)
**Sequencing:** third. Depends on `instance-registry` + `batch-harness` being green.
**This aspect spends real money and is never automated in CI.**

## Problem slice

Running the live mint. Everything before this is machinery; this is the experiment. It is
manual, staged, and gated — because the failure modes (fake PIVOT, TCC stall, `npx`
instability, runaway cost) are all cheaper to discover at n=1 than at n=65.

## In scope

1. **Pre-registration.** Copy the pre-registered gate criteria from the PRD into
   `docs/technical/PHASE0_RESULTS.md` **and commit it, before Stage 3 runs.** Ordering is
   non-negotiable: criteria written down first, mint second.
2. **Stage 1 — one instance.** Run the existing manual smoke
   (`tests/test_minting_driver_smoke.py`, `BELAY_EVAL_LIVE=1`), which by all evidence in
   the repo has **never been run**. Then one real registry instance end-to-end through the
   harness. Gate: **≥1 genuinely verifiable turn** and the rename bridge resolving against
   a *real* capture. Do not proceed otherwise.
3. **Stage 2 — ~10 instances.** Gate: verifiable turns across multiple repos; **measure and
   record per-instance wall-clock and inference cost**; confirm `npx` server stability
   across sequential sessions and that macOS TCC does not prompt mid-batch. Extrapolate to
   the full run and **agree a stop-loss before Stage 3**.
4. **Stage 3 — full mint.** Launch ~65–70 instances to land a denominator ≥50 after
   attrition. Includes the 2–3 clean control instances.
5. **Verification.** Run `belay phase0 run` per batch (filesystem, shell), producing two
   ledgers, then `belay phase0 report` on each.
6. **Control check.** If any clean control returns FAIL, **the mint is void** — the
   instrument is manufacturing violations. Reported with the same standing as
   `INSTRUMENT SUSPECT`, never quietly excluded.

## Out of scope

- Writing the results document or adjudicating cases (that is `audit-and-publish`).
- Any CI involvement. Every command here is `manual`-marked or run by hand.
- Changing the harness (that is `batch-harness`) — if a defect surfaces mid-stage, it goes
  back to that aspect with a failing test.

## Acceptance criteria

Mostly procedural rather than test-asserted; the *tests* live in the other aspects.

1. `PHASE0_RESULTS.md` contains the pre-registered criteria in a commit that **precedes**
   the Stage-3 mint commit. Verifiable from `git log`.
2. Stage 1 produces a real capture where `belay phase0 run` yields ≥1
   `VERIFIED_CLEAN`/`VERIFIED_FLAGGED` instance — i.e. **not** `INSTRUMENT SUSPECT`.
3. Stage 2 records per-instance wall-clock and cost, written into the planning dir.
4. Stage 3 yields a violation-rate **denominator ≥50** across the combined batches.
5. Every control instance's disposition is recorded, and a FAILing control is escalated
   rather than dropped.
6. The mint's raw outputs (ledgers, corpus cases) exist locally under gitignored paths;
   **no raw state is committed or egressed** (guardrail #6).

## Dependencies

- `instance-registry`, `batch-harness` — both green.
- macOS + Seatbelt (`belay sandbox check`).
- BYOK model key in env; pinned MCP servers (`eval/README.md:50-72`).

## Risks / open questions

- **R10 bandwidth / cost** — the reason for staging and the stop-loss. An abandoned
  half-finished mint is worse than a deliberately smaller, honestly-labeled one.
- **R7** — if UNVERIFIED dominates, that is a **gate signal**, reported as such, not a bug
  to hide or a run to quietly redo.
- **Attrition rate is unknown** — the ~65–70 launch target is an estimate. If Stage 2
  shows heavy attrition, the launch count is raised (or the shortfall is stated plainly).
- **Re-running the mint after a defect fix** produces a *new* observation, not a
  reproduction (`RUNBOOK.md:282`). Any decision to discard a partial mint must be
  disclosed in the results — silently re-rolling until the number looks good is precisely
  the dishonesty this project exists to prevent.
