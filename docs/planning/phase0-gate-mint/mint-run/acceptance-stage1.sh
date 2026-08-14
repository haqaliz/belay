#!/usr/bin/env bash
# DRAFT (agent, 2026-08-14) — NOT FROZEN. Freeze = replace this marker with the dated
# s5-style line ("Frozen YYYY-MM-DD BEFORE it was run: this file contains no result")
# — a prose-only edit — and commit VERBATIM before the stage runs; the invocation and
# env below are then immutable, and no result may ever be added to this file.
#
# STAGE 1 — probe (2 controls: CTL-1 + CTL-4) · root eval/mint/s6a · registry
# eval/instances/s6stage1.json. Runbook: plan_20260814.md (authoritative); pre-registered
# readings: prd.md (CTL-4 outcomes, D-3, stop-loss).
#
# Freeze protocol (run once; stdout committed verbatim to acceptance-stage1.out):
#   * batch over the 2-record probe registry with the full gate composition:
#     --toolset filesystem+shell (the boundary offers the pinned shell server, so
#     run_process turns can be captured), --provider claude-cli, --model claude-opus-5,
#     --max-steps 20. No --verify flag: the dual-server verify is the separate step
#     below, composed by hand.
#   * Verify is the dual-server composition: --shell-server MUST precede --server —
#     --server is nargs=REMAINDER and would swallow every later argument, silently
#     replaying everything against the filesystem server. mkdir -p runs runs first:
#     an absent runs/ discards a completed verification. Server entrypoints are
#     ABSOLUTE ($PWD/...): replay spawns the server with cwd set to the scratch
#     restore, so a relative path reads "replay did not answer target".
#   * CTL-4 outcome readings (pre-registered): PASS -> the verify chain is proven live
#     end to end; stage 2 launches. UNVERIFIED (named cause: EVIDENCE_UNOBSERVABLE,
#     CLAIM_UNCLASSIFIABLE, or an offered-toolset abstain) -> adjudicate wiring-vs-
#     steering BEFORE stage 2; a declared re-probe is permitted ONLY for a wiring
#     defect; a steering finding is recorded and stage 2 still launches. FAIL -> D-3:
#     stop, adjudicate, void recorded as a void.
#   * CTL-1 (read-only) must abstain, not FAIL: a trajectory FAIL on a control is the
#     D-3 void the probe exists to catch at minimum cost.
#   * INSTRUMENT SUSPECT -> wiring failure, never a result; STOP and fix.
#   * Ledger: runs/s6a.json -> docs/planning/phase0-gate-mint/mint-run/ledgers/s6a.json.
#     Findings: docs/planning/phase0-gate-mint/mint-run/STAGE1_FINDINGS.md.
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
  --root eval/mint/s6a --registry eval/instances/s6stage1.json \
  --toolset filesystem+shell --provider claude-cli --model claude-opus-5 --max-steps 20

# 2. Verify (dual-server composition; --shell-server BEFORE --server, load-bearing).
run mkdir -p runs
run uv run belay phase0 run eval/mint/s6a/batch --ledger runs/s6a.json \
  --corpus-dir corpus/local \
  --shell-server "node $PWD/eval/servers/node_modules/mcp-server-commands/build/index.js" \
  --server node "$PWD/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js" '{workspace}'

# 3. Bank the ledger under the run directory.
run mkdir -p docs/planning/phase0-gate-mint/mint-run/ledgers
run cp runs/s6a.json docs/planning/phase0-gate-mint/mint-run/ledgers/s6a.json
