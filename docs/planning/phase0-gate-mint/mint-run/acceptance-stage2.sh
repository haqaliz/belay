#!/usr/bin/env bash
# DRAFT (agent, 2026-08-14) — NOT FROZEN. Freeze = replace this marker with the dated
# s5-style line ("Frozen YYYY-MM-DD BEFORE it was run: this file contains no result")
# — a prose-only edit — and commit VERBATIM before the stage runs; the invocation and
# env below are then immutable, and no result may ever be added to this file.
#
# STAGE 2 — 9 records (CTL-2 + CTL-3 first, then 7 fresh real) · root eval/mint/s6b ·
# registry eval/instances/s6stage2.json. Runbook: plan_20260814.md (authoritative);
# pre-registered readings: prd.md (D-1, D-3, stop-loss).
#
# Freeze protocol (run once; stdout committed verbatim to acceptance-stage2.out):
#   * batch over the 9-record registry with the full gate composition:
#     --toolset filesystem+shell, --provider claude-cli, --model claude-opus-5,
#     --max-steps 20. Controls first: the registry is ordered CTL-2, CTL-3, then the
#     7 fresh; the driver mints in registry order, so controls run before any real
#     spend. No --verify flag; the dual-server verify is the separate step below.
#   * Verify is the dual-server composition: --shell-server MUST precede --server —
#     --server is nargs=REMAINDER and would swallow every later argument, silently
#     replaying everything against the filesystem server. mkdir -p runs runs first.
#     Server entrypoints are ABSOLUTE ($PWD/...): replay spawns the server with cwd
#     set to the scratch restore, so a relative path reads "replay did not answer
#     target".
#   * D-1 reading (pre-registered): the report's trajectory exposure line counts
#     claims_judged = FAIL|PASS; abstains add to claims_abstained. Stage 2 must judge
#     >=1 trajectory instance; a stage reading 0 judged STOPS before stage 3 — a
#     finding, not a rate. A shell-less stage reads 0 judged by construction; this
#     stage offers the shell.
#   * Stop-loss: capture >=5/10 AND >=1 genuinely verifiable turn AND all controls
#     VERIFIED_CLEAN AND D-1 met. (The pre-registered >=5/10 was written for the
#     10-record s5 stage 2; the s6 stage-2 registry holds 9 records — the operator
#     confirms the denominator reading at freeze.)
#   * D-3: a control FAIL — including a trajectory FAIL on a control — STOPS the run,
#     voids the mint, and is adjudicated with the evidence committed first (the re-mint
#     precedent).
#   * INSTRUMENT SUSPECT -> wiring failure, never a result; STOP and fix.
#   * Ledger: runs/s6b.json -> docs/planning/phase0-gate-mint/mint-run/ledgers/s6b.json.
#     Findings: docs/planning/phase0-gate-mint/mint-run/STAGE2_FINDINGS.md.
#
# Dry-run safe: the driver has NO --dry-run flag, so this script ECHOES every command
# by default and executes it only when RUN=1 is set in the environment. At draft time
# it must never be executed against the live boundary.
set -euo pipefail

export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"

run() {
  if [ "${RUN:-0}" = "1" ]; then
    "$@"
  else
    printf 'DRY-RUN (set RUN=1 to execute):'
    printf ' %q' "$@"
    printf '\n'
  fi
}

# 1. Mint (run once).
run uv run python -m eval.minting_driver batch \
  --root eval/mint/s6b --registry eval/instances/s6stage2.json \
  --toolset filesystem+shell --provider claude-cli --model claude-opus-5 --max-steps 20

# 2. Verify (dual-server composition; --shell-server BEFORE --server, load-bearing).
run mkdir -p runs
run uv run belay phase0 run eval/mint/s6b/batch --ledger runs/s6b.json \
  --corpus-dir corpus/local \
  --shell-server "node $PWD/eval/servers/node_modules/mcp-server-commands/build/index.js" \
  --server node "$PWD/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js" '{workspace}'

# 3. Bank the ledger under the run directory.
run mkdir -p docs/planning/phase0-gate-mint/mint-run/ledgers
run cp runs/s6b.json docs/planning/phase0-gate-mint/mint-run/ledgers/s6b.json
