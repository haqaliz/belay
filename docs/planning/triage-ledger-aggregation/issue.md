# Issue #52 — feat: triage ledger multi-trace aggregation

## Why
`belay triage-ledger <verify.json>` currently measures one document per invocation. Aggregating a directory/run set was deferred by name at `calibration-ledger` (2026-09-22).

## Scope
- Accept multiple verify documents / a directory, aggregate rows.
- Same pure-re-render discipline: no replay, deterministic, byte-stable `--json`.
- State the excluded/skipped counts and the denominator explicitly.

## Exit criteria
- Aggregation matches hand-computed reliability/ECE on a fixture set.
- Zero decided rows keeps the named refusal (no rates, exit 0).

## Status
Deferred by name; not launch-blocking.
