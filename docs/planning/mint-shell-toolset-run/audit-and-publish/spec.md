# Aspect Spec — audit-and-publish

Part of `docs/planning/mint-shell-toolset-run/prd.md`. Turns the mint-run ledgers
into an audit trail and the pre-registered gate decision line.

## Problem slice

A mint without an audit is a claim. Every trajectory FAIL must be adjudicated
(S-5), the number must be re-derivable from the committed ledgers, and the owner
writes the decision line from committed evidence — with the mandatory disclosure
set, never from the run's favorability.

## In scope

- Evidence inventory: `FLAGS.md` (all flagged turns, the trajectory table — per
  instance: claim class, evidence count, verdict, cause).
- Hand-audit: `AUDIT.md` — every flagged turn adjudicated TP / FP / unverifiable;
  **every trajectory FAIL adjudicated** (no sampling of the trajectory axis);
  root-cause keys kebab-case; independence read off `(instance, tool)`; corpus
  labels applied (`belay corpus label`); precision table with a real denominator.
- Hand-replay: `HAND_REPLAY.md` — one FAIL replayed end-to-end
  (`belay corpus run` re-executes the verdict computation; trajectory cases have no
  per-turn diff).
- Reproducibility: `REPRODUCIBILITY.md` — clean-checkout `belay phase0 report`
  byte-identical to the committed acceptance outputs; mismatch → STOP.
- Decision line (owner): PROCEED / PIVOT / VOID verbatim, with the mandatory
  disclosure set (`phase0-remint/audit-and-publish/plan_20260809.md:97-103`):
  rate with denominator; FP rate stated; UNVERIFIED by named cause; exposure on
  both lines (file-comparisons; trajectory judged/abstained by cause) with Rule B's
  mechanical reading; the trajectory rule's measured precision on real model text;
  pool composition; coverage limits (filesystem-only verify composition, shell
  exclusion, NOT_COVERED, MCP boundary, "any command ≈ suite" approximation); the
  ToS assumption; "reproducible" in the decided words; the D-1 gate supersession.
- Publication: `docs/technical/PHASE0_RESULTS.md` updated (run results + decision);
  the launch checklist L1 line written
  (`docs/planning/launch-readiness/CHECKLIST.md`).
- Runbook walk: `eval/README.md` corrected end-to-end from the run.

## Out of scope

- Re-running the mint; re-deriving any published number except by the gate
  decision; engine changes; agents writing the decision line or adjudicating.

## Acceptance criteria

1. Every trajectory FAIL has an adjudication line in `AUDIT.md` (S-5); the
   unaudited count is 0.
2. `belay corpus score` prints a real denominator (TP/FP/FN with provenance).
3. `REPRODUCIBILITY.md`: clean-checkout report output is byte-identical to the
   committed `acceptance-stage*.out` renders — or a STOP is recorded.
4. The decision line states PROCEED / PIVOT / VOID with the full disclosure set;
   the void/stop readings match the pre-registered rules, not the run's favor.
5. `PHASE0_RESULTS.md` and the launch checklist L1 reflect the decision.

## Dependencies

- mint-run ledgers (`mint-run/ledgers/s6{a,b,c}.json`), capture roots
  `eval/mint/s6{a,b,c}/`, the corpus under `corpus/local/`.
- Pre-registered audit rules: `phase0-remint/audit-and-publish/plan_20260809.md`
  (S-1..S-6, phases 1–6).

## Risks

P3 (reproducibility mismatch → STOP), adjudication drift (owner only), corpus
labels diverging from `AUDIT.md` (re-run `belay corpus run` to pin MATCH).
