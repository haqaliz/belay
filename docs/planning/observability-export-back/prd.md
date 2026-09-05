# PRD — observability-export-back

> C9's second aspect: export Belay verdicts back into an OpenTelemetry collector as span
> attributes/events. Completes the locked Phase-1 interop deliverable whose export-back
> half is a named deferral (`docs/technical/CAPABILITY_ROADMAP.md:859-861`, `:900`;
> `docs/ROADMAP.md:272`, `:263`).
> Branch: `feat/observability-export-back/aliz`. Owner: `aliz`. Decisions confirmed
> 2026-09-05 (prd-interview): own planning dir; attributes + one event; new subcommand
> `belay interop export`; `--out FILE` default stdout; rc 0 on success / rc 1 on
> operational failure.

## Problem Statement

A team already running Langfuse / Phoenix / an OTel collector cannot see a Belay verdict
in the dashboard they already watch (`docs/planning/observability-interop/prd.md:15`).
C9's first slice proved the ingest direction — OTLP spans correlate deterministically to
MCP turns and get the replayed verdict attached — but the export direction is a named
deferral on every surface that mentions it (`CAPABILITY_ROADMAP.md:859-861`; `ROADMAP.md:263`,
`:272`; `CHECKLIST.md:266`; `STATUS.md:43`, `:72`; `CHANGELOG.md:1194-1207`). The
positioning claim *"we complement Langfuse/Phoenix, we don't compete"* stays rhetorical
until a Belay verdict can travel back into the observability surface the team already
uses. This is the surface with the lowest adoption cost the product has: it does not ask
a team to switch anything.

**Evidence it is real:** the roadmap's own C9 rationale names this as the point of the
capability — "It converts the incumbents from competitors into distribution"
(`CAPABILITY_ROADMAP.md:823-824`) — and the MCP 2026-07-28 revision makes trace context
protocol-native, which the roadmap reads as "C9 got easier AND more urgent"
(`CAPABILITY_ROADMAP.md:63-68`).

## Goals & Success Metrics

- **Shipped:** `belay interop export <otlp> <trace>` writes a valid OTLP/JSON document in
  which every ingested span carries its verdict as attributes (plus one event), with the
  coverage line attached — the pre-registered C9 acceptance: "Exported verdicts round-trip
  into a fixture collector with the axis and status intact"
  (`CAPABILITY_ROADMAP.md:839`).
- **Honest:** every exported span is either its real replayed verdict or `UNVERIFIED` with
  a named cause; `PASS` never appears without its coverage line (R5 —
  `ROADMAP.md:368`); a non-replayable ingested span exports `UNVERIFIED`, never `PASS`.
- **Measurable:** the existing suite stays green (2091 tests at v0.27.0); the new RED
  tests land first; determinism proven by test (two identical runs → byte-identical
  export); zero new runtime dependencies (machine-enforced by the import guard).
- **Doc-true:** the deferral lines that the slice actually retires say so, and only those;
  the "no Langfuse integration" honesty lines survive unless this slice genuinely
  retires them.

## User Personas & Scenarios

- **The engineer running agents in production** (ICP): already watches their team's
  Langfuse/Phoenix/OTel dashboard. After this slice they can run
  `belay interop export agent-run.otlp agent-run.trace --server -- mcp-server-fs` and
  their dashboard's spans now carry `belay.verdict.status`, the worst axis, the cause,
  and the coverage line — a FAIL is visible next to the span it belongs to, without
  opening a second tool.
- **The evaluator / platform engineer**: exports verdicts into a shared collector
  pipeline for audit dashboards; gets the honesty contract in-band (UNVERIFIED and
  NOT_COVERED travel with every span), so no downstream dashboard can render an
  unmarked span as verified.

## Requirements

### Must-have

1. **`belay interop export` subcommand** mirroring `correlate`'s flags (positional `otlp`,
   positional `trace`, `--server`, `--manifest-dir`, `--replays`, `--timeout`) plus
   `--out FILE` (default stdout). Same fail-closed error behavior as `correlate`
   (missing/malformed files, directory trace argument).
2. **Verdict enrichment per ingested span, pure and deterministic:**
   - Matched span → its replayed `TurnVerdict` carried **verbatim** (axis + status
     intact; nothing re-computed, nothing re-reduced — C9 computes no verdict of its
     own, `docs/planning/observability-interop/prd.md:143-145`).
   - Unmatched span → `UNVERIFIED` + `no-matching-mcp-turn`; ambiguous → `UNVERIFIED` +
     `ambiguous-correlation` — never `PASS`, never a bare span.
   - The export is a pure function of (parsed OTLP document, correlation results): two
     identical inputs → byte-identical output.
   - **Keyed on the `(traceId, spanId)` pair**, matching `build_turn_index`
     (`src/belay/interop/correlate.py:65`) — never `span_id` alone (8-byte span ids can
     collide across traces in one document).
   - **Input purity:** the parsed OTLP document is never mutated — asserted by
     deep-equality before/after, so the round-trip and determinism tests hold.
3. **Attribute contract** (the exported shape; see Trace/Verdict Contracts below):
   machine fields as span attributes on the correlated span; one span event carrying the
   verdict message/diff; the coverage line travels with every status (a `PASS` exported
   without its coverage is the named failure mode of this surface).
4. **Exit semantics:** rc 0 on successful export; rc 1 on operational failure
   (parse/read/write), fail-closed. Verdict contents never gate the exit code.
5. **Honesty acceptance (RED first):** (a) exported verdicts round-trip into a fixture
   collector (parse the export back) with axis and status intact
   (`CAPABILITY_ROADMAP.md:839`); (b) a non-replayable ingested span exports `UNVERIFIED`,
   never `PASS`; (c) the coverage line (`NOT_COVERED` dimensions with named causes)
   survives the round-trip; (d) absent-never-zero: a verdict with no cause exports no
   cause key, never `""`; (e) deterministic, no network — fixture collector only;
   (f) the parsed document is unmutated (deep-equal before/after); (g) a byte-stable
   exported fixture for the canonical OTLP fixture pins the attribute contract (drift
   shows in the diff, mirroring `belay verify --json`'s pinned machine contract).
6. **Zero-dep / zero-LLM:** stdlib `json` only, no OTel SDK import, nothing in
   `src/belay/interop/` outside the zero-LLM guard (machine-enforced by existing tests).

### Should-have

7. **Help text** states the honesty behavior in one line (mirroring
   `test_help_states_the_no_server_unverified_behavior`).
8. **Docs updates in the same PR**, exactly as wide as the slice: `CAPABILITY_ROADMAP.md`
   C9 section + sequencing row (deferral → shipped slice; drop the **stale**
   `NOT_COVERED` reclassification item — it shipped via `interop-merge-repair`,
   `STATUS.md:660-673`; keep multi-trace-directory aggregation deferred);
   `ROADMAP.md:272/:263` and the `docs/planning/observability-interop/` PRD/spec deferral
   lines (only the "exporting verdicts back into a collector is deferred" halves — the
   "no Langfuse integration" lines stay); `STATUS.md` entry per convention; `CHANGELOG.md`
   per repo convention.

### Nice-to-have

9. `--json`-style machine output of the export summary (correlation rate with
   denominator) alongside the human report.

## Technical Considerations

- **Capability:** C9, second aspect. Dependencies C1–C4 all shipped
  (`CAPABILITY_ROADMAP.md:846`); slice 1 (`belay interop correlate`) shipped v0.5.0.
  The slice is unblocked.
- **Pipeline position:** capture (C1) → sandbox (C2) → replay (C3) → verdict (C4/C5/A3)
  → ingest+correlate+attach (C9 slice 1) → **export (this slice)**. It consumes
  `correlate_and_attach` output and the original parsed OTLP document; it produces
  nothing the engine's verdict machinery reads.
- **Verdict impact:** **none.** No verdict, axis, status, reduction, corpus, or
  published number changes; no `verify_turn` change. The export re-emits existing
  verdicts verbatim. This is pinned by test: the round-trip asserts axis+status equality
  with the source `TurnVerdict`.
- **Attach-boundary gap (known):** `CorrelatedSpan` carries only `span_id` from the
  original span — `trace_id`, `name`, `start_time_unix_nano`, `attributes` are dropped
  (`src/belay/interop/attach.py:101-116`). The exporter therefore keys on `span_id` over
  the **original parsed spans list** (the attach boundary is untouched), or threads the
  fields through — decided in the plan; keying on the original list is the leaner seam.
- **OTLP value constraint:** attribute values are scalars / scalar arrays only; nested
  sub-verdicts cannot be embedded natively — the sub-verdict list is serialized as a
  JSON-string attribute (or flattened per-index; decided in the plan — the round-trip
  test is the arbiter).
- **Replay determinism:** the export itself is deterministic and offline; the only
  non-deterministic stage is the pre-existing replay inside `correlate_and_attach`,
  unchanged. "No network" (`CAPABILITY_ROADMAP.md:840`) is honored: the collector is a
  fixture (a file), never a live OTLP exporter (`prd.md:194-195`).
- **Integration point:** `src/belay/interop/` (new `export.py`), CLI
  `_parser()`/`interop` group (`cli.py:2886-2936`), tests following
  `tests/test_interop_*.py` patterns (fixtures `tests/fixtures/interop/spans_ok.json`,
  `trace_of()` helper, `verify=` stub seam).

## Trace/Verdict Contracts

Export attribute contract (proposed; the round-trip test pins it):

- `belay.verdict.status` — string, one of PASS/WARN/FAIL/UNVERIFIED (the reduced status).
- `belay.verdict.axis` — string, worst axis (e.g. A1/A2/A3); present only where the
  verdict has one (absent-never-zero).
- `belay.verdict.cause` — string, named cause; **absent when None**, never `""`.
- `belay.verdict.turn_index` — int, present for matched spans only.
- `belay.verdict.coverage` — string (JSON array) naming NOT_COVERED dimensions (e.g.
  `["effect:network"]`); **absent when none** (absent-never-zero — a PASS rendered
  without it is the failure mode this contract exists to prevent).
- `belay.verdict.sub_verdicts` — string, JSON encoding of the sub-verdict list
  (axis/kind/status/message per sub-verdict); the "axis and status intact" round-trip
  floor.
- Span event `belay.verdict` — carries the verdict message / diff (observed vs
  expected where present).

Every ingested span is marked: matched → the real verdict; unmatched/ambiguous →
UNVERIFIED + named cause. No span is exported bare.

## Risks & Open Questions

- **R5 (Med/Fatal-trust) — the live risk.** Interop is where over-claiming is easiest
  (`CAPABILITY_ROADMAP.md:833-834`). Mitigation: the "non-replayable span exports
  UNVERIFIED, never PASS" test is written first; the coverage-line round-trip is
  asserted; absent-never-zero is asserted per key. The PRD's docs step retires deferral
  lines only where the slice achieves them.
- **R9 (Med/High) — incumbents add replay.** Export-back is the mitigative move: it
  makes Belay complementary by construction. Not changed by this slice beyond slice 1.
- **R7 (Med/High) — UNVERIFIED as the default verdict.** The export carries UNVERIFIED
  with named causes; it does not change the UNVERIFIED rate. No UNVERIFIED-rate claim is
  made or implied by this slice.
- **Open (decided in the plan, not the PRD):** sub-verdict serialization (JSON-string vs
  flatten); keying on the original spans list vs threading fields through
  `CorrelatedSpan`; whether the export summary prints to stderr or the human report
  goes to stdout with `--out` set.
- **Open for the owner (not this unit):** whether the launch PH assets' "export-back is
  deferred" line moves — it is tied to the Langfuse screenshot prohibition
  (`docs/planning/launch-demo/ph-assets.md:112`) and only the owner re-writes launch
  claims.

## Out of Scope

- **Live OTLP exporter / collector connection** — "no network" is load-bearing
  (`prd.md:194-195`; `spec.md:52`). The fixture collector is a file.
- **Anything Langfuse-specific** — no vendor integration, nothing to imply one
  (`ROADMAP.md:263`).
- **Multi-trace-directory aggregation** — separate named deferral
  (`CAPABILITY_ROADMAP.md:860-861`).
- **The `NOT_COVERED` reclassification** — already shipped (`interop-merge-repair`,
  `STATUS.md:660-673`); only the stale deferral line is corrected.
- **Console-side OTel export** — a different surface (`live-console/prd.md:186`).
- **No verdict-axis or corpus change** of any kind.

## Non-Functional Requirements

- Deterministic, no network, runs in CI (fixture collectors only).
- Zero runtime dependencies (stdlib `json`); import guard stays green.
- Zero LLM in the path (existing guard covers `src/belay/interop/`).
- No raw-data egress: the export carries **verdicts and coverage**, never trace bytes or
  state; it runs only when the operator runs it.