# Aspect: trace-observations

**Slug:** `approval-gate/trace-observations` · **Depends on:** `decision-model` + `proxy-deny` (aspects 1, 3)

## Problem slice

The approval gate's events become first-class trace observations: two additive record
kinds (`approval_hold`, `approval_decision`), written through the recorder's
documented extension point, readable by a derived reader, and invisible-but-skipped
to every old reader. No schema bump, no `frame` records for events that never crossed
the server boundary, and the trace-ordering guarantee untouched.

## In-scope

- Extend `trace.py:KINDS` (trace.py:55-66) with `approval_hold` and
  `approval_decision` — additive, written via `TraceWriter.record` (the documented
  extension point, trace.py:483-493); the envelope (`v`, `seq`, `t_in`,
  `observation_point: "proxy"`) applies unchanged.
- Field contract:
  - `approval_hold`: `hold_id`, `tool`, `request_id`, `triggers` (list of annotation
    state names, e.g. `["destructiveHint"]`), `timeout` (seconds).
  - `approval_decision`: `hold_id`, `decision` (`approve`/`deny`), `cause`
    (closed vocabulary: `APPROVED` / `DENIED` / `APPROVAL_TIMEOUT` /
    `APPROVAL_SHUTDOWN` / `APPROVAL_FAULT`), `waited` (seconds, injected-clock).
- The hold record is written when the hold begins (S1 — a live feed can render
  "awaiting approval"); the decision record is written **before** the refusal is
  delivered to the client (M7 ordering) and before an approved frame is forwarded.
- A derived reader `derive_approval_events(records)` (mirroring
  `derive_annotations`' shape) returning the events in seq order; absent records →
  empty list, never a placeholder.
- Old-reader compatibility: `replay/reader.py:139-152` skips unknown kinds by
  contract — a round-trip test proves an approval-carrying trace reads with all
  frame records intact and the new kinds skipped-with-name.
- `docs/technical/TRACE_FORMAT.md`: the two kinds documented (fields, meaning,
  the never-a-frame rule).
- The e2e denied trace correlates cleanly: `index.classify` over it produces no
  `response-without-request` and no `unanswered` from the approval event (nothing
  from the gate flows through the correlation machinery).

## Out-of-scope

Verify/console reporting (aspect 5), the live cache's internal state (aspect 2),
banking, schema bumps, frame-record changes.

## Acceptance criteria (test-first)

1. A writer with the new kinds writes records whose envelopes match every existing
   record's shape (`v`, `seq`, `t_in`, `observation_point: "proxy"`); seq is
   allocated under the writer's lock and is unique.
2. The gate (aspect 2, real `record` wiring) writes `approval_hold` at hold start and
   `approval_decision` before the refusal delivery / before forwarding an approved
   frame — pinned by ordering assertions in the e2e deny and approve traces.
3. `derive_approval_events` returns the events in seq order with exactly the field
   contract; a trace with no approval records returns `[]`.
4. An approval-carrying trace round-trips through the reader: every `frame` record
   is intact and byte-identical; the new kinds appear as named skips, not errors.
5. `index.classify` over an e2e denied trace yields no `response-without-request`
   and no `unanswered` caused by the gate's events (the refusal is not a frame).
6. `tests/test_trace_ordering.py` stays green untouched (the new kinds never wait,
   never park, never enter the request index — written via `record`, not
   `_record_frame`).
7. `TRACE_FORMAT.md` documents both kinds with the never-a-frame rule and the closed
   cause vocabulary.

## Dependencies and sequencing

Aspect 1's vocabulary (hold ids, causes), aspect 3's deny path (the e2e traces the
records must reflect). The kinds can be added and the reader built before aspect 3
lands; the e2e ordering tests need 3.