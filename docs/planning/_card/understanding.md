# Understanding — second corpus-filling mint (`feat/corpus-mint-second-run`)

Source: `docs/planning/_card/issue.md` (inline brief, 2026-09-22) · dig agents 2026-09-22.

## What this work really is

The owner's S-1 decision, taken in the affirmative: **declare a second corpus-filling
mint run** (the recommendation the record already makes — `docs/STATUS.md:117-119`).
The first run STOPPED at its pre-registered gate (`NO_VERIFIABLE_TURNS: 2`,
`INSTRUMENT SUSPECT`, UNVERIFIED 3/3 = 100%) for a cause the engine has since fixed.
The remaining scope of `phase0-corpus-mint` is exactly `mint-run` (re-declared),
`corpus-banking`, `audit-and-publish` — the two deterministic aspects already shipped.

It is a **measured** unit (live, stochastic, unrepeatable, freeze-protocol) with
deterministic seams, not a feature build. Its deliverables: the first real corpus
growth since 2026-08-12 (moat #2 — trajectory FAILs bank, per-turn FAILs bank), the
A3 claim column's first real verdicts, and the real volume the calibration ledger
(v0.37.0) explicitly waits on.

## The instrument blocker is closed (verified at v0.37.0)

- `effect-conformance-coverage` (v0.35.0): the *observed-but-not-declared* producer
  now yields `effect NOT_COVERED`, `verdict.reduce` drops it before ranking
  (`src/belay/verify/effect.py:640-657`, `verdict.py:99-114`), so a replaying turn
  against the annotation-less npm filesystem server reduces to PASS-with-NOT_COVERED,
  `replayed_any` is set, `VERIFIED_CLEAN` is reachable, the denominator is non-zero.
- Residuals, stated not hidden: `UNRESTORABLE_SNAPSHOT_FAILED` is untouched by
  v0.35–v0.37 (run 1 lost 1/3 probe turns to it; pre-existing, absorbed at volume by
  the 2026-08-12 run) and the three *observation-failure* effect producers remain
  UNVERIFIED (`effect.py:659-670`).

## The code paths are mapped and ready

- Frozen run-1 scripts remain the authoritative invocation shape: mint via
  `python -m eval.minting_driver batch` (`--root` absolute under
  `~/dev/at/holder/belay/`, `--registry eval/instances/cm-stageN.json`,
  `--toolset filesystem+shell`, `--provider claude-cli --model claude-opus-5`),
  verify via **stock `belay phase0 run`** with `--shell-server` **before** `--server`
  (`nargs=REMAINDER`), `BELAY_CLAIM_AUTHOR` exported. MH-1 roots verified working in
  run 1 (`mint-run/STAGE1_FINDINGS.md:81-87`).
- A3 on the phase0 path is env-only and threaded: `author_from_env()` →
  `cli.py:2938` → `run_batch(claim_author=…)` (`cli.py:2950`) → engagement gate
  `src/belay/phase0/runner.py:419`. Live-proven at n=1 (184.5 s, exit 0 = D3 silence).
- Banking: per-turn FAILs ingest per turn (`runner.py:445-466`); trajectory FAILs
  bank `trace-<instance>-trajectory` (`runner.py:480-549`); A3 FAILs bank
  `trace-<instance>-claim` (`runner.py:560-599`). `corpus run` over the grown corpus
  needs `--shell-server` for shell-bearing cases or SKIPs with a named cause
  (v0.36.0 `corpus-shell-routing`; `src/belay/corpus/run.py:524-562`).
- Registry: committed `cm-stage1.json` (CTL-1 + CTL-4) and `cm-stage2.json`
  (CTL-2 + CTL-3 + 8 fresh reals, controls first); seed 20260919, `SEED_HISTORY`
  empty; regeneration byte-identical is the reproducibility check; the 8 reals were
  **never driven** (stage 2 never launched) so they are eligible.

## Decisions this unit must make (open questions for the interview)

1. **Re-driving the four controls.** Run-1 stage-1 controls (CTL-1, CTL-4) produced
   observations; the anti-re-roll contract's letter reads "an instance that produced
   an observation is never re-armable" (`checkpoint.py:15-21`). Controls are the
   run's own calibration instruments, not population draws, and run 1's stage-1 gate
   never cleared — but the letter does not distinguish. Recommended: re-drive the
   committed controls in fresh roots, recorded as a declared decision (same as the
   gate mints' per-stage fresh controls).
2. **Fresh roots.** Run-1 roots `cm1`/`cm2` under the holder are taken (cm1 holds
   run-1's batch + checkpoint; cm2 was never touched). New frozen scripts, roots
   `cm3`/`cm4`, reusing the committed registries verbatim.
3. **The `--verify` shell-threading parity gap** (found by this dig, unfixed):
   `run_verify` threads `claim_author` but not `shell_server_command`
   (`eval/minting_driver/entrypoint.py:995-1063`), while the printed command emits
   `--shell-server` (`entrypoint.py:696-698`) — the same defect class the a3-author
   aspect fixed for A3, and `eval/README.md:727-729` still calls them equivalent.
   Not blocking (the run uses `phase0 run` directly). Decide: fix it here as a small
   deterministic eval-only aspect, or record it as out of scope.
4. **n.** Q2 of the prior PRD confirmed n≈12 staged; unchanged. Stop-loss by stage.

## Guardrail check

Corpus (moat #2) work only — no agent framework, no LLM judge (A3's check is
execution-decided, exit code only), no egress (roots under the local holder), no
published number moves, no violation rate (Q1 — the fresh residue is ~100%
django+sympy). UNVERIFIED never PASS (INSTRUMENT SUSPECT ⇒ STOP, MH-5). The verdict
axes touched: A1 (trajectory), A3 (claim) — both observed, never modified.

## Suite baseline

2743 passing (v0.37.0). Deterministic acceptance before any spend: registry
regenerates byte-identically, frozen scripts carry no result shapes (grep-checked),
suite green.