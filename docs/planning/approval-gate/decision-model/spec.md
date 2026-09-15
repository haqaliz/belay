# Aspect: decision-model

**Slug:** `approval-gate/decision-model` · **Depends on:** nothing (stdlib + `belay.declared`)

## Problem slice

The pure decision core of the approval gate: given a c2s frame and the live annotation
facts for the tool it names, decide hold / no-hold, and model a hold's life (pending →
approved / denied / timed out) with a closed cause vocabulary. No I/O, no proxy
coupling, no trace writes — everything testable with plain bytes and dicts.

## In-scope

- Parse a frame **copy**: detect `method == "tools/call"`, extract `params.name` and
  the JSON-RPC `id`.
- Decide from tri-state facts (`belay.declared`): hold iff `destructiveHint` or
  `openWorldHint` is `declared-true`. `not-declared`, `declared-false`,
  `declared-non-boolean`, unknown tool, or no snapshot → forward untouched.
- Hold state machine: `pending` → resolved with one of the closed causes
  `APPROVED` / `DENIED` / `APPROVAL_TIMEOUT` / `APPROVAL_SHUTDOWN`; waited-seconds
  accounting; late resolution is refused (a resolved hold never re-resolves).
- Hold ids: deterministic, unique per hold, filesystem-safe, human-meaningful
  (monotonic sequence + sanitized tool name; the `_safe_case_id` precedent,
  `corpus/add.py:122-150`).
- Injectability of the clock (deadline decisions are pure functions of an injected
  monotonic clock).

## Out-of-scope

Batch JSON-RPC frames (a hold would require rewriting the frame — the proxy cannot;
batch frames are **never held** and forwarded untouched — document in the docstring).
I/O, channels, proxy changes, trace records, the annotation cache (aspect 2).

## Acceptance criteria (test-first)

1. `is_tools_call(frame)` is true exactly for single JSON-RPC requests with
   `method == "tools/call"`; false for notifications, other methods, responses,
   batches, and unparseable bytes — never raises on garbage.
2. `tool_name(frame)` / `request_id(frame)` extract correctly; a non-string or absent
   `params.name` yields None (never a hold on doubt).
3. `triggers_for(facts)` returns exactly the declared-true annotations among
   `destructiveHint` / `openWorldHint`, using the `declared.py` vocabulary; every
   other tri-state and an absent dict yield no hold.
4. The state machine resolves each pending hold exactly once; a second resolution
   raises or is refused by name; `close_all(APPROVAL_SHUTDOWN)` resolves every pending
   hold with that cause.
5. Hold ids are deterministic for equal inputs, unique across holds, filesystem-safe
   (no `/`, no path separators, no empty segments), and carry the tool name.
6. Timeout decisions are exact functions of the injected clock: `deadline` reached →
   `APPROVAL_TIMEOUT`; decision observed before deadline wins; the same inputs always
   produce the same outcome.

## Dependencies and sequencing

None. First aspect; everything else builds on the vocabulary and state machine it
exports.