# Aspect spec — `ingest-correlate-attach`

**Parent PRD:** `docs/planning/observability-interop/prd.md` (C9, first slice)
**One-line boundary:** read OTLP/JSON spans → correlate each to its MCP turn by captured W3C
trace context → attach the existing verdict → report the correlation rate. **No export-back.**

---

## Problem slice & user outcome

An engineer who already collects OpenTelemetry spans runs one command against their exported
spans + the trace Belay captured, and gets, per span, the grounded verdict for the MCP turn it
corresponds to — plus a correlation rate telling them what fraction of their agent's recorded
activity Belay could verify at all (the R6 number).

## In-scope requirements (from the PRD must-haves)

1. **Stdlib-only OTLP/JSON ingest** — parse `ResourceSpans → ScopeSpans → Span`
   (`traceId`, `spanId`, `name`, `startTimeUnixNano`, `attributes`) with stdlib `json` only. **No
   `import opentelemetry`** in `src/belay/`. New package `src/belay/interop/`.
2. **Deterministic correlation by W3C trace context** — index MCP turns by the `traceparent`
   span-id Belay already captures as `trace_context` records (`connection.py:199-211`); join
   ingested spans on `traceId`+`spanId`. Turn identity stays the positional ordinal `n` over
   `tool_calls(derive_correlation(records))`.
3. **Attach the existing verdict** — for a correlated, verifiable turn, call `verify_turn`
   (unchanged) and attach the resulting `TurnVerdict`. C9 computes no verdict of its own; **no axis
   changes.**
4. **Ambiguity fails safe** — a span joining to >1 turn, a re-used span-id, or a `traceparent` on a
   non-`tools/call` frame → `UNVERIFIED` cause `ambiguous-correlation`; never a best-guess attach.
5. **Uncovered → UNVERIFIED, never PASS** — a span with no matching MCP turn (cause
   `no-matching-mcp-turn`) or matching an unrestorable-pre-state turn (cause
   `unrestorable-pre-state`) → `UNVERIFIED`. Falls out of `reduce` (empty→UNVERIFIED,
   `verdict.py:80-82`); pinned by a dedicated test.
6. **Correlation-rate report** — `matched / total` ingested spans **with denominator** + the
   uncorrelated bucket (by named cause), via `_emit` (`cli.py:73`) in the honest style.
7. **`belay interop correlate` subcommand** — argparse group mirroring `phase0`/`corpus`
   (`cli.py:1107-1517`); positional `<otel-spans.json> <trace-dir-or-file>`, optional
   `--manifest-dir`, `--json`; heavy imports lazy inside the handler.
8. **`--json` machine-readable output** — span-id → matched turn → verdict status + rate summary,
   stdlib-serialized (the first general machine-readable verdict surface).
9. **Extend the zero-LLM guard** — add `src/belay/interop/` to `GUARDED_ROOTS`
   (`tests/test_verify_zero_llm.py:38`).
10. **Malformed-OTLP guard** — a non-conforming spans file → a recorded, honest error, never a
    silent empty correlation.
11. **Docs sync** — C9 row in `CAPABILITY_ROADMAP.md`, `CLAUDE.md` status block, README
    honest-coverage statement (correlation needs propagated W3C trace context; uncorrelated spans
    are reported, never PASSed).

## Out-of-scope boundaries

- Export verdicts back to OTLP (span attributes/events / fixture-collector round-trip) — 2nd aspect.
- OTel SDK dependency; live OTLP exporter/collector; time-window correlation; `NOT_COVERED`.
- Any change to `proxy/sandbox/snapshot/replay/verify` beyond the `GUARDED_ROOTS` addition.

## Acceptance criteria (testable — written first, the repo is test-first)

- **AC1** A fixture OTLP/JSON span set whose spans carry `traceparent`s present in a fixture trace
  correlates each to its MCP turn (`CAPABILITY_ROADMAP.md:480`).
- **AC2** A span with no matching MCP turn → `UNVERIFIED`, cause `no-matching-mcp-turn`; asserted
  **never `PASS`** (`CAPABILITY_ROADMAP.md:481`, R5).
- **AC3** A span matching an unrestorable-pre-state turn → `UNVERIFIED`, cause
  `unrestorable-pre-state`.
- **AC4** A span joining to >1 turn (or a `traceparent` on a non-`tools/call` frame) → `UNVERIFIED`,
  cause `ambiguous-correlation`; never attached to a guessed turn.
- **AC5** A correlated, verifiable turn attaches the exact `TurnVerdict` `verify_turn` produces
  (status + sub-verdicts), byte-for-byte with the standalone `belay verify` path.
- **AC6** The correlation rate is reported as `matched/total` with the denominator, and the
  uncorrelated bucket is broken down by named cause.
- **AC7** `--json` output round-trips (stdlib `json.loads`) with span-id, matched turn index,
  verdict status, and rate summary intact.
- **AC8** A malformed OTLP/JSON file yields a named error, not an empty success.
- **AC9** `tests/test_import_guard.py` and `tests/test_verify_zero_llm.py` stay green with
  `src/belay/interop/` present (zero-dep + zero-LLM preserved).
- **AC10** Deterministic, no network — all fixtures, CI-runnable.

## Dependencies & sequencing

- Depends on merged C1–C4 (all on master). Reuses `read_trace`, `derive_correlation`, `tool_calls`,
  the `trace_context` derivation (`connection.py`), and `verify_turn` unchanged.
- Natural internal order: (a) OTLP/JSON parser [standalone] ∥ (b) trace_context→turn index +
  correlation join [reads trace] → (c) attach + report + CLI + `--json` [needs a,b] → (d) docs +
  guard-root + honest-coverage.

## Open questions / risks specific to this aspect

- **Span-id vs parent-id semantics.** Which W3C field identifies "the MCP call span" — the span's
  own `spanId`, or the `traceparent`'s `parent-id` recorded on the MCP frame? Resolve against a
  real captured `trace_context` record during RED (the fixture must be built from an actual capture
  shape, not invented). This is the one place the fixture could encode a wrong assumption.
- **OTLP version pinning.** Pin fixtures to a named OTLP/JSON version; parse defensively.
