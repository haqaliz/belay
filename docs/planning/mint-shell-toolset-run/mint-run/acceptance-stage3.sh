#!/usr/bin/env bash
# STAGE 3 — the remaining fresh non-control draw (58). Frozen 2026-08-12 BEFORE it
# was run: this file contains no result. See docs/planning/mint-shell-toolset-run/mint-run/plan_20260812.md
# Phase 4. The run happens once (resumable on quota stop: re-run the IDENTICAL
# command on the same root); stdout is committed verbatim to acceptance-stage3.out.
set -euo pipefail
export BELAY_EVAL_SERVER_ROOT="${BELAY_EVAL_SERVER_ROOT:-$PWD/eval/servers}"
uv run python -m eval.minting_driver batch \
  --root eval/mint/s6c --registry eval/instances/stage6c.json \
  --provider claude-cli --model claude-opus-5 --max-steps 20 --request-timeout 120 \
  --toolset filesystem+shell
