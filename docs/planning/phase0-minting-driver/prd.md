# PRD — Phase-0 Minting Driver

**Slug:** `phase0-minting-driver` · **Branch:** `feat/phase0-minting-driver/aliz` · **Owner:** aliz
**Parent:** `docs/planning/phase0-corpus-run/` (this is should-have #8 of that PRD, deferred when
the runner shipped in v0.2.0). **Capability:** eval/mint infrastructure for the Phase-0 gate — NOT
a C-id, NOT a product surface.

---

## Problem Statement

The Belay engine (C1–C6) and the Phase-0 corpus **runner** (`belay phase0 run/report`, v0.2.0) are
built and green. But `docs/technical/PHASE0_RESULTS.md` is still all `TO-BE-FILLED`: **no real
traces exist to feed the runner.** The runner is an instrument with no input. Producing that input
is the single thing standing between the whole built engine and the Phase-0 gate — which answers
the only *Fatal* risk in the register, **R1** (*does the engine catch anything real?*).

To mint real traces, something must drive an agent so its file/shell actions **cross the MCP
boundary** one turn at a time. That is this unit: a thin, sequential, BYOK MCP agent loop behind
`python -m belay.proxy`. It is explicitly eval infrastructure, kept out of the product CLI, and is
the one place in the plan that could drift toward an agent framework — so it is fenced hard
(guardrail #1).

## Goals & Success Metrics

**Primary goal (CI-green DoD):** a minimal driver under `eval/` that, given a task + MCP server
command, runs an LLM loop issuing **exactly one `tools/call` at a time** through the proxy, proven
by a **deterministic, offline, CI-safe** control-flow test (fake model + fake transport) asserting
never >1 call in flight and strict send→await→next ordering.

**Success = all of:**
- The loop issues tool calls strictly sequentially; the deterministic test asserts it. No network,
  no LLM, runs in CI.
- The BYOK model seam is a single injectable protocol (`propose_next`) with: a deterministic
  **fake** (CI), an **Anthropic** reference client, and a **local OpenAI-compatible** reference
  client. Neither real client is imported or exercised in CI.
- The driver lives under `eval/`, imports nothing from `src/belay` except invoking
  `python -m belay.proxy` as a subprocess. `tests/test_import_guard.py` stays green; no new runtime
  dependency lands in the `belay` package.
- A single-instance **smoke** (manual-gate-only, env-guarded, never CI) drives the real path:
  spawns the proxy with **all three** env vars (gated sandbox path), the real MCP filesystem +
  shell servers, and a real model, on one curated macOS-runnable instance — and asserts ≥1
  file-edit `tools/call` is captured with a **restorable pre-state** such that `run_batch` verifies
  ≥1 turn.
- Honesty preserved: the driver never fabricates trace records (the proxy writes them); it never
  labels or scores; it emits no verdict.

**Explicitly out of "done":** the live ≥50-instance mint and the published number (parent PRD
Scope B). This unit ships the *tool*; the founder runs it.

## Decisions (resolved in the interview)

1. **Gated sandbox path.** The driver sets `BELAY_TRACE_DIR` + `BELAY_SANDBOX_SCOPE` +
   `BELAY_SNAPSHOT_DIR` so turns are snapshotted and verifiable. Darwin+Seatbelt only. Capture-only
   was rejected: it yields UNVERIFIED turns and fails the "runner can verify ≥1 turn" bar.
2. **Drive `run_batch` directly** in the smoke helper, passing an explicit
   `manifest_dir_for=`, mirroring `tests/test_phase0_e2e.py:161-168`. This sidesteps the
   proxy-stem vs `<trace-stem>.manifests` naming mismatch with **zero engine change**.
3. **BYOK: seam + fake + two reference clients.** `propose_next(messages) -> ToolCall | Done`
   protocol. Ship the deterministic fake (CI) plus an Anthropic Messages/tool-use client and a
   local OpenAI-compatible client, both key-from-env, never a vendor default, nothing proxied, no
   raw-state egress. CI-green DoD needs neither real client.

## Requirements

### Must-have (CI-green)

1. **Sequential MCP client loop.** Spawns the proxy subprocess, speaks newline-delimited JSON-RPC
   over its stdin/stdout, correlates replies by `id`. Reuses `belay.replay.client`'s
   `converse`/`_Replies` send-await-correlate core (stdlib-only) rather than the dev-only `mcp`
   SDK. Runs `initialize` → `tools/list` → then the propose→call→observe loop. **One call in
   flight, always**; a step budget bounds the loop.
2. **Model seam (`propose_next`).** Injectable protocol returning either one `ToolCall` (name +
   args) or `Done`. Deterministic fake for tests; the loop is model-agnostic behind it.
3. **Two reference clients**, BYOK, key-from-env, isolated so importing the driver core does not
   import either SDK. Not exercised in CI.
4. **Env/proxy wiring helper.** Builds the proxy command + the gated env (all three vars), pointed
   at the chosen MCP server command. Enforces the proxy's own rule (scope set ⇒ snapshot dir set).
5. **`eval/` placement + isolation.** No `belay` subcommand; no `src/belay` import except the proxy
   entrypoint as a subprocess. Documented in-file as eval/mint infra, not a product, not a
   framework.
6. **Deterministic control-flow test (the shippable proof).** Fake model + fake MCP transport;
   asserts never >1 tool call in flight, strict ordering, `Done` terminates, step budget caps.

### Should-have

7. **Single-instance smoke** (manual gate, env-guarded, never CI): real model + real npx MCP
   servers + gated proxy on one curated instance → `run_batch` verifies ≥1 turn.
8. **Instance-curation notes** for macOS-runnable SWE-bench-lite instances (no Docker) — notes,
   not product code.
9. **A short `eval/README.md`** documenting the servers (`@modelcontextprotocol/server-filesystem`,
   `mcp-server-commands`), the gated env, the macOS gotchas (Node 20/22, pin `npx -y pkg@version`,
   neutral allowed-dir to dodge TCC), and how the smoke maps to the RUNBOOK's Step 1.

### Nice-to-have

10. A tiny `eval/` entry script so the founder can run one instance by ID at mint time.

## Technical Considerations

- **Where code lands:** net-new `eval/` (e.g. `eval/minting_driver/`) + `tests/` for the
  deterministic loop test. Nothing under `src/belay/`. The two reference clients live in separate
  modules so the SDK imports are lazy/isolated.
- **Reuse:** `belay.replay.client.converse` + `_Replies` (send/await/correlate). The real-SDK path
  in `tests/test_real_client.py` is a reference for spawning the proxy, but the driver does not
  depend on the `mcp` SDK.
- **Servers (pinned):** filesystem `npx -y @modelcontextprotocol/server-filesystem@<ver> <dir>`
  (write tools `write_file`/`edit_file`, declares annotations → feeds A2 conformance); shell
  `npx -y mcp-server-commands@<ver>` (`run_process`; no annotations — A1 invariants are the
  load-bearing check for shell). No official shell server exists; this is a flagged judgement call.
- **Determinism split:** the loop is deterministic given a fake model; the live mint is not (real
  LLM) — hence the manual gate, mirroring the roadmap's C8 model-seam discipline.
- **Verdict impact: none.** Adds/changes no verdict logic or axis. Feeds A1 + A2; A3 doesn't exist.

## Risks & Open Questions

- **Guardrail #1 (framework drift)** — the one real risk. Fence it: one call → wait → repeat, no
  planning/memory/multi-step autonomy, out of the product CLI, documented as non-product. If a task
  wants to grow it, stop and flag.
- **R6 (MCP boundary → false zero)** — mitigated by construction (all file/shell via MCP servers);
  the smoke is the "verify one instance before scaling" check.
- **R7 (batching → UNVERIFIED)** — mitigated by construction (one call in flight).
- **macOS-only** — the gated smoke requires darwin+Seatbelt; the deterministic test does not and
  runs everywhere.
- **Open:** which curated instance for the smoke (founder's pick / notes); exact pinned server
  versions (set in plan).

## Out of Scope

- The live ≥50-instance mint and the published number (parent PRD Scope B).
- Any new verdict logic or axis; A3.
- Linux/Docker substrate.
- Shipping the driver as a product surface / `belay` subcommand.

## Definition of Done (this unit)

Code merged on `feat/phase0-minting-driver/aliz` with: the sequential MCP minting-driver loop +
model seam + fake + two isolated BYOK reference clients under `eval/`, the deterministic CI-safe
control-flow test, the manual-gated single-instance smoke (never CI), instance-curation notes, an
`eval/README.md`, and `uv run pytest` green with the import guard intact. The live mint is a
documented, runnable next step — not a prerequisite for merge.
