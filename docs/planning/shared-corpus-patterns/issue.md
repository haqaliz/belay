# Issue #58 — feat: shared corpus (Phase 2 team layer)

## Why
Phase 2 goal (`docs/ROADMAP.md`): the team's failure corpus as a queryable, growing, shared asset. Today `corpus/` is local-only and gitignored.

## Scope
- Opt-in, pattern-level sharing only; never raw state.
- Consented ingest/egress path plus provenance.
- Queryable corpus across a team.

## Exit criteria
- Two self-hosted instances can share labeled cases without raw-data egress.
- Precision/recall reporting works across the shared set.

## Status
Phase 2 goal, demand-pull. Not launch-blocking.
