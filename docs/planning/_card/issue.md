# Card: feat/phase0-minting-driver

**Type:** feat · **Slug:** phase0-minting-driver · **Owner:** aliz
**Branch:** feat/phase0-minting-driver/aliz

No GitHub issue — task source is the inline brief below plus the already-written aspect spec.

## Source of truth (already in repo)

- `docs/planning/phase0-corpus-run/minting-driver/spec.md` — the aspect spec (should-have of the
  phase0-corpus-run PRD; the runner shipped in v0.2.0, this is the deferred should-have).
- `docs/planning/phase0-corpus-run/prd.md` — parent PRD (requirement #8 is this driver).
- `docs/planning/phase0-corpus-run/RUNBOOK.md` — the reproduce-the-number procedure; Step 1
  (Capture) is what this driver automates.

## Brief

Build the Phase-0 **minting-driver**: a thin, sequential, BYOK MCP agent loop that drives an
agent's file/shell actions through off-the-shelf MCP filesystem + shell servers placed **behind
`python -m belay.proxy`**, one `tools/call` at a time. It exists to produce the *real traces* the
already-built `belay phase0 run/report` consumes at the live gate — the last missing piece before
the Phase-0 number can be published (the only Fatal risk, R1).

Non-negotiables from the spec:
- Lives under a new `eval/` dir — **NOT** `src/belay/`, **NOT** the `belay` CLI. No import from
  `src/belay` except the proxy entrypoint used as a subprocess.
- **One tool call in flight at any moment** (satisfies R7 by construction) — all edits/shell go
  **through MCP servers** (satisfies R6 by construction).
- BYOK: model key from env; never a vendor default, nothing proxied, no raw-state egress.
- **Not an agent framework.** One tool call → wait → repeat. If it grows planning/memory/
  multi-step autonomy, stop — that's framework drift (guardrail #1).

Acceptance (from spec):
1. Deterministic (CI-safe) unit test: the loop provably issues tool calls sequentially — fake
   model + fake MCP transport, asserting never >1 in flight.
2. Manual-gate-only smoke (never in CI, live model): on one curated macOS-runnable instance the
   driver produces a trace where ≥1 file-edit `tools/call` crosses the proxy with a restorable
   pre-state — i.e. the runner can verify ≥1 turn.

Open questions to settle in the plan: which concrete off-the-shelf MCP filesystem + shell servers;
the BYOK model client seam.
