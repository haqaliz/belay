# Issue / Brief

> Source: no GitHub issue — the work was handed off by `belay-next` (2026-08-12) as
> the next unit named by `docs/planning/trajectory-toolset-rescope/prd.md` → *Out of
> Scope*: "The mint itself (the next unit): fresh stage runs, the ≥50 denominator, the
> gate decision line."

## Brief

Run the Phase-0 mint under the shell-offered toolset exactly per the v0.17.0 runbooks
(`docs/planning/trajectory-toolset-rescope/mint-dual-server/plan_20260812.md`,
`docs/planning/trajectory-toolset-rescope/controls-rescope/plan_20260812.md`) and the
pre-registered gate criteria (`docs/planning/phase0-live-mint/prd.md`). Stage 1 is the
control gate; stage 2 is 3 controls + 7 fresh real instances via the composite
transport; stage 3 drives the ≥50-instance denominator with the quota-stop semantics
from `phase0-mint-resilience`. Acceptance is the gate itself: ≥3 independent
hand-audited TPs, denominator ≥50, no `INSTRUMENT SUSPECT`, no FAILing control, FP
rate stated, and the number published in `PHASE0_RESULTS.md` re-derivable via `belay
phase0 report` — while a healthy-instrument ~0 rate is recorded as a STOP with named
causes, not a clean launch signal. This unit ships ledgers and the gate decision
line, nothing else — C7/C8/Linux stay untouched.
