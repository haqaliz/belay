#!/usr/bin/env bash
# STAGE 3 — the full 68 (selected.json). Frozen 2026-08-09 BEFORE it was run: this file
# contains no result. See docs/planning/phase0-remint/mint-run/plan_20260809.md Phase 3.
# The run happens once (resumable on quota stop: re-run the IDENTICAL command on the same
# root); stdout is committed verbatim to acceptance-stage3.out.
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver batch \
  --root eval/mint/s5c --registry eval/instances/selected.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20
