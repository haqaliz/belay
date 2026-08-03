#!/usr/bin/env bash
# The measurement for `miss-measurement`, as ONE scripted invocation.
#
# v0.11.0 re-verified every banked capture under the rule that ships and reported 1/15
# instances (6.7%). Fourteen instances flagged nothing -- and the record could not say
# whether that meant the captures are clean or the rule is BLIND to them, because an A1
# verdict carried no statement of whether the rule had anything to judge at all. This run
# re-verifies the same captures under tooling that now records EXPOSURE, so "silent"
# separates into "judged N file(s) and found nothing", "0 file(s) compared", and
# "unrecorded".
#
# The freeze protocol is the one used by `invariant-rule-wiring/acceptance.sh` and by
# `reverify-measurement/acceptance.sh`, unchanged, because the failure it guards against is
# the same one: iterating against the data until it says something, then presenting the
# result as if it were the first attempt.
#
#   1. the frozen tooling is committed FIRST, in a commit containing no result of this run;
#   2. this script is run ONCE and its output committed verbatim in the NEXT commit,
#      whatever it says;
#   3. a second run is permitted ONLY if it is declared as such in the write-up.
#
# Then the git history IS the evidence. Freeze point: recorded in the commit that adds this
# file; the tooling it exercises is `a1-exposure-accounting` (f1c8bd8..6ef118d) and
# `corpus-recorded-miss` (6ef118d..ab91342).
#
# A TIMING PROBE WAS RUN BEFORE THIS SCRIPT WAS COMMITTED, and is declared here rather than
# left to be discovered: `belay phase0 run` over the s1p stage (11 of the 392 turns) with
# `--no-ingest`, its ledger written outside the repo and its stdout piped to /dev/null, so
# the wall-clock was observed and the VERDICTS WERE NOT. It reported 2.63s real, from which
# this run was budgeted at roughly 95s. Its ledger was then inspected for two instrument-
# health facts only -- disposition and how many turns were walked (VERIFIED_CLEAN, 11) --
# both of which v0.11.0 had already published. No finding entered from the probe.
#
# Run under the DEFAULT invariants -- no --invariants file and no --no-default-invariants.
# The point is what the shipped default now does, and what it now says about itself.
#
# WHAT THIS RUN CANNOT DO, stated here so no reader has to infer it:
#
#   * It CANNOT clear the Phase-0 gate. The pre-registered PROCEED clause requires a
#     denominator >= 50, and that clause counts INSTANCES MINTED, not the rule that scored
#     them -- it is detector-independent, so no re-verification of already-banked captures
#     can ever satisfy it. R1's quantitative form stays untested.
#   * It is NOT a precision measurement. Nothing here is adjudicated by execution.
#   * Any recall figure that follows from it rests on TWO held-out turns. n=2 IS NOT A BASE
#     RATE, and it is NOT comparable to the `recall 0.00 (0/1, n=1)` already on the record --
#     different detector, different population, different adjudication set.
#   * Exposure NARROWS the blindness question; it does not close it. It can show that the
#     rule was never given anything to judge on a named instance. It CANNOT show that an
#     exposed-and-passed turn was correctly passed -- only human adjudication does that.
#
# The reading of whatever comes out is pre-registered in `../prd.md` section 2.1, committed
# at 0d4fef0, before any of this ran.
#
# The captures are ~4.7 GB and NOT movable (they embed absolute snapshot paths), so the paths
# below are absolute and machine-specific by necessity.
set -u

MINT=/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint
SERVER=/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js

# A FRESH, PRESERVED corpus dir: never `corpus/local/`, and never a throwaway temp dir --
# a capability that catches something must compound the corpus, so anything flagged here is
# kept as a `pending` case for later adjudication. Note the only 7 human-labeled cases in
# existence live in a DIFFERENT worktree, so they are out of this run's reach by
# construction rather than by care.
CORPUS=corpus/miss-measurement-20260803

# The ledgers are committed (see the aspect plan, Phase 3): `runs/` is gitignored, and the
# published number being re-derivable from a repo artifact is a claim `docs/ROADMAP.md`
# already makes and nothing currently backs. A ledger holds trace ids, counts, dispositions
# and causes -- no raw data -- so committing one does not touch the no-raw-data-egress
# guardrail.
LEDGERS=docs/planning/under-firing-measurable/miss-measurement/ledgers

mkdir -p "$LEDGERS"

for STAGE in s1 s1b s1p s2 s3; do
  echo "############################################################"
  echo "## STAGE $STAGE"
  echo "############################################################"
  uv run belay phase0 run "$MINT/$STAGE/batch" \
    --ledger "$LEDGERS/miss-$STAGE.json" \
    --corpus-dir "$CORPUS" \
    --server node "$SERVER" '{workspace}'
done

echo "############################################################"
echo "## POPULATION (all five stages, deduped by instance)"
echo "############################################################"
uv run belay phase0 combine \
  s1="$LEDGERS/miss-s1.json" \
  s1b="$LEDGERS/miss-s1b.json" \
  s1p="$LEDGERS/miss-s1p.json" \
  s2="$LEDGERS/miss-s2.json" \
  s3="$LEDGERS/miss-s3.json"
