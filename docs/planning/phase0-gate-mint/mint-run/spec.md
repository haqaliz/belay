# Spec — aspect 3: `mint-run` (run, ledger-style; no code)

Unit: `feat/phase0-gate-mint` · Source: `docs/planning/phase0-gate-mint/prd.md` M8-M12 ·
This aspect produces **no product or eval code** — it is the pre-registered execution of the
gate mint under the freeze protocol, with ledger-style acceptance.

## Problem slice

The ≥50 gate denominator has never been minted; the gate decision line for R1 does not exist.
The harness (v0.17.0) plus aspects 1 and 2 make the run well-defined; this aspect executes it
and produces the record: pre-registered readings, freeze scripts, stage runs, per-stage
ledgers, full adjudication, `PHASE0_RESULTS.md` update, and the PROCEED/PIVOT decision.

## Pre-registered readings (fixed here, before any run)

- **Canonical gate criteria**: verbatim block quoted in the PRD (PROCEED iff ≥3 independent
  hand-audited TPs AND denominator ≥50 AND no `INSTRUMENT SUSPECT`; PIVOT otherwise; FP rate
  stated; a FAILing control voids — D-3).
- **D-1 (trajectory exposure)**: stage 2 must judge ≥1 trajectory instance
  (`claims_judged` = FAIL|PASS); a stage reading 0 judged stops before stage 3.
- **CTL-4 stage-1 outcome readings**: PASS → chain proven, launch stage 2; UNVERIFIED →
  adjudicated (wiring vs steering; a fix is a declared second run, then re-probe); FAIL → D-3
  void. (PRD, pre-registered.)
- **Stop-loss**: stage 1 capture + ≥1 verifiable turn + controls clean; stage 2 capture
  ≥5/10 + controls clean + D-1; quota breaker owns mid-stage stops; resume on the same root.
- **Freeze protocol**: invocation script committed FIRST containing no result; each stage run
  once; verbatim output committed next, whatever it says; a second run only if declared.
- **Controls-first**: controls head the stage-2 registry; stage 3 carries controls too (they
  drove first at stage 2; the write-up states it).
- **Composition**: `--toolset filesystem+shell`, `--provider claude-cli`, `--model
  claude-opus-5`, `--max-steps 20`; roots `eval/mint/s6{a,b,c}`; `mkdir -p runs` before every
  `belay phase0 run`; verify with `--server <fs> --shell-server <shell>` (aspect 1).

## In-scope requirements

1. **Stage 1** (2 controls: CTL-1 + CTL-4): freeze script → run → verbatim output → verify
   (dual-server composition) → ledger `runs/s6a.json` → committed under
   `mint-run/ledgers/s6a.json` → `belay phase0 report` re-render → stage findings note with
   the CTL-4 outcome reading applied.
2. **Stage 2** (9: CTL-2 + CTL-3 + 7 fresh): same protocol; D-1 reading applied; stop-loss
   applied; a control FAIL stops and voids (adjudicated first — the re-mint precedent:
   adjudication evidence committed before the void line).
3. **Stage 3** (83: 80 fresh real + 3 controls): same protocol, multi-day as needed
   (quota-stop → resume on the same root; `no_observation` re-arms, `captured` never
   re-rolls); the ≥50 clause counted from the report's per-instance denominator
   (CLEAN+FLAGGED, controls partitioned out).
4. **Adjudication in full** (no sampling on the trajectory axis): every flagged turn and
   every trajectory FAIL/PASS gets a written finding; labels via `belay corpus label`;
   `belay corpus run`/`score` after; committed under `audit-and-publish/`
   (FLAGS / AUDIT / HAND_REPLAY / REPRODUCIBILITY pattern from `phase0-remint`).
5. **`PHASE0_RESULTS.md` update**: new number (violation rate + denominator + FP rate +
   trajectory exposure per instance + UNVERIFIED-by-cause + per-turn FAIL rate) and the gate
   decision line — PROCEED or PIVOT with reasons, never renarrated. Published numbers stand
   unedited.
6. **Forecast comparison** (S13): the 29/65 = 44.6% forecast vs realized `claims_judged`,
   stated as comparison, not validation.
7. **Runbook**: `eval/README.md` gains the dual-`--server` verify invocation and the staged
   run walk.

## Out of scope

- Any engine or eval code (aspects 1-2 own it); any change to the detector, vocabulary, or
  gate criteria mid-run (freeze discipline: "Do not change the invariant mid-mint").
- Re-minting observed instances; corpus migration of the 5 remint FPs (documented debt).

## Acceptance criteria (ledger-style)

- **AC-1**: stage 1 captured both controls; CTL-4's outcome reading applied; controls
  `VERIFIED_CLEAN` or the recorded finding says why not; gate passed or the run stopped with
  the named rule.
- **AC-2**: stage 2 captured ≥5/10; controls clean; ≥1 trajectory instance judged (D-1); the
  stop-loss/D-1/D-3 decision recorded with the reading that fired.
- **AC-3**: stage 3 driven to quota-stop or completion; ≥50 distinct fresh non-control
  instances verified (from the committed ledger); no `INSTRUMENT SUSPECT`; every UNVERIFIED
  turn/instance has a named cause.
- **AC-4**: every flag adjudicated with a written finding; labels applied; `corpus run` green
  (0 REGRESSION); reproducibility asserted — `belay phase0 report` re-renders each committed
  ledger to the published headline.
- **AC-5**: `PHASE0_RESULTS.md` updated with the number and the decision line; no published
  number re-derived; the write-up states the controls-first ordering, the toolset, the
  coverage boundary (MCP-only, `NOT_COVERED` network), and the abstain-reclassification note
  (R7).

## Dependencies & sequencing

- Requires: aspects 1 (verify composition + smoke) and 2 (stage registries + observed set).
- The operator runs the freeze scripts in the main thread; agents draft scripts, findings,
  and the audit — never the live run.
