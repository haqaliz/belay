#!/usr/bin/env bash
# POST-RUN-2 SCORE — `belay corpus score` over the holder corpus, after the recompute.
# Frozen BEFORE it was run: THIS FILE CONTAINS NO RESULT. Each run's stdout is committed
# verbatim as acceptance-cm-run2-corpus-score-<stage>.out, whatever it says. Pinned by
# shape in tests/test_corpus_banking_freeze.py.
#
# Cases bank `pending`; only the owner labels (S-1). A rate with a 0 denominator prints
# n/a, never a fabricated 1.00 — this script reads the score, it never labels.
set -euo pipefail

HOLDER="$HOME/dev/at/holder/belay"

echo "=== corpus score — $HOLDER/corpus-local ==="
uv run belay corpus score "$HOLDER/corpus-local"
