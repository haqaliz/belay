# REPRODUCIBILITY — Clean-Checkout Renders

> **STATUS: WRITTEN 2026-08-12.** Ledgers re-rendered from a clean checkout of
> `7295b01` (`git worktree add` at that commit, fresh `uv sync`) via
> `belay phase0 report`; each render's headline compared against the committed
> `mint-run/acceptance-stage{1,2,3}.out` renders. **All byte-identical — no
> mismatch, no STOP.**

## Renders

| Ledger | Committed headline | Clean-checkout headline | Byte-identical |
|--------|--------------------|-------------------------|----------------|
| s6a    | 0/1 = 0.0%, 1 VERIFIED_CLEAN | 0/1 = 0.0%, 1 VERIFIED_CLEAN | ✅ |
| s6b    | 5/11 = 45.5%, 5 FLAGGED | 5/11 = 45.5%, 5 FLAGGED | ✅ |
| s6c    | 37/52 = 71.2%, 37 FLAGGED | 37/52 = 71.2%, 37 FLAGGED | ✅ |

Per-instance rows (trajectory lines, turn counts, cause buckets) rendered
identically on all three; spot-checked on s6c's 20 trajectory FAIL lines and the
cause aggregates (CU 20 / EU 7 / NCR 6) — all match the committed `acceptance-stage3.out`.

## Method

- `git worktree add /tmp/repro-clean 7295b01` (the stage-3 result commit; ledgers
  committed under `mint-run/ledgers/`)
- `uv sync` in the clean worktree
- `belay phase0 report docs/planning/mint-shell-toolset-run/mint-run/ledgers/s6{a,b,c}.json`
  — a pure re-render, no replay, no network

**The number is re-derivable from a repo artifact by a stranger.** The case-level
half of "reproducible" (captures under `eval/mint/s6*/`) is gitignored, as the
no-raw-data-egress guardrail requires — the ledger → report path is the published
boundary.
