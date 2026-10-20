# Issue #50 — bug: A2 effect axis ignores annotation staleness

Labels: bug

## Why
`annotation_for_turn` reads only `annotation_snapshot` and never `annotation_staleness`, so a snapshot invalidated by an un-re-snapshotted `tools/list_changed` is used as if live. The trajectory rule handles this case by name (`TOOLSET_UNKNOWN`); A2's effect axis does not, and can therefore emit a grounded FAIL against a contract the server already retracted.

## Scope
- Route staleness through `annotation_for_turn` / `contract_in_force`.
- Abstain with a named cause (UNVERIFIED), never FAIL, when the snapshot is stale.
- Keep single-snapshot traces byte-unchanged.

## Exit criteria
- A stale-contract turn verifies UNVERIFIED with a named cause, not FAIL.
- Anti-overreach test: a fresh contract still FAILs as today.

## Status
Named follow-up in `docs/STATUS.md` (2026-09-21, `effect-conformance-coverage`). Not launch-blocking.
