#!/usr/bin/env bash
# STAGE 2 — 4 controls + 7 fresh real (11). Frozen 2026-08-12 BEFORE it was run:
# this file contains no result. See docs/planning/mint-shell-toolset-run/mint-run/plan_20260812.md
# Phase 3. The run happens once; stdout is committed verbatim to acceptance-stage2.out.
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver batch \
  --root eval/mint/s6b --registry eval/instances/stage6b.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20 --request-timeout 120 \
  --toolset filesystem+shell
