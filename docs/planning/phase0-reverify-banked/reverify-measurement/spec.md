# Aspect — `reverify-measurement`

**Unit:** `phase0-reverify-banked` · **Order: 3.** **Covers PRD must-have M-5, M-4a, S-2.**

---

## Problem slice

Everything is now in place to run the measurement safely and report it honestly:
`corpus-collision-guard` made a re-run incapable of corrupting the 7 labeled cases or shrinking
its own denominator; `ledger-reporting-honesty` made a ledger state its detector, a population
state both denominators and its dedup rule, and a control stay out of the headline.

What remains is to **run it once, under the freeze protocol, and commit the output verbatim**.

## User outcome

One comparable measurement of the shipped A1 rule (`no-assertion-weakening`) over all banked
captures, whose provenance a stranger can audit from git history alone.

## In scope

**R1 · One scripted invocation.** A committed `acceptance.sh` pinning the exact commands: absolute
trace dirs, the absolute `--server` path, and a **fresh, preserved** `--corpus-dir` (M-4a). No
parameters, no ambiguity about what "the run" means.

**R2 · The freeze protocol** (from `invariant-rule-wiring/acceptance.sh`, verbatim):
1. the frozen tooling is committed FIRST, in a commit containing no result of the run;
2. the script is run ONCE and its output committed verbatim in the NEXT commit, whatever it says;
3. a second run is permitted ONLY if declared as such in the write-up.

**R3 · All five stages** (S-2) — `s1`, `s1b`, `s1p`, `s2`, `s3` — including the **7 s3 captures
that appear in no published ledger**, then combined into one population.

**R4 · Default invariants.** No `--invariants`, no `--no-default-invariants`: the point is what
the shipped default now does.

**R5 · Offline.** No network, no API key, no model call. If the run needs either, that is a defect.

## Out of scope

- **Interpreting the result.** The reading is pre-registered in `prd.md` §2.1 and applied in
  `record-correction`. This aspect produces the number; it does not decide what it means.
- **Hand-adjudicating** anything the run flags — a follow-on, as the PRD says.
- **Re-running to get a different answer.** Prohibited by R2 clause 3.
- Any code change to `src/belay/`. If the run reveals a defect, that is a finding for the next
  unit unless it makes the measurement impossible.

## Acceptance criteria

1. `acceptance.sh` is committed in a commit containing **no** result of the run, and names its own
   freeze point.
2. The run completes over all 5 stages and the population combine succeeds.
3. `acceptance.out` is the **raw, complete, unedited** stdout of that one invocation.
4. The output carries: the detector identity (**recorded**, not `unrecorded` — these ledgers are
   produced by today's rule), both denominators, the dedup rule, disagreements, the controls
   block, and the UNVERIFIED-by-cause breakdown.
5. The 7 human labels in the **other** worktree's `corpus/local/` are byte-identical afterwards —
   verified, not assumed. The run writes only to `corpus/reverify-20260731/`.
6. No network call and no API key are involved.

## Dependencies and sequencing

- **Depends on:** `corpus-collision-guard` (done), `ledger-reporting-honesty` (done).
- **Blocks:** `record-correction`.

## Risks

| Risk | Assessment |
|---|---|
| **Wall-clock** — 397 turns, each a restore + re-invoke + diff | Unknown until run; it is one command and it runs in the background. |
| **A turn degrades to UNVERIFIED** (cross-root args) | Safe direction; it appears in the by-cause line. Only `s1` was spot-checked for single-root-relative args. |
| **The result is ambiguous** (zero flags) | Pre-registered: `prd.md` §2.1's blindness clause. Publish as "sensitivity unconfirmed", never "the data is clean". |
| **A second run is tempting** | Prohibited unless declared. The git history is the evidence. |
