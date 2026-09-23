#!/usr/bin/env bash
# STAGE 2 — CTL-2 + CTL-3 + 8 fresh real (10 records), controls FIRST. DECLARED SECOND
# RUN 2026-09-22 (owner S-1). Frozen BEFORE it was run: THIS FILE CONTAINS NO RESULT. The
# run happens once; stdout is committed verbatim to acceptance-cm-run2-stage2.out,
# whatever it says (Rule D, phase0-mint-run/prd.md:97-101).
#
# RUN THIS ONLY AFTER THE STAGE 1 GATE HAS BEEN EVALUATED AND CLEARED BY HAND.
#
# Controls are driven FIRST because a FAILing control VOIDS the run (D-3) — that is what
# killed the 2026-08-09 re-mint — so a void is discovered before the real instances are
# spent. A void is published as such, never hidden.
#
# The 8 real instances are drawn from the conservative fresh set (30, never in any
# committed registry) under seed 20260919; see ../mint-registry/. This is NOT a gate run:
# n < 50 by construction, and NO violation rate is published from it.
#
# Run-2 amendment: the registries are reused verbatim (no regeneration, no seed change);
# the four controls are re-driven as a declared owner decision — controls are the run's
# own calibration instruments, not population draws, and run-1's stage-1 gate never
# cleared.
#
# --root and --clones-dir are ABSOLUTE and OUTSIDE the worktree on purpose: manifests
# record an absolute source_root, and a worktree-relative root dies with the worktree.
# That defect was repaired at the start of this unit (three missing symlinks, 1344 dead
# recorded paths); writing outside the worktree removes the cause rather than adding a
# fourth stub symlink later.
set -euo pipefail

HOLDER="$HOME/dev/at/holder/belay"
export BELAY_EVAL_SERVER_ROOT="$HOLDER/servers"
# A3: the claim column can be filled for the first time. run_verify's missing
# claim_author= was fixed in this unit, and the reference author is proven live at n=1
# (../a3-author/live-run.md).
export BELAY_CLAIM_AUTHOR="$(python3 -c 'import sys;print(sys.executable)') -m belay.verify.reference_claim_author --model claude-opus-5"

FS_SERVER="$HOLDER/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
SHELL_SERVER="$HOLDER/servers/node_modules/mcp-server-commands/build/index.js"
ROOT="$HOLDER/mint/cm4"

echo "=== STAGE 2 — mint ==="
uv run python -m eval.minting_driver batch \
  --root "$ROOT" \
  --registry eval/instances/cm-stage2.json \
  --clones-dir "$HOLDER/clones" \
  --provider claude-cli --model claude-opus-5 \
  --max-steps 20 --request-timeout 120 \
  --toolset filesystem+shell

echo
echo "=== STAGE 2 — verify (stock belay phase0 run) ==="
# --shell-server MUST precede --server: --server is nargs=REMAINDER and swallows
# everything after it (eval/README.md:790-793).
uv run belay phase0 run "$ROOT/batch" \
  --ledger "$HOLDER/runs/cm-run2-stage2.json" \
  --corpus-dir "$HOLDER/corpus-local" \
  --shell-server "node $SHELL_SERVER" \
  --server node "$FS_SERVER" '{workspace}'