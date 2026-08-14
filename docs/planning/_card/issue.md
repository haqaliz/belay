# phase0-gate-mint — work card

> Unit: `feat/phase0-gate-mint` · branch `feat/phase0-gate-mint/aliz` ·
> worktree `.claude/worktrees/feat-phase0-gate-mint` · base `origin/master` (v0.17.0)

## Brief

No GitHub issue exists for this work; the source is the inline brief handed off by the
`belay-next` recommendation (2026-08-14), reproduced verbatim:

> Run the Phase-0 gate mint: fresh stage runs under the shell-offered toolset (v0.17.0 —
> filesystem + shell on one boundary, per-instance cwd) to fill the ≥50-instance denominator
> and produce the gate decision line for R1, whose quantitative form is still untested.
> Pre-register the PRD (D-1 trajectory exposure reading, D-3 void rule, freeze scripts pinning
> `--toolset filesystem+shell`, controls-first ordering); stages 1 (1 control) → 2 (3 controls +
> fresh real, claude-opus-5 subscription path) → 3 (the ≥50 denominator). Caveat: control claim
> steering is stochastic — the write control must classify abstain, since that path voided the
> re-mint — and stage 3 previously hit a provider daily cap, so budget wall-clock across days
> (the phase0-mint-resilience re-arm rule). Acceptance, test-first where code is touched and
> ledger-style where it is not: controls captured and clean (write control → trajectory
> UNVERIFIED with named cause, suite-running control → PASS); ≥50 instances minted with zero
> INSTRUMENT SUSPECT; every trajectory FAIL hand-adjudicated; the violation rate published with
> denominator and false-positive rate; the PROCEED/PIVOT decision recorded per the pre-registered
> rule. Source: docs/planning/trajectory-toolset-rescope/prd.md:170-171.

## Motivating record (from the repo, 2026-08-14)

- `docs/planning/trajectory-toolset-rescope/prd.md:170-171` — "**The mint itself** (the next
  unit): fresh stage runs, the ≥50 denominator, the gate decision line. This unit ships the
  toolset + rule; it produces no Phase-0 number."
- `docs/planning/trajectory-toolset-rescope/prd.md:149-150` — "**R1 (premise) — STILL OPEN,
  now measurable.** This unit makes the axis able to measure the population; it does not retire
  the risk. The next mint's audit decides."
- `docs/planning/phase0-remint/audit-and-publish/AUDIT.md` — the adjudication of the voided
  re-mint: 5/5 trajectory FAILs false positives by construction (14 filesystem tools, no
  shell); trajectory precision 0.00; the D-3 void.
- `docs/ROADMAP.md` R1 — quantitative form untested; "1/15 and 4/16 are NOT comparable" etc.
- `docs/technical/PHASE0_RESULTS.md` → the canonical pre-registered gate criteria block
  (phase0-live-mint/prd.md → *Pre-registered gate criteria*, fixed 2026-07-21).
- `docs/planning/phase0-mint-run/` — the funded mint that was stopped by the exposure gate
  (stage 2, 8/10, exposure zero).
- `docs/planning/phase0-mint-resilience/` — daily provider cap, re-arm rule, no_observation.
- `docs/planning/subscription-model-client/` — ClaudeCliModel on the subscription path.
