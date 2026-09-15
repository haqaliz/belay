# Invariant Authoring Experiment — unit card

> `gh` issue not used — `invariant-authoring-experiment` is a slug, not a numeric issue
> id (no GitHub issue exists for this work). Source is the inline brief below, produced
> by the `belay-next` skill handoff (2026-09-15) and executed by the owner.

## Brief

Build R3's third mitigation: the Phase-2 invariant-authoring experiment
(`docs/ROADMAP.md:308`; `docs/planning/invariant-library/prd.md:151-152` names it the
later unit). Test-first — write the RED test before any engine code: an invariant
inferred from a task spec must FAIL the corrupt-success fixture and PASS or abstain the
clean control, and a mis-broad authored invariant must degrade to UNVERIFIED, never FAIL
— the A1 precision-0.00 history (`invariant-test-mutation-shape`,
`docs/technical/CAPABILITY_ROADMAP.md:388`) is the guardrail. The slice is an
inferred-from-task-spec authoring path whose output is a deterministic-enforceable A1
invariant (no new verdict axis, no LLM-judge verdict — execution decides), driven
through the existing BYOK subscription-model-client. Deliverable: per-entry fixture
corrupt-success corpus cases that recompute MATCH (the invariant-library pattern,
`prd.md:93-96`) and the first real authored invariant run against a launch-capture.
Caveat: no concrete slice exists in any file — this brief is the spec's seed; keep the
first slice narrow and abstain-by-default so a bad model write can never manufacture a
violation.

## Axes

- **A1 (invariant)** — the authored artifact is an A1 invariant; deterministic
  enforcement is the same `src/belay/verify/` machinery, no new verdict axis.
- **A3 (claim re-derivation) precedent** — "a model writes a check; execution decides"
  is the shipped A3 design (`claim-re-derivation-a3`); this experiment applies the same
  split to A1 authoring. A3 itself is untouched and can never emit PASS.