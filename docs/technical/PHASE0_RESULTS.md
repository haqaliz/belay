# Phase-0 Gate Results

The violation rate that decides PROCEED vs PIVOT on the Phase-0 → Phase-1 transition.

## What this is

This document records the Phase-0 gate result: the reproducible violation rate of the Belay engine on the SWE-bench-lite corpus under controlled conditions (macOS, MCP boundary only, default invariants). This is the measured answer to:

**"What fraction of tool calls does Belay flag, and how many of those are grounded detections vs false positives or unverifiable instances?"**

Until the live mint runs, the numbers below are unfilled — they are placeholders. This project's honesty rule (borrowed from the core verdict contract) states: **UNVERIFIED is never rendered as a result.** Placeholder numbers, marked clearly, serve that principle: no invented data.

The decision gate (`PROCEED`/`PIVOT`) depends on this number and the audit it supports. See `docs/ROADMAP.md` Phase-0→1 gate and risk R1.

---

## The Numbers (TO-BE-FILLED at live gate)

### Per-Instance Violation Rate

**Headline:** <!-- FILL AT LIVE GATE: e.g., "15 / 63 instances (24%)" --> **TO-BE-FILLED**

The numerator is FAILing instances (tool calls that Belay flagged as a structural violation). The denominator is instances evaluated in the run. This is the top-line metric the gate reads.

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

**Gate requirement:** ≥3 hand-audited true positives, and a stated false-positive rate (never undeclared).

### Hand-Audited True Positives

**Count:** <!-- FILL: count, e.g., "7 TP" --> **TO-BE-FILLED**

Each true-positive is a violation Belay detected that a human confirmed reflects a structural failure in the agent's trace or state. The gate requires ≥3 audited TPs for PROCEED.

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

**PROCEED if:**
1. The violation rate is non-zero (at least one real violation detected), AND
2. The corpus includes ≥3 hand-audited true positives, AND
3. The false-positive rate is measured and stated (never omitted).

**PIVOT if:**
1. The violation rate is ~0 (no violations, or all UNVERIFIED → no measurable signal), OR
2. The corpus does not reach ≥3 audited TPs, OR
3. An instrument-suspect mint is observed (see runbook, Run step, for the guard).

### Decision

<!-- FILL: choose one line below -->
**TO-BE-FILLED**

<!-- Example PROCEED line:
**PROCEED.** Violation rate 15/63 (24%), 7 audited TPs, 2 FPs (87% precision, 100% coverage on decided instances).
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

