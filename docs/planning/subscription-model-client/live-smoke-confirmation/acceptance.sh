#!/bin/sh
# live-smoke-confirmation — the single live invocation, run ONCE (plan S-4).
#
# The test it runs was frozen at 363fac2, BEFORE this script existed and before any
# live call was made: the freeze protocol's whole point is that the output cannot have
# been fitted to the tooling.
#
# BELAY_EVAL_SERVER_ROOT points at the pinned MCP server installed in a sibling
# worktree. eval/servers/ does not exist in this worktree, and the servers are
# version-pinned, so pointing at the existing install is equivalent to installing it
# again -- and avoids both a network fetch and a second copy of third-party JS.
# (Traces and corpus cases are NEVER copied between worktrees. Servers are not traces.)
set -eu
cd "$(dirname "$0")/../../../.."
BELAY_EVAL_LIVE=1 \
BELAY_EVAL_SERVER_ROOT=/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers \
uv run pytest tests/test_minting_driver_claude_cli_smoke.py -m manual -q -rA
