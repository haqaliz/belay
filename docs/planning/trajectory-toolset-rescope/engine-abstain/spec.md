# Spec — aspect `engine-abstain`

**PRD:** `docs/planning/trajectory-toolset-rescope/prd.md` (Requirements 1–3, 9–10) · **Date:** 2026-08-12

## Problem slice

`suite-before-success-claim` FAILs on a verification claim with zero `run_process` turns
(`src/belay/verify/trajectory.py:378-382`) without knowing whether a command tool was ever
offered. The remint proved this FAIL is pre-determined by construction when the boundary
offers only filesystem tools (5/5 FPs, precision 0.00). This aspect makes the rule
**ability-aware**: never FAIL without a command tool on the boundary; never abstain when the
toolset is genuinely unknown; never mask usage.

## In scope

1. New closed abstain causes `NO_COMMAND_TOOL_OFFERED` and `TOOLSET_UNKNOWN` (alongside
   `NO_CLAIM_RECORDED` / `CLAIM_UNCLASSIFIABLE` / `EVIDENCE_UNOBSERVABLE`).
2. A derived **offered-toolset fact** computed from the trace's recorded `tools/list`
   frames (`derive_annotations`, `src/belay/annotations.py:103-155` — already emits
   `annotation_snapshot` tool names) and passed through the facts seam; the evaluator never
   sees raw records (provenance boundary preserved).
3. Decision order in `evaluate_trajectory_invariant`: claim checks unchanged → toolset check
   → evidence check unchanged. Snapshot exists + `run_process` offered → evidence decides
   (PASS/EVIDENCE_UNOBSERVABLE/FAIL exactly as today). Snapshot exists + no `run_process` →
   UNVERIFIED `NO_COMMAND_TOOL_OFFERED`. No snapshot, or staleness
   (`annotation_staleness` recorded) → UNVERIFIED `TOOLSET_UNKNOWN`. Union of names across
   snapshots (any snapshot before the claim counts as offered — a snapshot after the claim
   is not evidence of ability before the claim).
4. **False-abstention invariant:** a trace containing any `run_process` turn can never
   abstain `NO_COMMAND_TOOL_OFFERED` — usage is proof of offering; pinned by test.
5. Surfaces extended (no forks): disposition (UNVERIFIED never flags — holds), ledger
   (absent-never-zero — holds), `belay phase0 report` trajectory lines + aggregate (new
   causes render by name), corpus ingest (UNVERIFIED ingests nothing — holds). Per-turn path
   untouched (`INSTANCE_LEVEL_RULES` exclusion, pinned by test).
6. Corpus fixtures: bank (a) no-command-tool + verification claim → expected
   `{"status": "UNVERIFIED", "cause": "NO_COMMAND_TOOL_OFFERED"}`; (b) command-tool offered +
   zero evidence → expected FAIL (positive preserved). Verify `corpus run` classifies a
   declared-UNVERIFIED recomputing UNVERIFIED as `MATCH` (fix if it does not — a small
   `_classify_trajectory_case` gap, in scope).
7. Migration of the 5 local remint FP cases (gitignored `corpus/local/` in the remint
   worktree): documented operator step — delete the 5 FAIL-expected cases (human labels stay
   in the audit record), re-bank nothing there; the new fixture negatives carry the behavior
   in CI. Runs where the cases live; not blocked on in this worktree.
8. Reclassification check: run the new rule over the banked s4/s5 population once (operator
   step where the traces live) — every v0.15 FAIL becomes UNVERIFIED with a named cause, zero
   new FAILs; recorded ledger-style, not published as a rate.
9. Docs: `TRACE_FORMAT.md` (derived offered-toolset fact), `CAPABILITY_ROADMAP.md` C5 status
   block, `CLAUDE.md` status block, `README.md` coverage limits (ability precondition),
   decision note for the "confirmed" vocabulary (kept; conservatism by design).

## Out of scope

- Classifier vocabulary changes; A2/A3; trace-format changes; the mint itself;
  `mint-dual-server` and `controls-rescope` aspects (this aspect's fixtures use fabricated
  traces only — no live shell server needed).

## Acceptance criteria (tests written first)

1. Evaluator + real-path: fs-only `tools/list` + VERIFICATION claim + zero commands →
   UNVERIFIED `NO_COMMAND_TOOL_OFFERED`; no flags; disposition `VERIFIED_CLEAN`.
2. No `tools/list` at all → UNVERIFIED `TOOLSET_UNKNOWN`; `tools/list_changed` without
   re-snapshot → UNVERIFIED `TOOLSET_UNKNOWN`.
3. `run_process` in `tools/list` + zero evidence → FAIL unchanged (existing pinned tests
   updated: their fixtures must now offer `run_process`).
4. Any `run_process` turn in the trace → never `NO_COMMAND_TOOL_OFFERED` (invariant test).
5. `belay phase0 report` renders both new causes per instance and in the by-cause aggregate;
   ledger round-trips; no per-turn verdict changes (poisoning test green).
6. `belay corpus run`: banked negative (declared UNVERIFIED) → MATCH; banked positive
   (declared FAIL) → MATCH; suite green; existing corpus 7/7 MATCH preserved.
7. Deterministic, no network; full suite (`uv run pytest`) green with the new cases.

## Dependencies & sequencing

Parallel to `mint-dual-server`. `controls-rescope` depends on this aspect's abstain
semantics for its expected-verdict pinning (steered write-control claims abstain under the
new rule). Engine version v0.17.0 at release.

## Risks

- False abstention (derivation misses an offered tool) → the false-abstention invariant is
  the guard; the union-over-snapshots rule covers re-snapshots; staleness never guesses.
- Declared-UNVERIFIED corpus classification may not exist in `_classify_trajectory_case` —
  small in-scope fix if so; fail-closed validation (`case.py:285-321`) already admits
  UNVERIFIED status.
- The reclassification check needs the banked traces (gitignored, remint worktree) — an
  operator step; the fixture tests do not depend on it.
