# Spec — score-denominator-proof

**Aspect of:** `corpus-trajectory-banking` · `docs/planning/corpus-trajectory-banking/prd.md`
(requirements M4, M5).

## Problem slice

Once banking works, prove the measurement pipeline: a banked, human-labeled trajectory case
must count into `corpus score` precision/recall with a real denominator — without changing
`score()`. And the fail-closed honesty contract must be pinned: an unrestorable-pre-state
trajectory FAIL stays unbankable with its named cause.

## In scope

- End-to-end test (synthetic fixtures, the repo's existing rig): mint an instance with a
  trajectory FAIL → case banks → label it true-positive → `corpus score` computes
  precision/recall with real denominators in a corpus mixing per-turn and trajectory cases.
- `score()` itself is untouched (it already reads `expected.reduced_status` +
  `human_label`; a trajectory case's expected carries `reduced_status = FAIL`).
- Negative test: a trajectory FAIL naming an unrestorable pre-state refuses to bank with
  the named pre-state cause (fail-closed; ordering: pre-state check before collision
  check); the instance keeps `VERIFIED_FLAGGED` and stays in the violation denominator.
- `metrics.py` is unchanged; the test asserts the honest `n/a` never appears where a real
  denominator exists.

## Out of scope

- Any `corpus score` CLI output change (PRD decision: end-to-end proof only).
- The 5 unrestorable mint instances themselves (their traces are gone; the synthetic
  fixture carries the contract).

## Acceptance (RED first)

1. A labeled trajectory FAIL case in a mixed corpus yields precision `1.00` (1 TP / 0 FP,
   real denominator) and recall with a real denominator — hand-computed values match the
   test's assertion.
2. The same corpus with the label `pending` yields `n/a` — never a fabricated rate
   (`_ratio`'s None → n/a contract).
3. An unrestorable-pre-state trajectory FAIL produces no case, a named pre-state cause in
   `trajectory_unaddable`, disposition `VERIFIED_FLAGGED`, and the instance present in
   `violation_denominator()`.
4. The existing metrics suite (zero-denominator n/a, never 1.00) stays green unchanged.

## Dependencies & sequencing

Second aspect — needs the id namespace from aspect 1 for the banking fixture. Purely
test-side; no production code change is expected in this aspect (if the tests force a
production change, the plan must say which requirement it serves).

## Open questions

None.