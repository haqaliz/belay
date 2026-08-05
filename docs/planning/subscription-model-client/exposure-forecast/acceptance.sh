#!/usr/bin/env bash
# The exposure forecast, run ONCE. Frozen before it had a result.
#
# The script was committed at `f82d12f` containing no output; this file is the exact
# invocation, and `acceptance.out` is its verbatim stdout. That ordering is the whole
# protocol: if the figures had been seen first, no reader could tell whether the
# instrument was built to produce them.
#
# Everything here is offline and deterministic — no network, no API key, no model call,
# no clone, no clock, no randomness. The only inputs are two files that are already
# committed (`eval/instances/pool.json`, `eval/instances/selected.json`), and the gold
# patches are deliberately NOT among them: an answer key sitting next to the eval is a
# mint-voiding contamination hazard (`prd.md` D-4). Re-running this on an unchanged
# registry must reproduce `acceptance.out` byte for byte.
#
# No argument is passed. The defaults ARE the committed registries, and naming them here
# would let this file and the script disagree about what was measured.
#
# Expected, from `plan_20260805.md` §0 (probed 2026-08-05 with the same token set):
#   59/166 total · django 22/82 · sympy 20/56 · sphinx 8/13 · pytest 6/7 ·
#   pylint 3/3 · requests 0/4 · flask 0/1 · statement length min 239 / median 787 / max 1970
# Reproducing those is the check that the instrument is sound — the same bar
# `under-firing-measurable` had to clear against its independent static survey. A
# disagreement is a reason to STOP and investigate, never a reason to adjust either side.
set -euo pipefail

cd "$(dirname "$0")/../../../.."

uv run python eval/scripts/forecast_exposure.py \
  > docs/planning/subscription-model-client/exposure-forecast/acceptance.out
