# C10 slice 2 — the calibration ledger

> Inline brief (no GitHub issue). Source: the merged C10 PRD
> (`docs/planning/jev-triage/prd.md`) + the belay-next/owner handoff 2026-09-22.

## Brief

Build the **calibration ledger** — the moat-compounding half of C10. It measures whether
a triage model's "calibrated confidence" actually predicts a real violation on real
Belay verdicts: reliability curve, ECE, and the decision-relevant number — at the chosen
triage threshold, how many true violations would have been skipped.

The PRD's sequencing condition is met: *"build the ledger after the instrument can
produce a decided per-turn verdict"* — the `effect-conformance-coverage` fix shipped
(v0.35.0), so decided per-turn verdicts are reachable (VERIFIED_CLEAN no longer
structurally impossible).

## What the PRD already promises (quote)

- "The **calibration ledger** — Jev's confidence on each triaged turn vs the
  execution-grounded verdict replay later produced. This is the moat-compounding piece
  and it is pure Belay: it measures whether Jev's 'calibrated confidence' is actually
  calibrated *on real agent traces* (reliability curve, ECE, and the decision-relevant
  number — at the chosen triage threshold, how many true violations were skipped)."
- "Shadow mode is the default... record the triage scores alongside, until the
  calibration ledger earns a tighter budget." — the ledger's whole purpose is to earn
  (or refuse) a tighter budget.
- Named follow-up from the shipped unit: "skipped turns' scores in budgeted mode
  (coherent today — scores pair with verdicts; **the ledger slice will extend the
  section**)."

## Already shipped (what the ledger consumes)

- `belay verify` shadow mode records per-turn `{score, confidence}` in the additive
  `triage` JSON section, paired with the `turns` verdicts — the raw ledger rows exist
  today when a triage author is configured.
- The Jev reference author + live proof (v0.36.0): `jev-1.13.0`, `{"score": 0.82,
  "confidence": 0.63}` at n=1 — a vendor claim until this ledger measures it.
- Decided verdicts are reachable on existing captures (s1p: 0/11 UNVERIFIED; the demo
  capture) — small-data validation without a new mint.

## Honesty constraints (the house contract)

- The ledger measures *prediction of violations on the turns actually replayed* —
  calibrated ≠ caused. UNVERIFIED turns must be excluded from the calibration column
  (the corpus precedent: UNVERIFIED excluded, the engine never labels its own cases).
- Small n is a recorded state, never a base rate: the ledger prints its denominator; the
  mint re-run (owner's S-1 declaration) supplies volume later.
- No published number moves from earlier units (`11/60 = 18.3%`, `precision 0.00`,
  `1/15`, `4/16`, `recall 0.00`).
- The ledger must never be built against a 100%-UNVERIFIED column (the false-zero
  failure the PRD named).

## Open questions for the owner (Phase 3)

1. Surface: a `belay triage-ledger` command consuming the verify `--json` (score+verdict
   pairs already in it) vs a `--triage-ledger FILE` flag on verify writing while
   verifying?
2. "True violation" definition for the calibration column: per-turn reduced FAIL, with
   UNVERIFIED excluded?
3. The ledger's budget-earning output: threshold sweep (violations-skipped vs budget
   saved at each threshold) — the shape of the decision number?