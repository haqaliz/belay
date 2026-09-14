# Aspect: divergence-banking

## Problem slice

A caught regression must compound: moat #2 says every caught failure becomes a labeled,
replayable corpus case. Today `phase0 run` banks flagged turns, but the gate's divergences
have no path into the corpus.

## User outcome

When `gate check` finds a regression, the divergent turns bank as self-contained corpus
cases by default; `belay corpus run` then recomputes them `MATCH` — the regression is now
a permanent guard.

## In scope

- `gate check` default-on ingest of divergent turns via the existing `add_case` path
  (`src/belay/corpus/add.py:280`): standard per-turn id namespace, self-contained case dir
  (trace + pre-state manifests + invariants + server command + expected verdict), labeled
  `pending` (the engine never labels its own cases).
- `--no-ingest` disables banking (parity with `phase0 run`'s opt-out).
- Ingest failure is error-contained: the gate's verdict/exit code is unaffected; the failure
  is reported (never silently dropped) — mirroring the phase0 ingest discipline.
- A banked divergence recomputes `MATCH` through `belay corpus run` (the case stores what
  the recompute needs; no re-resolution of names).

## Out of scope

- Labeling (human act, via `belay corpus label`).
- Shared/remote corpus.
- Banking non-divergent turns; banking trajectory/claim cases beyond the existing v4/v5
  namespaces (reuse as-is; no schema change).

## Acceptance criteria (written first)

1. A regression banks its divergent turn(s) as case(s); `belay corpus run` recomputes each
   `MATCH` (real replay, no network).
2. `--no-ingest` banks nothing and the gate's verdict/exit code is unchanged.
3. An ingest failure (e.g. case-id collision) does not change the gate's verdict/exit code
   and is reported on the gate surface with a named message.
4. A clean gate check banks nothing.
5. Deterministic, no network.

## Dependencies & sequencing

Depends on `gate-check` (needs the divergence set and the verified capture). Independent of
`surface-docs`.

## Open questions

- Whether banked divergences use `kind=corrupt-success` or a neutral label. Default: the
  existing per-turn case shape with `pending` label; `kind` naming decided in tech-plan
  against the case schema.
- Case id collisions across repeated gate runs (same trace stem) — reuse the existing
  `CaseExistsError` behavior: report, do not clobber.
