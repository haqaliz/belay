# PRD — A2 effect axis must abstain on a stale annotation contract

**Issue:** #50 · **Type:** bug · **Branch:** `bug/50/aliz` · **Slug:** `annotation-staleness`

## Problem

`annotation_for_turn` picks the `tools/list` snapshot in force at the call's
`request_seq`. It ignores `notifications/tools/list_changed` frames between that snapshot
and the call. Under MCP, a `list_changed` invalidates the snapshot until the client
re-lists; until then nobody knows the contract.

Consequence: a turn can be FAILed against a contract the server already retracted. For a
tool that declared `readOnlyHint: true` before the change, any observed mutation becomes a
grounded **FAIL** even though the declaration may no longer exist. That is a false verdict
on the axis whose whole claim is "grounded, never guessed".

Belay already records the invalidation (`annotation_staleness`), and the trajectory rule
already abstains on it (`TOOLSET_UNKNOWN`). A2 is the only reader that does not.

**Severity:** correctness of a verdict, not cosmetics. Silent today because the record is
produced only when no later re-snapshot exists anywhere in the trace, so the common
"change then re-list" session never exposes it.

## What this ships

A per-call staleness gate inside `annotation_for_turn`:

> The contract is stale for turn *N* when a `notifications/tools/list_changed` frame has
> `snapshot_seq < notification.seq < call.request_seq`, where `snapshot_seq` is the
> `source_seq` of the oldest snapshot in force (twins included).

On a stale contract, return a `TurnAnnotation` with:

- `readonly` unobserved (the tri-state's not-declared state), `openworld` likewise;
- a named `producer` (`stale-snapshot`, new member of the closed `Producer` literal);
- a `cause` naming the notification.

`render_effect_verdict` then falls through to `UNVERIFIED` (its default for any producer
that is not `server-declared-nothing`). No table change, no `kind` change.

## Non-goals

- No new verdict status, axis, kind or reduction rule.
- No trace-format change; `annotation_staleness` stays a derived fact.
- No change to `_staleness`'s record semantics (whole-trace fact).
- No change to `_uncovered_calls` / `annotation_gap` (a separate reader with the same
  blind spot; named as a follow-up, not silently bundled).
- No corpus back-fill, no recomputation of published numbers.
- Not the "coverage sentence duplicated across 8 render sites" follow-up.

## Acceptance criteria

1. **Stale abstains.** A trace with `tools/list` → `list_changed` → `tools/call`, replayed
   with a mutation, verifies `UNVERIFIED` with cause naming the notification — never `FAIL`,
   never `PASS`.
2. **Named producer.** The abstention carries `producer == "stale-snapshot"`; it is not
   `server-declared-nothing`, so it can never render `NOT_COVERED`.
3. **No regression.** A `list_changed` *after* the call leaves the verdict unchanged
   (`tests/test_verify_effect.py:199` stays green, unmodified).
4. **No list_changed.** Snapshot → call with no notification yields the same status as
   today (declared-true + mutation → FAIL; declared-false → PASS; absent → NOT_COVERED).
5. **Re-snapshot clears it.** `list_changed` → `tools/list` → call uses the new snapshot and
   is not stale.
6. **Composite twins.** One `list_changed` between the twin snapshot and the call abstains
   the whole turn (conservative; never a false FAIL).
7. **Network reader.** The same turn's `openworld` sub-verdict abstains for the same cause
   (no second code path).
8. **Bucket unchanged.** A stale turn reports the existing `replayed but effect unverified`
   canonical cause; no new `REPLAYED_*` label, no `--json` schema change.
9. **Docs.** `STATUS.md`, `CHANGELOG.md` and the module docstring record the fix and that
   no published number moves.

## Risks

- **R-a:** A trace-global gate would abstain calls that precede the notification. Mitigated
  by AC-3's pinned test and a per-call window.
- **R-b:** A future edit reusing `any(annotation_staleness)` silently re-breaks it. Mitigated
  by a unit test at the helper boundary, not only end-to-end.
- **R-c:** Abstaining rewards a server that emits `list_changed` spuriously. Accepted: the
  contract genuinely is unknown, and UNVERIFIED is the honest status.

## Open questions

- 🟡 **Q1 — scope of the gate:** does a `list_changed` before the first snapshot, followed by
  a snapshot and then the call, count as stale? Proposed: no (the snapshot is after it).
- 🟡 **Q2 — `_uncovered_calls` parity:** leave its stale `annotation_gap` as a named
  follow-up, or fix both in this unit? Proposed: follow-up (different verdict path).
