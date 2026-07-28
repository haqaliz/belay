# Aspect — `gate-readiness-unblocked`

**Unit:** `phase0-mint-resilience` · **Order: FIRST** · **Needs no quota, no API key, no model.**

> `audit-and-publish/spec.md:87-88`: the doc corrections *"are **not** blocked by the mint and
> can land early — doing so de-risks the tail."* This aspect is that early landing.

---

## Problem slice

Four things are undone that need nothing from any provider, and one of them would actively
corrupt a resumed mint if a reader followed it.

1. **7 of 12 s3 captures have never been verified.** `runs/s3-partial.json` covers only the 5
   day-1 instances; the 7 captured on 2026-07-24 (`pylint-6506`, `pylint-7114`, `pytest-5221`,
   `pytest-5227`, `pytest-5692`, `pytest-6116`, and the `pylint-5859` re-mint) have no ledger.
2. **The gate criteria were never pre-registered** into the document that will publish them.
   `git log -- docs/technical/PHASE0_RESULTS.md` shows only `ee12495` (template) and `05369c1`
   (NOT_COVERED docs). The requirement was *"Non-negotiable ordering: written down first, mint
   second"* (`phase0-live-mint/prd.md:137-139`).
3. **The RUNBOOK has six defects**, one of which — `RUNBOOK.md:94-103`, *"**Parallelism is
   allowed**"* with a `for … &` loop — contradicts sequential-by-design and `StdioMcp`
   thread-unsafety.
4. **Three divergent gate statements.** `PHASE0_RESULTS.md:97-107` carries a non-zero-rate
   PROCEED clause the pre-registered block deliberately removed, and **omits** both the ≥50
   denominator and the independence rule.

## User outcome

A reader can locate the canonical gate criteria, verify from `git log` when they were fixed,
and follow a runbook that does not tell them to do something that breaks the instrument. The
banked denominator is fully verified and known, rather than partially measured.

## In scope

- **Verify all 12 s3 captures** with the stock `belay phase0 run` against the current tree,
  producing a committed-in-spirit ledger (the ledger itself is gitignored run data; its
  *numbers* go into the findings note). Record: dispositions, per-turn statuses, UNVERIFIED
  causes, whether `INSTRUMENT SUSPECT` fired, and both controls' dispositions.
- **Merge the s2 and s3 accounting** into one honest statement of the current denominator,
  naming the 5 s2∩s3 overlaps as re-mints (not new denominator) and stating the distinct
  count (**16 of 68**, or 14 excluding controls).
- **Pre-register into `PHASE0_RESULTS.md`**, in its own commit, verbatim from
  `phase0-live-mint/prd.md:58-71`, plus:
  - the **commit hash and timestamp**, so the timing claim is checkable
    (`phase0-gate-readiness/prd.md:130-136`);
  - the sentence that pre-registration is a **timing control, not an independence control**;
  - the honest note that it did **not** precede Stage 3, and why the timing claim still holds
    for `prd.md` (fixed 2026-07-21, before any live mint) but not for this document.
- **Reconcile the three gate statements.** The pre-registered block becomes canonical;
  `ROADMAP.md:119-121` and `PHASE0_RESULTS.md:97-107` point at it and stop restating it
  differently. Transcribe the decided "reproducible" wording (`phase0-live-mint/prd.md:187-194`):
  the *mint* is a fresh observation and is not reproducible; the *ledger → report path* is
  fully reproducible from fixed traces.
- **Fix the RUNBOOK's six defects**, verified against current line numbers (older specs cite
  ~+15 stale):

  | # | Defect | Site |
  |---|---|---|
  | 1 | stale *"NOT YET BUILT"* driver | `:50` |
  | 2 | invalid `--` proxy argv | `:77`, `:85`, `:128`, `:135` |
  | 3 | false `trace-<instance-id>.jsonl` naming claim (it is `trace-<ts>-<hex>`, renamed by the bridge) | `:67` |
  | 4 | wrong `corpus show` form | `:205` |
  | 5 | "all 300" vs "≥50" | `:31`, `:73` vs `:92` |
  | 6 | **"Parallelism is allowed"** + `for … &` loop | `:94-103` |

  Plus de-stale the `:5-18` BLOCKED banner — recording, in order, that the single-instance
  block was lifted by v0.4.0 and the **batch** block by `replay-batch-server-rooting`
  (`audit-and-publish/spec.md:52-55`: *"the history is the evidence that the guards work"*).
- **Write `STAGE3_PARTIAL_FINDINGS.md`** in this aspect's directory: the forensic account of
  the quota stop (250/day cap, `retryDelay` ≈ 10h50m, 56 instances lost in 3m48s), the exact
  banked-denominator arithmetic, and the composition skew (django 0/19, sympy 1/18, sphinx
  1/13 — the *diverse* stratum is banked, the concentrated half is not).

## Out of scope

- Any code change under `eval/` or `src/belay/` — this aspect is docs + running the existing
  verifier.
- The hand-audit itself (human judgement; it is the gate *after* this unit's code lands).
- Changing the `tests/` read-only invariant.
- Running any live model.

## Acceptance criteria

1. `belay phase0 run` has been executed over **all 12** s3 captures, and its numbers are
   recorded in `STAGE3_PARTIAL_FINDINGS.md` with the denominator stated **with** its
   composition.
2. Every UNVERIFIED turn in that run carries a **named cause**; a turn published under
   `unknown` is a blocker, not a bucket (`PHASE0_RESULTS.md:45`).
3. Both banked controls' dispositions are recorded. **A FAILing control voids the mint** and
   is escalated, never quietly excluded (`mint-execution/spec.md:31-33`).
4. `PHASE0_RESULTS.md` contains the pre-registered criteria **verbatim**, with the
   pre-registration commit hash and timestamp, and the timing-not-independence sentence.
5. `git log -- docs/technical/PHASE0_RESULTS.md` shows the pre-registration commit, and the
   document states plainly that it did not precede Stage 3.
6. `PHASE0_RESULTS.md` no longer contains a non-zero-rate PROCEED clause, and **does** carry
   the ≥50 denominator and the independence rule.
7. `ROADMAP.md` and `PHASE0_RESULTS.md` each point at the canonical block rather than
   restating it divergently.
8. All six RUNBOOK defects are fixed, verified by re-reading the cited lines. In particular
   `RUNBOOK.md` no longer tells a reader parallelism is allowed.
9. The suite stays green; no test is modified.

## Dependencies & sequencing

- **Depends on:** nothing. Land first.
- **Blocks:** nothing structurally, but its findings feed the audit gate and every later
  aspect's write-up.
- **Execution location:** the verification run needs the captures, which live in
  `.claude/worktrees/feat-verdict-coverage-status/eval/mint/s3/batch/` and are **not
  movable**. Run the verifier there against this tree's engine; commit only documents here.

## Risks

- **`runs/` `FileNotFoundError`** (`STAGE1_REMINT_FINDINGS.md:104-105`) discards a *completed*
  verification run when the ledger's parent dir is absent. `mkdir -p runs` before running, and
  confirm whether it is still live — if it is, note it for the should-have fix.
- **Expected `belay corpus run` REGRESSIONs** for cases stored before the `NOT_COVERED`
  release: the network sub-verdict recomputes from `UNVERIFIED` to `NOT_COVERED`.
  `PHASE0_RESULTS.md` already documents this as expected — confirm any diff is confined to
  the `A2 / effect:network` entry. A REGRESSION touching any other axis is a real one.
- **Do not let the s3 verification imply a gate result.** 12 instances is not 50; the findings
  note must state the denominator and refuse to present a rate as the number.
