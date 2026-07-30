# feat/phase0-reverify-banked

**Type:** feat · **Id (slug):** `phase0-reverify-banked` · **Owner:** aliz
**Source:** inline brief (no GitHub issue — the tracker has never been used; all PRs are
issue-free). Produced by `/belay-next` on 2026-07-30 and invoked as
`bbf feat phase0-reverify-banked`.
**Base:** `origin/master` @ `24815de` (v0.10.0).

> **Predecessor.** This card replaces the previous `_card/issue.md`, which described
> `feat/invariant-test-mutation-shape` (merged straight to `master` at `884467e`, released
> v0.10.0). That unit replaced the 0.00-precision `tests/` read-only default with
> **`no-assertion-weakening`** over `tests`/`testing` path segments, and its own closing
> sentence names this unit as the successor: *"R1 stays untested until a re-mint runs under
> this rule — which is now the next unit."* Its brief is preserved in git history at
> `cdde2db`.
>
> **Divergence from that sentence, deliberately.** The predecessor assumed the successor was
> the **funded re-mint**. `/belay-next` ranked the re-mint second, because the re-mint's
> enabling client (`subscription-model-client`) is still unbuilt and an 11-hour spend under a
> detector whose held-out precision is unmeasured repeats the mistake v0.9.0 recorded. This
> unit is the cheap measurement that comes first; the re-mint is its follow-on.

---

## Brief

Re-verify every banked Phase-0 capture under the detector that ships on `master` today
(`no-assertion-weakening`, v0.10.0), producing one comparable 16-instance population, and
correct the published record so no number is presented as current when an obsolete detector
produced it.

The captures are machine-bound and live in place: `eval/mint/{s1,s1b,s1p,s2/batch,s3/batch}`
inside the `feat-verdict-coverage-status` worktree, replayed against the absolute-path MCP
filesystem server in the `feat-phase0-mint-execution` worktree — do not move or remove either,
and do not re-mint anything.

Acceptance is **test-first**:

- **(a)** a merged ledger over all stages with an explicit, tested dedup rule for the five
  instances appearing in both `s2` and `s3`;
- **(b)** a ledger records the rule identity that produced it, and a report rendered from an
  old-detector ledger is never presented as current;
- **(c)** captured controls are verified and reported separately, and a FAILing control in a
  *re-verification* is labeled a detector false positive, not "mint void" — the void condition
  belongs to a fresh mint;
- **(d)** corpus re-ingestion never overwrites an existing human label, and a case whose
  recomputed verdict changed is reported rather than silently relabeled;
- **(e)** the whole run is deterministic and offline, executable with no API key.

Treat the measurement under the freeze protocol used at `95e6ff8`: commit the rule/tooling
first, then the verbatim output, and state the denominator (16 < the pre-registered 50) on
every surface — this is a decision input for whether to fund the re-mint, not a gate run, and
R1 stays untested.

### Out of scope

- **Resuming the mint to n≥50**, and `subscription-model-client` (`docs/planning/
  phase0-mint-resilience/subscription-model-client/spec.md`, specified but unbuilt). This unit
  is the decision input for that spend, not the spend.
- **Any change to the A1 rule itself.** `no-assertion-weakening` is measured here, not edited.
  A defect it exposes is a finding for the next unit unless it makes the measurement
  impossible.
- Any change to A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED` boundary.
- C7 live console; C8 (A3 claim re-derivation); C9 export-back.

---

## Why this unit, and why now

| File | Says |
|---|---|
| `docs/ROADMAP.md:160` | *"The action is to **fix the instrument and re-measure**"* — the instrument is now fixed; this is the re-measure |
| `docs/ROADMAP.md:280` (R1) | R1's quantitative form *"is tested only by a re-mint under a detector with **measured non-zero precision**"* — the new rule has no such measurement yet |
| `CLAUDE.md` (status block) | *"**What is NOT claimed: a precision number.** ~13 labeled points from 4 instances. Read it as **'0.00 → not yet measured'**"* |
| `docs/technical/CAPABILITY_ROADMAP.md:460` | *"This is an invariant problem, not a sample-size problem"* — and its corollary: don't spend the mint before the detector is measured |
| `docs/planning/phase0-mint-resilience/prd.md:290` | *"Recommendation: decide after the audit gate — if the audit suggests a PIVOT, do not spend 11 hours first"* |

**The concrete integrity problem.** Every published Phase-0 number — `4/16`, `precision 0.00`,
`3/93`, `0% UNVERIFIED` in `docs/technical/PHASE0_RESULTS.md`, plus `runs/s2.json` and
`runs/s3-partial.json` — was produced by the `tests/` read-only detector, which **no longer
ships**. The record and the code now disagree, and re-verification is the only thing that
re-aligns them.

**The measurement opportunity.** The new rule was *fitted* on the 7 negative fixtures and
`pytest-5227`. The banked set is larger than the published record, measured on disk
2026-07-30 (`ls eval/mint/*/batch/trace-*.jsonl`):

| | Captures | Distinct trace ids |
|---|---|---|
| `s1`, `s1b`, `s1p` | 3 | 1 (`pallets__flask-4045`, captured three times) |
| `s2/batch` | 9 | 7 instances + **2 controls** |
| `s3/batch` | 12 | 12 instances, **0 controls** |
| **total** | **24** | **17** = 15 non-control instances + 2 controls |

`s2/batch ∩ s3/batch` is **5 instances** (`flask-4992`, `requests-1963`, `pylint-5859`,
`pytest-5221`, `pytest-5227`) — independent re-mints of the same instance, not copies — which
is the overlap `PHASE0_RESULTS.md:146` describes and the one acceptance (a) must dedup.

**Do not confuse that 5 with the published overlap of 2.** The published `16` is a *sum of
ledger rows* across four ledgers (`s1p` 1 + `stage1-recheck` 1 + `s2` 9 + `s3-partial` 5), and
`s2.json ∩ s3-partial.json` is only **2** rows — because **`s3-partial.json` ledgered just 5
of s3's 12 captures**. The other **7 s3 captures appear in no ledger under `runs/` at all**,
so the re-verification population is *bigger and cleaner* than the published one: **15 unique
non-control instances**, against a published denominator of 16 double-counting rows. Still far
below the pre-registered ≥50 — the gate is untouched either way.

---

## Logistics the dig must know

- **The captures are NOT in this worktree.** They are at
  `/Users/aliz/dev/at/belay/.claude/worktrees/feat-verdict-coverage-status/eval/mint/`
  (`s1`, `s1b`, `s1p`, `s2/batch`, `s3/batch`), with the old-detector ledgers alongside at
  `…/runs/{s1p,s2,s3-partial,stage1-recheck}.json`. `eval/mint/` and `runs/` are gitignored
  and the captures embed absolute snapshot paths — **they are not movable** (verified
  previously: moving breaks replay). Point at them by absolute path; never copy or relocate.
- **The MCP server the traces name** is at
  `/Users/aliz/dev/at/belay/.claude/worktrees/feat-phase0-mint-execution/eval/servers/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js`
  (confirmed present). Each corpus case's `server_command` is an absolute path to it, so the
  corpus is **machine-bound through the server** — a known, unfixed property.
- **Neither of those two worktrees may be removed.** Both are detached HEAD with ~5.5 GB of
  unregenerable mint data.
- **The 7 labeled negative fixtures** are at `…/feat-verdict-coverage-status/corpus/local/`
  (`trace-pallets__flask-4045-turn8`, `trace-pallets__flask-4992-turn{10,12,14,19}`,
  `trace-pylint-dev__pylint-5859-turn{6,11}`), with a hand-label backup at
  `…/corpus-labels-backup-20260729/`. `belay phase0 run` **ingests flagged turns**, so a
  re-run touches this directory.
- **s3's 56 "failed" instances contain traces with 0 `tools/call`** (~19.9 K of handshake
  each), consistent with the recorded 12-captured/56-failed split. They are not verifiable
  turns and must not inflate a denominator.
- Stock entrypoints: `belay phase0 run <trace-dir> --ledger OUT.json` (`src/belay/cli.py:1161`)
  and `belay phase0 report <ledger.json>` (a pure re-render, `:1246`).
- Baseline on this branch: `uv run pytest` — **1005 passed, 1 skipped, 1 deselected**
  (inherited from v0.10.0; to be re-confirmed by the dig).

---

## Known caveats, carried forward from `/belay-next`

1. **This unit cannot clear the gate, and must not be published as if it could.** The
   denominator is **15 unique non-control instances** (published as 16 ledger rows) against a
   pre-registered **≥50**, so PROCEED is mechanically unreachable *whatever the result*, and
   **R1's quantitative form stays untested**. The ≥50 clause is detector-independent — it
   counts instances minted, not the rule that scored them — so no re-verification can ever
   satisfy it. Say this early and explicitly in the write-up; it is the sentence that stops a
   re-measurement being read as a gate run.
2. **Comparability.** All banked stages must be re-verified under one rule, or the population
   splits — the incomparability `docs/technical/CAPABILITY_ROADMAP.md:466` warns about.
3. **Labels.** The 7 hand-labeled negatives must survive a re-run unrelabeled; a recomputed
   verdict change is a *report*, never a silent overwrite.
4. **A FAILing control means something different here.** In a fresh mint a FAILing clean
   control **voids the mint**; in a re-verification it is a **detector false positive** — the
   very signal this unit exists to measure. Conflating the two would manufacture a void.
