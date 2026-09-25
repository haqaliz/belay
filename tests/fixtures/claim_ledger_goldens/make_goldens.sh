#!/usr/bin/env bash
# Regenerate the committed-ledger `phase0 report` goldens from commit 1ada903 — the
# tree BEFORE claim-axis-legibility touched any claim surface. Never hand-edit the
# outputs; re-run this script.
#
# The render runs in a scratch worktree of 1ada903 with ITS OWN venv (`uv sync` there):
# `uv run` from a copied tree can import the original checkout's package, which would
# render the current code and call it the old one (the measurement-traps rule).
# `--corpus-dir` points at an empty scratch directory so the scoring section never
# reads whatever `./corpus/local` holds on the machine that runs it.
set -euo pipefail

BASE=1ada903
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
LEDGERS="$REPO/docs/planning/phase0-corpus-mint/mint-run/ledgers"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/claim-goldens.XXXXXX")"
TREE="$SCRATCH/tree"
CORPUS="$SCRATCH/empty-corpus"
mkdir -p "$CORPUS"

cleanup() {
  git -C "$REPO" worktree remove --force "$TREE" 2>/dev/null || true
  rm -rf "$SCRATCH"
}
trap cleanup EXIT

git -C "$REPO" worktree add --detach "$TREE" "$BASE" >/dev/null
(cd "$TREE" && uv sync --quiet)

for ledger in "$LEDGERS"/cm-*.json; do
  name="$(basename "$ledger" .json)"
  (cd "$TREE" && uv run --quiet belay phase0 report --corpus-dir "$CORPUS" "$ledger") \
    > "$HERE/$name.report.txt"
  echo "wrote $name.report.txt"
done
