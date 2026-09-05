# Understanding — observability-export-back

**Worktree:** `feat/observability-export-back/aliz` · **Source:** `docs/planning/_card/issue.md` (inline brief, belay-next pick 2026-09-05).

## What the work is really asking

C9's second aspect: **export Belay verdicts back into an OpenTelemetry collector as span
attributes/events** — completing the locked Phase-1 interop deliverable whose export-back
half is a named deferral (`docs/technical/CAPABILITY_ROADMAP.md:859-861`, `:900`;
`docs/ROADMAP.md:272`, `:263`; `docs/planning/observability-interop/prd.md:184-186`,
`:192`). The point is the positioning claim made real: *"a Belay FAIL is visible inside
the dashboard the team already watches"* (`CAPABILITY_ROADMAP.md:829`) — near-zero
adoption cost, incumbents as distribution (R9 mitigation, `ROADMAP.md:372`).

The slice is deliberately narrow: **OTLP/JSON in → verdicts attached → OTLP/JSON out into
a fixture collector (a file / in-memory sink)**. No live exporter, no OTel SDK, no
network, no Langfuse-specific integration, no multi-trace-directory aggregation
(separate deferral item, `CAPABILITY_ROADMAP.md:860-861`). The `NOT_COVERED`
reclassification item in that same deferral list is **stale** — it shipped via
`interop-merge-repair` (`STATUS.md:660-673`), so the roadmap's deferral line should be
read as superseded on that item, and the brief requires NOT_COVERED in the export's
coverage line.

## The code surface (agent-mapped, file:line cited)

- `src/belay/interop/otlp.py` — `parse_otlp(json_text) -> list[Span]` (`:148`); `Span`
  frozen dataclass: `trace_id, span_id, name, start_time_unix_nano, attributes` (`:44-60`).
  Stdlib-only; malformed input raises `OtlpParseError`, never `[]`.
- `src/belay/interop/correlate.py` — `build_turn_index(records) -> TurnIndex` (`:111`),
  `match_span(span, index) -> Matched(n)|Unmatched|Ambiguous` (`:166`). Deterministic
  string-equality on `(traceId, spanId)` vs the captured W3C `traceparent`; ambiguity is
  first-class.
- `src/belay/interop/attach.py` — `correlate_and_attach(records, spans, ...) ->
  list[CorrelatedSpan]` (`:135-146`); `CorrelatedSpan` (`:101-116`) carries `span_id,
  turn_index, verdict` (the byte-identical `TurnVerdict`), `cause`. The `_REPLAYED_CAUSES`
  closed vocabulary (`:84-94`) keeps "not replayed" vs "unrestorable" honest.
  **Key gap: `trace_id`, `name`, `start_time_unix_nano`, `attributes` are dropped at the
  attach boundary** — an exporter that enriches the original span needs them (either
  thread them through, or export from the original spans list keyed by `span_id`).
- `src/belay/interop/report.py` — `correlation_summary/render/to_json` (`:50/:121/:154`);
  the `--json` payload per span: `{span_id, turn_index, status, cause, sub_verdicts:
  [{axis, kind, status, message}|null]}`. Only serializer today; omits
  observed/expected and trace_id/name/timestamps.
- CLI: `belay interop` group, required action subparser (`cli.py:2886-2888`);
  `correlate` only subcommand (`:2890-2936`), handler `_cmd_interop_correlate`
  (`:2211-2284`). Exit code 0 iff worst status PASS (`_worst`, `:1263-1282`).
- Verdict model (`src/belay/verify/verdict.py`, `turn.py`): `Status` enum with
  sub-verdict-only `NOT_COVERED` (`verdict.py:55`); `Verdict{axis,kind,status,observed,
  expected,message}` (`:76-96`); `TurnVerdict{turn_index,tool_name,status,sub_verdicts,
  cause,replayed_is_error}` (`turn.py:92-116`). No `to_dict` — serialization is
  hand-written per call site.
- Tests to follow: `tests/test_interop_{otlp,correlate,attach,cli}.py` (40 tests), the
  OTLP fixture `tests/fixtures/interop/spans_ok.json`, `trace_of(tmp_path, frames)`
  helper, `verify=` stub seam (`_never_call` spy), seatbelt-gated real-replay tests.
  `test_ac7_json_output_round_trips_with_correlation_and_spans` pins the `--json`
  shape export will build on.

## Acceptance mapping (from the handoff brief + the pre-registered C9 spec)

1. **Round-trip:** exported verdicts round-trip into a fixture collector with the axis
   and status intact (`CAPABILITY_ROADMAP.md:839` — pre-registered).
2. **Honest coverage line in the export:** which spans were verified and which are
   UNVERIFIED/NOT_COVERED with named causes (`CAPABILITY_ROADMAP.md:831-834`); a
   non-replayable ingested span exports UNVERIFIED, never PASS (R5 —
   `ROADMAP.md:368`; interop is where over-claiming is easiest). The export therefore
   marks **every** ingested span: matched → its real verdict; unmatched →
   UNVERIFIED + `no-matching-mcp-turn`; ambiguous → UNVERIFIED + `ambiguous-correlation`.
3. **Deterministic, no network, fixture collector only** (`CAPABILITY_ROADMAP.md:840`;
   `prd.md:194-195` — a live OTLP exporter is explicitly out of scope).
4. **No verdict-axis change** — C9 re-emits the unmodified `verify_turn` result
   (`prd.md:143-145`; the export must not re-compute or re-reduce anything).
5. **Zero-dep / zero-LLM** — stdlib `json` only (`prd.md:139-141,196,202,213`; the
   import guard enforces).

## Strategic-constraint check (CLAUDE.md)

- Harness-adjacent surface (interop), not a framework, not a bare LLM judge. ✓
- Protects the moat rather than being it: makes "complement, don't compete" shipped
  rather than rhetorical; converts incumbents into distribution (R9). ✓
- Honesty contract binds the export: UNVERIFIED-never-PASS and the coverage line must
  travel with the status (CLAUDE.md verdict contract). ✓
- No raw-data egress: the export carries **verdicts + coverage**, never traces/state;
  and it is opt-in by construction (an operator runs the export command). ✓
- Test-first: acceptance as RED tests before code. ✓

## Verdict-axis placement

None. This unit changes no verdict, axis, status, reduction, or corpus behavior — it
**re-emits existing verdicts** in OTLP attribute/event form. `verify_turn`,
`verdict.reduce`, every published number, and the correlate CLI surface are pinned
unchanged by existing tests; the new tests must prove the export carries the verdict
verbatim (axis + status intact) and adds nothing.

## Open questions for the PRD

1. **Export shape** — verdict as span **attributes** on the correlated span (enrichment,
   the "FAIL visible in the dashboard" reading), span **events** (diff/message), or a new
   child span? Docs say "attributes/events" (`CAPABILITY_ROADMAP.md:829`) — the PRD must
   pick. Lean: attributes for machine fields + one event for the message/diff.
2. **Attribute keys** — a `belay.*` namespace (the MCP spec's reverse-DNS exception is
   for `io.modelcontextprotocol/*`; Belay's own namespace is ours). E.g.
   `belay.verdict.status`, `belay.verdict.axis`, `belay.verdict.cause`,
   `belay.verdict.coverage`, per-sub-verdict fields. OTLP attribute values are scalars /
   scalar arrays — sub-verdicts likely need flattening or a JSON-string attribute
   ("axis and status intact" is the floor: reduced status + worst axis).
3. **CLI surface** — new subcommand `belay interop export <otlp> <trace> [--server …
   ] [--out FILE]` mirroring correlate's flags (self-contained pipeline), vs a `--export`
   flag on correlate, vs consuming a prior `correlate --json` output. Lean: new
   subcommand, `--out` (default stdout or `<stem>.verified.json`).
4. **Reuse vs thread-through** — export from the original spans list keyed by `span_id`
   (attach boundary untouched) vs threading trace_id/name/attributes through
   `CorrelatedSpan`. Lean: keyed on original spans — pure function, deterministic.
5. **Docs surface** — which lines update: `CAPABILITY_ROADMAP.md:859-861/:900` (deferral
   → shipped slice; keep multi-trace aggregation + drop the stale NOT_COVERED item),
   `ROADMAP.md:272/:263` (the "export-back deferred" halves), `STATUS.md` (append entry
   per convention), `CHANGELOG.md`, the observability-interop PRD's deferral lines, and
   the launch-demo/ph-assets "export-back is deferred" lines. **The "no Langfuse
   integration" honesty lines mostly survive** — an OTLP-file export is not a Langfuse
   integration; the PRD must say exactly what the slice does and does not retire.
6. **Eval data** — none new: the slice inherits slice 1's correlation rate (R6
   measurement). Noted honestly: this is a surface/positioning slice (like C7), not a
   detection slice; it adds no corpus cases.
7. **Exit semantics** — export mirrors `_worst` (rc 0 iff all exported verdicts PASS)?
   Or always 0 (a pure export)? Ask.

## Hazards

- **Over-claim drift (R5):** the export is the newest surface where a PASS rendered
  without its coverage line is the named failure mode (CLAUDE.md). Every exported span
  must carry its coverage; the test for "a non-replayable span exports UNVERIFIED,
  never PASS" is the load-bearing honesty test, written first.
- **Attach-boundary gap:** `CorrelatedSpan` drops trace_id/name/attributes — a naive
  exporter that reads only correlation results cannot re-join to the original spans.
  Keying on `span_id` over the original parsed document sidesteps it.
- **OTLP value types:** attribute values must be scalar / scalar-array; a verdict's
  nested sub-verdicts and observed/expected cannot be embedded natively — flatten or
  JSON-string, and the round-trip test must prove axis+status survive.
- **Stale deferral list:** `CAPABILITY_ROADMAP.md:860-861` still names the NOT_COVERED
  reclassification as deferred; it shipped (`STATUS.md:660-673`). The PRD should correct
  that line when updating the deferral wording — a correction, not a reclassification.