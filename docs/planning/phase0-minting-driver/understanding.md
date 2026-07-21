# Understanding — phase0-minting-driver

**Phase 2 deep-dig note.** Grounds the plan in the real proxy/trace contract and names the one
contradiction the spec's acceptance criteria hide. Source: aspect spec
(`docs/planning/phase0-corpus-run/minting-driver/spec.md`), parent PRD, RUNBOOK, and a code map of
`src/belay/proxy.py`, `trace.py`, `phase0/runner.py`, `replay/client.py`, `cli.py`.

## What the work really is

A minimal, eval-only **MCP client with an LLM in the loop**: it spawns `python -m belay.proxy
<mcp-server-cmd>` as a subprocess, and runs one turn at a time — LLM proposes exactly one
`tools/call`, the driver sends it through the proxy, waits for the result, feeds it back to the
LLM, repeats — until the task is done or a step budget is hit. Because every file edit and shell
command is an MCP `tools/call` through the proxy, they cross the boundary and get captured (R6 by
construction); because only one is ever in flight, no turn batches into an unrestorable snapshot
(R7 by construction). It exists to produce the *real traces* the already-shipped `belay phase0
run/report` consumes — the last missing piece before the Phase-0 number (R1, the only Fatal risk).

It is **not** an agent framework: no planning, no memory, no multi-step autonomy, no tool
authoring. One call → wait → repeat. If it grows past that, stop (guardrail #1). It lives under a
new `eval/` dir, never `src/belay/`, never the `belay` CLI.

## The integration contract (verified against source)

- **Invocation:** `python -m belay.proxy <server-cmd> [args...]`. No argparse, **no `--`
  separator** — the *entire* argv after `-m belay.proxy` is the downstream server command, spawned
  verbatim via `subprocess.Popen` (`proxy.py:475-480`, usage at `proxy.py:531-533`; confirmed by
  `tests/test_real_client.py:44-46`).
- **Wire:** byte-transparent, **newline-delimited JSON-RPC** (NOT LSP `Content-Length` framing;
  `proxy.py:1-27,137-146`). The driver writes each JSON-RPC message as one `\n`-terminated line to
  the proxy's **stdin**, reads `\n`-delimited replies from its **stdout**, correlates by JSON-RPC
  `id`. The proxy owns stdout for protocol only; server stderr is forwarded, never traced.
- **Reusable machinery:** `src/belay/replay/client.py` — `converse()` + `_Replies` (send frame +
  `\n`, flush, await by id) is transport/direction-agnostic and works unchanged pointed at the
  proxy subprocess (`replay/client.py:247-290,175-244`). It is a *replay* client (sends
  pre-recorded frames, no `initialize` handshake), so the driver adds the request construction and
  the LLM loop, but reuses the send/await/correlate core. **Do not import the `mcp` SDK from any
  code the product ships** — it's dev-only and banned from `src/belay` by the import guard; `eval/`
  is outside `src/belay` so it *could* use the SDK, but reusing the stdlib `converse` keeps it
  zero-dep and mirrors the engine.
- **Trace output:** the proxy auto-writes `<BELAY_TRACE_DIR>/trace-<UTCstamp>-<8hex>.jsonl`
  (`trace.py:145-149`). The driver constructs nothing — it just talks MCP. `belay phase0 run
  <dir> --server <cmd...> --ledger out.json` globs `trace-*.jsonl` (`phase0/runner.py:108`,
  `cli.py:999-1065`).

## ⚠️ The contradiction the acceptance criteria hide (decide this first)

The smoke criterion says the driver must produce a trace where a file edit "crosses the proxy
**and is captured with a restorable pre-state** — i.e. the runner can verify at least one turn."
But the spec's *In scope* only lists `BELAY_TRACE_DIR` prose in places that read as capture-only.
These are not the same setup:

- **Capture-only** (only `BELAY_TRACE_DIR` set): the proxy records frames but takes **no
  snapshots**. Every turn's `state_handle` is `{"status":"absent"}` (`trace.py:132,253-257`), so
  `verify_turn` returns **UNVERIFIED** and the instance resolves to **`no-verifiable-turns`** in
  the phase0 ledger. That fails the smoke criterion ("the runner can verify ≥1 turn") and, worse,
  a whole mint of these reads as **INSTRUMENT SUSPECT**, not a clean run.
- **Gated/sandbox path** (all three set: `BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR` +
  `BELAY_TRACE_DIR`): the proxy takes a per-turn snapshot so the pre-state is restorable and the
  turn is verifiable. This path is **darwin + Seatbelt only** (matches the engine's macOS-only
  constraint, README:156) and **hard-refuses to start if scope is set without snapshot dir**
  (`proxy.py:544-554`).

**Resolution (to confirm in the interview):** the driver targets the **gated path** — it sets all
three env vars — because "the runner can verify ≥1 turn" is the acceptance bar. Capture-only is
insufficient by the spec's own words.

### Secondary: the `.manifests` naming misalignment

`belay phase0 run`'s default manifest lookup expects `<trace-stem>.manifests` *next to each trace*
(`phase0/runner.py:74-83`), but the proxy names the trace stem at runtime (timestamp+uuid) and
writes manifests to `<BELAY_SNAPSHOT_DIR>.manifests` (`cli.py:371-373`). These don't auto-align
across a multi-instance mint. Options for the plan:
1. Driver writes one trace per instance into a per-instance dir and passes an explicit
   `manifest_dir` — but `belay phase0 run` (the CLI) uses the default lookup. `run_batch(...)`
   *does* accept an explicit `manifest_dir_for=` (used in `tests/test_phase0_e2e.py:161-168`).
2. Driver arranges snapshot output so the sibling `<trace-stem>.manifests` convention is satisfied
   (e.g. one BELAY_SNAPSHOT_DIR per instance, then rename/symlink to match the trace stem).

This is a **wiring** decision for the plan, not a code change to the engine. Flag: do not touch
engine verdict logic to paper over it.

## Verdict-axis placement

The driver **changes no verdict logic** and adds no axis. It *feeds* A1 (tests/ read-only, the
cheat catcher) and A2 (replay result-equivalence + effect-conformance) by producing traces. A3
does not exist yet. Server annotations matter for A2 effect-conformance: the filesystem server
*declares* annotations (`write_file`: `readOnlyHint:false, destructiveHint:true`), giving a real
conformance contract; the shell server declares none (inherits fail-safe defaults) — fine, since
A1 user-declared invariants are the load-bearing mechanism for shell.

## Concrete server picks (from research)

- **Filesystem:** `@modelcontextprotocol/server-filesystem` (official reference; npm 2026.7.10).
  Launch: `npx -y @modelcontextprotocol/server-filesystem <abs-allowed-dir>`. Write tools:
  `write_file`, `edit_file` (both declare annotations). This is the canonical, no-competitor pick.
- **Shell:** `mcp-server-commands` (g0t4; npm 0.8.2). Launch: `npx -y mcp-server-commands`. Single
  tool `run_process` (shell `command_line` mode runs the test suite). No official shell server
  exists — this is a flagged judgement call; declares no annotations.
- **macOS gotchas:** Node 20/22 LTS; pin exact `npx -y pkg@version` for reproducible evals and to
  avoid stale `~/.npm/_npx` cache; point the filesystem allowed-dir at a neutral working dir (not
  `~/Desktop`/`~/Documents`) to dodge macOS TCC prompts mid-run; `run_process` uses `/bin/sh`, not
  your zsh.

## The BYOK model seam

Model-agnostic behind an env-keyed client (spec + guardrail #4: BYOK, never a vendor default,
nothing proxied, no raw-state egress). The loop needs: given a system prompt + task + the running
message history (tool results appended), return either a single tool call (name + args) or a
"done" signal. The seam is one function/protocol — `propose_next(messages) -> ToolCall | Done` —
with a real implementation (the founder's chosen model via its SDK, key from env) and a **fake**
for the deterministic control-flow test. Keep the fake in-repo; the real client is BYOK.

## Test strategy (test-first)

- **CI-safe, deterministic (RED first):** unit test on the loop's control flow with a fake model +
  fake MCP transport, asserting **never >1 tool call in flight** and strict send→await→next
  ordering. This is the shippable proof and the only test that runs in CI. No network, no LLM.
- **Manual-gate-only (never in CI):** the single-instance live smoke — env-guarded marker
  (mirrors the C8 model-seam discipline), real model + real npx MCP servers on one curated
  macOS-runnable instance, asserting ≥1 file-edit `tools/call` captured with a restorable
  pre-state such that `belay phase0 run` verifies ≥1 turn.

## Open questions for the interview

1. **Gated path confirmed?** Driver sets all three env vars (darwin+Seatbelt) so turns are
   verifiable — agreed? (The alternative, capture-only, fails the smoke bar.)
2. **Manifest alignment:** option 1 (per-instance `manifest_dir`) vs option 2 (naming convention).
   Does the driver's smoke helper drive `run_batch` directly, or must it feed the *CLI* `belay
   phase0 run`?
3. **Model/SDK for the real client** — founder's pick (Anthropic? local?). The loop stays
   model-agnostic regardless.
4. **Instance curation:** which one curated macOS-runnable SWE-bench-lite instance for the smoke
   (should-have #9 — notes, not product code)?
