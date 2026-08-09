# Spec — `phase0-remint/audit-and-publish`

**PRD:** `docs/planning/phase0-remint/prd.md` · **Date:** 2026-08-09

## Problem slice

Turn the committed stage ledgers into the Phase-0 gate decision, with the trajectory rule's
**first precision measurement on real model text** as a first-class outcome. The audit is a
human act on committed evidence; agents prepare evidence, never judgments.

## In scope

- Evidence inventory of every flag from the committed ledgers (FLAGS.md), including every
  trajectory FAIL and abstain by cause.
- The hand-audit (AUDIT.md): every flag adjudicated TP/FP/unverifiable; root-cause keys per
  TP; independence read off `(instance, tool)`; `belay corpus label` applied (TPs require
  `root_cause`); the pre-registered sampling rule if >30 flags (all control flags + all
  first-flag-in-instance + seed-committed random sample; unaudited count stated).
- **The trajectory precision table (M6):** every trajectory verdict (FAIL/PASS/UNVERIFIED
  by cause) listed per instance; each FAIL adjudicated — did the agent claim verification
  success with zero (or failing) command runs, and did it have the suite-run ability and
  skip it? PASSes and abstains noted. The rule's precision on real text is decided here.
- One FAIL hand-replayed end-to-end (HAND_REPLAY.md) — the symmetric FP guard's second half.
- Reproducibility check (REPRODUCIBILITY.md): `belay phase0 report` re-renders each ledger
  byte-identically in a clean checkout.
- The decision line (owner): `PHASE0_RESULTS.md` dated section (PROCEED/PIVOT verbatim, FP
  rate, pool composition, coverage limits, Rules B and C applied mechanically), plus
  `PHASE0_AUDIT.md` correction block if warranted, `docs/ROADMAP.md` R1 cell + gate blocks,
  `CLAUDE.md` status block, `CAPABILITY_ROADMAP.md` C5 gate status.
- RUNBOOK walk + corrections (stale ledger/case examples; add trajectory-rule content).
- Forecast post-hoc comparison results carried into the decision section.

## Out of scope

- Re-running the mint; re-deriving any published number except by the gate decision; engine
  changes; labeling by agents (labels are human).

## Acceptance criteria

1. Every flagged case (or the pre-registered sample) has a corpus label; every TP has a
   root-cause key; the audit note names each TP's instance and tool; `corpus score` prints
   precision/recall and both independent-TP counts with a real denominator.
2. The trajectory table is complete (per-instance verdicts, FAILs adjudicated) — the rule's
   precision is stated or stated-unmeasured, never predicted.
3. The hand-replay note states the one FAIL's observed delta and its verdict under the
   restored pre-state.
4. Committed ledgers re-render identical rates via `belay phase0 report`.
5. `PHASE0_RESULTS.md` carries the decision line with the full disclosure set; the diff is
   dated; the decision is PROCEED or PIVOT verbatim from the criteria.
6. ROADMAP R1 and the C5 gate block carry the dated update; CLAUDE.md status block synced.
7. RUNBOOK walk committed with corrections (incl. trajectory content); anything the walk
   disproves is fixed in the same unit, never left as a known-stale artifact.

## Dependencies

`mint-run` (committed ledgers for all completed stages) + the corpus ingest from
`belay phase0 run` (ingest ON). The audit is the owner's act; agents execute Phases 1, 4, 6.

## Risks

Control FAIL void (nothing to audit — the void is published as the decision); heavy
abstention (the trajectory table is mostly UNVERIFIED — a stated result, not a silence);
high rate (Rule C evidence must precede any publication); a trajectory PASS flood (an
instance that runs any command before claiming — the rule's known approximation, adjudicated
per instance).
