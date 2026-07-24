# Understanding — observability-interop (C9)

**Phase-2 dig, 2026-07-24.** Grounded in two read-only code maps of `master`. Every claim is
file:line-cited. This note frames the real problem and the decisions the PRD must resolve; it
does **not** commit to a design.

---

## What the work is really asking

Make Belay **additive** to an observability stack a team already runs: take the OpenTelemetry /
OpenLLMetry spans they already collect, **correlate** each to the MCP turn Belay recorded, attach
Belay's execution-grounded **verdict** to it, and **export** the verdict back out so a Belay
`FAIL` is visible inside their existing dashboard. This converts constraint #4 ("complement
observability, don't compete") and risk **R9** ("incumbents add replay") from positioning into a
shipped fact, and its by-product measures **R6** (how much agent activity actually crosses MCP).

It touches **no verdict axis** — C9 ingests, correlates, and re-emits existing verdicts. It does
**not** score anything. Guardrails hold by construction (no framework, no LLM judge).

---

## The two findings that reshape the feature

### 1. ✅ Correlation is DETERMINISTIC, not a time-window heuristic (makes it easier + stronger)

C1 **already captures W3C trace context.** `connection.py:59` recognizes
`("traceparent","tracestate","baggage")`, `_meta_of()` (`connection.py:100-115`) reads them off
`params._meta`/top-level `_meta`, and `_trace_context()` (`connection.py:199-211`) emits a derived
`trace_context` record per frame that carries them verbatim (`TRACE_FORMAT.md:468-488`). The raw
`_meta` also survives base64-verbatim in `raw` (`trace.py:233`).

This matters because the trace records **only `t_in`** — a single proxy-observed wall-clock stamp
per frame, **no `t_out`, no duration, no server timing** (`trace.py:92-93,329`;
`TRACE_FORMAT.md:75-82`). Time-window correlation (what the roadmap implicitly assumed) would have
been lossy and would have folded in Belay's own proxy overhead. **Instead, correlation should key
on the W3C `traceparent`** an MCP client propagates into `_meta` → deterministic span-id ↔ MCP-turn
join. There is **no intrinsic turn id** otherwise — a turn is a per-run positional ordinal `n`
over `tool_calls(derive_correlation(records))` (`index.py:190-200`, `runner.py:162`), and every
other candidate key (JSON-RPC `id`, `seq`, hashes, `t_in`) is per-run.

**Consequence for the eval metric (R6):** the "correlation rate" is literally *"of the collected
OTel spans, how many carry a `traceparent` that matches a captured MCP turn."* A span that matches
= activity that crossed MCP; a span with no match = activity that did **not** cross MCP (built-in
`Bash`/`Edit`, a raw LLM call). So the correlation rate **is** R6, measured honestly — and it
degrades gracefully: a client that doesn't propagate trace context yields a low, *explained*
correlation rate, never a fabricated one.

### 2. ⚠️ Zero runtime dependencies is ENFORCED — the OTel SDK is banned by a test

`tests/test_import_guard.py:84-111` (`test_src_imports_stdlib_and_first_party_only`) walks all of
`src/belay/` with `ast` and **fails on any third-party import**. `src/belay` is pinned to zero
runtime deps (a stated selling point: README "zero runtime dependencies, stdlib only"). So
`import opentelemetry` in `src/belay/` **trips the guard**.

**Implication — the load-bearing PRD decision:** C9 interops at the **data-format** level, not the
SDK level. OTLP has a well-defined **JSON encoding**; Belay ingests OTLP/JSON and emits OTLP/JSON
span attributes/events, parsed/serialized with **stdlib `json` only** — no `opentelemetry` import.
This preserves zero-dep and is consistent with the whole byte-transparent, stdlib-only
architecture. The alternative (add `opentelemetry` to `[project].dependencies` and carve out the
guard) is possible but sacrifices the zero-dep property and should be rejected unless the PRD finds
a concrete blocker to the stdlib path.

---

## The surfaces C9 hooks (map result)

- **Verdict types** (`verify/verdict.py:34-72`, `verify/turn.py:73-90`): `Status` = exactly
  `{PASS,WARN,FAIL,UNVERIFIED}`; `Verdict{axis,kind,status,observed,expected,message}`;
  `TurnVerdict{turn_index,tool_name,status,sub_verdicts,cause}`. **No `to_dict`** — serialization
  is hand-done at each call site. `reduce` is worst-status-wins, **empty→UNVERIFIED**
  (`verdict.py:74-82`) → the "non-replayable span → UNVERIFIED, never PASS" acceptance falls out
  for free.
- **Only existing structured output is the phase0 ledger** (`phase0/ledger.py:128-144`); there is
  **no `--json` flag anywhere** (`cli.py`). C9's export is the first general machine-readable
  verdict surface.
- **CLI** is argparse subparsers built in `_parser()` (`cli.py:1107-1517`); a new `belay interop`
  group mirrors `phase0`/`corpus` exactly (`.add_subparsers`, `.set_defaults(func=…)`, lazy heavy
  imports inside handlers). Existing groups: `sandbox, replay, verify, corpus, phase0`.
- **Trace/manifest reading (the ingest hook)**: `phase0/runner.py:_verify_one_trace:140-228` —
  `read_trace` → `tool_calls(derive_correlation(records))` → per-turn loop (`runner.py:170-187`),
  manifests resolved as `<stem>.manifests` (`runner.py:74-83`). Injected `verifier=`/`ingester=`
  seams already exist (`runner.py:96-97`). This is exactly where span↔turn correlation hooks.
- **Honesty guards C9 must not trip / must extend**: `tests/test_verify_zero_llm.py` (AST ban on
  inference imports — note it guards `verify/` and `corpus/`; if C9 code lives in a new
  `interop/`, decide whether to add it to `GUARDED_ROOTS`), `tests/test_import_guard.py`
  (stdlib+first-party only), `tests/test_verdict.py` (UNVERIFIED outranks PASS). All plain-text
  rendering via `_emit`, no color — status is the literal word.

---

## Open questions for the PRD / interview

1. **Stdlib-only OTLP vs the OTel SDK** — recommend stdlib-only OTLP/JSON (preserves zero-dep).
   Confirm, or name the blocker that forces the SDK.
2. **Scope of the first slice** — ingest+correlate+attach-verdict is the core; export-verdicts-back
   is the second half. One aspect or two? (Acceptance lists both ingest-correlate and export.)
3. **Input format** — OTLP/JSON (`ResourceSpans`) as the canonical ingest shape? OpenLLMetry is
   OTLP-with-conventions, so OTLP/JSON covers both. Confirm the fixture shape.
4. **Export shape** — verdict as span **attributes** on the correlated span, span **events**, or a
   new child span? "No network" (acceptance #4) means export writes OTLP/JSON to a file / in-memory
   sink ("fixture collector"), not a live OTLP exporter.
5. **`UNVERIFIED` vs `NOT_COVERED`** for a non-correlatable / non-replayable span — follow the
   `UNVERIFIED` spec on master (`CAPABILITY_ROADMAP.md:481`); flag the `verdict-coverage-status`
   interaction (that branch is unmerged). Distinguish *span-has-no-MCP-turn* (out of scope →
   arguably NOT_COVERED later) from *span-maps-to-an-unrestorable-turn* (UNVERIFIED).
6. **New subcommand shape** — `belay interop <action>`; likely `export` (verdicts→OTLP) and maybe
   a correlate/report action. New package `src/belay/interop/`.
7. **Docs sync (required by `CLAUDE.md`)** — CLAUDE.md status, ROADMAP, CAPABILITY_ROADMAP (mark C9
   built), README honest-coverage statement (an ingested non-MCP span is reported UNVERIFIED, never
   PASS — R5 is easiest to violate here).

## Contradiction to flag (not paper over)

The roadmap's C9 acceptance (`CAPABILITY_ROADMAP.md:479-483`) implies correlation without saying
how; the dig shows the *right* mechanism (captured `traceparent`) is already in the trace, which is
**better** than the roadmap assumed — but it means **correlation only works for MCP clients that
propagate W3C trace context into `_meta`.** That is a real coverage limit and must be stated in the
honest-coverage docs, not hidden: Belay correlates the spans that carry trace context; the rest are
reported as uncorrelated, never silently PASSed.
