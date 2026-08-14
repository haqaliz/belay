# Aspect Spec — mint-run

Part of `docs/planning/mint-shell-toolset-run/prd.md`. The staged run itself: setup,
frozen invocations, the three stages, per-stage verification and gates, ledgers.

## Problem slice

Every prior mint stopped at its own pre-registered gate. This aspect executes the
next mint under the shell-offered toolset (`--toolset filesystem+shell`) so the
trajectory rule can produce its first real-text measurement, and records each stage's
outcome verbatim, once, under the freeze protocol.

## In scope

- Environment setup: `eval/servers/` install (pinned versions) or
  `BELAY_EVAL_SERVER_ROOT`, scratch workspace outside macOS TCC dirs, `claude` CLI
  login check, `uv sync`.
- Fresh stage files `eval/instances/stage6{a,b,c}.json` (built via the existing
  registry tooling; stage 6b = 4 controls at the head + 7 fresh real = 11 records;
  stage 6c = the full remaining fresh non-control pool from a committed draw).
- Frozen invocation scripts `acceptance-stage1/2/3.sh` **containing no result**,
  committed before any run.
- Pre-flight smoke (PRD U8): `pytest-7432` under `filesystem+shell`, once.
- Stage runs (PRD U1–U5), once each, main thread, verbatim stdout committed.
- Per-stage verification (PRD U9): stock `belay phase0 run` + `belay phase0 report`,
  ledger copied into `mint-run/ledgers/`, ingest on.
- Gates: Rule A (stage 1), stage-2 gates incl. trajectory exposure ≥1 of 11 judged
  (D-1) and all controls `VERIFIED_CLEAN` (D-3 void), stage-3 denominator ≥50 with
  canonical block in `PHASE0_RESULTS.md` before the run.
- Findings notes per stage; corpus migration attempt (PRD S1); runbook walk
  corrections (PRD S2).

## Out of scope

- The audit and decision line — the `audit-and-publish` aspect.
- Any `src/belay/` change; any re-run of a captured instance; any second run except
  a declared quota-resume with the identical command on the same root.
- Extending the claim classifier; changing controls or server pins mid-mint.

## Acceptance criteria

1. The frozen scripts commit before stage 1 with **no result** in them (grep-checked).
2. The pre-flight smoke runs once; its verbatim output commits; an instrument-class
   finding stops the mint before stage 1.
3. Stage 1: capture exists AND ≥1 genuinely verifiable turn AND the control
   `VERIFIED_CLEAN` — its trajectory line **abstains** (`CLAIM_UNCLASSIFIABLE` or
   no verification claim), never FAIL.
4. Stage 2: ≥5/11 captured, ≥1 verifiable turn, all 4 controls `VERIFIED_CLEAN`
   (any FAIL → VOID), trajectory exposure **≥1 of 11 judged** from the report's
   trajectory aggregate (0 judged → STOP).
5. Stage 3: denominator ≥50 distinct fresh **non-control** instances (controls
   partitioned out); `INSTRUMENT SUSPECT` → STOP; capture rate <50% → the smaller
   denominator is published instead.
6. Every stage's ledger re-renders via `belay phase0 report` with both exposure
   lines (file-comparisons; trajectory judged/abstained by cause).
7. `run_process` turns are dispositioned per the U9 composition (echoed /
   UNVERIFIED-by-cause; never counted as replayed evidence when not replayed).

## Dependencies

- v0.17.0 eval toolset (composite transport, `--toolset filesystem+shell`,
  per-instance `cwd`), controls re-scope with the positive control — shipped.
- Pre-registered rules: `phase0-live-mint/prd.md:53-84`,
  `phase0-remint/prd.md:182-215`, `phase0-mint-resilience/prd.md:99-137`.
- The dual-server runbook: `trajectory-toolset-rescope/mint-dual-server/`.
- `audit-and-publish` consumes this aspect's ledgers.

## Risks

P1 (quota daily cap → pause/resume), P2 (positive control command fails in the
contained run → recorded finding), P4/P5 (shell-turn replay seam → U9 disposition),
P6 (smoke finds a broken shell path → STOP). All handled per the PRD's risk table.
