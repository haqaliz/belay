#!/usr/bin/env bash
# POST-RUN-2 RECOMPUTE — `belay corpus run` over the holder corpus, after a stage's
# verify has ingested. Frozen BEFORE it was run: THIS FILE CONTAINS NO RESULT. Each
# run's stdout is committed verbatim as acceptance-cm-run2-corpus-run-<stage>.out,
# whatever it says (Rule D, phase0-mint-run/prd.md:97-101). Pinned by shape in
# tests/test_corpus_banking_freeze.py.
#
# Frozen AFTER stage 1's verify, not before it (a sequencing deviation, recorded in
# FINDINGS.md): the ingest happens inside `belay phase0 run`, which the mint-run script
# already froze; this script only recomputes what is banked.
#
# --shell-server is REQUIRED: a trajectory case whose stored trace spans both boundaries
# recomputes its run_process turns against it, and without it SKIPs with a named cause
# (corpus-shell-routing, src/belay/corpus/run.py). `corpus run` carries no --server —
# each case replays its stored server_command, which points into $HOLDER/servers
# (machine-bound through the SERVER, unchanged).
set -euo pipefail

HOLDER="$HOME/dev/at/holder/belay"
SHELL_SERVER="$HOLDER/servers/node_modules/mcp-server-commands/build/index.js"

echo "=== corpus run — $HOLDER/corpus-local ==="
uv run belay corpus run "$HOLDER/corpus-local" --shell-server "node $SHELL_SERVER"
