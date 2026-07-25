# PRD — `observability-interop` (C9, first slice)

**Unit:** feat/observability-interop · **Owner:** aliz · **Date:** 2026-07-24
**Branch:** `feat/observability-interop/aliz` (off `origin/master`, v0.4.0)
**Inputs:** `docs/planning/_card/issue.md` (brief), `docs/planning/observability-interop/understanding.md` (dig)
**Capability:** **C9 — Observability interop** (`docs/technical/CAPABILITY_ROADMAP.md:462-489`)

---

## Problem Statement

Belay's positioning rests on constraint #4 — *"complement observability, don't compete"*
(`CLAUDE.md`) — and on retiring risk **R9** (*"observability incumbents add replay"*,
`ROADMAP.md:245`). Today that is **rhetoric, not code**: nothing in `src/belay/` reads or writes
an OpenTelemetry span. A team already running Langfuse / Phoenix / an OTel collector cannot see a
Belay verdict inside the dashboard they already watch, and Belay cannot say — with a number — how
much of their agent's activity it actually verified.

There is a second, quieter cost: **R6** (*"the interesting failures don't cross the MCP boundary"*,
`ROADMAP.md:242`) is the highest-impact unmeasured assumption under the locked wedge, and nothing
in the engine measures it. The fraction of a real agent's spans that correspond to an MCP turn Belay
saw **is** R6, and C9 is the first capability positioned to compute it.

**Who has this problem:** the engineer evaluating Belay who already runs observability and asks
"does this sit *beside* what I have, or replace it?"; and the founder, who needs R6 measured before
committing to a Phase-2 second surface.

**Evidence it's real:** the map confirms zero interop code exists
(`understanding.md` §"Any existing interop"); the only structured verdict output today is the
phase0 ledger, and there is no general machine-readable verdict surface at all
(`understanding.md` §"surfaces C9 hooks").

---

## Goals & Success Metrics

The deliverable is a **shipped, tested ingest+correlate+attach slice** plus the R6 metric it
produces. Export-verdicts-back-to-OTLP is explicitly a **second aspect** (out of scope here).

| Metric | Target | Source |
|---|---|---|
| Fixture OTLP/JSON span set ingests and correlates to matching MCP turns | **passes as a test** | `CAPABILITY_ROADMAP.md:480` |
| A non-correlatable / non-replayable span → `UNVERIFIED`, never `PASS` | **asserted by a dedicated test** | `CAPABILITY_ROADMAP.md:481`, R5 |
| Correlation rate (spans matched to MCP turns ÷ total ingested spans) | **computed + reported with its denominator** | `CAPABILITY_ROADMAP.md:485-487` (R6 eval data) |
| Zero runtime dependencies preserved | **`tests/test_import_guard.py` stays green** | `understanding.md` §2 |
| Deterministic, no network | **CI-runnable, fixtures only** | `CAPABILITY_ROADMAP.md:483` |

**Explicit non-goal:** a *high* correlation rate. A low, *explained* rate (few clients propagate
W3C trace context today) is a valid, honest result — it measures R6, it does not advertise C9.

---

## User Personas & Scenarios

Belay's ICP is the engineer running agents unattended who must answer *"did this run actually do
the right thing?"*. This slice serves the sub-case where that engineer **already collects OTel
spans**: they point `belay interop` at their exported spans + the trace Belay captured, and get,
per span, the grounded verdict for the MCP turn it corresponds to — and a correlation rate telling
them what fraction of their agent's recorded activity Belay was able to verify at all.

---

## Requirements

### Must-have

1. **A stdlib-only OTLP/JSON ingest.** Parse OpenTelemetry spans from their **OTLP JSON encoding**
   (`ResourceSpans` → `ScopeSpans` → `Span`, with `traceId`/`spanId`/`name`/`startTimeUnixNano`/
   `attributes`) using stdlib `json` only. **No `import opentelemetry`** anywhere in `src/belay/` —
   `tests/test_import_guard.py:84-111` must stay green. OpenLLMetry is OTLP-with-conventions, so
   OTLP/JSON covers it.
2. **Deterministic correlation by W3C trace context.** Match an ingested span to an MCP turn using
   the `traceparent` Belay already captures per frame as a `trace_context` record
   (`connection.py:199-211`, `TRACE_FORMAT.md:468-488`). The join key is the W3C
   `trace-id`/`parent-id` (span-id), **not** a time window (the trace records only proxy-observed
   `t_in`, no duration — `understanding.md` §1). A turn's identity remains its positional ordinal
   `n` over `tool_calls(derive_correlation(records))`.
3. **Attach the existing verdict.** For a correlated span whose MCP turn is verifiable, run the
   existing verify path (`verify_turn`, unchanged) and attach the resulting `TurnVerdict`
   (`axis`/`kind`/`status`/`message` per sub-verdict + reduced status). C9 **re-emits** verdicts;
   it computes none of its own and changes **no axis**.
   - **Correlation must be unambiguous or it is `UNVERIFIED` — never a guessed attach.** A span that
     joins to **more than one** MCP turn (duplicate/re-used span-ids, a `traceparent` that appears on
     a **non-`tools/call`** frame, or any many-to-one collision) is reported `UNVERIFIED` with cause
     `ambiguous-correlation`, **not** attached to a best-guess turn. Attaching a verdict to the wrong
     span is a false report — the R5 failure mode — so ambiguity fails safe. Pinned by a test.
4. **`UNVERIFIED`, never `PASS`, for the uncovered cases** — asserted by test:
   - a span with **no matching MCP turn** (activity that did not cross MCP) → `UNVERIFIED`;
   - a span matching a turn whose pre-state is **unrestorable** → `UNVERIFIED`.
   Both fall out of the existing `reduce` (empty→`UNVERIFIED`, `verdict.py:80-82`) — the test pins
   the contract so a future refactor can't manufacture a false `PASS`.
5. **The correlation-rate report.** Emit `matched / total` ingested spans **with the denominator**,
   plus the uncorrelated count, via the `_emit` sink (`cli.py:73`) in the honest style — the
   uncorrelated bucket is its own line, never folded into a PASS/match count.
6. **A `belay interop correlate` subcommand.** New argparse group mirroring `phase0`/`corpus`
   (`cli.py:1107-1517` pattern): `belay interop correlate <otel-spans.json> <trace-dir-or-file>
   [--manifest-dir …]`, heavy imports lazy inside the handler. New package `src/belay/interop/`.
7. **Machine-readable output.** Because the phase0 ledger is the *only* structured verdict surface
   today and there is no `--json` flag, this slice ships a `--json` output for its correlation
   result (span-id → matched turn → verdict status + correlation-rate summary), stdlib-serialized.
8. **Honesty-guard coverage of the new package.** Add `src/belay/interop/` to `GUARDED_ROOTS` in
   `tests/test_verify_zero_llm.py:38` so the AST inference-import ban covers it too — C9 must never
   grow an LLM path.
9. **Docs sync (required by `CLAUDE.md`).** Update the C9 row in `CAPABILITY_ROADMAP.md` (first
   slice built), the `CLAUDE.md` status block, and the README **honest-coverage** statement: Belay
   correlates spans that carry W3C trace context; spans without it are reported **uncorrelated**,
   never silently PASSed (R5).

### Should-have

10. **A named cause on every uncovered span**, mirroring the UNVERIFIED-cause discipline
    (`cli.py:601-621`): `no-matching-mcp-turn` vs `unrestorable-pre-state` are distinct, so the
    report explains the correlation rate rather than just stating it.
11. **A malformed-OTLP guard** — a non-conforming spans file yields a recorded, honest error, never
    a silent empty correlation (mirrors C1's malformed-server discipline, `CAPABILITY_ROADMAP.md:140`).

### Nice-to-have

12. A `--min-correlation` advisory line that flags a suspiciously low rate for the write-up (never a
    gate; C9 is a measurement).

---

## Technical Considerations

**Where it sits in the pipeline:** downstream of capture (C1) and verify (C4/C5), *beside* the
phase0 runner. It reads a trace + manifests exactly as `phase0/runner.py:_verify_one_trace`
(`runner.py:140-228`) does, and reuses `read_trace` → `derive_correlation` → `tool_calls` →
`verify_turn`. **No change to capture, sandbox, replay, or any verdict axis.**

**Correlation mechanism (the load-bearing design fact):** C1 already captures
`traceparent`/`tracestate`/`baggage` verbatim (`connection.py:59,199-211`). The correlate step
derives the `trace_context` records from the trace, indexes MCP turns by their captured
`traceparent` span-id, and joins ingested OTLP spans on `traceId`+`spanId`. This is **deterministic
and reproducible** from fixed inputs — the property the gate cares about.

**Dependencies:** C1, C2, C3, C4 — **all merged** (`CAPABILITY_ROADMAP.md:489`). No blocker.

**Zero-dep constraint:** OTLP/JSON parsed and emitted with stdlib `json`. The OTel SDK is
**rejected** (would trip `tests/test_import_guard.py:84-111` and forfeit the zero-dep selling
point). Confirmed 2026-07-24.

**Verdict impact: none.** C9 re-emits `TurnVerdict`s produced by the unchanged verify path. The
only new verdict *surface* is span-level attachment; the only new *status path* is the explicit
`UNVERIFIED` for uncovered spans, which is the existing reduction, not a new rule.

**Eval data captured:** the correlation rate — a direct measurement of **R6**
(`CAPABILITY_ROADMAP.md:485-487`).

**Corpus-compounding guardrail — reconciled.** The standing rule is *"every subsequent capability
must add cases; a capability that catches nothing new does not ship"* (`CAPABILITY_ROADMAP.md:371`).
C9 **re-emits** existing verdicts against a new *surface*; it detects no new failure class, so it
adds **no new corpus cases** — and that is correct, not a violation. C9's analogue of "compounding
the moat" is its **eval data**: the correlation rate (R6), which the C9 spec names as its eval
output in place of corpus cases (`CAPABILITY_ROADMAP.md:485-487`). Stated here so a reviewer does
not read the absence of new cases as a missed guardrail.

**Rough effort (feasibility signal).** Small–medium, ~2–4 focused sessions: a stdlib OTLP/JSON
parser + a `trace_context`→turn index + the join + a `belay interop correlate` handler + the
report, all fixture-tested. No new dependency, no sandbox/replay/verify change, reuses `verify_turn`
wholesale — the risk is in the correlation edge cases (must-have #3 addendum), not in volume of
code.

---

## Risks & Open Questions

| Risk | Assessment |
|---|---|
| **Built before the Phase-0 gate clears** (Phase-1, "cut second", `CAPABILITY_ROADMAP.md:528`) | Eyes-open, founder-chosen parallel track. Mitigated by keeping the slice small and moat-protecting; durable regardless of the gate because it measures R6 and preserves zero-dep. **Not the critical path — the number is.** |
| **R5 — over-claiming on the interop surface** (Med/**Fatal-trust**) | The easiest place to render a false PASS. Mitigated by the dedicated "uncovered span → UNVERIFIED, never PASS" test (must-have #4) and the honest-coverage doc (#9). |
| **R6 — activity doesn't cross MCP** (High/High) | This slice *measures* it rather than mitigating it. A low correlation rate is a reported finding, not a failure. |
| **Correlation needs the client to propagate W3C trace context** | Real coverage limit. Clients that don't propagate `_meta` trace context yield uncorrelated spans → low, explained rate. Stated in the honest-coverage docs, never hidden. |
| **OTLP/JSON shape drift** | OTLP is a stable, versioned wire format; pin the fixtures to a named OTLP JSON version and parse defensively (must-have #11). |
| **Ambiguous correlation → wrong-span attach** (R5-adjacent) | A span joining to >1 turn, a re-used span-id, or a `traceparent` on a non-`tools/call` frame could attach a verdict to the wrong span — a false report. Mitigated by the fail-safe rule: ambiguity → `UNVERIFIED` cause `ambiguous-correlation`, never a guessed attach (must-have #3 addendum), pinned by test. |
| **Push, not demand-pull** | The roadmap ranks demand-pull above push (`ROADMAP.md` principle), and **no design partner asked for C9**. This slice is justified by R6-measurement + low-regret parallel work while the mint runs — *not* by user demand. Assumption stated, not hidden: if it ships and no one uses the interop, the R6 number it produced is still the win. |

**Open questions**
1. **NOT_COVERED interaction (deferred).** A span with no MCP turn is arguably `NOT_COVERED`
   ("never inside what Belay checks"), not `UNVERIFIED`. `NOT_COVERED` lives only on the unmerged
   `feat/verdict-coverage-status` branch, so this slice uses `UNVERIFIED` per master spec
   (`CAPABILITY_ROADMAP.md:481`) and files the reclassification as a follow-up for when that branch
   merges. Confirmed 2026-07-24.
2. **Export aspect (deferred).** Exporting verdicts back as OTLP span attributes/events into a
   fixture collector (`CAPABILITY_ROADMAP.md:472-473,482`) is a **separate second aspect**, planned
   after this slice lands.

---

## Out of Scope

- **Exporting verdicts back to OTLP** (span attributes/events / fixture collector round-trip) — the
  deferred second aspect.
- **A live OTLP exporter or collector connection** — "no network" (`CAPABILITY_ROADMAP.md:483`);
  ingest and any future export are file/in-memory only.
- **The OpenTelemetry SDK** as a dependency — rejected for zero-dep.
- **Time-window correlation** — trace context is the deterministic key; there is no `t_out`/duration
  to window on anyway (`understanding.md` §1).
- **Any change to `src/belay/{proxy,sandbox,snapshot,replay,verify}`** beyond adding
  `interop/` to the zero-LLM guard's `GUARDED_ROOTS`. No verdict axis changes.
- **`NOT_COVERED`** — depends on the unmerged coverage-status branch (open question #1).
- **A new runtime dependency** of any kind.

---

## Honesty Properties (non-negotiable)

1. A span Belay could not correlate or could not replay is **`UNVERIFIED`, never `PASS`**.
2. The correlation rate is **always** reported with its denominator.
3. An uncorrelated span is its own reported bucket with a **named cause**, never folded into a match.
4. The coverage limit (correlation needs propagated W3C trace context) is **stated** in the
   honest-coverage docs, not hidden.
5. No LLM anywhere in the interop path — enforced by extending the AST inference-import ban.
6. Zero runtime dependencies preserved — enforced by the existing import guard.
