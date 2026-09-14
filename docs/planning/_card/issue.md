# CI Regression Gate — unit card

> Phase 1 dump: `gh` issue not used — `ci-regression-gate` is a slug, not a numeric
> issue id (no GitHub issue exists for this work). Source is the inline brief below,
> produced by the `belay-next` skill handoff (2026-09-13) and executed by the owner.

## Brief

Phase 2's first goal per `docs/ROADMAP.md:305` — "a past run replays in CI; a new agent
version that breaks a previously-passing trajectory fails the build" — the R11 surface
with a named budget, and the only Phase-1→2-gate criterion that is buildable (users
asking for a shared/CI surface, `docs/ROADMAP.md:295`). Build the engine slice: a
baseline-bank + re-run compare that diffs a new capture's trajectory/verdicts against a
stored baseline and reports divergence with named causes, bankable into the corpus — no
LLM, deterministic, grounded in the existing capture/verify/corpus machinery (`corpus
run` already gates detector regression; this is the agent-side complement).

Caveat: the surface is roadmap-listed, not yet demand-validated, so keep the
CLI/compose wiring minimal and make the acceptance tests carry the shape.

Test-first, per the repo discipline — acceptance tests (written first):

1. A baseline capture re-verified after an injected trajectory change (new failing turn,
   changed tool sequence) yields a named regression, never a silent pass.
2. An unchanged re-run yields clean, byte-stable against the baseline.
3. A regression's divergence lands as a banked corpus case and recomputes MATCH through
   `corpus run`.
4. An unrestorable/missing baseline yields UNVERIFIED with a named cause.
5. Deterministic, no network, runs in CI.

Read `docs/planning/launch-readiness/CHECKLIST.md:10-14` first — no ☐ item remains
open, so this pick starts Phase 2, not the checklist.