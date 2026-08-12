# Spec — aspect `mint-dual-server`

**PRD:** `docs/planning/trajectory-toolset-rescope/prd.md` (Requirements 4–6, 8, 11) · **Date:** 2026-08-12

## Problem slice

The trajectory axis cannot measure the mint population until `run_process` is reachable, but
the driver is single-server by construction (`eval/minting_driver/batch.py:42-45`): one
`build_server_command`, one `StdioMcp`, one flat tool list in the prompt
(`claude_cli_client.py:492-514`). This aspect offers the pinned shell server
(`mcp-server-commands@0.8.2`, `servers.py:69-73,165-171`) alongside the filesystem server on
one boundary, with the shell's cwd at the per-instance workspace, behind the gated proxy per
server — eval-only, no `src/belay/` change.

## In scope

1. **Composite transport** (new `eval/minting_driver/composite.py`): fronts two proxied
   `StdioMcp` sessions; merged tool list (verbatim names — **no prefixing**; `run_process`
   must stay `run_process` or the trajectory evidence gate `_EVIDENCE_TOOL` breaks);
   tool-name → session routing for `tools/call`; **one call in flight across the whole
   composite** (R7); error containment (a dead session fails its own call, never the other);
   `close()` closes both.
2. **Per-instance shell cwd:** `StdioMcp.__init__(command, env, cwd=None)` passes `cwd` to
   `Popen` (`transport.py:217-224`); the proxy process inherits it and spawns the server
   with it (`proxy.py:475-480` spawns without cwd → inherits). Shell session spawned with
   `cwd=layout.work_dir`; filesystem session unaffected (absolute `allowed_dir`).
3. **Toolset selection:** `--toolset {filesystem,filesystem+shell}` on the batch CLI
   (`entrypoint.py`/`cli.py`), default `filesystem` (behavior-neutral — the s5 freeze
   invocations stay valid verbatim). `filesystem+shell` builds both servers per instance.
   Registries (`stage4.json` etc.) untouched — server choice is the invocation, per the
   existing boundary (`controls.py:59-62`).
4. **Driver wiring:** `run_mint`/`run_task` accept a server composition; single-server path
   byte-compatible with today. tools/list discovery (`batch.py:159-186`) uses the composite's
   merged list. The prompt receives the merged list.
5. **CI-safe tests** (deterministic, no network, no node servers): composite unit tests
   against the fake servers/fixtures already in `eval/minting_driver/fakes.py` and
   `tests/fixtures/shell_command_server.py`; `Popen` cwd assertion; toolset-parsing pure
   tests; the live dual-server smoke stays `manual`-marked, never in CI.
6. **Runbook:** `eval/README.md` — dual-server install (both pinned servers — already the
   documented install command), invocation example with `--toolset filesystem+shell`,
   shell-cwd note, unchanged macOS TCC gotchas.

## Out of scope

- The mint itself; the trajectory rule (`engine-abstain` aspect); controls
  (`controls-rescope` aspect); any `src/belay/` change; multi-server beyond the two pinned
  servers; `--toolset shell` alone (nice-to-have, only if free).

## Acceptance criteria (tests written first)

1. Composite transport (fake servers): merged tool list; a `tools/call` for an fs tool
   reaches the fs session only; `run_process` reaches the shell session only; replies
   round-trip verbatim; interleaving safety (a second call while one is in flight raises);
   `close()` closes both sessions.
2. `StdioMcp(cwd=...)` passes the value to `Popen` (patched spawn); absent cwd → no `cwd`
   argument (byte-compatible with today's spawns).
3. `--toolset` parsing: `filesystem` → exactly today's single-server path;
   `filesystem+shell` → both servers, shell spec carries `cwd=layout.work_dir`; invalid
   toolset → clear CLI error.
4. Tool names preserved verbatim across the composite (no prefix) — asserted by test.
5. One-call-in-flight holds across the composite (control-flow test, CI).
6. Live smoke: `manual`-marked — a real `run_mint` on one instance with `--toolset
   filesystem+shell` produces a trace whose tools/list contains `run_process` and whose
   `run_process` turn replays under `belay phase0 run` (relocation rules handle `cwd` and
   `command_line`). Never in CI.
7. Full suite green; existing minting-driver tests unmodified and green.

## Dependencies & sequencing

Independent of `engine-abstain` (parallel). `controls-rescope` depends on this aspect (the
suite-running control's evidence is a real `run_process` turn). The shell server must be
installed per `eval/README.md` for the manual smoke only — CI never spawns it
(`servers.py` raises `MissingServerError`; the driver's CI tests use fakes).

## Risks

- Composite routing bug would cross-wire tools (an edit call hitting the shell) — the
  routing map is built from each session's own `tools/list`; the verbatim-name test and
  per-session isolation tests are the guards; a mis-wire here reads as `INSTRUMENT SUSPECT`
  in a mint (the load-bearing failure mode, same class as `bridge_capture`).
- The shell server's cwd: set at spawn; the sandbox scope is the workspace, so writes stay
  contained; replay already restores `cwd=scratch` — no replay change.
- `mcp-server-commands` behavior on real repos (suite runs may fail/hang) — a measured
  finding, not a defect; the manual smoke is the first evidence.
