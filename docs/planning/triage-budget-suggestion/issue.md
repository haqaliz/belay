# Issue #53 — feat: triage budget auto-tuning

## Why
The calibration ledger `informs` the replay budget but the operator still sets the knobs by hand. Auto-tuning was deferred by name at `calibration-ledger` (2026-09-22).

## Scope
- Propose (not silently apply) threshold/top-N from a ledger.
- Human confirmation stays in the loop; no skip may become PASS.

## Exit criteria
- A tuning suggestion is reproducible from the same ledger.
- A skipped turn remains UNVERIFIED-by-budget.

## Status
Deferred by name; not launch-blocking.
