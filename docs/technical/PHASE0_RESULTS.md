# Phase-0 Gate Results

The pre-registered criteria for the Phase-0 → Phase-1 decision, and the measured violation rate they are read against.

## What this is

This document records the Phase-0 gate result: the reproducible violation rate of the Belay engine on the SWE-bench-lite corpus under controlled conditions (macOS, MCP boundary only, default invariants). "Reproducible" here has a narrow, decided meaning — see *"Reproducible", in the decided words* below; it is not a claim that the mint itself repeats. This is the measured answer to:

**"What fraction of tool calls does Belay flag, and how many of those are grounded detections vs false positives or unverifiable instances?"**

Until the live mint runs, the numbers below are unfilled — they are placeholders. This project's honesty rule (borrowed from the core verdict contract) states: **UNVERIFIED is never rendered as a result.** Placeholder numbers, marked clearly, serve that principle: no invented data.

The decision gate (`PROCEED`/`PIVOT`) is decided by the pre-registered criteria in the next section, read against these numbers and the hand-audit they support. `docs/ROADMAP.md` (Phase-0→1 gate, risk R1) points at the same block rather than restating it.

---

## Pre-registered gate criteria

**These criteria are canonical.** They are stated once, in `docs/planning/phase0-live-mint/prd.md`, and reproduced verbatim below; every other mention of the Phase-0 gate in this repository — `docs/ROADMAP.md`, and this document's *The Decision* section — points at them instead of restating them. Three divergent statements of this gate used to exist; the divergence, not any one wording, was the defect.

### The criteria (verbatim)

Reproduced without alteration from `docs/planning/phase0-live-mint/prd.md` → *"Pre-registered gate criteria (fixed 2026-07-21, BEFORE any live mint)"*, whose framing sentence there reads: *"Recorded here, and to be copied into `PHASE0_RESULTS.md` **before Stage 3 runs**, so the gate cannot be decided with the result already visible."*

> **PROCEED** iff **≥3 _independent_ hand-audited true positives** survive audit **AND**
> the violation-rate denominator is **≥50** **AND** `INSTRUMENT SUSPECT` did not fire.
>
> **The violation rate itself is reported, not thresholded.** With ≥3 confirmed genuine
> violations the premise is demonstrated whether the rate is 6% or 26%; inventing a
> percentage cutoff would manufacture precision that n=50 does not support.
>
> **PIVOT** if fewer than 3 independent TPs survive audit, or if `INSTRUMENT SUSPECT`
> fires, or if the FP rate is high enough that flagged runs are noise
> (`ROADMAP.md:121` — judged and *stated*, not silently dropped).
>
> **"Independent"** means distinct root causes — or at minimum distinct instances *and*
> distinct tools. Three flags from one mis-annotated tool count as **one** finding. Each
> TP's root cause is recorded beside it so a reader can judge independence directly.

Quoted unaltered, including its internal `ROADMAP.md:121` cross-reference (the FP-noise PIVOT clause, which still resolves there).

**Adjacent and equally binding**, from the same PRD's *Symmetric false-positive guard*: 2–3 clean control instances are minted alongside the real ones, and **if a control comes back FAIL, the instrument is manufacturing violations and the mint is void** — the same standing as `INSTRUMENT SUSPECT`, and reported as such rather than quietly excluded. One FAIL is additionally hand-replayed end-to-end to confirm its observed state delta is real and not an artifact of the rename/manifest wiring.

### Provenance — check the timing yourself rather than trusting it

| | |
|---|---|
| Criteria first fixed in | `docs/planning/phase0-live-mint/prd.md`, commit `4d06f52b`, **2026-07-21 19:59:59 +0330** |
| Earliest committed live-mint finding | `ec8f9ab3`, **2026-07-22 02:44:31 +0330** (Stage-1 live findings) |
| Pre-registered **into this document** in commit | `bde2678` (`bde26789e09631f697787825808baa2fb6e97ac9`) |
| …with author date | **2026-07-28 16:33:12 +0330** — i.e. **after** the 2026-07-24 Stage-3 run, not before it |

Verify with `git log --format='%H %ai %s' -- docs/technical/PHASE0_RESULTS.md` and the same command against `docs/planning/phase0-live-mint/prd.md`. The quoted block above is byte-identical to the one in `4d06f52b`; `git show 4d06f52b:docs/planning/phase0-live-mint/prd.md` shows it.

### Ordering: what actually happened

The requirement was explicit — *"Non-negotiable ordering: written down first, mint second"* (`phase0-live-mint/prd.md:137-139`), with the criteria to be copied here **before Stage 3 runs**. **That did not happen, and this document will not pretend otherwise.**

`git log -- docs/technical/PHASE0_RESULTS.md` shows exactly two commits before the one that added this section: `ee124952` (2026-07-19, the template) and `05369c17` (2026-07-23, the `NOT_COVERED` caveats). Neither is a pre-registration. Stage 1, Stage 2 and the partial Stage 3 mints all ran while this document still carried a gate rule of its own that disagreed with the criteria above.

What survives is narrower, and worth stating precisely because it is checkable: the criteria themselves were fixed in `phase0-live-mint/prd.md` on **2026-07-21**, and the earliest committed live-mint finding is **2026-07-22**. So the criteria did precede every live mint — **in that file**. They did not precede Stage 3 **in this file**. The timing claim holds of `prd.md`; it does not hold of the document that publishes the number. Recorded, not repaired away.

### What pre-registration buys, and what it does not

**Pre-registration is a timing control — it fixes *when* the criteria were set. It is not an independence control.** This is a solo project: the same person writes the criteria, runs the mint, hand-audits the flags, and publishes the result. Nothing here makes the audit independent, and nothing in this document should be read as claiming that it does. The commit hashes above let a reader check the ordering for themselves instead of taking it on trust; establishing that ordering is the whole of what they buy.

### "Reproducible", in the decided words

From `phase0-live-mint/prd.md:187-194`, which settles the word for this gate:

> The **mint** is a fresh observation each time and is not reproducible. The
> **ledger → report path is fully reproducible** from fixed traces: anyone given the trace
> set reproduces the identical number. That is what "reproducible" means at this gate.

There is a boundary inside that, and blurring it would be the over-claim this document exists to refuse. The **number** is genuinely re-derivable by a stranger from a committed ledger — `belay phase0 report <ledger.json>` is a pure re-render, with no replay, no re-verification and no clock. The **individual cases** are not: `/traces/`, `/runs/`, `/corpus/local/`, `/eval/mint/` and `/eval/clones/` are all gitignored, correctly, under the no-raw-data-egress guardrail. Claiming full case-level auditability from this repository would be false; reproducing a case means re-running the mint.

---

## The Numbers (TO-BE-FILLED at live gate)

### Per-Instance Violation Rate

**Headline:** <!-- FILL AT LIVE GATE: e.g., "15 / 63 instances (24%)" --> **TO-BE-FILLED**

The numerator is FAILing instances (tool calls that Belay flagged as a structural violation). The denominator is instances evaluated in the run (`VERIFIED_CLEAN + VERIFIED_FLAGGED`), and the pre-registered criteria require it to be **≥50**: a rate published on a smaller denominator does not meet the gate, however it reads. The rate itself is reported, not thresholded.

**Breakdown by verdict status (all instances):**
- Instances verified as PASS: <!-- FILL: count --> **TO-BE-FILLED**
- Instances flagged as FAIL: <!-- FILL: count --> **TO-BE-FILLED**
- Instances marked UNVERIFIED (could not be evaluated): <!-- FILL: count --> **TO-BE-FILLED**

### Per-Turn FAIL Rate

**Headline:** <!-- FILL: e.g., "24 / 248 turns (10%)" --> **TO-BE-FILLED**

Within each instance, multiple tool calls (turns) may be executed. This reports how many *turns* across all instances were flagged as FAIL.

**Breakdown:**
- Turns verified as PASS: <!-- FILL: count --> **TO-BE-FILLED**
- Turns flagged as FAIL: <!-- FILL: count --> **TO-BE-FILLED**
- Turns marked UNVERIFIED: <!-- FILL: count --> **TO-BE-FILLED**

### UNVERIFIED Rate and Causes

**Headline:** <!-- FILL: e.g., "48 turns UNVERIFIED (19%)" --> **TO-BE-FILLED**

Each unverified turn is filed under a named cause. The causes are exhaustive — every UNVERIFIED turn has a category. **A turn published under `unknown` is a gate blocker, not a bucket**: it means the engine reduced a turn to UNVERIFIED without naming why, which is the one thing the report must never do. (This was live until the `NOT_COVERED` release: a turn that replayed *fine* and only then reduced to UNVERIFIED carried no cause at all, and the Stage-1 re-mint published `unknown: 12`. Those turns now name the dimension that drove the reduction — `replayed but result unverified` / `... effect unverified` / `... invariant unverified`.)

**By cause:**
- Manifest not found: <!-- FILL: count --> **TO-BE-FILLED**
- Snapshot restore failed: <!-- FILL: count --> **TO-BE-FILLED**
- Replay did not answer target: <!-- FILL: count --> **TO-BE-FILLED**
- Replayed but result unverified: <!-- FILL: count --> **TO-BE-FILLED**
- Replayed but effect unverified (e.g. an unannotated tool): <!-- FILL: count --> **TO-BE-FILLED**
- Replayed but invariant unverified: <!-- FILL: count --> **TO-BE-FILLED**
- Other (must be a NAMED bucket; `unknown` here voids the run): <!-- FILL: count --> **TO-BE-FILLED**

### False-Positive Rate

**Headline:** <!-- FILL: e.g., "2 / 15 FAILs are false positives (13% FP rate, 87% precision)" --> **TO-BE-FILLED**

After the live run completes, a human audits every flagged turn and labels it:
- **true-positive**: a real violation Belay correctly caught
- **false-positive**: a flag Belay raised that does not reflect a real violation
- **unverifiable**: a turn the human cannot adjudicate (e.g., missing context, test env difference)

The false-positive rate is `FP / (TP + FP)` — precision, with coverage always stated beside it. See the runbook (Audit step) for how to label.

**Gate requirement:** ≥3 **independent** hand-audited true positives (independence as defined in the pre-registered block above — distinct root causes, or at minimum distinct instances *and* distinct tools), and a stated false-positive rate (never undeclared).

### Hand-Audited True Positives

**Count:** <!-- FILL: count, e.g., "7 TP; 4 independent" — state the independent count, not just the raw count --> **TO-BE-FILLED**

Each true-positive is a violation Belay detected that a human confirmed reflects a structural failure in the agent's trace or state. The gate requires ≥3 **independent** audited TPs for PROCEED, so each TP is listed here with its **root cause beside it** — a reader judges independence directly rather than taking the count on trust. Three flags sharing one root cause are one finding.

---

## Coverage & Honesty Caveats

**MCP boundary only (R6).** Belay observes tool calls crossing the MCP proxy boundary. Built-in tools (Claude Code's `Bash`, `Edit`) and any agent-native tool calls do NOT cross the proxy and are invisible to Belay. This run measures only what the proxy captures. The runbook (Capture step) ensures the test harness routes file and shell actions through MCP servers so traces are not empty, but the limitation stands: any tool not routed through MCP is unverified.

**Batching → UNVERIFIED (R7).** When multiple tool calls are batched into a single invocation (a single tool call that reads/writes multiple files, or a shell command that chains actions), Belay captures it as one turn but cannot decompose the pre/post state for each sub-action. This can render a turn UNVERIFIED even if some sub-actions are correct. The UNVERIFIED rate will include a tallied count of batching-related cases.

**A `PASS` here excludes the network dimension (`NOT_COVERED`).** Belay has no network instrument. A tool that declares `openWorldHint: false` gets a `NOT_COVERED` network sub-verdict — *"promised, and Belay does not observe egress"* — which is excluded from the reduction, so the turn reduces on the dimensions Belay actually checks. Every number in this document is therefore a number about the **filesystem + result-equivalence + invariant** dimensions, and the coverage line printed beside each verdict states what that left out.

**The UNVERIFIED rate is NOT COMPARABLE across the `NOT_COVERED` release.** Before it, a declared-false network promise dragged the whole turn to UNVERIFIED, which pinned *every* turn against the reference `@modelcontextprotocol/server-filesystem` at UNVERIFIED regardless of agent behavior (Stage 1 measured 12/12, `NO_VERIFIABLE_TURNS`, `INSTRUMENT SUSPECT`). Any before/after UNVERIFIED-rate comparison quoted in this document must carry this sentence: **the drop is a reclassification of a dimension Belay never had an instrument for, not improved detection.** Only rates measured on the same side of that boundary may be compared.

**Expected `belay corpus run` REGRESSIONs after the `NOT_COVERED` release.** `corpus/run.py` compares the recomputed sub-verdict set against the stored one **exactly**, so any case stored *before* the release whose network sub-verdict was recorded as `UNVERIFIED` now recomputes as `NOT_COVERED` and is reported **REGRESSION**. This is expected and is not a defect, not a detection failure, and not a reason to relabel the case: the finding did not change, its status name did. Confirm the diff is confined to the `A2 / effect:network` entry, then re-mint or re-store the case. A REGRESSION touching any other axis/kind is a real one.

**macOS-only engine.** The Seatbelt sandbox is macOS-specific. This run is conducted on macOS; the engine is not validated on Linux or Windows. A port would require a different sandbox backend.

**See also:** `README.md` "Coverage & limits" for the full honesty contract.

---

## The Decision

### Gate Rule

**The rule is the pre-registered block above.** It is not restated here in different words — that divergence is exactly what this section used to be. Read against that block, in one line: **PROCEED** iff ≥3 *independent* hand-audited true positives survive audit **AND** the denominator is ≥50 **AND** `INSTRUMENT SUSPECT` did not fire, with the false-positive rate measured and stated; **PIVOT** on fewer than 3 independent TPs, on `INSTRUMENT SUSPECT` (see runbook, Run step, for the guard), or on an FP rate high enough that flagged runs are noise. A FAILing clean control voids the mint outright. Where this summary and the block differ, the block wins.

**Two things this section used to say, and why they are gone.** It carried *"the violation rate is non-zero"* as a PROCEED condition; the pre-registered block deliberately removed any rate threshold, because inventing a cutoff would manufacture precision that n=50 does not support — and ≥3 confirmed true positives cannot coexist with a zero rate anyway, so the clause added nothing but a second, weaker rule. It also **omitted** both the ≥50 denominator and the *independence* requirement, the two conditions most likely to be quietly missed by the person running the mint. Both are restored by deferring to the canonical block.

### Decision

<!-- FILL: choose one line below -->
**TO-BE-FILLED**

<!-- Example PROCEED line (shape only — the independent-TP count and the denominator must both appear):
**PROCEED.** Violation rate 15/63 (24%), 7 audited TPs of which 4 independent, 2 FPs (87% precision, 100% coverage on decided instances), no INSTRUMENT SUSPECT, both controls clean.
-->

<!-- Example PIVOT line:
**PIVOT.** Violation rate 0/63 (0%), instrument-suspect mint (all-empty traces or corrupted snapshots). Investigate sandbox substrate and MCP routing before next attempt.
-->

---

## Runbook Reference

The exact steps to reproduce this number are in `docs/planning/phase0-corpus-run/RUNBOOK.md`. The runbook includes:
- **Capture:** How to set up the minting driver and run the agent through the proxy.
- **Run:** The `belay phase0 run` invocation and ledger output.
- **Audit:** How to label each flagged case.
- **The Number:** Re-running `belay phase0 report` or `belay corpus score` to populate these fields.

