# Aspect: baseline-bank

## Problem slice

There is no way to bank a known-good run as a baseline: the corpus stores *cases* (one
flagged/declared turn or instance), not a whole run's expected verdicts. A CI gate needs a
self-contained, replayable baseline keyed by run id.

## User outcome

`belay gate baseline <trace> [--server -- CMD…]` verifies the capture and stores a
baseline the gate can later re-verify and diff against, with provenance a reviewer can read.

## In scope

- CLI: `belay gate baseline <trace>` (replay-bearing surface) with `--server`, `--replays`,
  `--timeout`, `--shell-server`, `--invariant-library`/`--invariants`/`--no-default-invariants`
  (parity with `verify`), `--force` for re-banking, `--json` (S1).
- Resolve run id from the trace's `run_identity` record; `--run-id` fallback (S2); absent ⇒
  exit 2, named cause `NO_RUN_IDENTITY`.
- Verify the capture via `_verify_one_trace(..., ingest=False)`; store a self-contained
  baseline directory under `baselines/local/<run-id>/` (gitignored) containing: the trace,
  its manifests + snapshots, the resolved server command, provenance (`engine version`,
  platform, capabilities, capture_platform), and the expected verdict set — per-turn
  (status + ordered sub-verdict set), trajectory (`status`/`cause`/`evidence_count`), claim
  when declared.
- Refuse re-banking an existing run id without `--force` (exit 2, named message).
- Never upload; path user-specified.

## Out of scope

- Versioned baselines / history (v1 is one baseline per run id).
- Baseline diffing (that is `gate-check`).
- Banking into the corpus (that is `divergence-banking`).
- Metadata the trace doesn't carry (model/prompt) — provenance is engine + platform +
  server command only.

## Acceptance criteria (written first)

1. A clean capture banks: the baseline directory is self-contained, and re-reading it yields
   the expected verdict set byte-stable across two banks of the same trace.
2. A capture with no identity (and no `--run-id`) exits 2 with `NO_RUN_IDENTITY`, and
   nothing is written.
3. Re-banking an existing run id without `--force` exits 2 and leaves the existing baseline
   untouched; `--force` replaces it.
4. Provenance is recorded (engine version, platform, capabilities, server command) and
   round-trips through the store.
5. Deterministic, no network.

## Dependencies & sequencing

Depends on `run-identity`. Blocks `gate-check` and `divergence-banking`.

## Open questions

- Exact store layout (`baseline.json` + `trace.jsonl` + `manifests/` + `snapshots/`) —
  mirrors the capture layout and the corpus case precedent; pin in tech-plan.
- Whether the baseline stores the *full* expected verdict set or only the dimensions the
  gate compares. Default: full set — it is the re-derivation record.
