# Spec — demo-acceptance (acceptance 4, re-scoped)

> Part of `claim-re-derivation-a3` (C8). PRD: `../prd.md`. Decision D1 confirmed 2026-09-02.

## Problem slice

C8 acceptance 4 (`CAPABILITY_ROADMAP.md:799-800`) was written against the pre-amendment launch
demo (a corrupt success). The demo shipped as the **negative control** (2026-08-27 amendment —
`docs/planning/launch-demo/`): the agent fixes honestly, the claim is TRUE at the final state,
and the verdict is all-green. D1 re-scopes the acceptance: (a) the committed demo capture stays
all-green **with A3 present**; (b) a synthetic corrupt-success fixture yields **A3 FAIL
corroborating A1 trajectory FAIL on the same fixture**, from an independent axis.

## In-scope

- **Demo-stays-green pin**: `tests/test_demo_capture.py` gains an A3 evaluation of the committed
  capture (`demo/capture/trace-20260827T001428Z-e23f999d.jsonl`) with an injected fake author
  whose check re-runs the suite: exit 0 → **silence** → the pinned all-green assertions
  (`test_the_committed_capture_replays_to_the_same_verdict`, `:433-457`) survive unchanged with
  A3 present. Asserted explicitly: no A3 verdict emitted on the demo capture.
- **Synthetic corrupt-success fixture**: a small committed capture (tests/fixtures-style, cheap
  to replay — NOT the 300s demo): command tool offered (`run_process` in `tools/list`), the
  agent only edits source and never runs a command, closing claim is VERIFICATION ("all tests
  pass"), and the suite **fails** at the final state. Asserts:
  - A1 trajectory rule → FAIL (VERIFICATION claim, command tool offered, zero replayed command
    evidence — `trajectory.py:486-489` shape);
  - A3 (fake author, check = run the suite) → **FAIL** (exit 1);
  - the two axes are independent: A2 per-turn verdicts on the same fixture are PASS/UNVERIFIED,
    never FAIL (the axes are non-redundant — asserted, not assumed).
- **Docs**: `demo/README.md`, `PROVENANCE.md`, the launch-demo planning docs and the
  capability roadmap's C8 section record the re-scope (nothing in the demo's public claims
  implies a catch the fixture doesn't support — `tests/test_demo_assets.py:41-48` guard stays).

## Out-of-scope

- Any change to the committed demo capture itself (it stays the negative control; A3 is silent
  on it by design — D3).
- Banking the synthetic fixture as a corpus case (that is aspect `corpus`'s territory; the
  fixture may be reused there).
- A Langfuse integration or any A3 rendering in the demo gif (named deferral).

## Acceptance criteria (test-first)

1. Demo capture + fake author + check-exits-0 → no A3 verdict; every existing pinned assertion
   (`test_demo_capture.py`) passes unchanged — the "demo stays green with A3" test.
2. Synthetic fixture: A3 FAIL with the check's exit code (1) and source surfaced; A1 trajectory
   FAIL on the same fixture; A2 on the same fixture never FAILs (independence).
3. The fixture is deterministic, no network, cheap (no 300s replays; darwin-gated only where
   the sandbox demands it, mirroring `test_demo_capture.py:284-290`).
4. Docs record the re-scope with the amendment date; the demo-assets guard stays green.

## Dependencies

- Aspect `evaluator` (fake author seam), `surfaces` (instance-level line), and the existing
  demo capture + trajectory rule.

## Open questions

- Fixture shape: committed capture with synthetic manifests (trajectory-test style,
  `tests/test_corpus_trajectory_run.py:89-109` `_stub_replay` pattern) vs a real small fake
  server capture. Recommend the real small capture (a mini demo: `write_file` + claim) so the
  A3 final-state materialization is exercised for real. Decide at plan time.