# Aspect — `audit-and-publish`

**Unit:** `phase0-mint-execution` · **Sequence:** 5 of 5
**Placement:** `docs/technical/PHASE0_RESULTS.md`, `docs/planning/phase0-corpus-run/RUNBOOK.md`,
`docs/ROADMAP.md`, `STAGE1_FINDINGS.md`

---

## Problem slice

Turn the ledger into **the number**, hand-audit every flag, and write the PROCEED or PIVOT.
This is where over-claiming would be easiest and most damaging, so the honesty properties are
the acceptance criteria.

**User outcome:** a reader who disagrees with the conclusion can locate every underlying case
and **re-derive the number from the committed ledger**.

---

## In scope

1. **Hand-audit every flagged case** via `belay corpus label`. Until then the FP rate prints
   `n/a` and the gate cannot be met. **Record each TP's root cause beside it**, so a reader
   can judge the ≥3-**independent** requirement directly rather than taking it on trust.
2. **Hand-replay one FAIL end-to-end** to confirm its observed delta is real and not a
   rename/manifest artifact — the second half of the symmetric FP guard.
3. **Fill `PHASE0_RESULTS.md`: 18/18 fields + the decision line.** Zero remaining
   `TO-BE-FILLED` markers (note the section heading at `:17` carries one too, so it must be
   reworded).
4. **Publish the instance-pool composition beside the number**, with the django/sympy
   concentration stated as a limitation.
5. **Disclose the shell-server exclusion** as a coverage limit (honesty property 7).
6. **Correct the RUNBOOK — six defects, not five:**
   | # | Defect | Correction |
   |---|---|---|
   | 1 | `:50` "NOT YET BUILT" driver | shipped in v0.3.0 (`eval/minting_driver/`) |
   | 2 | `:77,85,128,135` invalid `--` proxy argv | drop the `--`; `--server` is `nargs=REMAINDER` |
   | 3 | `:67` claims traces are written `trace-<instance-id>.jsonl` | they are `trace-<ts>-<hex>.jsonl`; the **bridge** renames them |
   | 4 | `:205` `belay corpus show corpus/local/<case-id>` | `belay corpus show <case-id> --corpus-dir <dir>` |
   | 5 | `:73` "all 300" vs `:94` "≥50" | ≥50 is the gate requirement; 300 is the full set |
   | 6 | `:94-103` "parallelism is allowed" + a parallel loop | **sequential by design** — `StdioMcp` is not thread-safe |
   Cited line numbers in the old specs are ~+15 stale; verify against the file.
7. **Walk the corrected RUNBOOK end-to-end by hand once.** It is the reproduce-the-number
   artifact — if it does not work, the number is not reproducible.
8. **Reconcile the three gate statements.** `ROADMAP.md:117-121`, `PHASE0_RESULTS.md:92-100`
   (missing the "reproducible" clause, adding a non-zero-rate clause the pre-registered block
   deliberately removes), and the pre-registered block. **The pre-registered block is
   canonical**; the others point at it.
9. **State "reproducible" in the decided words:** the mint is a fresh observation and is not
   reproducible; the **ledger → report path is fully reproducible** from fixed traces —
   anyone given the trace set reproduces the identical number.
10. **De-stale the BLOCKED notices precisely.** `STAGE1_FINDINGS.md:9-12` and
    `RUNBOOK.md:5-18` say the number is blocked on finding #3. The single-instance block is
    lifted by v0.4.0; the **batch** block was real until `replay-batch-server-rooting` merged.
    Record both, in that order — the history is the evidence that the guards work.

---

## Out of scope

- Publishing anywhere external. This fills in-repo docs only.
- Re-running the mint to improve the number.

---

## Acceptance criteria

1. `PHASE0_RESULTS.md` has **zero** `TO-BE-FILLED` markers and a decision line.
2. **The violation rate never appears without its denominator anywhere in the document.**
3. **`INSTRUMENT SUSPECT`, if it fired, is reported as UNVERIFIED-of-the-experiment and never
   as a 0% violation rate.**
4. **UNVERIFIED is never rendered as PASS.**
5. The FP rate is stated with its coverage, even if unflattering.
6. Every UNVERIFIED instance traces to a named cause; the cause list is exhaustive.
7. Each TP's root cause is recorded; independence is auditable by a reader.
8. **A PIVOT is written as plainly as a PROCEED.**
9. The six RUNBOOK defects are fixed and the corrected procedure has been followed end-to-end
   by the author at least once.
10. A reader can re-derive the number from the committed ledger.

---

## Dependencies and sequencing

- **Depends on:** `mint-execution`.
- **Blocks:** the Phase-0 → Phase-1 gate, and therefore C7.
- Items 6, 8, 9, 10 (the doc corrections) are **not** blocked by the mint and can land early —
  doing so de-risks the tail, and item 7 (walking the RUNBOOK) is best done *as* Stage 1 runs.

---

## Open questions / risks

- **Auditor bias is structural**: the person auditing needs ≥3 TPs. Counterweights are the 3
  in-batch controls, the hand-replayed FAIL, and per-TP root causes.
- **If the flag count makes a full audit infeasible**, the sampling rule is revisited
  **explicitly and stated in the results**, never silently.
- **PIVOT is a legitimate, documented outcome.** The roadmap is explicit that discovering the
  premise is wrong in week 4 is a success.
