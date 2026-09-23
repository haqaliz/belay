# Aspect — `corpus-banking`

**Grade: MEASURED** (with deterministic seams). Follows `mint-run`; consumes its
captures and ledgers. The banking machinery already exists in the engine — this aspect
runs it, observes it, and names what it cannot do.

## Problem slice

Turn the run's captures into **banked corpus cases** — moat #2's first real growth
since 2026-08-12 — and prove the corpus recomputes cleanly. The three capabilities
shipped unexercised since the last mint (trajectory banking, the A3 claim column, the
recorded-miss declaration) get their first real-data exercise. Nothing here invents new
machinery; it uses what shipped:
`belay phase0 run` ingests per-turn FAILs (`src/belay/phase0/runner.py:445-466`),
trajectory FAILs bank `trace-<instance>-trajectory` (`runner.py:480-549`), A3 FAILs
bank `trace-<instance>-claim` (`runner.py:560-599`), `belay corpus run` recomputes
(`src/belay/corpus/run.py`).

## In scope

1. After each stage's verify (aspect `mint-run`), confirm what banked: per-turn cases,
   `trace-<instance>-trajectory` cases, `trace-<instance>-claim` cases — counts with
   the denominator stated.
2. Per-turn FAILs that could not bank are reported **`flagged-but-unaddable` with named
   causes** (the `ValueError → flagged_unaddable` seam, `runner.py:465-466`; the ledger
   lines), never silent.
3. **`belay corpus run` over the grown corpus**: 0 REGRESSION, with `--shell-server`
   supplied for shell-bearing trajectory cases (v0.36.0 `corpus-shell-routing` — a
   trajectory recompute without it SKIPs with
   `TRAJECTORY_SHELL_BOUNDARY_NOT_SUPPLIED` / `TRAJECTORY_FILESYSTEM_BOUNDARY_UNEXPRESSIBLE`,
   `src/belay/corpus/run.py:524-562`). Each case's `server_command` points into
   `eval/servers/` (machine-bound through the SERVER — unchanged, stated).
4. `belay corpus score` re-read after banking: `precision`/`recall` stay `n/a`
   (cases bank `pending`; only the owner labels, S-1) — the honest reading, recorded.
5. A follow-on note, named not built: the calibration ledger (v0.37.0) awaits decided
   per-turn volume like this run's; consuming these traces under a triage-configured
   `belay verify` is a later unit, not this aspect.

## Out of scope

- **Owner adjudication / labeling** (S-1) — the evidence pack is `audit-and-publish`'s
  job, judgments are the owner's.
- Any recorded-miss **declaration** — only the owner may declare one (schema v3), and
  only if adjudication finds a miss.
- Any change to banking machinery, case schema, or the corpus CLI.
- A violation rate (Q1) — dispositions and counts only.

## Acceptance — measured, never asserted

| # | Criterion |
|---|---|
| B1 | Every trajectory FAIL from the run's ledgers banks as `trace-<instance>-trajectory` and recomputes MATCH under `corpus run` (M2) |
| B2 | Every per-turn FAIL banks, or is reported `flagged-but-unaddable` with its named cause (M3) |
| B3 | `corpus run` over the grown corpus: 0 REGRESSION, 0 unexplained SKIP (M5); every SKIP's cause named and accounted |
| B4 | The A3 column is filled per instance — a verdict or a named cause, never `claim unrecorded` (M7) |
| B5 | `corpus score` reads as expected (pending-excluded; precision/recall `n/a` stated, never fabricated) |
| B6 | No published number moves (M10) |

## Deterministic seam (test-first, before the run)

A committed helper invocation for the post-run `corpus run` — the exact command with
`--shell-server` placement — pinned by a test asserting its shape (the `mint-run` freeze
pattern), so the recompute cannot be mis-invoked after the run. The engine behavior
itself is already pinned by the shipped suite.

## Dependencies / sequencing

Depends on `mint-run` (captures + ledgers). Runs after the stage verifies, before
`audit-and-publish`. The deterministic seam (helper + pin) is built before any spend,
alongside `verify-parity`.

## Risks

- A run that banks nothing is a **recorded result** (the likeliest outcome at n=8 —
  carried from `mint-run`); B1–B4 then report zero counts with the denominator stated,
  never a red failure.
- Corpus recompute SKIP causes must be distinguished from banking failures — every SKIP
  named, none papered over.
- Case-id collisions with prior banked namespaces are fail-closed by design
  (`CaseIdCollisionError`, the registry generator's guard) — a collision is reported,
  never re-seeded.