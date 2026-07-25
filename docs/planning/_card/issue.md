# Card — feat/observability-interop

**Type:** feat · **Slug:** `observability-interop` · **Owner:** aliz
**Branch:** `feat/observability-interop/aliz` (off `origin/master`)
**Source:** no GitHub issue — inline brief (from the `belay-next` handoff, 2026-07-24)

---

## Brief

Build **C9 — Observability interop** (`docs/technical/CAPABILITY_ROADMAP.md:462-489`): ingest
OpenTelemetry / OpenLLMetry-style spans so Belay can attach verdicts to traces a team already
collects, and export verdicts back as span attributes/events so a Belay `FAIL` is visible inside
the dashboard the team already watches (Langfuse / Phoenix / any OTel collector).

This turns the strategic claim *"we complement observability, we don't compete"* into a shipped
fact rather than positioning (`CLAUDE.md` constraint #4). Deps **C1–C4 are merged**; this is
deterministic, offline-testable engine work on the moat-**protecting** side — no LLM, no agent
framework.

### Why this, now (from `belay-next`)

- The roadmap explicitly flags C9 to **move earlier than week 8**: the MCP **2026-07-28**
  revision reserves `traceparent`/`tracestate`/`baggage` in `_meta` citing the **OTel semantic
  conventions for MCP**, and deprecates Logging with OTel as its migration path — trace context
  is becoming *protocol-native* (`CAPABILITY_ROADMAP.md:62-68`).
- Unblocked (deps C1–C4 merged, `CAPABILITY_ROADMAP.md:489`), low-regret, and TDD's cleanly on
  macOS (fixture-based, no network) — unlike the Linux sandbox slice.
- Retires **R9** (incumbents add replay → make them distribution, not competitors) and
  **measures R6** (its eval data is the correlation rate between third-party spans and MCP turns,
  which decides whether the Phase-2 second surface is needed — `CAPABILITY_ROADMAP.md:485-487`).

### Acceptance (test-first — `CAPABILITY_ROADMAP.md:479-483`)

1. A fixture OTel span set ingests and **correlates to the matching MCP turns**.
2. A **non-replayable ingested span yields `UNVERIFIED`, never `PASS`** — asserted explicitly.
   Interop is exactly where over-claiming is easiest and most damaging (**R5**).
3. **Exported verdicts round-trip** into a fixture collector with the axis and status intact.
4. Deterministic, no network.

### Eval data captured

The **correlation rate** between third-party (OTel) spans and MCP turns — a direct measurement
of **R6** (how much of a real agent's activity actually crosses the MCP boundary).

### Caveats to carry into the dig

1. **Past the uncleared Phase-0 gate.** C9 is Phase-1 and marked *"cut second"*
   (`CAPABILITY_ROADMAP.md:528`). If the Stage-3 mint PIVOTs, this is wasted like any Phase-1
   work. It is the *lowest-regret* parallel build — durable infra the protocol is moving toward —
   but it is **not** the critical path. The number still is (separate track).
2. **Verdict-status design question.** The C9 spec says a non-replayable ingested span →
   `UNVERIFIED` (`CAPABILITY_ROADMAP.md:481`). But `NOT_COVERED` (built on the *unmerged*
   `feat/verdict-coverage-status` branch) arguably fits better — an ingested non-MCP span is
   *"never inside what Belay checks,"* not *"tried and could not."* This branch forks from
   `master`, where `NOT_COVERED` does **not** exist, so **follow the `UNVERIFIED` spec for now**
   and flag the interaction; resolve it if/when coverage-status merges.

### Guardrails (must hold)

- No agent framework; no bare LLM judge. C9 ingests/exports and correlates — it does not score.
- No raw-data egress: interop runs on the user's infra; exported verdicts carry axis/status,
  not raw state.
- **`UNVERIFIED` is never rendered as `PASS`** — the honesty contract is most fragile exactly on
  the interop surface (R5).

### Related in-flight work (avoid collision — confirmed non-overlapping)

- `feat/replay-relocation-shell/aliz` — another session; touches `src/belay/replay/`. No overlap.
- `feat/verdict-coverage-status/aliz` — built, unmerged; touches `src/belay/verify/` (adds
  `NOT_COVERED`). Interaction noted in caveat #2; no direct file collision expected.
- `feat/phase0-mint-execution/aliz` — the mint; touches `eval/`. No overlap.
