# Understanding — `mint-shell-toolset-run`

## What this unit is really asking

Run the Phase-0 mint under the **shell-offered toolset** — the measurement that every
prior unit explicitly deferred (`trajectory-toolset-rescope/prd.md:170`: *"The mint
itself (the next unit): fresh stage runs, the ≥50 denominator, the gate decision
line"*). v0.17.0 shipped everything the run needs: the composite transport (two
proxied MCP servers, one in-flight, verbatim `run_process`), per-instance `cwd`,
`--toolset filesystem+shell`, re-scoped controls (steered write claims + a new
positive control), and the runbooks. **This unit produces no `src/belay/` change** —
it ships ledgers, the audit, and the pre-registered gate decision line, or an honest
STOP/VOID with named causes.

The decision the run earns: **PROCEED** (≥3 independent hand-audited TPs, denominator
≥50, no `INSTRUMENT SUSPECT`, FP rate stated) or **PIVOT** — including the honest
reading of a healthy-instrument ~0 rate as evidence about R1, and a control FAIL as a
void regardless of how it is later adjudicated (pre-registered D-3).

## What the work touches

- `eval/` — the minting driver, instance registry, stage files, capture roots
  (`eval/mint/s6{a,b,c}` fresh roots for this mint), ledgers, and the audit
  artifacts. No `src/` change.
- `docs/planning/phase0-live-mint/prd.md` — canonical pre-registered gate criteria
  (fixed 2026-07-21); the block must be copied into `PHASE0_RESULTS.md` before
  stage 3 runs.
- `docs/planning/phase0-remint/prd.md` — run rules (A stage-gating, B near-zero
  reading, C high-rate suspicion, D freeze protocol; decisions D-1..D-6).
- `docs/planning/trajectory-toolset-rescope/` — the runbooks this unit executes:
  `mint-dual-server/plan_20260812.md` (transport, smoke, verify composition) and
  `controls-rescope/` (steered controls, positive control, `composition-note.md`
  with the recommended stage composition).
- `docs/planning/phase0-mint-resilience/prd.md` — quota-stop semantics (quota →
  batch stop, `no_observation` re-arms, `captured` never re-rolls, no `--force`).

## Confirmed environment state (2026-08-12, in this worktree)

- Branch `feat/mint-shell-toolset-run/aliz` at v0.17.0 (`0007b37`), clean.
- `claude` CLI 2.1.228 present (`/Users/aliz/.local/bin/claude`) — the
  `claude-cli` subscription path; model per D-6: `claude-opus-5`, `--max-steps 20`,
  `--request-timeout 120`.
- `eval/instances/`: `controls.py` (4 controls, `CONTROL_EXPECTATIONS`),
  `stage1.json`, `stage2.json`, `stage4.json`, `stage4a.json`, `pool.json`
  (166 strict-eligible), `selected.json`. Fresh stage files for this mint's
  composition are needed.
- `eval/servers/` **absent** in this worktree — must be installed
  (`npm install --prefix eval/servers @modelcontextprotocol/server-filesystem@2026.7.10
  mcp-server-commands@0.8.2`) or pointed at the holder root via
  `BELAY_EVAL_SERVER_ROOT` (e.g. `~/dev/at/holder/belay/servers`).
- macOS TCC: the scratch/workspace root must be outside Desktop/Documents/Downloads.
- The 5 banked remint FP cases live in the remint worktree's gitignored
  `corpus/local/` — migration is documented, not blocked; the new regression
  fixtures pin behavior (`trajectory-toolset-rescope/prd.md:161-163`).

## The stage composition (from `controls-rescope/composition-note.md`)

- **Stage 1** — the read-only control `control__flask-read-only` alone (probe of the
  capture → verify spine). Gates: capture + ≥1 genuinely verifiable turn + control
  `VERIFIED_CLEAN`, else STOP (wiring defect).
- **Stage 2** — 3 launched controls + the positive control
  (`control__flask-verify-with-command`) + **7 fresh real** instances, controls at
  the head, under `--toolset filesystem+shell`. Gates: capture rate ≥5/11, ≥1
  verifiable turn, all controls `VERIFIED_CLEAN` (control FAIL **voids**), and the
  **trajectory exposure gate ≥1 of 10 judged** (D-1; with the shell toolset the
  positive control should be judged — that is the D-3 tripwire's positive side).
- **Stage 3** — the remaining fresh non-control instances to the ≥50 denominator,
  with the pre-registered gates: no abort except quota-stop and the stage-2 gate
  outcome; capture rate <50% is the stop-loss → publish the smaller denominator.
  The canonical gate block must be copied into `PHASE0_RESULTS.md` before stage 3
  runs.

## The freeze protocol (binds the whole unit)

Invocation tooling committed **first, containing no result**; each stage run **once**;
verbatim output committed next, **whatever it says**; a second run only if declared.
Steering is stochastic — a control that FAILs (even adjudicated later as an artifact)
voids the mint by D-3; never re-steer mid-mint; never re-roll a `captured` instance.

## Open questions for the interview

1. **Stage-3 pool size** — drive the full remaining fresh non-control pool
   (remint-style, ~65; D-5 gate denominator) or stop at ≥50? Recommendation: the
   full pool — quota semantics pause/resume, and a larger denominator is strictly
   better for the number.
2. **Stage-file naming** — fresh stage files for this mint (following the
   `s6{a,b,c}` fresh-root convention) vs reuse? Recommendation: fresh.
3. **Spend envelope** — stage 3 on the operator's subscription is the big cost; any
   cap beyond the pre-registered gates (e.g. stop after N instances per day)?
   Recommendation: the pre-registered rules only (quota-stop pauses, not aborts).
4. **Corpus migration** — migrate the 5 banked FP cases from the remint worktree if
   reachable, or leave documented-unblocked? Recommendation: try once, don't block.

## Axes

A2 (replay) and A1 (invariant) verdicts and the **trajectory rule** (instance-level,
`suite-before-success-claim`) are all exercised as **measurements** on real model
text for the first time. The unit itself does not change any axis — it is the
trajectory axis's first gated measurement.
