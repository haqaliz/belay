# Aspect — `mint-execution`

**Unit:** `phase0-mint-execution` · **Sequence:** 4 of 5 · **the only aspect that spends money**
**Placement:** operational — produces traces, ledgers, and corpus cases, not source

---

## Problem slice

Run the staged live mint and produce the ledger the number is computed from. This aspect is
**an operation, not a feature**: its output is data plus a written record of what was run.

**User outcome:** a committed ledger and corpus from ≥50 verifiable instances, with every
UNVERIFIED traced to a named cause and every control's disposition recorded.

---

## In scope

### Stage 1 — re-mint (~1 instance)

Re-mint `pallets__flask-4045` — the Stage-1 instance — and confirm in the wild what v0.4.0
proved in fixtures.

- **`VERIFIED_FLAGGED 1/1` must not recur** on a known-correct edit.
- **The same trace + manifests must yield an identical verdict** against the original
  workspace **pristine**, **mutated**, and **deleted**. This is the strongest available proof
  that no live state leaks into the verdict.

### Stage 2 — attrition and cost (~10 instances)

- Measure per-instance **cost** and **wall-clock**, and the **attrition rate** (how many
  instances yield ≥1 verifiable turn).
- Answer the open operational questions: does macOS TCC prompt mid-batch despite the
  sibling-dir layout? Are the pinned server versions still installable?
- **Extrapolate Stage 3's cost and compare it to the ceiling** agreed at the gate. If it
  exceeds, re-cut the target **before** Stage 3 and state the consequence for the denominator.

### Stage 3 — the mint (~65–70 instances, incl. 3 controls)

- Sequential, resumable, error-contained. Filesystem server only.
- **The pre-registered gate criteria must already be committed into `PHASE0_RESULTS.md` in an
  earlier commit** — verifiable from `git log`. Criteria written down first, mint second.
  Non-negotiable ordering.

---

## Out of scope

- The shell batch (known-contaminated; disclosed as a coverage limit).
- Parallel minting.
- Retrying instances to improve the number.

---

## Acceptance criteria

These are operational checks, verified against artifacts rather than by unit tests.

1. **Stage 1's three-way verdict identity** (pristine / mutated / deleted) is recorded with
   the actual command transcript, so it is re-runnable.
2. **Each stage gates on ≥1 genuinely verifiable turn** before the next begins.
3. **Denominator ≥50** (`VERIFIED_CLEAN + VERIFIED_FLAGGED`) after attrition.
4. **Every control's disposition is recorded.** A FAILing control **voids the mint** — the
   same standing as `INSTRUMENT SUSPECT`, escalated and reported, **never quietly excluded**.
5. **A suspiciously high rate is investigated against the controls before it is published**
   (honesty property 8). Given the defect this unit exists to fix, a near-100% rate is
   evidence of an instrument fault until proven otherwise.
6. **The checkpoint and ledger are committed**, so the ledger → report path is reproducible by
   anyone holding the trace set.
7. **Every UNVERIFIED instance traces to a named cause.**
8. **The exact commands run are recorded** — Stage 1's biggest reproducibility failure was an
   uncommitted driver script and no command transcript. Do not repeat it.

---

## Dependencies and sequencing

- **Depends on:** `replay-batch-server-rooting` (**hard** — no spend before it merges),
  `mint-entrypoints`, `instance-pool`.
- **Blocks:** `audit-and-publish`.

---

## Open questions / risks

- **Cost is unbudgeted** and this PRD sets no abort threshold without sign-off (self-critique
  gap #2). Stage 2 is the designed measurement; the ceiling must be agreed before Stage 3.
- **R10 — solo bandwidth.** ~65–70 instances plus a full hand-audit is the spike.
- **A partial mint may not be silently re-rolled.** Any decision to discard a partial run is
  disclosed — "silently re-rolling until the number looks good is precisely the dishonesty
  this project exists to prevent" (`phase0-live-mint/mint-execution/spec.md:71-74`).
- **`INSTRUMENT SUSPECT` is a legitimate outcome** and is never rendered as a clean 0%.
