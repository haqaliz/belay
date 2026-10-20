# Understanding — issue #50, A2 effect axis ignores annotation staleness

## What the work is really asking

`annotation_for_turn` correlates a `tools/call` against the most recent `tools/list`
snapshot before it. MCP says `notifications/tools/list_changed` invalidates that snapshot
until the client re-lists. Belay records the invalidation (`annotation_staleness`) but A2
never reads it, so a turn can be judged against a contract the server already retracted —
including a grounded **FAIL** on `readOnlyHint: true` when the tool may no longer declare it.

The trajectory rule already abstains in this situation (`TOOLSET_UNKNOWN`). A2 does not.
That asymmetry is the defect.

## Affected area

- `src/belay/annotations.py` — `_staleness` (record producer), `contract_in_force`.
- `src/belay/verify/effect.py` — `annotation_for_turn` (`PRODUCER_*` return sites),
  `render_effect_verdict` (status split keys on `producer`, not `cause`), and the two other
  A2 readers of the same annotation (`render_openworld_verdict`, `network_subverdict`).
- Tests: `tests/test_verify_effect.py`, `tests/test_effect_absent_contract.py`,
  `tests/test_annotations.py`, `tests/test_effect_composite_snapshot.py`.
- Docs: `TRACE_FORMAT.md` (no format change), `STATUS.md`, `CHANGELOG.md`.

## A fact that changes the fix

`_staleness` emits a record only when **no later snapshot exists anywhere in the trace**.
So the record is a whole-trace fact, not a per-call one. A call between a `list_changed`
and a later re-snapshot produces no record at all. The fix must therefore read the raw
notification frames per call, not `any(annotation_staleness)`.

## Contradictions / traps checked

- `tests/test_verify_effect.py:199` has a `list_changed` **after** the call and still expects
  FAIL. A per-call window (`snapshot_seq < notification.seq < request_seq`) leaves it green.
  A trace-global gate would wrongly abstain it — this is the trap.
- Status must stay `UNVERIFIED` and `kind` must stay `effect`: narrowing `kind` would make
  every stored corpus case of that kind a `REGRESSION`, and would need
  `_PREFIX_LABELS` + `_REPLAYED_CAUSES` registrations. Message-only causes are invisible to
  `corpus run` (cases store axis/kind/status only), which is the compatible choice.
- Producer iv (`server-declared-nothing` → `NOT_COVERED`) must not absorb a stale contract:
  "the server declares nothing" is false when the snapshot was retracted.

## Axis

A2 only. No A1/A3 change, no reduction change, no published number moves.

## Open questions for the PRD

1. Should a stale contract also abstain the `openWorldHint` (network) reader? It shares
   `annotation_for_turn`, so leaving it would require a second code path. Recommendation:
   abstain both — same unknowable contract.
2. Is a stale contract a named producer (`stale-snapshot`) or a bare UNVERIFIED? Named,
   matching the module's discipline that every abstention says why.
