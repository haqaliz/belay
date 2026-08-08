# Understanding — phase0-mint-run

Date: 2026-08-09. Replaces the stale `subscription-model-client` understanding (that unit is
merged; the file was never rewritten).

## What this unit really is

The **execution, audit, and publish of the Phase-0 gate mint** on the funded subscription
path. The deliverable is not a capability and not new engine code: it is a filled
`PHASE0_RESULTS.md` decision line (PROCEED or PIVOT) backed by a fresh run's number. The
machinery is all shipped and is consumed as-is:

- **Minting:** `python -m eval.minting_driver {one|batch}` with `--provider claude-cli`,
  staged registries, checkpoint/resume with `no_observation` re-arm, gated capture,
  sequential single-in-flight drive, fresh client per instance, request_timeout 120 s
  (`eval/minting_driver/`, `eval/README.md`).
- **Verification:** `belay phase0 run --ledger … --server node <fs-server> '{workspace}'`
  (no `--`), `combine`, `report` — pure re-render, `INSTRUMENT SUSPECT` defense, per-instance
  exposure reporting (`src/belay/phase0/`, `src/belay/verify/`).
- **Audit:** `belay corpus add/run/score/list/show/label` with root-cause keys and
  independence grouping (`src/belay/corpus/`).
- **Draw:** `selected.json` — 68 records = 65 real + 3 controls, seed `20260723` committed.

## Affected areas

- `eval/minting_driver/` + `eval/instances/` + `eval/README.md` (runbook) — execution surface.
- `docs/technical/PHASE0_RESULTS.md`, `PHASE0_AUDIT.md`, `docs/ROADMAP.md` — publish surface.
- `docs/planning/phase0-live-mint/` + `phase0-mint-execution/` (audit-and-publish specs,
  gate criteria) — governing requirements.
- Possibly `eval/minting_driver/clients/claude_cli_client.py` + one test, IF `--safe-mode`
  is decided into the shipped argv (eval-side only; the card's "consume the engine as-is"
  constraint covers `src/belay/`, which must not change).

## State summary (from the dig, all file-cited)

**SHIPPED and to be consumed as-is:** funded client (20 criteria green; smoke `363fac2` →
`91f1e21`, `claude-opus-5`, 5 turns, 1 real `edit_file`, 0 UNVERIFIED, VERIFIED_CLEAN);
entry points; draw; gated capture; quota breaker; replay batch rooting; ledger schema with
detector + exposure; canonical gate criteria committed at `bde2678` (prd-level at
`4d06f52b`, 2026-07-21, predating every mint — the card's "criteria predate the first
Stage-3 mint commit" check resolves at the prd level, and the doc-level disclosure is
already in `PHASE0_RESULTS.md:44-61`).

**Published numbers that stand unedited until this gate run supersedes them:** `4/16`,
`precision 0.00`, `3/93`, `recall 0.00`, `1/15`, 17 judgments, decision PIVOT.

## Open decisions (this unit's to make — the interview must resolve these)

1. **Mint model** — default candidate `claude-opus-5` (D-2 precedent + smoke evidence the
   full id works at n=1: `live-smoke-confirmation/acceptance.out`). R-6: 12 banked s3
   instances ran on `gemini-3.1-pro-preview`; a single-model re-mint of all 68 is
   "the mint's call" and the card's "run the ~65–70-instance batch through `claude -p`"
   reads as a full fresh run.
2. **`--safe-mode` in the shipped argv** — unprobed, absent from code and tests today.
   Probably right for reproducibility (isolates hooks/plugins/`CLAUDE.md` without touching
   auth, P2 evidence) — but it is a change to `claude_cli_client._build_command` + a test,
   and it must be probed before being adopted.
3. **Stop-loss / abort threshold** — `phase0-gate-readiness/prd.md:125-128` required one
   "committed before any Stage-3 run"; none exists anywhere. The subscription limit shape is
   unknown (R-4): unrecognised errors classify `terminal`, and the first real limit is "a
   finding for the mint unit". ~11 h wall-clock estimate (68 × ~10 min).
4. **`--max-steps`** — default 12 (`entrypoint.py:100`); Stages 1–3 ran `--max-steps 20`;
   the smoke ran at 12. Must be chosen and stated.
5. **Controls FIRST** — not enforced by code (`selected.json` appends controls last; the
   driver preserves registry order). Must be achieved via `one` invocations or a
   controls-first registry. The third control (`control__requests-read-then-write`) has
   **never** been driven live.

## Ambiguities and contradictions to flag (not paper over)

- `_card/understanding.md` was stale (subscription-model-client); this note replaces it.
- RUNBOOK ledger/case examples still describe an older format
  (`docs/planning/phase0-corpus-run/RUNBOOK.md:304-318,348` vs the shipped schema).
- README "re-run `npm view`" note conflicts with code-pinned versions
  (`eval/README.md:168-174` vs `servers.py:61-74`) — pins win.
- This worktree has no `eval/servers/` and is not in the banked-data symlink list
  (`eval/README.md:55-72`): install or symlink servers, and `mkdir -p runs` before
  `belay phase0 run` (an absent ledger dir discards a completed run).
- The smoke's zero-exposure finding (`pytest-7432` edited source, `files_compared: 0`)
  strengthens R-3: a near-zero mint result must be published under the pre-registered
  reading rules as **uninterpretable about agents**, never as evidence of honesty.
- The exposure forecast's 44.6% (29/65) has an **unmeasured** relationship to exposure
  (floor claim withdrawn 2026-08-05).

## Verdict axes

No axis changes. A1/A2 are the instruments of the measurement (defaults on:
`no-assertion-weakening` on `tests`+`testing` segments); A3 untouched and disabled.

## Guardrail check

No agent framework (the oracle is a no-tools completion subprocess), no LLM judge (verdicts
are replay-grounded), no raw-data egress (traces/corpus stay gitignored and on-box;
committed artifacts are ledgers/acceptance outputs only), honest verdicts (UNVERIFIED never
PASS; INSTRUMENT SUSPECT never a 0%), zero runtime deps preserved. A `--safe-mode` argv
change is eval-side only and keeps all 20 criteria testable offline via the `runner=` seam.
