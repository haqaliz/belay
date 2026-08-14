#!/usr/bin/env bash
# DRAFT (agent, 2026-08-14) — NOT FROZEN. Freeze = replace this marker with the dated
# s5-style line ("Frozen YYYY-MM-DD BEFORE it was run: this file contains no result")
# — a prose-only edit — and commit VERBATIM before the stage runs; the invocation and
# env below are then immutable, and no result may ever be added to this file.
#
# STAGE 3 — 83 records (80 fresh real + 3 controls) · root eval/mint/s6c · registry
# eval/instances/s6stage3.json. Runbook: plan_20260814.md (authoritative);
# pre-registered readings: prd.md (>=50 clause, D-3, stop-loss).
#
# Freeze protocol (run once, resumable; stdout committed verbatim to
# acceptance-stage3.out):
#   * batch over the 83-record registry with the full gate composition:
#     --toolset filesystem+shell, --provider claude-cli, --model claude-opus-5,
#     --max-steps 20. No --verify flag; the dual-server verify is the separate step
#     below.
#   * Multi-day resume: a quota stop ends the batch; the operator waits out the cap
#     and resumes with the IDENTICAL command on the SAME root (no_observation re-arms;
#     captured never re-rolls; MintReport prints STOPPED EARLY). The final .out is
#     either one block or two declared runs with both blocks — never a re-roll.
#   * The >=50 clause is counted from the report's denominator (VERIFIED_CLEAN +
#     VERIFIED_FLAGGED instances, controls partitioned out). Every UNVERIFIED instance
#     must carry a named cause; INSTRUMENT SUSPECT -> wiring failure, never a result;
#     STOP and fix.
#   * Verify is the dual-server composition: --shell-server MUST precede --server —
#     --server is nargs=REMAINDER and would swallow every later argument, silently
#     replaying everything against the filesystem server. mkdir -p runs runs first.
#     Server entrypoints are ABSOLUTE ($PWD/...): replay spawns the server with cwd
#     set to the scratch restore, so a relative path reads "replay did not answer
#     target".
#   * D-3: a control FAIL — including a trajectory FAIL on a control — voids the mint:
#     stop, adjudicate with committed evidence, record the void.
#   * Ledger: runs/s6c.json -> docs/planning/phase0-gate-mint/mint-run/ledgers/s6c.json.
#     Findings: docs/planning/phase0-gate-mint/mint-run/STAGE3_FINDINGS.md.
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

# 1. Mint (run once; resumable on the same root).
run uv run python -m eval.minting_driver batch \
  --root eval/mint/s6c --registry eval/instances/s6stage3.json \
  --toolset filesystem+shell --provider claude-cli --model claude-opus-5 --max-steps 20

# 2. Verify (dual-server composition; --shell-server BEFORE --server, load-bearing).
run mkdir -p runs
run uv run belay phase0 run eval/mint/s6c/batch --ledger runs/s6c.json \
  --corpus-dir corpus/local \
  --shell-server "node $PWD/eval/servers/node_modules/mcp-server-commands/build/index.js" \
  --server node "$PWD/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js" '{workspace}'

# 3. Bank the ledger under the run directory.
run mkdir -p docs/planning/phase0-gate-mint/mint-run/ledgers
run cp runs/s6c.json docs/planning/phase0-gate-mint/mint-run/ledgers/s6c.json
