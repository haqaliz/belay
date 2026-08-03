# PRD — `under-firing-measurable`

**Unit:** `feat/under-firing-measurable` · **Owner:** aliz · **Date:** 2026-08-03
**Base:** `origin/master` @ `4e5634d` (v0.11.0) · **Baseline:** 1238 passed, 1 skipped, 1 deselected
**Card:** `docs/planning/_card/issue.md` · **Dig:** `docs/planning/_card/understanding.md`

---

## 1. Problem statement

Belay's Phase-0 record can say a capture flagged nothing. It cannot say whether the detector
**had anything to judge**. Those are different facts and the engine conflates them.

The record already names this gap twice, in the criteria and in the data:

- `docs/ROADMAP.md:152-155` — *"the record now also carries a gap in the criteria themselves —
  they are **entirely precision-side**, with **no recall clause and no procedure by which a
  missed violation could ever enter the count**."*
- `docs/technical/PHASE0_RESULTS.md` (blindness clause) — v0.11.0 *"cannot separate 'those
  captures contain no weakenings' from 'the rule is blind to them'."*
- `CLAUDE.md` — *"`FN 0` is an artifact of construction, and the corpus cannot measure recall."*
- `PHASE0_RESULTS.md` — *"**A detector that is blind on a dimension abstains on nothing:
  perfect decisiveness is exactly what silent blindness looks like from this metric.**"*

**Three concrete defects, verified by dig, in ascending order of depth.**

**D1 · Exposure is computed and thrown away.** `_evaluate_content_rule`
(`src/belay/verify/invariants.py:320-468`) counts `compared` — the in-scope files it actually
judged — at `:430`. Of its **nine** return paths it appears on **one**, and there only as
English prose (`:465-466`). The **FAIL** path (`:440`), the one an under-firing analysis most
needs, reports neither `compared` nor `in_scope`. Nothing downstream can see it:
`InstanceRecord` (`src/belay/phase0/ledger.py:100-134`) has no exposure field, and **no
serializer anywhere writes `Verdict.observed` or `Verdict.expected`** — the only three writers
(`corpus/add.py:336-342`, `corpus/run.py:164-172`, `interop/report.py:154-190`) all project to
`(axis, kind, status)`.

**D2 · Only flagged turns are ingested.** `phase0/runner.py:255` —
`flagged_turns = [n for n in range(len(calls)) if verdicts[n].status is Status.FAIL]` — is the
only automated ingest population, so a **miss** never becomes a case.
*(Correction to the card: `add_case` enforces **no** precondition on verdict status —
`verdict` is read once, at `add.py:336` — and `belay corpus add --turn N` applies no FAIL
filter (`cli.py:764-845`). `metrics.py`'s FN branch is implemented and already unit-tested
(`metrics.py:242-243`, `tests/test_corpus_metrics.py:95`). The manual path exists; it is
undocumented and contradicted by its own help text, which asserts *"one flagged turn"*
(`cli.py:1683`, `cli.py:1699`, `add.py:1`, `add.py:272`).)*

**D3 · `corpus run` inverts on a stored miss — the deep one.** A recorded miss has
`expected.reduced_status == "PASS"`. `classify_case` (`corpus/run.py:201-228`) compares the
recomputed verdict against `expected` alone and never consults `human_label`. So a stored miss
reports **MATCH** — *the regression suite certifies that the engine still misses it* — and flips
to **REGRESSION**, exit 1 (`cli.py:908-914`), **the day the detector is sharpened to catch it.
CI would go red for a fix.** `run.py:31-35` pre-emptively forbids the cheap escape: *"Do not add
a new SKIP cause to quiet that."*

### Why now, and for whom

The next unit is the funded re-mint (`subscription-model-client`, ~11 h). **A mint at n≥50 that
produces few flags would be uninterpretable in exactly the way v0.11.0 was**, and would very
likely be misread as evidence for R1. Exposure accounting is worth more on that future mint than
on the banked data. Building it *after* the spend wastes the spend.

The ICP is the same person the gate serves: whoever must answer *"did this run actually do the
right thing?"* and today cannot distinguish a clean run from an un-instrumented one.

---

## 2. Goals & success metrics

| # | Metric | How it is judged |
|---|---|---|
| **M0** | **The headline deliverable:** for every instance in the report, the reader is told **exactly one** of *"judged N file(s), found nothing"* / *"given nothing to judge"* / *"unrecorded"* — never a bare silence | a test that walks all three states end to end on real fixtures |
| M0b | **No verdict changes value.** Default behaviour for a single-ledger, control-free run is **byte-identical** to today | the existing `phase0` suite passes unchanged, plus an explicit equality test |
| M1 | Exposure is **structured data** on every A1 return path that has it, and **absent** (never `0`) on every path that does not | test per path, all nine enumerated |
| M2 | An old ledger — every ledger in `runs/` — reads exposure as **`unrecorded`**, never as `0` | pinned against a real fixture shaped like `runs/s2.json` |
| M3 | Exposure reaches `phase0 run`, `phase0 combine` **and** `belay verify`, with the `combine` merge rule stated in the output | test per surface (the coverage-line-per-surface precedent) |
| M4 | A turn the detector did **not** flag can be ingested by an opt-in path, and **never** enters `flagged_turns` or moves the violation numerator | numerator/denominator proven unchanged by test |
| M5 | A stored **recorded miss** never classifies `MATCH`, and a detector that starts catching it does **not** turn `corpus run` red | test both directions |
| M6 | `corpus score` reports **recall with a real denominator**; `n/a` never renders as `1.00` or `0.00` | existing `_ratio`/`_rate` discipline, extended by test |
| M7 | The measurement runs **once**, under the freeze protocol, offline, no API key | tooling commit precedes output commit; output committed verbatim |
| M8 | A **ledger is committed**, so the published number is re-derivable by `belay phase0 report` | the artifact exists in git |
| M9 | The 7 existing human labels survive **byte-identical**, asserted **per case** | per-case equality, never an aggregate |
| M10 | Every stale published claim this unit touches carries a dated correction; no dated record is rewritten | inventory addressed, none silently edited |

**Explicit non-metric — exposure is reported, not thresholded.** No target value. High exposure
and zero exposure are **both** successful outcomes of this unit; only an unattributed or hidden
exposure figure is a failure. Likewise the recall result: *finding* a miss and *finding none* are
both successes. **The only failure is a number without its denominator.**

### 2.1 Pre-registered reading rule — fixed BEFORE the run

**PROPOSED, pending owner approval at this review gate. It must be committed before the
measurement runs, or it is post-hoc.** Structure copied from
`docs/planning/phase0-reverify-banked/prd.md` §2.1.

| Observed | Reading | Action |
|---|---|---|
| **≥1 of the 2 held-out turns adjudicated a weakening** | the rule **misses** on data it was not fitted on | recall gets a real numerator (n=2). Store as the corpus's **first recorded miss**. This argues for **sharpening before spending**, not for funding the mint. |
| **Both held-out turns adjudicated clean** (or not weakenings) | **no held-out miss observed at n=2** | Publish as *"0 misses found of 2 adjudicated; sensitivity still unconfirmed"*. **Never** as *"the rule has good recall"* — n=2 is not a base rate. |
| **Instrument exposure = 0 on an instance the ledger reported silent** | that instance's silence carries **no information about the rule** | Report it as a **named category**. The blindness clause is *narrowed* for those instances, never *discharged*. |
| **Instrument exposure > the static survey's 17 turns / 6 instances** | the static estimate was built as a **superset**, so exceeding it means the **instrument is wrong** | Do **not** publish an exposure figure. Investigate first. (A *lower* count is expected and fine.) |
| **Exposure absent on a re-read old ledger** | a **format gap**, not a finding | Must render `unrecorded`. Reading it as *"compared nothing"* would fabricate the very finding this unit exists to establish. |
| **UNVERIFIED rises, or `INSTRUMENT SUSPECT` fires** | an instrument report, **not** a rate | Do not publish a rate. Fix the instrument first. |

**The blindness clause, restated for this unit.** Exposure accounting **narrows** the blindness
question; it does not close it. It can prove *"the rule was never given anything to judge"* for a
named set of instances. It **cannot** prove that an exposed-and-passed turn was correctly passed —
only human adjudication does that, at n=2 here. A zero-miss result is published as *"no held-out
miss observed; sensitivity unconfirmed"*, never as *"the rule is sensitive"*, and never as
evidence for or against R1.

**What success does NOT mean.** This unit **cannot produce a PROCEED**. The pre-registered clause
requires a denominator **≥50** counting *instances minted* — detector-independent
(`PHASE0_RESULTS.md:25-38`; *"no re-verification of banked captures can ever satisfy it"*), so
**R1's quantitative form stays untested**. n=2 is not a base rate, exactly as `ROADMAP.md:280`
records for n=1.

**Non-comparability, declared in advance.** Any recall figure this unit produces is **not**
comparable to the `recall 0.00 (0/1, n=1, hand-adjudicated)` already in the record: different
detector, different population, different adjudication set. It must be published with that
sentence attached, following the `1/15` vs `4/16` and `NOT_COVERED` precedents.

---

## 3. What the banked data can and cannot support

Static, argument-based survey of all 24 captures; turn counts reproduce `acceptance.out`
**exactly** (392 non-control), so the extraction is sound. **This is an upper bound**, not the
rule's own `compared` count — the rule judges the replayed delta against the task pre-state, and
a write that *creates* a test file cannot weaken anything.

- **17** real writes to a `.py` file under a `tests`/`testing` **path segment**, across **6 of 15**
  instances. **9 instances have zero exposure.**
- Of the 17: **7 flagged** (all `pytest-5227`, fitted-on); **10 passed**.
- Of those 10: **1** is `pytest-5227` s2 turn 8 (fitted-on, known-correct PASS); **7 are exactly
  the already-adjudicated false positives** (`flask-4045` t8; `flask-4992` t10/12/14/19;
  `pylint-5859` t6/11) — the corpus's existing negative fixtures.

**The entire held-out un-adjudicated set is therefore two turns:**

| instance | stage | ledger turn | file |
|---|---|---|---|
| `pytest-dev__pytest-5692` | s3 | 8 | `testing/test_junitxml.py` |
| `pytest-dev__pytest-6116` | s3 | 15 | `testing/test_collection.py` |

**n = 2, and the PRD pre-registers that cap.** The nine zero-exposure instances cannot be
rescued by any re-verification of this data — only a new mint reaches them.

---

## 4. Requirements

### Must-have

**M-1 · Exposure is a fact, and absence is representable.**
The A1 verdict carries, where it exists, the number of in-scope files **compared** and the number
**touched** (`in_scope`). On the five early abstains (`invariants.py:359,365,371,382,388`) and on
the `read-only` rule — which has no exposure concept at all — it is **absent**, not `0`. The
file-budget abstain (`:398`) has `in_scope` but no `compared`; it reports what it has and marks
the rest absent. `compared` counts **judgement attempts** (it includes deletions, and increments
before `_judge_file` may return UNVERIFIED); this is documented, not smoothed over.

**M-2 · Absent survives serialization end to end.**
Follow the `detector` pattern, not the `not_covered_turns` one: `Optional[…] = None`, absent →
`None`, and **omit the key from `to_json`** rather than writing `null` or `{}`
(`ledger.py:228-239`). The new field is **never** in `_REQUIRED_INSTANCE_FIELDS`; old ledgers load
unchanged and render `unrecorded`. **Never fold exposure into `turn_status_counts`** —
`total_turns()` sums it blindly and is the denominator of the FAIL rate, the UNVERIFIED share and
the coverage fractions. The **ERRORED** record (`runner.py:157-167`) answers **absent**, not `0`.

**M-3 · Three surfaces, one merge rule.**
`phase0 run`'s report, `phase0 combine`'s population report (which today renders **no** coverage
section at all, `report.py:404-471` — and is the surface the 1/15 headline is published from), and
`belay verify`'s per-turn and aggregate output (`cli.py:565-578`, `:597-633`). `combine` needs a
`Population` accessor written from scratch; **its merge rule is chosen and printed in the output**,
alongside the existing `(stage, trace_id)` dedup line.

**M-4 · Zero-exposure is a named category, not silence.**
An instance whose A1 exposure is `0` is reported as *"the rule was given nothing to judge"* —
distinct from *"judged and found nothing"* and distinct from *"unrecorded"*. Three states, three
renderings, no collapsing.

**M-5 · An unflagged turn can be ingested, without touching the numerator.**
An **opt-in** ingest population on `phase0 run` (explicitly named turn indices), landing in **new**
`InstanceRecord` buckets. A case added this way **must not** enter `flagged_turns`, must not change
the disposition, and must not move `violation_denominator()` or `violating_instances()` — proven by
test, not by inspection. It routes through the same `except ValueError` discipline as the existing
ingest, so a collision stays a `CaseExistsError` and can never become `ERRORED`.

**M-6 · A recorded miss is declared, never inferred.**
Case schema **v3**: an optional declaration that *"this `expected` verdict is a recorded MISS, not
guarded behaviour."* Omitted ⇒ undeclared (a normal case), exactly as `task_prestate` and
`root_cause` do it (`case.py:233-249`); a malformed value raises a **named** `ValueError`; the
field is never added to `_REQUIRED_FIELDS`, because *"a required new field would reject every case
already sitting in `corpus/local/`"*. **The engine never sets it from a verdict** — that is the D3
boundary in `add.py:34-42` (*"no code path from `verdict` to `human_label`"*) applied to a second
field. It is a human declaration, arriving the same way a label does.

**M-7 · `corpus run` stops inverting.**
A declared recorded-miss case (a) **never classifies `MATCH`** while the engine still misses it —
a MATCH there would certify blindness as a pass; and (b) when the engine starts catching it,
`corpus run` **does not go red** — a fixed detector is not a regression. `_SKIP_CAUSES` is **not**
widened (`run.py:31-35`; a SKIP means *"this box could not evaluate the case"*, an environment gap
— a recorded miss is identical on every box). Classification must **not** read `human_label` —
that would couple regression detection to the labels the metric scores independently.

**M-8 · Recall is scorable and honest.**
`metrics.py` needs no change (M6's shape already produces FN). `corpus score` names FN's
provenance so a reader cannot mistake a recorded miss for a detection, and `_ratio`/`_rate` keep
rendering a zero denominator as `n/a` — *never* `1.00`, never `0.00`.

**M-9 · The help text stops asserting a precondition the code does not have.**
`cli.py:1683`, `cli.py:1699`, `add.py:1`, `add.py:272`.

**M-10 · The measurement, once, frozen, committed — with its ledger.**
The invocation script is committed in a commit containing **no result**, run **once**, and its
**raw, complete, unedited** stdout committed in the next commit, whatever it says (the protocol at
`invariant-rule-wiring/acceptance.sh:9-14`, re-used unchanged by `reverify-measurement`). Default
invariants only. Offline, no API key, no model call. Ingests into a **fresh** corpus dir, never
`corpus/local/`. **The resulting ledger(s) are committed** — a ledger holds only trace ids, counts,
dispositions and causes, so this does not touch the no-raw-data-egress guardrail, and it closes the
`ROADMAP.md` claim that the number *"is re-derivable by a stranger from a committed ledger"*, which
today nothing backs (the v0.11.0 ledgers were never committed and no longer exist).

**M-10a · What "the run" means, pre-registered before it happens.**
"The run" is **one invocation of the committed script**, which loops the five stages internally —
the shape `reverify-measurement/acceptance.sh` already uses. If that invocation **aborts** (crash,
bad path, disk), the abort is **declared in the write-up** and the script is re-run; clause 3 of
the protocol (*"a second run is permitted ONLY if it is declared as such"*) is the governing rule
and an undeclared re-run is a protocol violation, not a retry. **A re-run to get a different
answer remains prohibited.** Because v0.11.0's wall-clock was never recorded, the smallest stage is
timed **before** the script is committed, so the budget is known rather than discovered.

**M-11 · The two held-out turns are adjudicated, in their own evidence grade.**
Human adjudication, reported separately from execution, exactly as `PHASE0_RESULTS.md` keeps them
apart. A turn adjudicated a weakening becomes a corpus case labeled `true-positive` **through
`belay corpus label`** with a human-supplied `root_cause` key (`curate.py:74-79`), plus the M-6
declaration. **A found-but-unflagged violation is a false negative, not a hand-audited TP** — the
gate's TP count is untouched either way.

**M-12 · The 7 existing labels survive byte-identical**, asserted **per case** — *"an aggregate
count would let one silently-truncated note through."*

**M-13 · Record correction.** A dated `Correction — 2026-08-xx` section in `PHASE0_RESULTS.md`
carrying: the warning banner, originals kept with corrections appended, a literal *"what changed
and what did not"* table, the **evidence grade** per claim, and what was deliberately left intact.
Sync `CLAUDE.md`, `CHANGELOG.md` (`[Unreleased]`), `docs/ROADMAP.md` (the gate block and the R1
row), `docs/technical/CAPABILITY_ROADMAP.md`; `README.md:183` as its separate obligation; verify
`VISION.md` needs no edit and **record that verification**. **No dated planning document is
rewritten.**

### Should-have

- `belay corpus list` / `show` surface the recorded-miss declaration so it is visible without
  reading `case.json`.
- The report names the **three** exposure states in its own prose, so a future reader inherits the
  distinction rather than re-deriving it.

### Nice-to-have

- A one-line exposure summary in `belay verify`'s aggregate even when A1 declared nothing.

---

## 5. Technical considerations

**Capability:** C5 (A1 invariant verdict) + C6 (failure corpus). No new capability. Phase 0
instrument work; **this is not a gate run.**

**Verdict impact — A1 only, and additive.** No change to A2/A3 semantics, `verdict.reduce`, or the
`NOT_COVERED` boundary. `reduce` reads only `.status` (`verdict.py:96-114`), so exposure is
invisible to it by construction. **No verdict changes value** as a result of this unit — that is a
testable claim and it is M-4's companion: default behaviour for a single-ledger, control-free run
is byte-identical to today.

**`UNVERIFIED` path:** unchanged. Exposure is orthogonal to it — a turn can be `UNVERIFIED` *and*
have judged files, and that combination must render both.

**Zero-dependency and offline** are load-bearing (`pyproject.toml:41`). Static AST guards
(`tests/test_import_guard.py`) stay green; no clock is read inside `add_case` (`captured_at` stays
injected); a git sha must not be read by the library.

**Machine-bound, unchanged:** corpus cases carry absolute `server_command` paths into
`eval/servers/`; off darwin every case is an up-front SKIP. This unit inherits that and does not
worsen it.

**Guardrails:** harness-side throughout. No agent framework. No LLM anywhere — exposure is a count
produced by the same deterministic comparison that produces the verdict, and adjudication is
explicitly a **human** step in its own evidence grade.

---

## 6. Risks & open questions

| Risk | Severity | Mitigation |
|---|---|---|
| **Read as a gate run, or as a recall measurement with a real base rate** | **Top risk** | M-10's script states what it cannot do *inside the script*; §2.1 pre-registers n=2 as a cap; first paragraph of the write-up says it |
| A `0` exposure on an old ledger read as *"compared nothing"* — **fabricating the finding** | High | M-2: omit-key + `unrecorded`, pinned against a real old-ledger fixture |
| The `corpus run` fix half-lands and CI goes red on a genuine detector improvement, so someone deletes the FN cases | High | M-7 tests **both** directions; the "do not widen `_SKIP_CAUSES`" doctrine is honored explicitly |
| The opt-in ingest silently moves the violation rate | High | M-5 proves numerator and denominator unchanged by test |
| Adjudicating 2 turns produces nothing and the unit reads as wasted | Medium | Pre-registered as a **success** outcome; the instrument, not the n=2 result, is the deliverable that pays off on the re-mint |
| Human labels damaged by re-ingest | Medium | M-12 per-case byte-equality; fresh corpus dir; existing `CaseExistsError` guard |
| Measurement runtime unknown (v0.11.0's wall-clock is not recorded) | Medium | Measure the single smallest stage first; the freeze protocol permits one run, so budget it before committing the script |
| **R1 misread** (`ROADMAP.md:134-135`) | Medium | Every surface repeats: this neither supports nor refutes the premise |

**Open questions**

1. **What exactly does the recorded-miss declaration key on?** A boolean, or a richer object
   naming *why* the case is stored (miss / guarded / fixture)? A boolean is smaller; an object
   ages better. → tech-plan decision, aspect B.
2. **Which of MATCH/REGRESSION/SKIP does a recorded miss get, or is a fourth outcome needed?** A
   fourth outcome touches `CorpusRun`'s counters and the `has_regression` exit contract
   (`run.py:145-161`). → aspect B, decided with tests first.
3. **`combine` merge rule:** sum-over-captures (matches `total_turns()`) or reduce-over-instances
   (matches the violation denominator)? They differ and both are defensible; the answer is printed
   in the output either way. → aspect A.
4. **Does the exposure fact need to reach the corpus case `expected` blob** (so a stored case
   records what the rule judged), or is the ledger enough? Reaching it means changing the two
   mirrored writers together (`add.py:336-342` / `run.py:164-172`) and could shift what
   `_divergences` compares. **Default: no** — keep it out of `expected` unless a test demands it.

---

## 7. Out of scope

- **`subscription-model-client` and the re-mint.** This unit is the decision input for that
  ~11-hour spend, not the spend.
- **Any change to the `no-assertion-weakening` rule itself.** It is measured here, not edited. A
  defect this exposes is a finding for the next unit unless it makes the measurement impossible.
- Any change to A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED` boundary.
- Re-mining, re-capturing, moving or copying any banked capture.
- Re-deriving any published number. `4/16`, `precision 0.00`, `3/93`, `0% UNVERIFIED`, `1/15` all
  stand unedited; only annotations and new figures are added.
- Rewriting `CHANGELOG.md`'s shipped entries, or any dated planning document.
- C7 live console; C8 (A3); C9 export-back.

---

## 8. Aspects

| Aspect | Boundary |
|---|---|
| `a1-exposure-accounting` | Exposure as structured, absent-capable data: the nine A1 return paths → ledger → `phase0 run` / `combine` / `belay verify`, with the merge rule and the three exposure states stated in the output. |
| `corpus-recorded-miss` | Case schema v3 declaration, the opt-in non-flagged ingest path that cannot move the numerator, `corpus run` stops inverting, `corpus score` names FN provenance, help text corrected. |
| `miss-measurement` | The frozen single run with its committed ledger, adjudication of the two held-out turns in their own evidence grade, and the dated record correction across the doc surface. |

Sequencing is strict: **A → B → C.** C cannot store an adjudicated miss without B's declaration,
and cannot report exposure without A.
