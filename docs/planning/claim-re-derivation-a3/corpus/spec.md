# Spec — corpus (intent-drift cases, schema v5)

> Part of `claim-re-derivation-a3` (C8). PRD: `../prd.md`.

## Problem slice

Every A3 FAIL becomes a labeled, replayable **intent-drift** case (moat #2 must compound with
each capability — `CLAUDE.md`), and `corpus run`/`corpus score` treat it as first-class without
inverting or weakening anything that exists.

## In-scope

- **Case schema v5** (`src/belay/corpus/case.py:74-89` pattern): an optional instance-level
  `claim` expected field mirroring the v4 `trajectory` field (`case.py:82-88`,
  `_validate_trajectory` `case.py:285-321`): `{"status": <FAIL|WARN|UNVERIFIED>,
  "cause": <named cause or null>, "check": {"source": str, "exit_code": int or null}}`.
  Absent = no A3 dimension declared (byte-compatible with every prior case); malformed is a load
  error, never a silent drop. `CASE_SCHEMA_VERSION = 5`.
- **Banking**: A3 FAIL at trace close (phase0 runner, ingest path) banks an intent-drift case —
  self-contained: trace + claim record + final-state manifests + the check source. Case id in a
  disjoint instance-level namespace (`_safe_case_id` `src/belay/corpus/add.py:122-142` pattern).
- **Recompute**: `corpus run` routes a `claim`-bearing case through the instance path
  (`_verify_one_trace`, `ingest=False` — `src/belay/corpus/run.py:479-543` pattern); MATCH /
  REGRESSION decided on the A3 dimension (divergence named `claim status`); declared-miss
  transitions STILL_MISSED / MISS_CLOSED where applicable. **Under `--no-claim-axis`, a
  claim-bearing case SKIPs with a named cause — never REGRESSES** (the refutation stays green).
- **Metrics**: `corpus score` needs no change — A3 FAIL counts positive (`metrics.py:236`),
  human labels true-positive/false-positive/unverifiable/pending unchanged; an A3-bearing case
  with no recompute-able A3 (axis disabled) lowers coverage, never fabricates precision.
- **`corpus show`** renders the declared A3 expected beside the recomputed outcome, incl. the
  check source.

## Out-of-scope

- Any change to per-turn case semantics, `recorded_miss` (v3), or trajectory (v4) behavior.
- A3 WARN-path cases (v0 WARN vocabulary stays empty — PRD nice-to-have).

## Acceptance criteria (test-first)

1. An A3 FAIL banks an intent-drift case in its own namespace; per-turn and trajectory case
   shapes coexist byte-identically (RED-first like `corpus-trajectory-banking`,
   `tests/test_corpus_trajectory_{ingest,run,schema,show}.py`).
2. Recompute routes a `claim` case through the instance path and reports MATCH on an equal
   recompute, REGRESSION on divergence, SKIP-with-cause under `--no-claim-axis`.
3. Schema v5 round-trips; v4-and-earlier cases load unchanged; malformed `claim` field is a
   load error.
4. Labeled intent-drift cases score with real denominators; unrestorable pre-state stays
   unbankable fail-closed.
5. `corpus run --no-claim-axis` on a corpus containing a claim-bearing case: every PASS/FAIL
   identical to the axis-on run, and the claim case SKIPs with a named cause — the refutation.

## Dependencies

- Aspects `evaluator`, `surfaces`. C1–C6 (corpus machinery shipped).

## Open questions

- Whether the check source (potentially large) lives in the case payload or as a sidecar file
  in the case dir. Recommend sidecar (case dir already holds trace + manifests). Decide at
  plan time.