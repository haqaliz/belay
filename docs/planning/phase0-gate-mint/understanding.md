# Understanding — phase0-gate-mint

Date: 2026-08-14 · Unit: `feat/phase0-gate-mint` · Base: `origin/master` (v0.17.0)
Source: inline brief (docs/planning/_card/issue.md) + agent dig over the planning docs, eval harness, and verify spine.

## What this work really is

The Phase-0 gate mint: fresh stage runs under the **shell-offered toolset** (v0.17.0 —
`--toolset filesystem+shell`) to fill the **≥50-instance denominator** and produce the gate
decision line for **R1's quantitative form**, which is still untested
(`docs/planning/trajectory-toolset-rescope/prd.md:149-150`, `:170-171`). This is the unit
every prior record names as "the next unit". It is a **gate run** first and a **code unit**
second — most of its acceptance is ledger-style (freeze protocol, committed ledgers,
adjudication, decision line), not test-first code.

## The canonical constraints (pre-registered, cannot be re-written now)

- **PROCEED** iff ≥3 *independent* hand-audited TPs AND denominator ≥50 AND no `INSTRUMENT
  SUSPECT`; **PIVOT** on fewer than 3 TPs or noise-level FP rate; a **FAILing clean control
  voids the mint** (D-3) (`docs/planning/phase0-live-mint/prd.md:58-84`, canonical copy in
  `docs/technical/PHASE0_RESULTS.md:25-38`).
- Freeze protocol: invocation tooling committed **first, containing no result**; each stage
  run **once**; verbatim output committed next; second run only if declared
  (`docs/planning/phase0-remint/prd.md:208-209`).
- The successor PRD must **pre-register its D-1 reading** against the toolset change:
  `claims_judged` = FAIL|PASS, abstains add to `claims_abstained`; a shell-less stage reads
  0 judged and stops (`trajectory-toolset-rescope/prd.md:138-142`).
- The mint is sequential, single-model (`claude-opus-5`, subscription path), `--max-steps 20`,
  every edit behind the gated proxy; controls drive first; the violation rate is reported
  with its denominator and FP rate.

## Affected areas

1. **Verify spine (engine, `src/belay/phase0/runner.py`, `src/belay/verify/`, `src/belay/replay/`)** —
   THE critical-path gap. `belay phase0 run` resolves **one** `--server` command per trace
   (`runner.py:110-154`); a dual-server capture's `run_process` turns replayed against the
   filesystem command "are not expected to reproduce their replies" (`eval/README.md:797-805`).
   Consequence at code level: `TurnFact.replayed` requires `replayed_is_error is not None`
   (`trajectory.py:208-283`); an MCP method-not-found error envelope has no `result.isError`
   → `replayed=False` → every shell turn lands in the `EVIDENCE_UNOBSERVABLE` abstain
   (`trajectory.py:491-503`). The A2 axis would also manufacture divergences on those turns.
   Result: **CTL-4's expected PASS is structurally unreachable, real suite-runners are never
   judged, and D-1 exposure can die at stage 2.** The honest replay path exists and is proven
   per-turn (the manual smoke asserts a `run_process` turn replays against the rootless pinned
   shell command, PASS or UNVERIFIED-with-cause, never a silent miss — `tests/test_minting_driver_dual_server_smoke.py:52-57`); what does not exist is the **per-tool routing inside
   `belay phase0 run`**.
2. **Registries (eval, `eval/instances/`)** — `stage4.json`/`stage4a.json` still carry the
   **unsteered** CTL-2/CTL-3 task text (only `selected.json` was regenerated;
   `composition-note.md:44-51`) — reusing them verbatim re-opens the D-3 tripwire that voided
   the re-mint. CTL-4 (`control__flask-verify-with-command`, expected trajectory PASS) is
   composed nowhere. `stage2.json`'s header (launched 68/real 65) contradicts its 10-record
   list (harmless to `load_registry`, an inconsistency for the record).
3. **Run aspects (ledger-style, no code)** — freeze scripts pinning `--toolset
   filesystem+shell`, stage 1 (probe) → stage 2 (controls + fresh real) → stage 3 (≥50),
   per-stage `belay phase0 run` + committed ledgers, adjudication of every flag (trajectory
   FAILs are adjudicated in full, per the re-mint's audit discipline), `PHASE0_RESULTS.md`
   update, the gate decision line.
4. **The dual-server live smoke** (`mint-dual-server/smoke.md:68-83`) — **NOT RUN**, manual,
   operator-gated. First live evidence the composite works must precede stage spend.

## Contradictions / stale assumptions surfaced (flagged, not papered over)

- The skill/docs greenfield framing ("no pyproject.toml", "no commits") is stale: the engine
  is at v0.17.0, 50 commits, 1663 tests collected. Nothing to fix — noted for the record.
- `stage4.json` steered-vs-unsteered task text (above) — a real D-3 hazard, must be fixed by
  regeneration before any freeze.
- Verify composition gap (above) — the single biggest surprise for this unit; the README
  explicitly defers it to "the successor mint's verify composition", i.e. to us.

## Verdict axes

- **A1 only, instance-level.** The trajectory rule (`suite-before-success-claim`) is an A1
  rule; this unit's engine aspect makes its evidence (replayed exit-0 `run_process`)
  observable — an A1 precision/exposure fix, UNVERIFIED-never-PASS preserved. A2/A3 untouched.
- The A1 content rule (`no-assertion-weakening`) continues to run unchanged on `tests`/`testing`
  scopes; with the shell toolset, real agents editing source will again mostly compare zero
  files (the s4 finding) — the trajectory axis is the decision-relevant one this run.

## Open questions for the requirements interview

1. Stage composition: CTL-4 in stage 1 (probe) or stage 2 (recommended by
   `composition-note.md:32-42` — 3 + positive + 7 fresh = 11 records)? 
2. D-1 reading: minimum judged instances at stage 2 (re-mint read ≥1 of 10; strictness given
   that abstains now dominate the prior real claims)?
3. Scope of the engine aspect: `--shell-server` flag vs generic per-tool map; must the A2
   axis stay silent (NOT_COVERED-ish) on shell turns replayed against the wrong server, or
   does routing fix it cleanly?
4. Corpus migration of the 5 banked remint FPs (recompute → UNVERIFIED) — in scope here or
   noted as debt (they live in the remint worktree's gitignored `corpus/local/`)?
5. Stage 3 size: all 68 of `selected.json` (real 65 — enough for ≥50 after ~80% capture
   attrition) vs a fresh draw; multi-day resume is operator discipline, not code.
6. Is `draw_mint_set.py --target N` regeneration needed, or is the committed 68-draw
   sufficient (it is the one with steered text)?
