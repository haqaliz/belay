#!/bin/sh
# claim_author_wrapper.sh — the recording wrapper for the A3 claim author (probe).
#
# `--claim-author` points HERE instead of at the shipped module, so each engine
# invocation is an OBSERVED fact on disk rather than an inference from the JSON
# payload, whose author record is absent for both "no author configured" and
# "the authored check exited 0" (a3-author/live-run.md:60-89). What runs is still
# the shipped module, byte for byte:
#
#     python3 -m belay.verify.reference_claim_author --model <full-id>
#
# Per invocation the wrapper:
#   1. appends exactly one byte to $PROBE_MARKER  — "the author ran", counted by
#      the probe test as `invocations >= 1` (P2, the axis engaged);
#   2. records wall start/stop (`date +%s`) to $PROBE_WALL — the numeric form of
#      R-D's question, author wall-time vs the engine's own bound (S1);
#   3. runs the shipped module as a CHILD and propagates its exit code. A plain
#      `exec` is not used: an exec'd process could never write the end
#      timestamp. The child inherits this shell's stdin/stdout untouched, so the
#      module's JSON-in / JSON-out contract holds exactly.
#
# $BELAY_REFERENCE_AUTHOR_MODEL is passed through UNEDITED — no default is baked
# here (it is a probe parameter set by run-probe.sh; the module itself rejects
# empty ids and the opus/sonnet/haiku aliases).
#
# Run under `uv run` (as run-probe.sh and the manual test do), so `python3` on
# PATH is the project interpreter that can import belay — the run-3 mechanism
# (acceptance-cm-run3-stage2.sh sets the same command shape).

set -u

: "${PROBE_MARKER:?claim-author-wrapper: PROBE_MARKER must be set (run via run-probe.sh)}"
: "${PROBE_WALL:?claim-author-wrapper: PROBE_WALL must be set (run via run-probe.sh)}"
: "${BELAY_REFERENCE_AUTHOR_MODEL:?claim-author-wrapper: BELAY_REFERENCE_AUTHOR_MODEL must be set}"

printf x >> "$PROBE_MARKER"
echo "start:$(date +%s)" >> "$PROBE_WALL"

python3 -m belay.verify.reference_claim_author --model "$BELAY_REFERENCE_AUTHOR_MODEL"
rc=$?

echo "end:$(date +%s)" >> "$PROBE_WALL"
exit $rc