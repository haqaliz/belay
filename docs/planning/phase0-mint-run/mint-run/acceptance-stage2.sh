#!/usr/bin/env bash
# STAGE 2 — 3 controls + 7 fresh real (10). Frozen 2026-08-09 BEFORE it was run: this file
# contains no result. See docs/planning/phase0-mint-run/mint-run/plan_20260809.md Phase 2.
# The run happens once; stdout is committed verbatim to acceptance-stage2.out.
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver batch \
  --root eval/mint/s4b --registry eval/instances/stage4.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20
