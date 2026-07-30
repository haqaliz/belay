# PRD — `phase0-reverify-banked`

**Unit:** re-verify the banked Phase-0 captures under the shipped A1 rule, and correct the
published record. **Branch:** `feat/phase0-reverify-banked/aliz` · **Base:** `master` @ `24815de`
(v0.10.0) · **Owner:** aliz · **Date:** 2026-07-30.

**Inputs:** `docs/planning/_card/issue.md` (brief), `docs/planning/_card/understanding.md`
(four-agent dig). Interview decisions recorded in §3.

---

## 1. Problem Statement

**Two facts that are individually fine and jointly a defect.**

1. v0.10.0 replaced the A1 default. It was `{scope: b"tests/", rule: "read-only"}`; it is now
   **`no-assertion-weakening`** over any `tests` or `testing` path segment
   (`src/belay/verify/invariants.py:615`).
2. Every published Phase-0 number was produced by the **old** rule — `4/16`,
   `precision 0.00` (0 TP / 7 FP), `3/93`, the `0% UNVERIFIED` headline
   (`docs/technical/PHASE0_RESULTS.md`), plus the four ledgers in `runs/`.

So **the repo's published measurement no longer describes the code it ships**, and the
project's credibility rests on exactly that correspondence. Separately, the new rule has
**never been measured on data it was not fitted to**: it was designed against the 7 negative
fixtures and validated on one positive instance (`pytest-5227`), which `README.md:183` states
honestly as *"not yet measured"*.

**The evidence this is worth doing now.** `docs/ROADMAP.md:160` already names the action —
*"fix the instrument and re-measure"* — and the instrument is now fixed.
`docs/planning/phase0-mint-resilience/prd.md:290` recorded the sequencing rule: *"decide after
the audit gate — if the audit suggests a PIVOT, do not spend 11 hours first."* The alternative
unit (`subscription-model-client` → funded re-mint) costs ~11 hours of provider time under a
detector of unknown held-out precision. This unit costs **397 replayed turns, offline, no key**,
and tells us whether that spend is justified.

**Who has the problem.** The ICP directly: an engineer who must answer *"did this run actually
do the right thing?"* and whose trust in the answer depends on Belay's own numbers being
attributable to Belay's own current code. Immediately, the owner, who must decide whether to
fund a re-mint.

---

## 2. Goals & Success Metrics

**Primary goal:** produce one comparable, honestly-denominated measurement of the shipped A1
rule over all banked captures, and align the record with it.

| # | Metric | Target |
|---|---|---|
| M1 | Banked captures re-verified under one rule | **24 / 24** captures, **397** turns, 0 skipped silently |
| M2 | Per-instance violation rate published **with** its denominator | reported over **15** unique non-control instances, never as a bare % |
| M3 | Per-capture rate reported alongside | n=**24**, so dedup never hides an observation |
| M4 | UNVERIFIED reported **by named cause** | every UNVERIFIED turn has a cause; `unknown` count is **0** |
| M5 | Controls partitioned out of the headline | 2 captured controls reported separately, never folded into the rate |
| M6 | The 7 human labels intact after the run | byte-identical `human_label`/`root_cause`, verified |
| M7 | Every published stale number carries a correction | inventory of §7 fully addressed, none silently edited |
| M8 | Measurement runs **once**, under the freeze protocol | rule/tooling commit precedes output commit; output committed verbatim |

**Explicit non-metric:** *the violation rate is reported, not thresholded.* No target value.
A 0% result and a 40% result are both successful outcomes of this unit; only an
unattributable or hidden number is a failure.

### 2.1 Pre-registered reading rule — fixed BEFORE the run

**PROPOSED, pending owner approval at the review gate. It must be committed before the
measurement runs, or it is post-hoc.** This unit exists to inform one decision — fund the
re-mint, or fix the detector again — and this repo's credibility rests on deciding the reading
before seeing the number.

| Observed | Reading | Action |
|---|---|---|
| **≥1 flagged turn that is a plausible weakening** on an instance the rule was **not** fitted on | the rule fires on held-out data | **Fund the re-mint** (`subscription-model-client` next). Adjudication of the flags is a follow-on, not a precondition. |
| **Flags, but all on `pytest-5227`** (fitted-on) or all clearly benign in payload | not yet evidence of held-out sensitivity | Report honestly; decide re-mint vs another detector pass on the payloads. |
| **Zero flags across all 24 captures** | **AMBIGUOUS, and must be published as ambiguous** | See the blindness clause below. |
| **UNVERIFIED > 25% of turns**, or `INSTRUMENT SUSPECT` fires | this is an instrument report, **not** a rate | Do **not** publish a violation rate. Fix the instrument first. |
| **A control FAILs** | detector false positive (**not** "mint void" — D-M4) | A precision finding: report it, and it argues against funding the mint. |

**The blindness clause.** A zero-flag result does **not** distinguish *"the captures contain no
weakenings"* from *"the rule was over-corrected into blindness"*. The only in-population
evidence against blindness is `pytest-5227` turns 11/13 — **which the rule was fitted on**, so
it cannot serve as that control. Therefore a zero-flag result is published as **"no held-out
positive observed; sensitivity unconfirmed"**, never as "the data is clean" and never as
evidence for or against R1. Establishing a genuine held-out positive control is named as the
follow-on it is, not papered over.

**What success does NOT mean.** This unit **cannot** produce a PROCEED. The pre-registered
clause requires a denominator **≥50** (`docs/planning/phase0-live-mint/prd.md:58-71`), and that
clause counts *instances minted*, not the rule that scored them — it is detector-independent, so
no re-verification of banked data can ever satisfy it. **R1's quantitative form stays untested.**

---

## 3. Interview decisions (settled 2026-07-30)

| # | Decision | Rationale |
|---|---|---|
| D1 | **Per-instance headline (n=15), per-capture (n=24) alongside** | matches the gate's per-instance framing and the published rate's shape, while hiding no observation |
| D2 | **Worst-verdict-wins on duplicate mints, disagreements listed by name** | matches existing `violating_instances` semantics and is conservative in the safe direction; naming disagreements keeps the reduction auditable |
| D3 | **Detector identity becomes an optional field on the ledger schema** | a ledger becomes self-describing; the 4 existing ledgers must read back as **`unrecorded`**, never as *current* |
| D4 | **The `add_case` collision defect is fixed here, with tests** | it is a real product defect discovered by this unit, and leaving it armed makes every future re-verify hazardous |
| D5 | **Record correction stays minimal** (not asked — repo convention) | one correction per finding; `README.md:183` updated; the parked Open Items of `PHASE0_RESULTS.md` stay parked with a pointer |

---

## 4. Requirements

### Must-have

**M-1 · Collision safety before anything else runs.** `add_case` must not damage an existing
case. Today: `shutil.copytree` without `dirs_exist_ok` raises `FileExistsError` **after**
`trace.jsonl` has already been truncated (`corpus/add.py:272,279`); the error is not a
`ValueError` so `runner.py:261` misses it, `run_batch`'s catch-all marks the **whole instance**
`ERRORED` (`runner.py:147`), and `ERRORED` is excluded from `violation_denominator()`
(`ledger.py:114-120`) — a silently shrunken denominator that can trip `instrument_suspect()`,
i.e. **a fake PIVOT**. Required: detect an existing case id **before any write**, never
truncate on the way to failing, and surface it as a named, runner-handled outcome — never as a
lost instance. A human label must be impossible to overwrite by re-ingestion.

**M-2 · Detector identity on the ledger** (D3). A `RunLedger` records the A1 rules and scopes in
force, plus a code identity. Absent ⇒ renders and serializes as **`unrecorded`**; a stale ledger
must never render as current, on any surface (`phase0 report` included).

**M-3 · Merge + dedup across ledgers** (D1, D2). Merge N ledgers into one population keyed on
instance; worst-verdict-wins; every duplicated instance whose mints disagree named in the
output. Aggregates must not double-count (`RunLedger.instances` is a bare list, so a naive
concat corrupts every aggregate). Both denominators reported: instances (15) and captures (24).

**M-4 · Controls partitioned** (M5). Controls are identified today only by the `control__` id
prefix (`eval/instances/controls.py:89-150`) and `report.py` has no control branch, so they
currently fold into the headline rate. Required: controls excluded from the headline, reported
in their own block, and — **specific to a re-verification** — a FAILing control labeled a
**detector false positive**, explicitly *not* "mint void". The void condition belongs to a fresh
mint; conflating them would manufacture a void from a precision signal.

**M-4a · The run compounds the corpus, it does not discard.** `CAPABILITY_ROADMAP.md` C6
requires every capability to add cases. Newly flagged turns must therefore be ingested into a
**fresh, preserved** corpus directory (e.g. `corpus/reverify-YYYYMMDD/`) — **never** the existing
`corpus/local/` (which holds the only 7 human labels) and **never** a throwaway temp dir. Cases
land `pending`; adjudication is the follow-on. If the run flags nothing, the honest report is
"no new cases", not a silently empty corpus.

**M-5 · The measurement, run once, frozen.** A committed script pinning the exact invocation
(absolute trace dirs, the absolute `--server` path, the preserved fresh `--corpus-dir` of
M-4a), run **once**, its
raw stdout committed verbatim in the following commit, naming the freeze hash — per
`invariant-rule-wiring/acceptance.sh`. Deterministic and offline: no network, no key, and that
must be **pinned by a test**, not assumed.

**M-6 · The record correction** (D5, M7). Following the established convention: a warning banner
above stale numbers; original sentences kept with corrections appended beside them; a literal
*"what changed, and what did not"* table; **evidence grade stated** (execution vs human
adjudication); an explicit list of what was deliberately left untouched and why. Shipped
`CHANGELOG` entries are never rewritten — the correction lands in the next entry.
`README.md:183` is updated to describe the new status precisely.

### Should-have

- **S-1** `--no-ingest` on `phase0 run`, so a pure measurement can write no corpus cases at all
  (today the only lever is redirecting `--corpus-dir`).
- **S-2** The 7 s3 captures that appear in **no** ledger (`s3-partial.json` covered only 5 of 12)
  are included, and the write-up says so — the re-verified population is *larger* than the
  published one.
- **S-3** `CLAUDE.md`'s stale *"1005 tests"* corrected (measured: **1198 passed, 1 skipped,
  1 deselected**).

### Nice-to-have

- **N-1** A reusable `eval/scripts/` entry point for future re-verifications.
- **N-2** Per-instance turn-count table in the report, for cross-mint comparison.

---

## 5. Technical Considerations

**Capability:** hardens **C6/Phase-0 measurement machinery** (`src/belay/phase0/`,
`src/belay/corpus/`). No new capability; no C7/C8/C9 surface.

**Verdict impact: none.** This unit **measures** A1 and changes no verdict semantics — not A1's
rule, not A2, not A3, not `verdict.reduce`, not the `NOT_COVERED` boundary. The A1 rule is
deliberately untouchable here: it is the object of measurement, and editing it mid-measurement
is precisely what the freeze protocol prevents. `UNVERIFIED` paths are unchanged and must be
published by named cause.

**Feasibility, verified (not assumed).** `belay phase0 run` accepts an absolute `trace_dir`
(`runner.py:131`, `:81-90`); `--server` is a `REMAINDER` passthrough whose literal
`{workspace}` token is substituted per-trace with that trace's own recorded root
(`cli.py:1835-1846`), which is what lets one command verify a heterogeneous batch. The server
entrypoint exists (28,217 bytes, ESM), `node` is v22.21.1, and all 24 recorded `source_root`
paths exist today. Manifest count == turn count in all 24 captures.

**Data locality / no-egress.** Captures (4.7 GB) and the corpus live in two **other** worktrees,
gitignored, embedding absolute paths; they are not movable. Referenced by absolute path only.
Neither `feat-verdict-coverage-status` nor `feat-phase0-mint-execution` may be removed. Only the
ledger, the report output, and the write-up are committed.

**Guardrails.** No agent framework; no LLM judge (re-verification is pure re-execution, zero
model calls; the zero-LLM AST guard over `src/belay/verify/` is untouched); no raw-data egress;
UNVERIFIED never rendered as PASS.

---

## 6. Risks & Open Questions

| Risk | Assessment |
|---|---|
| **Read as a gate run** | **The top risk.** At n=15 vs ≥50 a PROCEED is mechanically impossible. Mitigation: M2 + a first-paragraph statement in the write-up; the ≥50 clause is detector-independent and must be quoted as such. |
| **Fake `INSTRUMENT SUSPECT`** (R6-adjacent) | The collision path can shrink the denominator to a false zero. Mitigation: M-1 lands **first**, before any run against the real corpus. |
| **Destroying the only 7 human labels** | The backup holds only flat `case.json` files — labels, **not** replayability. Mitigation: a **fresh preserved** `--corpus-dir` (M-4a, never `corpus/local/`) **and** M-1; M6 verifies labels byte-identical afterwards. |
| **R1 — the premise** | Untouched. This unit does not test R1; it decides whether the test is worth funding. A near-zero result here is **not** evidence for R1 at n=15. |
| **New-rule precision still not properly measurable** | Likely. 15 instances yields a *shape*, not a precision figure, and precision needs **human labels** on whatever it flags — adjudication is out of scope here. If it flags nothing, the honest report is "0 FP observed, 0 TP observed, precision n/a", never "precision 1.00". |
| **Cross-root turns degrade to UNVERIFIED** | Only `s1` was spot-checked for single-root-relative args. Degrades safely (UNVERIFIED, not false PASS) and would show in the by-cause line. |
| **Scope creep into parked defects** | The `16`-denominator inconsistency, the `0% UNVERIFIED` headline, and the "5 distinct runs" ambiguity are already parked with reasons (§7 of the understanding note). D5 keeps them parked with a pointer. |
| **R10 — solo bandwidth** | Six aspects, four of them small engine changes. Aspects are independently shippable; the measurement is one command. |

**Open questions**

1. **Does anything flagged here get hand-adjudicated?** Precision needs labels. Proposal:
   **out of scope** — this unit reports what fired, with payloads, and adjudication is a
   follow-on (that is what created the 7 labeled cases last time).
2. **Are the re-verified ledgers committed?** `runs/` is gitignored. The verbatim report output
   is committed (M-5); whether the JSON ledgers are is unresolved — leaning **no**, to keep the
   no-egress boundary crisp, with the report as the artifact.
3. **Does `pytest-5227` stay in the population?** It is the instance the rule was validated on,
   so it is **not** held-out. Proposal: include it, and mark it as fitted-on in the write-up so
   it never reads as independent confirmation.

---

## 7. Out of Scope

- **Resuming the mint to n≥50**, and `subscription-model-client`. This unit is the decision
  input for that spend, not the spend.
- **Any change to the A1 rule**, its scope, or its clauses. It is under measurement.
- **Hand-adjudication / labeling** of anything this run flags (open question 1).
- Any change to A2/A3 semantics, `verdict.reduce`, or `NOT_COVERED`.
- The parked record defects (D5): the `16` denominator composition, the `0% UNVERIFIED`
  whole-mint headline, the "5 distinct runs" reconciliation.
- Corpus **portability** — cases stay machine-bound through the absolute `server_command`.
  Known, unfixed, out of scope.
- C7 live console; C8 (A3); C9 export-back.

---

## 8. Proposed aspects

| Order | Aspect | Boundary |
|---|---|---|
| 1 | `corpus-collision-guard` | M-1 (+S-1): safe re-ingest; no partial write; no label loss; named runner outcome |
| 2 | `ledger-detector-identity` | M-2: detector block, `unrecorded` back-compat, carried on every surface |
| 3 | `ledger-merge-dedup` | M-3: merge, worst-wins dedup, both denominators, disagreements named |
| 4 | `control-partition` | M-4: controls out of the headline; FAILing control = detector FP, not void |
| 5 | `reverify-measurement` | M-5 (+S-2): freeze script, one run, verbatim output |
| 6 | `record-correction` | M-6 (+S-3): correction blocks, `README.md:183`, CHANGELOG next entry, doc sync |

Sequencing is hard for 1 → 5 (safety before the run) and 2,3,4 → 5 (the run must emit the
shapes it reports). 6 depends only on 5's output.
