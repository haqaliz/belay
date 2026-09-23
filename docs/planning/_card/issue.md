# C10's missing data, and moat #2's first real cases — the second corpus-filling mint

> Inline brief (no GitHub issue). Source: belay-next handoff 2026-09-22 → the owner's
> S-1 decision to declare a second run. Continuation of `docs/planning/phase0-corpus-mint/`
> (aspects 1–2 shipped; aspect 3 ran once and its pre-registered gate said STOP).

## Brief

Execute the **second corpus-filling mint**: `phase0-corpus-mint` aspects 3–5
(`mint-run` → `corpus-banking` → `audit-and-publish`) under the freeze protocol, on the
existing committed registry of **30 conservative-fresh instances** (never-drawn, prior
registries + ledgers excluded) with controls first.

**The instrument blocker is closed, not papered over.** The first run stopped at
`NO_VERIFIABLE_TURNS: 2` / `INSTRUMENT SUSPECT` / UNVERIFIED 3/3 = 100% because the
pinned npm filesystem server declares no annotations, so effect-conformance abstained
and worst-status-wins dragged every turn to UNVERIFIED. `effect-conformance-coverage`
(2026-09-21) moved the *not-declared* producer to `NOT_COVERED` (dropped before
ranking), closing the named gate. This unit is the measured run, not another fix.

**This is the owner's S-1 decision.** Live `claude-opus-5` spend must be authorized;
no spend happens before the frozen invocation scripts are committed in a commit
containing **no result** (grep-checked). Stages run once; verbatim outputs committed
next; a second run only if declared. D-3 void rule enforced (a FAILing control voids
the run — it killed the 2026-08-09 re-mint); `INSTRUMENT SUSPECT` ⇒ STOP.

## What the run produces (the acceptance, measured — reported whatever it says)

- Captures produced, with the capture rate and its denominator stated.
- Every trajectory FAIL banks as `trace-<instance>-trajectory` and recomputes MATCH
  under `corpus run` (the first real corrupt-success cases — moat #2 has not grown
  since 2026-08-12).
- Per-turn FAILs bank, or are reported `flagged-but-unaddable` **with named causes**.
- The A3 claim column is filled — a verdict or a named UNVERIFIED cause, never
  "claim unrecorded" (the `a3-author` aspect made this reachable).
- `corpus run` over the grown corpus is 0 REGRESSION.

## Deterministic acceptance (test-first, before any spend)

- The registry regenerates byte-identically (reproducibility check).
- The frozen scripts carry no result shapes (grep-checked).
- Full suite stays green at the 2743 baseline.

## Honesty constraints (the house contract)

- **Publish no violation rate** — the fresh residue is ~100% django+sympy, the exact
  monoculture the stratified draw exists to prevent.
- `precision` will still read `n/a` (cases bank `pending`; only a human may label, and
  S-1 makes that the owner's work — the evidence pack is prepared here, never judged).
- **No published number moves** (`11/60 = 18.3%`, `precision 0.00`, `1/15`, `4/16`,
  `recall 0.00`, `3/93` stand unedited).
- R-A stands: a real intent-drift (A3) case may not be producible — 18 launch-demo
  drives produced zero corrupt successes — an empty A3 column is a **recorded result**,
  not a red test.

## Open questions for the owner (Phase 3)

1. S-1 confirmed: declare the second run (this unit) — not stop, not re-scope?
2. Live spend authorized (Q6 of the prior PRD, re-confirmed for this unit) — n≈12
   staged per Rule A, stop-loss by stage?
3. Environment deltas to state, not hide: local `claude` version vs the 2026-08-12
   gate run's 2.1.228; engine now v0.37.0 (the run will use the shipped engine, not
   the U9-era composition).