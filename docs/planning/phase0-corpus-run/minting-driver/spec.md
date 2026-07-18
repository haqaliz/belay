# Aspect spec — minting-driver (should-have, live-gated)

**Parent PRD:** `../prd.md`. This aspect is **eval/mint infrastructure, NOT a product surface**
(CLAUDE.md guardrail #1). It is not part of the CI-green Definition of Done for this unit; it is
the tool that produces the real traces the runner consumes at the live gate.

## Problem slice & user outcome

To mint a real corpus, something must drive an agent through the Belay proxy such that its
file/shell actions actually cross the MCP boundary and are capturable one turn at a time. This
aspect provides a minimal, honest driver for that — and nothing more.

## In scope

- A thin, sequential, BYOK agent loop: LLM proposes ONE `tools/call` at a time against MCP
  filesystem + shell servers placed behind `python -m belay.proxy`, waits for the result, then
  proposes the next. One tool call in flight at any moment (satisfies R7 by construction).
- All file edits + shell run **through the MCP servers** (satisfies R6 by construction).
- A single-instance smoke runner that stands up: instance workspace on the macOS filesystem, the
  proxy with `BELAY_TRACE_DIR`/`BELAY_SANDBOX_SCOPE`/`BELAY_SNAPSHOT_DIR`, the MCP servers, and
  the agent — producing one trace + `.manifests`.
- Lives under `eval/` (NOT `src/belay/`, NOT the `belay` CLI). BYOK: reads the model key from env;
  never a vendor default, nothing proxied, no raw-state egress.

## Out of scope

- Any autonomy/orchestration beyond "one tool call, wait, repeat" — this is not an agent framework.
- Shipping in the product. No `belay` subcommand. No import from `src/belay` except the proxy
  entrypoint used as a subprocess.
- The ≥50-instance batch orchestration (that's the founder running the driver + the runner; a
  loop over instances is a shell script / notes, not product code).
- SWE-bench-lite instances that require Docker/Linux-only harnesses.

## Acceptance criteria

- **Manual gate only — never in CI** (uses a live model; non-deterministic). Mark any test that
  invokes the real model with a manual/opt-in marker and an env guard, mirroring the roadmap's
  C8 model-seam discipline.
- Smoke: on one curated macOS-runnable instance, the driver produces a trace in which ≥1
  `tools/call` (a file edit) crosses the proxy and is captured with a restorable pre-state — i.e.
  the runner can verify at least one turn. This is the R6 "verify with ONE instance before scaling"
  check made concrete.
- The loop provably issues tool calls sequentially (a unit test on the loop's control flow with a
  fake model + fake MCP transport, asserting never >1 in flight — this part IS deterministic and
  CAN run in CI).

## Dependencies & sequencing

- Depends on the proxy (C1) and sandbox/snapshot (C2), both merged. Sequenced AFTER phase0-runner
  (we consume traces before producing them).
- Instance curation (macOS-runnable, no Docker) is a prerequisite input, tracked as notes.

## Open questions / risks

- Which MCP filesystem + shell servers (off-the-shelf) — pick concrete ones during the plan.
- Model/BYOK choice is the founder's; the loop must be model-agnostic behind an env-keyed client.
- Guardrail: keep this minimal. If it grows planning/memory/multi-step autonomy, stop — that's
  framework drift.
