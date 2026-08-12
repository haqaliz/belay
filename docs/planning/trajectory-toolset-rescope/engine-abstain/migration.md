# Migration — `engine-abstain` (operator runbook)

**Date:** 2026-08-12 · **Engine change:** `suite-before-success-claim` is now ability-aware
(commits `f1ac8af` / `b42ab57`): it abstains `NO_COMMAND_TOOL_OFFERED` when the trace's
`tools/list` snapshots before the claim offer no `run_process`, and `TOOLSET_UNKNOWN` when
no snapshot (or a stale one) exists. A FAIL is now only reachable when the suite-run
ability was actually offered.

**Who runs this:** the operator, in the **phase0-remint worktree** (where the gitignored
`corpus/local/` cases and the banked ledgers live). **Not run here**: this checkout holds
neither the cases nor the ledgers' sibling trace directories.

Two parts: (1) migrate the 5 local remint FP cases, (2) run the banked-population
reclassification check once.

---

## Part 1 — Migrating the 5 local remint FP cases

The re-mint's 5 trajectory FAILs were adjudicated false positives by construction
(`docs/planning/phase0-remint/audit-and-publish/AUDIT.md:34-53`): the boundary offered 14
filesystem tools and no shell, so the rule's evidence was impossible to produce. The
human labels live in `AUDIT.md` and stay there — that is the record. The corpus cases
themselves carry the engine's stored `expected` trajectory **FAIL**, which under the
fixed rule **recomputes REGRESSION** (UNVERIFIED ≠ FAIL on the instance dimension). A
REGRESSION-red local corpus would be a false drift signal, and re-banking them as
UNVERIFIED negatives is what the CI fixtures (`tests/test_corpus_trajectory_run.py`,
tests 7–8) now do instead — so the correct migration is **deletion**, not re-labeling:

### Steps

1. In the phase0-remint worktree, delete these five case dirs under the gitignored
   `corpus/local/` (ids from `AUDIT.md:46-48`):

   ```
   corpus/local/trace-control__flask-write-new-file-turn2
   corpus/local/trace-pytest-dev__pytest-8365-turn4
   corpus/local/trace-sphinx-doc__sphinx-11445-turn3
   corpus/local/trace-sphinx-doc__sphinx-7738-turn8
   corpus/local/trace-sphinx-doc__sphinx-7975-turn6
   ```

   `rm -rf` each path; nothing else in the corpus changes.

2. Do **not** re-add them here. The behavior they held — "fs-only boundary + verification
   claim → UNVERIFIED `NO_COMMAND_TOOL_OFFERED`, and that verdict is stable" — is now
   banked as the CI negative fixture (declared UNVERIFIED recomputes MATCH) and the
   ingest-side test (UNVERIFIED ingests no case). Re-banking them locally would duplicate
   the fixture with no new information, and a local corpus is not a second CI.

3. Re-run `belay corpus run` in that worktree; expect the 5 deletions to drop out of the
   results (and any remaining cases to classify as before).

**Recorded:** the labels and adjudication remain the published record at `AUDIT.md`; this
migration note is the operator's evidence that the local engine-written cases were removed
rather than silently kept as REGRESSION-red fixtures.

---

## Part 2 — Banked-population reclassification check (run ONCE)

Re-verify the banked s5 population under the new engine, once, and record it ledger-style
next to this note. It is a **reclassification check**, not a measurement: the s5 numbers
were published under v0.15.0 and stand unedited; this run shows what the same traces
classify as under the fixed rule.

### Expected outcome (derived from the traces, stated before running)

- **s5b's 5 trajectory FAILs** (`trace-control__flask-write-new-file`,
  `trace-pytest-dev__pytest-8365`, `trace-sphinx-doc__sphinx-11445`,
  `trace-sphinx-doc__sphinx-7738`, `trace-sphinx-doc__sphinx-7975`): each claim is
  classified `VERIFICATION` (the audit's "determinable" column), each boundary offers
  exactly the 14 filesystem tools — no `run_process` — so each recomputes
  **UNVERIFIED `NO_COMMAND_TOOL_OFFERED`**.
- **s5's 5 abstains** (`trace-control__flask-read-only` ×2 stages,
  `trace-requests-read-then-write`, `trace-pytest-8906`, `trace-sphinx-8273`,
  `trace-sphinx-8282`): claim checks precede the toolset check, so these stay
  **UNVERIFIED `CLAIM_UNCLASSIFIABLE`** — the toolset causes never mask an
  unclassifiable claim.
- **Zero new FAILs, zero new PASSes**: no trace offers or uses `run_process`, so no
  evidence can exist and the evidence branch cannot fire.

### Steps

1. In the phase0-remint worktree, with the new engine installed, re-run over the s5
   batch trace dirs (the gitignored `eval/mint/s5{a,b}/batch/` the ledgers were built
   from — `plan_20260809.md:55-57,74`):
   ```
   uv run belay phase0 run eval/mint/s5b/batch \
     --ledger docs/planning/trajectory-toolset-rescope/engine-abstain/reclassification-s5b.json \
     --no-ingest
   ```
   (`--no-ingest` so the check writes no corpus cases; `--server` with the recorded
   filesystem server command and `'{workspace}'` if the traces need replay, exactly as
   the original acceptance run did.) Repeat for `s5a` if desired; the s5b stage is the
   one that carried the 5 FAILs.

2. Verify against the expectations above: every v0.15 FAIL is now UNVERIFIED with a named
   cause (`NO_COMMAND_TOOL_OFFERED` ×5), every v0.15 abstain keeps its cause, and the
   FAIL/UNVERIFIED totals hold with **zero new FAILs**.

3. Record the run **ledger-style** — append a short block under this section:

   ```markdown
   ### Reclassification run — <date>

   Engine <version> · ledger: `docs/planning/phase0-remint/mint-run/ledgers/s5{b}.json`
   · re-run output: `<output path>` · `--no-ingest`.

   | v0.15 verdict | → new verdict | count |
   |---|---|---|
   | FAIL | UNVERIFIED `NO_COMMAND_TOOL_OFFERED` | 5 |
   | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | UNVERIFIED `CLAIM_UNCLASSIFIABLE` | 5 |
   | new FAIL / new PASS | | 0 |

   Dispositions: all instances `VERIFIED_CLEAN` (UNVERIFIED never flags). **A
   reclassification, never a rate**: no Phase-0 number is derived from this run; the
   published s5 figures stand unedited.
   ```

**What this run is NOT:** not a gate run, not a Phase-0 number, not evidence about
agents, not a re-publication of the s5 verdicts. It confirms the fixed rule converts the
by-construction FAILs into named abstentions and introduces nothing new — the mechanical
consequence of the aspect's decision order, verified once against the real banked traces.
