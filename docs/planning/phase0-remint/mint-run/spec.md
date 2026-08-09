# Spec — `phase0-remint/mint-run`

**PRD:** `docs/planning/phase0-remint/prd.md` · **Date:** 2026-08-09

## Problem slice

The staged, frozen execution of the fresh Phase-0 mint under the v0.15.0 trajectory rule —
the work that produces the number and the gate outcome. Everything in this aspect is
execution and record-keeping; the engine (`src/belay/`, `eval/minting_driver/`) is consumed
as-is.

## In scope

- Frozen invocation scripts for stages 1–3 (`acceptance-stage{1,2,3}.sh`, containing **no
  results**), committed before any stage runs (Rule D).
- Stages 1 → 2 → 3 on fresh roots `eval/mint/s5{a,b,c}`, each run **once**, verbatim
  outputs committed after, per-stage findings notes.
- Per-stage gates (Rule A, re-read per D-1): stage 1 control `VERIFIED_CLEAN`; stage 2
  ≥5/10 captured, 3/3 controls clean, **trajectory exposure gate ≥1 of 10 judged**; stage 3
  no abort except the quota breaker.
- Verification + ledgers per stage (`belay phase0 run … --ledger runs/s5{N}.json
  --corpus-dir corpus/local`, ingest ON, no `--`), ledgers copied to
  `docs/planning/phase0-remint/mint-run/ledgers/` and committed.
- The forecast post-hoc comparison (S1): `eval/scripts/forecast_exposure.py` re-run vs
  realized trajectory exposure.

## Out of scope

- Any `src/belay/` change; any new registry/draw; re-running banked s4 captures;
  control-prompt changes; Phase-1 surfaces.

## Acceptance criteria (fixed before the run)

1. Each `acceptance-stageN.sh` contains the invocation, env, and protocol prose only — an
   embedded expected result is a defect.
2. Stage 1's gate passes (capture + ≥1 verifiable turn + control `VERIFIED_CLEAN`,
   including the trajectory abstain) or the unit STOPS with a named reason.
3. Stage 2's gate is decided mechanically from the report's trajectory aggregate (≥1 of 10
   judged), never by hand-inspection; a control FAIL voids the mint.
4. Stage 3's ledger re-renders the identical headline via `belay phase0 report` (M7).
5. Every UNVERIFIED instance traces to a named cause; `INSTRUMENT SUSPECT` → STOP.
6. Quota stops pause and resume on the same root; `captured`/`failed` are never re-driven.
7. The suite stays green (`uv run pytest` → 1626 passed) through the unit; no committed
   artifact contains raw trace data.

## Dependencies & sequencing

`audit-and-publish` depends on this aspect's committed ledgers. Stages within this aspect
gate on each other (Rule A); the owner is present at every checkpoint.

## Risks

Per PRD: control trajectory-FAIL voids (D-3, probed at stage 1); abstention re-firing the
exposure gate (D-1); high rate (Rule C); attrition shapes; quota stop.
