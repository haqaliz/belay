#!/usr/bin/env bash
# THE CLAIM-AUTHOR LIVE PROBE — frozen BEFORE it was run.
#
# THIS FILE CONTAINS NO RESULT. The run happens once; each trace's stdout is
# committed verbatim to run-trace-<id>.out next, whatever it says — and its
# stderr to run-trace-<id>.err — along with the wrapper's marker and wall files
# (probe-marker, probe-wall) as produced (Rule D, phase0-mint-run/prd.md:97-101;
# the run-3 precedent: mint-run/acceptance-cm-run3-stage2.sh). A second run
# happens ONLY if the owner declares one.
#
# WHAT IT MEASURES (spec.md): re-verify the two banked run-3 trajectory cases
# (django-11422, django-14382) through the real CLI with the shipped reference
# claim author behind a recording wrapper, so R-D's candidate cause — the
# engine's 60 s author bound against the reference author's own 600 s bound — is
# answered by observation, whatever the observation is. The JSON record of each
# document's author disposition is a fact to record, not one to predict:
# nothing in this file names a possible disposition.
#
# THE FREEZE IS GREP-CHECKED, and a reviewer re-runs the two probes: (1) this
# file contains no result shape — no sub-cause name, no status literal, no
# author-record key, no exit-code literal appears anywhere below, not even in
# comments; (2) the wrapper (claim_author_wrapper.sh) only records and re-runs
# the shipped module — it names no disposition either. Both files are expected
# to come back clean; that check IS the RED test of Phase A.
#
# The engine is unchanged by this file, and nothing here runs a model by itself:
# the wrapper is invoked BY the engine's A3 seam, exactly as the operator's
# BELAY_CLAIM_AUTHOR would be.
#
# Operator hazards, each of which made a run read like an engine fault
# (a3-author/live-run.md:91-105):
#   - --manifest-dir is REQUIRED on this surface (no default). It must be the
#     trace's stem + ".manifests" sibling — the directory that exists on disk
#     beside the trace (the .jsonl suffix is NOT part of the directory name).
#   - the '{workspace}' argv token after the server command is MANDATORY: the
#     replay substitutes the scratch root it restored into.
#   - the record of interest is read from the document's top-level A3 key —
#     fat-fingering its name made an earlier probe report an empty column
#     against a payload that carried a perfectly good record.
#
# --json precedes --server on purpose: --server is nargs=REMAINDER and swallows
# everything after it, so a trailing --json would land inside the server argv
# and stdout would be the human report, not the JSON document.
set -euo pipefail

# --- absolute paths, PWD-independent -----------------------------------------
PROBE_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$PROBE_DIR/../../../.." && pwd)"
HOLDER="$HOME/dev/at/holder/belay"
FS_SERVER="$HOLDER/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"

# --- environment wiring --------------------------------------------------------
WRAPPER="$PROBE_DIR/claim_author_wrapper.sh"
export BELAY_CLAIM_AUTHOR="$WRAPPER"
export PROBE_MARKER="$PROBE_DIR/probe-marker"
export PROBE_WALL="$PROBE_DIR/probe-wall"
# The probe day's pinned model. It is a probe parameter, not a baked result:
# override with BELAY_REFERENCE_AUTHOR_MODEL=<full-id> in the invoking shell.
# Full ids only — the module rejects the opus/sonnet/haiku aliases.
export BELAY_REFERENCE_AUTHOR_MODEL="${BELAY_REFERENCE_AUTHOR_MODEL:-claude-opus-5}"

cd "$REPO_ROOT"

for TRACE in \
  "$HOLDER/mint/cm6/batch/trace-django__django-11422.jsonl" \
  "$HOLDER/mint/cm6/batch/trace-django__django-14382.jsonl"
do
  ID="$(basename "$TRACE" .jsonl)"
  ID="${ID#trace-django__django-}"
  MANIFESTS="${TRACE%.jsonl}.manifests"
  OUT="$PROBE_DIR/run-trace-$ID.out"
  ERR="$PROBE_DIR/run-trace-$ID.err"

  echo "=== verify $ID (stdout -> $(basename "$OUT"), stderr -> $(basename "$ERR")) ==="
  rc=0
  uv run belay verify "$TRACE" \
    --manifest-dir "$MANIFESTS" \
    --claim-author "$WRAPPER" \
    --json \
    --server node "$FS_SERVER" '{workspace}' \
    > "$OUT" 2> "$ERR" || rc=$?
  echo "=== verify $ID finished, exit code $rc (verbatim output committed next, whatever it says) ==="
done