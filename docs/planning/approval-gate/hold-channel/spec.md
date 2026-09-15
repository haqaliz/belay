# Aspect: hold-channel

**Slug:** `approval-gate/hold-channel` · **Depends on:** `decision-model` (aspect 1)

## Problem slice

The approval directory contract and the live annotation cache: request files written
for the human, decision files read atomically under a bounded, fail-closed deadline,
refusal bytes produced on deny, and the tool-facts cache kept current from the live
wire so `decide_c2s` has facts at hold time.

## In-scope

- The directory contract: `<dir>/requests/<hold_id>.json` (hold id, tool,
  request_id, triggers, `created_at` wall time, `timeout` seconds) and
  `<dir>/decisions/<hold_id>.json` (`{"decision": "approve"|"deny", "reason": str}`).
  Request files written atomically (temp + rename); decision files read atomically
  (a partially-written file is retried, never guessed).
- The bounded poll loop: `poll_interval` (default 0.1 s), `BELAY_APPROVAL_TIMEOUT`
  (default 300 s), injected monotonic clock. Deadline and decision checked under one
  clock in one order (M14): a decision observed before the deadline wins; a decision
  file arriving after a timeout deny is ignored, never applied retroactively.
- Fail-closed deadline (M5): past the deadline → `APPROVAL_TIMEOUT` deny.
- The refusal: a JSON-RPC 2.0 error response with the request's own id, code
  `-32000`, message naming the gate and tool, `data` naming hold id and cause,
  newline-terminated. Produced by this module (it owns the serialiser); delivered
  through the injected `deliver` callback (never through the proxy's forwarder).
- The live annotation cache: tracks c2s request ids → method (bounded FIFO, mirroring
  `index.py:161-177`); an s2c frame whose id names a tracked `tools/list` request is
  parsed for `result.tools[].annotations` (the `annotations.py:60-81` shape);
  `notifications/tools/list_changed` clears the cache until the next snapshot
  (the staleness rule, live).
- The hook surface: `decide_c2s(frame) -> bool` (True = forward, False = suppress +
  refusal + records via injected `record`) and `observe_s2c(frame)` (cache only).

## Out-of-scope

Proxy changes (aspect 3), trace record kinds (aspect 4), console UI, HTTP listeners,
approval servers, adversarial analysis of decision files.

## Acceptance criteria (test-first)

1. A request file contains exactly the contract fields; the write is atomic (no
   partial file observable at any point — pinned by a reader racing the write or by
   temp-name inspection); an unwritable requests dir is a named startup failure.
2. A decision file with `approve` / `deny` resolves the matching hold; an unknown
   decision value or malformed JSON is treated as absent for that poll (retried) and
   never guessed; a file arriving after the deadline is ignored.
3. The deadline is exact under the injected clock: a deny with `APPROVAL_TIMEOUT`
   when no decision arrived; a decision written before the deadline wins even if the
   poll would have elapsed next tick.
4. `decide_c2s` returns False only for a triggered `tools/call`; returns True for
   everything else, including unparseable frames and batch frames; a suppressed call
   produced exactly one refusal delivery and the hold/decision records through the
   injected `record` callback.
5. The refusal is a single newline-terminated JSON-RPC error carrying the request's
   own id, code `-32000`, and `data.belay.approval` with hold id and cause.
6. The annotation cache: a `tools/list` response updates facts per tool (tri-state
   via `declared.declared_state`); a response to a non-`tools/list` request never
   updates facts; a `tools/list_changed` notification invalidates until the next
   snapshot; the id→method tracker is bounded (oldest dropped) and never unbounded.
7. `close_all` resolves every pending hold with `APPROVAL_SHUTDOWN` (M13) and every
   resolution is recorded; a held call's decision is recorded before the refusal is
   delivered (M7 ordering).

## Dependencies and sequencing

Aspect 1's vocabulary and state machine; the injected `record`/`deliver` callbacks
are fake-callable in tests here, wired to the real writer in aspect 4.