#!/usr/bin/env bash
# STAGE 1 — probe instance (1 control). Frozen 2026-08-09 BEFORE it was run: this file
# contains no result. See docs/planning/phase0-mint-run/mint-run/plan_20260809.md Phase 1.
# The run happens once; stdout is committed verbatim to acceptance-stage1.out.
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver one control__flask-read-only \
  --root eval/mint/s4a --registry eval/instances/stage4a.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20
