# TEMPLATE_REPRODUCIBILITY.md — the number is re-derivable (Phase 4)

> **DRAFT TEMPLATE** for unit `feat/phase0-gate-mint` (2026-08-14). Fill during the run.
> Pure re-render of each committed ledger with the stock CLI, compared against the verbatim
> report blocks committed in `STAGE<stage>_FINDINGS.md`.

**Date:** <yyyy-mm-dd> · **Branch:** `feat/phase0-gate-mint/aliz` @ <commit> · **Box:** macOS (darwin)

## Commands

```bash
uv run belay phase0 report docs/planning/phase0-gate-mint/mint-run/ledgers/s6a.json
uv run belay phase0 report docs/planning/phase0-gate-mint/mint-run/ledgers/s6b.json
uv run belay phase0 report docs/planning/phase0-gate-mint/mint-run/ledgers/s6c.json
```

(One ledger per stage; a stage that never ran is absent, not re-rendered.)

## Assertion table (one row per report line carried by the findings)

| Line | Committed output (verbatim, `STAGE<stage>_FINDINGS.md` report block) | Re-render (this run) | Match |
|---|---|---|---|
| run size | `run size: <n> instances` | <verbatim> | <✅\|✗> |
| disposition | `VERIFIED_CLEAN: <n>` / `VERIFIED_FLAGGED: <n>` / `ERRORED: <n>` | <verbatim> | <✅\|✗> |
| violation rate | `violation rate = <n>/<n> = <pct\|n/a>` | <verbatim> | <✅\|✗> |
| trajectory aggregate | `aggregate: <n> FAIL / <n> PASS / <n> UNVERIFIED (by cause: ...)` | <verbatim> | <✅\|✗> |
| trajectory exposure | per-instance trajectory lines (FAIL/PASS/UNVERIFIED-with-cause) | <all lines identical> | <✅\|✗> |
| per-turn FAIL rate | `per-turn FAIL rate = <n>/<n> = <pct\|n/a>` | <verbatim> | <✅\|✗> |
| UNVERIFIED share | `overall UNVERIFIED turn share = <n>/<n> = <pct>` | <verbatim> | <✅\|✗> |
| UNVERIFIED by cause | `<cause>: <n>` per bucket | <identical buckets> | <✅\|✗> |
| exposure lines | per-instance exposure sentences (judged / no-opportunity / unrecorded) | <all lines identical> | <✅\|✗> |

Byte-identical headline numbers on every committed ledger; any mismatch is recorded here
with what was reconciled — a divergence means the ledger and the published number disagree,
and the published number is re-derived, not hand-waved.

## What "reproducible" does and does not cover (decided words)

- **Covered:** the ledger → report path — anyone given the committed ledgers re-derives the
  identical numbers with the stock CLI.
- **Not covered (unchanged):** case-level auditability from this repository — traces live
  under gitignored `eval/mint/`, the corpus under gitignored `corpus/local/`, per the
  no-raw-data-egress guardrail. The *evidence inventory* (claims, tools, turn tables) is
  transcribed verbatim into the committed `FLAGS.md`, which is what a stranger can read here.
- **The corpus scores:** after the Phase-2 labels, `belay corpus score` prints precision /
  recall / coverage with its denominator (UNVERIFIED and `pending`/`unverifiable` labels
  excluded); the pre-label state (`pending <n>`, `precision n/a`) is recorded in `FLAGS.md`
  §3 at its transcription date.
