# REPRODUCIBILITY — clean-checkout renders

> **This is not a gate run, it produces no Phase-0 number, and it is not a result
> about agents.**
>
> **STATUS: WRITTEN 2026-09-23.** Both stage-1 ledgers were re-rendered from a clean
> checkout of `f7d7804` (`git worktree add --detach`, fresh `uv sync`) via
> `belay phase0 report`. Each render was diffed against the verify section (from
> `detector:` to EOF) of its committed `.out`. **Both byte-identical. No mismatch, no
> STOP.**

## Renders

| Ledger | Written by engine | Committed output | Rendered by | Byte-identical |
|---|---|---|---|---|
| `mint-run/ledgers/cm-stage1.json` (run 1) | 0.33.0 | `acceptance-cm-stage1.out` | 0.37.0 | ✅ |
| `mint-run/ledgers/cm-run2-stage1.json` (run 2) | 0.37.0 | `acceptance-cm-run2-stage1.out` | 0.37.0 | ✅ |

Run 1's ledger re-renders identically under an engine four minor versions newer. The
report is a pure re-render of stored fields, with no replay and no network.

## Method

```
git worktree add --detach <scratch> f7d7804
cd <scratch> && uv sync
uv run belay phase0 report docs/planning/phase0-corpus-mint/mint-run/ledgers/<ledger>.json > <ledger>.render
sed -n '/^detector:/,$p' docs/planning/phase0-corpus-mint/mint-run/<out> | diff - <ledger>.render
```

The ledgers were copied verbatim from `$HOLDER/runs/` and contain no absolute paths and
no raw workspace data. The captures stay under `$HOLDER/mint/cm3/` and are not
committed, as the no-raw-data-egress guardrail requires. The ledger → report path is the
re-derivable half.

## Engine-version delta and the NOT_COVERED boundary

Run 1 ran on **0.33.0** and run 2 on **0.37.0**. Two coverage boundaries separate them.
`effect-conformance-coverage` (v0.35.0) moved a not-declared `readOnlyHint` from
UNVERIFIED to NOT_COVERED, and the network NOT_COVERED boundary predates both.
**UNVERIFIED shares across the two runs (3/3, 5/5) are NOT comparable.** Neither run
recorded a NOT_COVERED dimension, because every turn died before reaching one.

## Pre-registered branch

Stage 1 → `INSTRUMENT SUSPECT` → STOP. Stage 2 (`acceptance-cm-run2-stage2.sh`, root
`cm4`) was **never run**, so there is no stage-2 ledger to reproduce.

---

## Run 3 — clean-checkout renders (2026-09-23)

Both run-3 ledgers were re-rendered from a clean checkout of `b6707ec` (`git worktree add
--detach`, fresh `uv sync`) with `belay phase0 report`, and each was diffed against the
verify section of its committed `.out`, using the same method as above.

| Ledger | Committed output | Byte-identical |
|---|---|---|
| `mint-run/ledgers/cm-run3-stage1.json` | `acceptance-cm-run3-stage1.out` | ✅ |
| `mint-run/ledgers/cm-run3-stage2.json` | `acceptance-cm-run3-stage2.out` | ✅ |

**Engine delta:** run 3 ran v0.37.0 **plus** the composite-snapshot fix (`aad775f`).
UNVERIFIED shares across runs 1 / 2 / 3 (3/3, 5/5, stage 1 1/5, stage 2 4/45) are **NOT
comparable**. The captures differ, and runs 2 → 3 cross a correlation change (a coverage
gain: effect now decides where it used to abstain, which is not improved detection).
