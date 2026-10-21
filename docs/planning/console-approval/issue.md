# Issue #55 — feat: console approval UI

## Why
The approval gate ships as an engine surface with a file contract (`BELAY_APPROVAL_DIR`); the console wiring was deferred by name at `approval-gate` (2026-09-15).

## Scope
- Console lists pending holds and writes approve/deny decisions.
- Fail-closed timeout is visible in the UI.
- A denied call stays an observation, never a turn or verdict.

## Exit criteria
- E2E: hold appears, approve forwards verbatim, deny returns the named refusal.
- No verdict axis changes.

## Status
Deferred by name; not launch-blocking.
