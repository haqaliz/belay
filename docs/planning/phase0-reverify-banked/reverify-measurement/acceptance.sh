#!/usr/bin/env bash
# The re-verification measurement for `phase0-reverify-banked`, as ONE scripted invocation.
#
# Every published Phase-0 number was produced by the A1 default that v0.10.0 REPLACED
# (`{scope: b"tests/", rule: "read-only"}` -> `no-assertion-weakening` over `tests`/`testing`
# path segments). The record therefore no longer describes the code that ships. This run
# re-verifies every banked capture under the rule that ships TODAY, so the number and the
# code correspond again.
#
# The freeze protocol is the one used by `invariant-rule-wiring/acceptance.sh`, unchanged,
# because the failure it guards against is the same one: iterating against the data until it
# says something, then presenting the result as if it were the first attempt.
#
#   1. the frozen tooling is committed FIRST, in a commit containing no result of this run;
#   2. this script is run ONCE and its output committed verbatim in the NEXT commit,
#      whatever it says;
#   3. a second run is permitted ONLY if it is declared as such in the write-up.
#
# Then the git history IS the evidence. Freeze point: recorded in the commit that adds this
# file; the tooling it exercises is `corpus-collision-guard` (1ad08b0..1e0cb1c) and
# `ledger-reporting-honesty` (527f26d..578379f).
#
# Run under the DEFAULT invariants -- no --invariants file and no --no-default-invariants.
# The point is what the shipped default now does.
#
# WHAT THIS RUN CANNOT DO, stated here so no reader has to infer it: it CANNOT clear the
# Phase-0 gate. The pre-registered PROCEED clause requires a denominator >= 50, and that
# clause counts INSTANCES MINTED, not the rule that scored them -- it is detector-independent,
# so no re-verification of already-banked captures can ever satisfy it. R1's quantitative form
# stays untested. The reading of whatever comes out is pre-registered in `../prd.md` section
# 2.1, including the blindness clause for a zero-flag result.
#
# The captures are ~4.7 GB and NOT movable (they embed absolute snapshot paths), so the paths
# below are absolute and machine-specific by necessity.
set -u

MINT=/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint
SERVER=/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js

# A FRESH, PRESERVED corpus dir (PRD M-4a): never `corpus/local/`, which holds the only 7
# human-labeled cases in existence, and never a throwaway temp dir either -- a capability that
# catches something must compound the corpus, so anything flagged here is kept as a `pending`
# case for later adjudication.
CORPUS=corpus/reverify-20260731
LEDGERS=runs

mkdir -p "$LEDGERS"

for STAGE in s1 s1b s1p s2 s3; do
  echo "############################################################"
  echo "## STAGE $STAGE"
  echo "############################################################"
  uv run belay phase0 run "$MINT/$STAGE/batch" \
    --ledger "$LEDGERS/reverify-$STAGE.json" \
    --corpus-dir "$CORPUS" \
    --server node "$SERVER" '{workspace}'
done

echo "############################################################"
echo "## POPULATION (all five stages, deduped by instance)"
echo "############################################################"
uv run belay phase0 combine \
  s1="$LEDGERS/reverify-s1.json" \
  s1b="$LEDGERS/reverify-s1b.json" \
  s1p="$LEDGERS/reverify-s1p.json" \
  s2="$LEDGERS/reverify-s2.json" \
  s3="$LEDGERS/reverify-s3.json"
