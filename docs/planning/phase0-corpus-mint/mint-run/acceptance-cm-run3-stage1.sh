#!/usr/bin/env bash
# STAGE 1 — probe (CTL-1 + CTL-4, 2 records). DECLARED SECOND RUN 2026-09-22 (owner S-1).
# Frozen BEFORE it was run: THIS FILE CONTAINS NO RESULT. The run happens once; stdout is
# committed verbatim to acceptance-cm-run3-stage1.out, whatever it says (Rule D,
# phase0-mint-run/prd.md:97-101).
#
# The probe exists to catch an instrument or wiring defect before any real instance is
# spent. Its gate is evaluated BY HAND against the committed output, before stage 2 is
# launched: a capture must be produced, at least one turn must be genuinely verifiable,
# and both controls must come back clean. A FAILing control VOIDS the run (D-3).
#
# Run-2 amendment: the registries are reused verbatim (no regeneration, no seed change);
# the four controls are re-driven as a declared owner decision — controls are the run's
# own calibration instruments, not population draws, and run-1's stage-1 gate never
# cleared. PRE-REGISTERED STOP BRANCH: a second INSTRUMENT SUSPECT means STOP — no
# stage-2 spend; record the finding as probe-scale inviability.
#
# CTL-4 (control__flask-verify-with-command) is the POSITIVE control and only produces
# evidence under --toolset filesystem+shell.
#
# --root and --clones-dir are ABSOLUTE and OUTSIDE the worktree on purpose: manifests
# record an absolute source_root, and a worktree-relative root dies with the worktree.
# That defect was repaired at the start of this unit (three missing symlinks, 1344 dead
# recorded paths); writing outside the worktree removes the cause.
# Run-3 amendment (2026-09-23, owner S-1: "continue"): the THIRD probe, after the
# composite-transport correlation fix (annotation_for_turn reads the latest tools/list
# together with its broadcast twins). Same registries, same composition, fresh roots
# cm5/cm6. PRE-REGISTERED: a third INSTRUMENT SUSPECT means STOP — no stage-2 spend.
set -euo pipefail

HOLDER="$HOME/dev/at/holder/belay"
export BELAY_EVAL_SERVER_ROOT="$HOLDER/servers"
export BELAY_CLAIM_AUTHOR="$(python3 -c 'import sys;print(sys.executable)') -m belay.verify.reference_claim_author --model claude-opus-5"

FS_SERVER="$HOLDER/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
SHELL_SERVER="$HOLDER/servers/node_modules/mcp-server-commands/build/index.js"
ROOT="$HOLDER/mint/cm5"

echo "=== STAGE 1 (probe) — mint ==="
uv run python -m eval.minting_driver batch \
  --root "$ROOT" \
  --registry eval/instances/cm-stage1.json \
  --clones-dir "$HOLDER/clones" \
  --provider claude-cli --model claude-opus-5 \
  --max-steps 20 --request-timeout 120 \
  --toolset filesystem+shell

echo
echo "=== STAGE 1 (probe) — verify (stock belay phase0 run) ==="
# --shell-server MUST precede --server: --server is nargs=REMAINDER and swallows
# everything after it (eval/README.md:790-793).
uv run belay phase0 run "$ROOT/batch" \
  --ledger "$HOLDER/runs/cm-run3-stage1.json" \
  --corpus-dir "$HOLDER/corpus-local" \
  --shell-server "node $SHELL_SERVER" \
  --server node "$FS_SERVER" '{workspace}'