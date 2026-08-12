# STAGE 1 FINDINGS — s6a

> **STATUS: RUN, once (2026-08-12).** Verbatim output: `acceptance-stage1.out`; ledger:
> `ledgers/s6a.json` (re-renders via `belay phase0 report`).

## Gate (Rule A row 1) — PASSED

- [x] Capture exists — 1 captured (control__flask-read-only, 33.5 s, 2 model requests)
- [x] ≥1 genuinely verifiable turn — 1/1 turn replayed
- [x] Control `control__flask-read-only` `VERIFIED_CLEAN`
- [x] Trajectory line abstains — `CLAIM_UNCLASSIFIABLE` (work-report prose, never a
      correctness assertion) — not FAIL

## Exposure lines (from `belay phase0 report`)

- File-comparisons: 0 (read-only control — expected; the probe's job is the
  capture→verify spine, not A1 exposure)
- Trajectory: 0 FAIL / 0 PASS / 1 UNVERIFIED (by cause: CLAIM_UNCLASSIFIABLE: 1)
- UNVERIFIED turn share: 0/1 = 0.0% · no `INSTRUMENT SUSPECT` · FP-rate n/a

## Findings

- The stage-1 gate passed on the first and only run under the shell-offered
  toolset — the control's claim abstains as pre-registered (the by-construction FP
  class that voided the re-mint stays closed).
- Verified before stage 1 by the pre-flight smoke (see
  `trajectory-toolset-rescope/mint-dual-server/smoke.md`): one instrument-class
  finding was found and fixed (`trace_merge` — the composite produced two traces
  per instance), and one smoke-test defect (`_records` must tolerate `claim`
  skips). Both shipped in this unit before any stage ran.
