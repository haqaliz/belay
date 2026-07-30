# Aspect — `ledger-reporting-honesty`

**Unit:** `phase0-reverify-banked` · **Order: 2 (of 4 after consolidation).**
**Covers PRD must-haves M-2, M-3, M-4.**

> **Consolidation note.** The PRD proposed `ledger-detector-identity`, `ledger-merge-dedup` and
> `control-partition` as three aspects. They are built here as **three phases of one aspect**,
> because all three modify `src/belay/phase0/ledger.py`, `report.py` and `cli.py`; as separate
> aspects they could not be built in parallel anyway, and splitting them across handoffs would
> produce merge conflicts rather than isolation. The three concerns stay independently testable.

---

## Problem slice

The Phase-0 report is about to be used to re-derive a published number, and it cannot currently
express three things that number depends on.

**1 · A ledger does not know which detector produced it.** `RunLedger` serializes nine fields
(`ledger.py:92-100,165-240`); none names a rule, scope, config, or code version. The four
ledgers in `runs/` were produced by the **replaced** `tests/` read-only rule and are
indistinguishable, *by reading them*, from one produced by today's `no-assertion-weakening`. That
is the exact confusion this unit exists to end.

**2 · Two ledgers cannot be combined.** There is no merge and no dedup anywhere
(`ledger.py`, `report.py`, `cli.py:1258-1273`). `RunLedger.instances` is a bare list and every
aggregate is computed over it, so a naive concatenation double-counts every shared `trace_id`.
The banked data needs this: **24 captures over 17 distinct trace ids**, with `flask-4045` minted
3× and five instances minted 2× (`s2/batch ∩ s3/batch`).

**3 · A control is counted as an ordinary instance.** Controls exist only as a `control__` id
prefix (`eval/instances/controls.py:89-150`); `report.py` has no control branch, so a control
folds silently into the headline violation rate. Worse, the meaning of a FAILing control is
**context-dependent** and nothing encodes that: in a *fresh mint* it voids the mint; in a
*re-verification of banked captures* it is a **detector false positive** — a precision signal,
which is the very thing this unit measures. Conflating them would manufacture a void.

## User outcome

A Phase-0 report states what produced it, over what population, with controls kept out of the
headline — so a reader can tell a current number from a stale one, and cannot mistake a
re-verification for a gate run or a precision signal for a void.

## In scope

**R1 · Detector identity on the ledger (M-2).** `RunLedger` carries an optional detector
identity: the A1 rules and scopes in force, plus a code identity. Absent ⇒ **`unrecorded`** on
every surface — never rendered, defaulted, or implied to be current. Follow the existing
optional-field precedent (`not_covered_turns`, `ledger.py:57-63,214-217`): field-presence
back-compat, no schema-version bump, old ledgers still load.

**R2 · Merge with an explicit dedup rule (M-3).** A function merges N ledgers into one
population keyed on `trace_id`, applying **worst-verdict-wins** (D2): an instance is violating if
**any** of its captures flagged. Both denominators are reported — **instances** (headline) and
**captures** (alongside, D1) — and every instance whose captures **disagree** is named in the
output. Aggregates must never double-count.

**R3 · Controls partitioned (M-4).** Controls are excluded from the headline rate and reported in
their own block with their own counts. A FAILing control is labeled, in this context, a
**detector false positive**, explicitly *not* "mint void" — with the distinction stated in the
output, not just in docs. If no id matches the convention, the report says "no controls in this
population" rather than implying there were none to run.

## Out of scope

- **Any change to a verdict, on any axis.** This aspect changes reporting and aggregation only.
- **The A1 rule**, the case schema, the ingestion trigger, `verdict.reduce`, `NOT_COVERED`.
- **Running the measurement** — that is `reverify-measurement`, under the freeze protocol.
- **Re-deriving or correcting published numbers** — that is `record-correction`.
- **Reconciling the parked record defects** (the `16`-denominator composition, the `0% UNVERIFIED`
  headline, "5 distinct runs") — deliberately parked (PRD D5).
- **Importing anything from `eval/`** into `src/belay/`. The `control__` prefix is a documented
  convention duplicated as a constant, not a dependency.

## Acceptance criteria (test-first)

**Detector identity**
1. A ledger written by a run records the A1 rules and scopes in force; a round-trip through
   `to_json`/`from_json` preserves them exactly.
2. An **existing ledger with no detector key loads**, and reports as **`unrecorded`** — never as
   the current detector, never as empty-and-therefore-fine. Pinned against a real fixture shaped
   like `runs/s2.json`.
3. `belay phase0 report` on a detector-less ledger prints `unrecorded` prominently. A reader
   cannot mistake it for a current-detector result.

**Merge and dedup**
4. Merging ledgers that share a `trace_id` yields **one** record for it; `violation_denominator()`
   counts it **once**. (A naive concat double-counts — that is the failure this pins.)
5. Worst-verdict-wins: an instance `VERIFIED_CLEAN` in one capture and `VERIFIED_FLAGGED` in
   another merges to **flagged**, and appears in `violating_instances()`.
6. Disagreeing instances are **named** in the report — the reduction is auditable, not silent.
7. Both denominators appear: instances (headline) and captures (alongside), each labeled.
8. Merging disjoint ledgers is order-independent and equals the union.

**Controls**
9. A `control__*` instance is **excluded** from the headline violation rate and its denominator.
10. Controls appear in their own block with their own pass/fail counts.
11. A **FAILing control** is reported as a **detector false positive**, and the output explicitly
    says this is *not* a mint-void condition in a re-verification.
12. A population with no controls says so explicitly.

**Boundary**
13. Every existing `phase0` test still passes unchanged — the new field, the merge, and the
    control partition are all additive. Default behaviour for a single-ledger, control-free run is
    byte-identical to today.

## Dependencies and sequencing

- **Depends on:** `corpus-collision-guard` (done — a safe re-run is a precondition for using any
  of this against real captures).
- **Blocks:** `reverify-measurement`, and through it `record-correction`.
- **Touches:** `src/belay/phase0/{ledger,report}.py`, `src/belay/cli.py`, plus
  `tests/test_phase0_{ledger,report,cli}.py`.

## Open questions / risks

| Item | Assessment |
|---|---|
| **What is "code identity"?** | Leaning the rule names + scopes (the semantic identity, which is what actually decides a verdict) plus an optional caller-injected version string. **A git sha must not be read by the library** — that would be a clock/environment read inside a deterministic path. Decide in the plan; injected-by-CLI is the safe shape. |
| **Worst-verdict-wins inflates a violation rate** | True, and accepted (D2): it is conservative in the direction of not hiding a violation. Mitigated by R2's disagreement list, so a reader can always see what the reduction did. |
| **`ERRORED` in one capture, `CLEAN` in another** | "Worst" must be defined over the *violation* question, not over "badness": a capture that errored is not evidence of a violation. Proposal: an instance is violating iff **any** capture flagged; it is in the denominator iff **any** capture is CLEAN or FLAGGED. Pin both in tests. |
| **Control prefix is a convention, not a guarantee** | An instance genuinely named `control__*` that is not a control would be mis-partitioned. Accepted: it is the same convention the mint already uses, and the report names which ids it treated as controls. |
