# Spec: `firing-and-docs` (aspect 3)

**Parent:** `docs/planning/authored-invariant-scope-shape/prd.md` (S1 through the CLI, S6,
R-C, the hard question)
**Grade:** deterministic e2e + docs (the live proof is `manual`)
**Depends on:** `scope-guard`.

## Problem slice
Prove end-to-end, through the real CLI, that (a) an authored **prefix** scope still FIRES on
a corrupt fixture whose delta touches the scoped path (the authoring path can, at last, do
what it claims), and (b) an authored **glob** scope verifies to UNVERIFIED, never PASS.
Then record the honesty lines.

## In scope
- CLI-level test: an authored artifact with a glob scope, enforced via
  `belay verify --invariants <artifact>` on a `tests/` corrupt fixture → the glob turn is
  UNVERIFIED with `authored-invariant-scope-uninterpretable`; the prefix-armed case FAILs.
- Docs: README (authored-invariant section, if present), `CLAUDE.md`, `docs/STATUS.md`
  (a block), and a note on `docs/planning/invariant-authoring/prd.md` pointing at this
  unit's fix; state R-C (the frozen live-run artifact's PASS was the defect symptom and now
  reads UNVERIFIED — the artifact is not rewritten) and R-E (the guard is glob-only).

## Out of scope
Rewriting the frozen live-run artifacts; a live-model CI test.

## Acceptance (test-first)
1. Reuse `tests/test_invariant_authoring_e2e.py` (`_infer_artifact` `:204`,
   `_weakening_fixture` `:185`) to pin the firing path; add the glob → UNVERIFIED CLI case.
2. `manual`-marked live proof (SH-2) mirroring `tests/test_reference_author_live.py`, never CI.
3. Docs pins: any machine-checked docs test (`tests/test_*docs*.py`) stays green.

## Open questions
Whether a docs test already asserts README claims that this unit changes.
