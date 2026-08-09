# REPRODUCIBILITY.md — the number is re-derivable (Phase 4)

**Date:** 2026-08-09 · **Branch:** `feat/phase0-remint/aliz` @ `f28b2cb` · **Box:** macOS (darwin)
**Procedure:** pure re-render of each committed ledger with the stock CLI, compared against
the verbatim outputs committed at `d559018`'s successors (`STAGE{1,2}_FINDINGS.md` report
blocks + `acceptance-stage{1,2}.out`).

## Commands

```bash
uv run belay phase0 report docs/planning/phase0-remint/mint-run/ledgers/s5a.json
uv run belay phase0 report docs/planning/phase0-remint/mint-run/ledgers/s5b.json
```

## Assertion table

| Line | Committed output (verbatim) | Re-render (this run) | Match |
|---|---|---|---|
| stage 1 run size | `run size: 1 instances` | `run size: 1 instances` | ✅ |
| stage 1 disposition | `VERIFIED_CLEAN: 1` | `VERIFIED_CLEAN: 1` | ✅ |
| stage 1 rate | `violation rate = 0/1 = 0.0%` | `violation rate = 0/1 = 0.0%` | ✅ |
| stage 1 trajectory | `aggregate: 0 FAIL / 0 PASS / 1 UNVERIFIED (by cause: CLAIM_UNCLASSIFIABLE: 1)` | identical | ✅ |
| stage 2 run size | `run size: 10 instances` | `run size: 10 instances` | ✅ |
| stage 2 disposition | `VERIFIED_CLEAN: 5` / `VERIFIED_FLAGGED: 5` | identical | ✅ |
| stage 2 rate | `violation rate = 5/10 = 50.0%` | `violation rate = 5/10 = 50.0%` | ✅ |
| stage 2 per-turn | `per-turn FAIL rate = 0/57 = 0.0%` | identical | ✅ |
| stage 2 UNVERIFIED | `overall UNVERIFIED turn share = 0/57 = 0.0%` | identical | ✅ |
| stage 2 trajectory | `aggregate: 5 FAIL / 0 PASS / 5 UNVERIFIED (by cause: CLAIM_UNCLASSIFIABLE: 5)` | identical | ✅ |
| stage 2 exposure line | `0 file-comparison(s) on all 10` | all 10 lines identical | ✅ |

Byte-identical headline numbers on both ledgers; no mismatch to reconcile.

## What "reproducible" does and does not cover (decided words)

- **Covered:** the ledger → report path, exactly as `ROADMAP.md:123` defines it — anyone
  given the two committed ledgers re-derives the identical numbers with the stock CLI.
- **Not covered (unchanged):** case-level auditability from this repository — traces live
  under gitignored `eval/mint/`, the corpus under gitignored `corpus/local/`, per the
  no-raw-data-egress guardrail. The *evidence inventory* (claims, tools, turn tables) is
  transcribed verbatim into the committed `FLAGS.md`, which is what a stranger can read
  here.
- **The corpus scores, once more:** after the Phase-2 labels were applied,
  `belay corpus score` prints `precision 0.00, recall n/a, coverage 1.00` (TP 0 / FP 5) —
  re-runnable by anyone with the corpus dir; the pre-label state (`pending 5`, `precision
  n/a`) is recorded in `FLAGS.md` §3 at its transcription date.
