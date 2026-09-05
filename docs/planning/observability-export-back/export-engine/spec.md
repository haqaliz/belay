# Aspect spec — `export-engine`

**Parent PRD:** `docs/planning/observability-export-back/prd.md` (C9, second aspect)
**One-line boundary:** the pure export function — given the parsed OTLP document and the
correlation results, produce a new OTLP/JSON document in which every ingested span carries
its verdict as attributes plus one event. No CLI, no I/O, no network.

---

## Problem slice & user outcome

The correlation results hold every span's verdict, but nothing can put a verdict back
*inside* the OTLP document a collector consumes. This aspect is the shape: the attribute
contract (below) that makes "a Belay FAIL is visible inside the dashboard the team
already watches" (`CAPABILITY_ROADMAP.md:829`) real, with the honesty contract in-band.

## In-scope requirements (from the PRD must-haves 2, 3, 5, 6)

1. **`src/belay/interop/export.py`** — a pure function:
   `build_enriched_document(document, spans, results) -> dict`, where `document` is the
   parsed OTLP/JSON doc (dict), `spans` the `parse_otlp` output, `results` the
   `correlate_and_attach` output. Deep-copies the document; **never mutates its inputs**
   (asserted by test).
2. **Document-order pairing (settled in the plan, 2026-09-05)** — `correlate_and_attach`
   returns exactly one `CorrelatedSpan` per input span, in input order (`attach.py:158-208`),
   and `parse_otlp` preserves document order (pinned by test). The export therefore pairs
   `results[i]` with `spans[i]` positionally, asserting equal lengths — the attach boundary
   is untouched (no `CorrelatedSpan` change, no `--json` report change). The
   `(traceId, spanId)` pair remains the *attribute-contract* key (each exported span's
   verdict attributes land on that span), but pairing needs no key.
3. **Every ingested span is marked** — matched → its replayed `TurnVerdict` verbatim
   (nothing re-computed, nothing re-reduced); unmatched → `UNVERIFIED` +
   `no-matching-mcp-turn`; ambiguous → `UNVERIFIED` + `ambiguous-correlation`. No span
   exported bare, never `PASS` for a non-replayable span.
4. **Attribute contract** (the exported shape; pinned by a byte-stable fixture):
   - `belay.verdict.status` — string (reduced status).
   - `belay.verdict.axis` — string, axis of the highest-ranked sub-verdict (rank table
     `verdict.py:67-73`, first among ties); **absent** when the verdict has none.
   - `belay.verdict.cause` — string; **absent when None, never `""`**.
   - `belay.verdict.turn_index` — int; matched spans only.
   - `belay.verdict.coverage` — JSON string array of `NOT_COVERED` sub-verdict `kind`s
     (e.g. `["effect:network"]`); **absent when none** (a PASS rendered without it is
     the named failure mode of this surface).
   - `belay.verdict.sub_verdicts` — JSON string array of
     `{axis, kind, status, message}`; **absent when empty**.
   - Span event `belay.verdict` — `timeUnixNano` = the span's own
     `start_time_unix_nano` (deterministic, from the input), attributes carrying
     `message` (and `observed`/`expected` where present).
5. **Deterministic output** — identical inputs → byte-identical document. Serialization
   with stable key order (settled: `json.dumps(..., sort_keys=True, indent=2)`), decided
   in the plan and pinned by the byte-stable fixture test.
6. **Zero-dep / zero-LLM** — stdlib only; `src/belay/interop/` already sits in the
   zero-LLM guard roots; no new imports outside the stdlib.

## Out-of-scope boundaries

- CLI, `--out`, exit codes — `export-cli` aspect.
- Live OTLP exporter/collector connection; OTel SDK; anything Langfuse-specific.
- Multi-trace-directory aggregation (separate named deferral).
- Any change to `verify_turn`, `verdict.reduce`, or the correlate CLI output shape.
- Threading `observed`/`expected` beyond the event; no new report surface.

## Acceptance criteria (testable — written first, the repo is test-first)

- **AC1** Round-trip: the exported document parses with `parse_otlp`; every span's
  `belay.verdict.status` + `belay.verdict.axis` equal the source verdict's reduced
  status + worst axis (`CAPABILITY_ROADMAP.md:839`).
- **AC2** A non-replayable ingested span (unmatched/ambiguous) exports `UNVERIFIED` with
  its named cause — asserted **never `PASS`** (R5).
- **AC3** The coverage line survives: a turn whose verdict carries a `NOT_COVERED`
  sub-verdict exports `belay.verdict.coverage` naming that dimension; a PASS without one
  exports **no** coverage key (absent-never-zero).
- **AC4** Absent-never-zero: no cause → no `belay.verdict.cause` key (never `""`); no
  sub-verdicts → no `belay.verdict.sub_verdicts` key.
- **AC5** Determinism + purity: two identical runs → byte-identical documents; the input
  document is deep-equal after the call.
- **AC6** Byte-stable fixture: the canonical fixture (`tests/fixtures/interop/
  spans_ok.json` + the canonical traceparent trace) exports to a committed, byte-identical
  document — contract drift shows in the diff.
- **AC7** Every ingested span is marked (no bare span in the exported document).
- **AC8** Document-order pairing is exercised: a document containing two spans that share
  a `spanId` across different traces attaches each to its own verdict (no cross-talk); a
  length mismatch between `spans` and `results` is a loud error, never a silent zip.
- **AC9** The existing serialization is untouched: `tests/test_interop_cli.py` ac6/ac7
  stay green unchanged (no `CorrelatedSpan` or report change).

## Dependencies & sequencing

- Depends on merged slice 1 (`correlate.py`, `attach.py`, `otlp.py`, the `--json`
  report) — all on master.
- Natural internal order: (a) `CorrelatedSpan.trace_id` (additive, pinned by AC9) →
  (b) `export.py` pure function → (c) the byte-stable fixture (AC6, last, once the
  serialization is settled).

## Open questions / risks specific to this aspect

- **Serialization formatting.** `sort_keys=True, indent=2` vs compact — settled in the
  plan; the byte-stable fixture is the arbiter and the only place this decision shows.
- **Worst-axis definition.** Highest-ranked sub-verdict by the existing rank table;
  first among ties. Deterministic; stated so the round-trip test and the implementation
  cannot disagree.
- **Pairing seam.** Positional pairing relies on the one-per-span-in-order invariant of
  `correlate_and_attach`; the length assertion is the guard, and the spec's AC8 covers
  the cross-trace shared-spanId shape.