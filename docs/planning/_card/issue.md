# Card: feat/replay-absolute-path-fidelity

**Type:** feat · **Slug:** replay-absolute-path-fidelity · **Owner:** aliz
**Branch:** feat/replay-absolute-path-fidelity/aliz (off `master`)

No GitHub issue (`gh` tracker empty). Task source: the inline brief below, produced by the
Phase-0 Stage-1 live mint (2026-07-22, PR #7). The finding is documented in that branch at
`docs/planning/phase0-live-mint/mint-execution/STAGE1_FINDINGS.md` (finding #3).

## Brief

**Belay's replay is unfaithful for MCP servers that use absolute paths / a launch-time root
directory — a large, common class that includes the reference filesystem server. This
blocks the Phase-0 number (R1, the only Fatal-impact risk).**

Confirmed by the first live mint. Driving `pallets__flask-4045` through the harness with a
capable model (Gemini), the model made a **correct** edit, yet `belay phase0 run` reported
`VERIFIED_FLAGGED 1/1 = 100%` — a **false positive**. Proven by experiment: reverting the
workspace to `base_commit` and re-running over the *same* trace + manifests **changed the
per-turn verdicts** (turn 0 `read_text_file`: FAIL → UNVERIFIED). A replay verdict must
depend **only** on the restored snapshot; that it moved with live workspace state is the
contamination.

### Root cause (verified against the engine's own design assumption)

Belay's replay isolates by restoring the snapshot into a fresh **scratch** dir and setting
the server's **cwd** to it (`src/belay/replay/client.py`; the design is stated in
`tests/fixtures/weakening_editor_server.py`'s docstring). This is faithful **only for
cwd-relative servers** — every test fixture is hand-written to use paths relative to cwd.

The reference **node filesystem MCP server** is the inverse: it takes an **absolute
`allowed_dir` at launch** and the recorded `tools/call` frames carry **absolute paths**,
which ignore cwd. So the scratch restore + `cwd=scratch` does nothing for it — the server
reads/writes the **original absolute path** regardless. `contained(server_command,
workspace=scratch)` (`src/belay/sandbox/launch.py:181-223`) confines *writes* to scratch via
Seatbelt but **does not rewrite the server argv or the recorded tool-call paths**, so reads
of the original workspace succeed and pull live (post-mint) state into the verdict.

**No `belay phase0 run --server` invocation can fix this**: the `allowed_dir` would need to
be the *dynamic per-replay scratch* path (a static CLI arg cannot express it), and the
recorded absolute tool-call paths would still resolve to the original workspace.

### Why this matters / why now

- It is the **direct blocker** for the Phase-0 violation-rate number, which is the whole
  Phase-0 → Phase-1 gate and retires R1 (the only Fatal risk).
- It touches the **deterministic replay spine — the moat** (`CLAUDE.md` constraint #2). A
  fix makes the core verdict trustworthy for real-world servers, not just fixtures.
- The manual smoke never caught it because it only asserts *some* turn is verifiable — a
  false-positive FLAG satisfies that. A real gap hid behind a green test.

## First task: adversarially verify before fixing

The finding is strongly evidenced but the fix design is open. The dig must FIRST re-confirm
the mechanism against the code (not just the Stage-1 experiment), then frame the design
choice. Candidate resolutions (the PRD picks one):

1. **Restore into the recorded workspace path** so `allowed_dir` and the recorded absolute
   paths align (replay reverts the real workspace to the per-turn pre-state), OR
2. **Rewrite** the server argv's root token AND remap recorded absolute tool-call paths from
   the original prefix to the scratch prefix, OR
3. Something else the dig surfaces (e.g. a bind-mount / path-alias approach).

Each has trade-offs (isolation vs. fidelity, generality across servers, determinism,
whether it mutates the user's real workspace).

## Acceptance (test-first, per repo convention)

1. **Regression test grounded in the Stage-1 repro**: a capture whose recorded tool calls
   use **absolute paths** into a workspace, replayed after the *original* workspace has been
   mutated (or removed), must yield a verdict that depends **only** on the restored
   snapshot — the verdict does **not** change when the live workspace changes. The
   falsifiable core of the fix.
2. A capture of a **correct, benign edit** via an absolute-path server must **not** be
   FLAGGED (no false positive); a genuinely corrupt one must still FAIL (no false negative).
3. Existing replay/verify tests (all cwd-relative fixtures) stay green — no regression to the
   case that already works.
4. Determinism preserved: replay stays a pure function of (trace, snapshot) — no clock, no
   network, no dependence on ambient filesystem state.

## Guardrails

- **Core-engine change** (`src/belay/replay` + `sandbox`), the deterministic spine and the
  moat. Highest care.
- Fixes the **A2 (replay)** axis; the verdict stays execution-grounded, never an LLM's
  opinion. `UNVERIFIED` is never rendered `PASS`; the fix must not manufacture a PASS where
  the pre-state genuinely cannot be reconstructed.
- Not an agent framework; no model in the loop.
- **Repro asset:** the Stage-1 driver (`scratchpad/drive_one.py`) and the captured trace
  under `/tmp/belay-mint-gemini/` exist in the session that filed this; the fix should bake a
  **committed fixture** (an absolute-path server + a synthetic trace) rather than depend on
  that ephemeral capture.
