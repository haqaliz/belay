# Spec — `audit-and-publish`

**Aspect of:** `phase0-mint-run` · **PRD:** `docs/planning/phase0-mint-run/prd.md`
**Date:** 2026-08-09

## Problem slice

The gate's verdict is only as good as its audit, and the number is only worth anything if a
stranger can re-derive it from the repo. This aspect turns the stage ledgers into the
decision line: hand-audit every flag (pre-registered sampling rule if >30), label cases with
root-cause keys, hand-replay one FAIL, commit ledgers + verbatim report outputs, fill
`PHASE0_RESULTS.md`, and walk the RUNBOOK end-to-end once, correcting what the dig found
stale (RUNBOOK ledger example `RUNBOOK.md:304-318`, case-id example `:348` — both describe
pre-ship formats).

## In scope

1. **Audit.** For every flagged case banked by the stage runs (or the pre-registered sample
   if >30: all control flags + first-flag-in-instance + seeded random remainder): read the
   trace + replay diff, judge TP / FP / unverifiable, `belay corpus label` with a kebab-case
   `root_cause` key per TP, record each TP's instance + tool so independence is auditable.
2. **Hand-replay one FAIL** end-to-end: `belay phase0 run` over that single trace (or the
   narrowest equivalent) against a restored pre-state, confirming the observed delta is real
   — not a rename/manifest artifact (the symmetric FP guard, `phase0-live-mint/prd.md:74-85`).
3. **Committed artifacts.** Ledgers + acceptance outputs + findings notes for every stage
   land under `docs/planning/phase0-mint-run/`; `belay phase0 report` re-renders each stage's
   rate exactly as its `acceptance.out` states (the `7ab5ba3` precedent).
4. **The decision.** Apply the canonical criteria (`PHASE0_RESULTS.md:17-42`): ≥3 independent
   TPs AND ≥50 denominator AND no `INSTRUMENT SUSPECT`, FP rate stated. Apply Rule B (near-zero
   reading) and Rule C (high rate = artifact until proven) as applicable. Write the decision
   line — PROCEED or PIVOT, each as plainly as the other — plus the full disclosure set: pool
   composition, exposure summary, UNVERIFIED by named cause, coverage limits (filesystem-only,
   shell exclusion, NOT_COVERED, MCP-boundary), ToS assumption, the "reproducible" decided
   meaning, and the ordering disclosure (criteria predate this mint).
5. **Sync the record.** `docs/ROADMAP.md` R1 row + gate blocks, `CLAUDE.md` status block,
   and `docs/technical/CAPABILITY_ROADMAP.md` C5 gate status get the dated update. No
   published number is re-derived except by the gate decision itself.
6. **RUNBOOK walk.** Follow `docs/planning/phase0-corpus-run/RUNBOOK.md` end-to-end against
   the stage-2 artifacts; commit corrections (the stale ledger/case examples, any other
   mismatch found on the walk).

## Out of scope

- Re-adjudicating the 7 banked FP cases or re-deriving any published number.
- Combining the 12 banked Gemini captures into the population (historical note only).
- Any `src/belay/` change; any corpus schema change.

## Acceptance criteria

1. Every flagged case (or the pre-registered sample) has a `corpus` label; every TP has a
   root-cause key; the audit note names each TP's instance and tool.
2. The hand-replay note states the one FAIL's observed delta and its verdict under
   pristine/mutated conditions as applicable.
3. Committed ledgers re-render identical rates via `belay phase0 report` (reproducibility
   by stranger).
4. `PHASE0_RESULTS.md` carries the decision line with the full disclosure set; the diff is
   dated and the decision is PROCEED or PIVOT verbatim from the criteria.
5. ROADMAP.md R1 and the C5 gate block carry the dated update; CLAUDE.md status block synced.
6. RUNBOOK walk committed with corrections; anything the walk disproves is fixed in the same
   unit, never left as a known-stale artifact.

## Dependencies & sequencing

Fourth and final aspect. Blocked by `mint-run`'s ledgers. The audit is a main-thread human
exercise (the auditor is the person who needs ≥3 TPs — `phase0-mint-execution/prd.md` Gap 3;
the pre-registration timing disclosure is restated).

## Open questions / risks

- Flag count unknown until stage 3 verifies; the pre-registered sampling rule (PRD req. 9)
  bounds the audit's tail.
- Solo-audit bias: structural counterweights are the in-batch controls, the hand-replayed
  FAIL, per-TP root causes, and Rule C — disclosed, not eliminated.
