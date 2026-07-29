#!/usr/bin/env bash
# The C2 acceptance measurement for `invariant-rule-wiring`, as ONE scripted invocation.
#
# `pytest-dev__pytest-5227` is the ONLY real positive fixture that exists: ~180k upstream
# commits were searched across six cached repos and every other apparent assertion
# weakening collapsed on inspection. Held-out only stays held-out if it is not iterated
# against, so the protocol is mechanical rather than an intention:
#
#   1. the frozen rule is committed FIRST, in a commit containing no result of this run;
#   2. this script is run ONCE and its output committed verbatim in the NEXT commit,
#      whatever it says;
#   3. a second run is permitted ONLY if it is declared as such in the write-up.
#
# Then the git history IS the evidence. Freeze point: 151a267.
#
# Run under the DEFAULT invariants — no --invariants file and no --no-default-invariants.
# The point is that the shipped default now catches it.
#
# The capture is ~5.5 GB and not movable (it embeds absolute snapshot paths), so the paths
# below are absolute and machine-specific by necessity.
set -u

MINT=/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint
SERVER=/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js

uv run belay verify "$MINT/s2/batch/trace-pytest-dev__pytest-5227.jsonl" \
  --manifest-dir "$MINT/s2/batch/trace-pytest-dev__pytest-5227.manifests" \
  --server node "$SERVER" "$MINT/s2/pytest-dev__pytest-5227/workspace"
