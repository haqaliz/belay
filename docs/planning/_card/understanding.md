# Phase-2 understanding — `under-firing-measurable`

**Date:** 2026-08-03 · **Base:** `origin/master` @ `4e5634d` (v0.11.0)
**Baseline confirmed in this worktree:** `uv run pytest` → **1238 passed, 1 skipped, 1 deselected**.

Produced from four read-only dig agents (A1 exposure path, corpus lifecycle, banked-data
exposure survey, repo conventions). Every claim below carries a citation; where a dig
**overturned** the card's premise, it is marked ⚠ **CORRECTION**.

---

## 1. What the work is really asking

v0.11.0 measured **1/15 instances (6.7%)** under `no-assertion-weakening`. Fourteen instances
flagged nothing, and the record cannot say whether that means *clean* or *blind*
(`PHASE0_RESULTS.md` → blindness clause). This unit is supposed to make that separable, and
to make a *missed* violation representable so under-firing can be regression-tested.

The dig confirms the problem is real, but **relocates it**. Two of the three assumed defects
are not where the card said they were.

---

## 2. ⚠ CORRECTION — the corpus can ALREADY store a false negative

The card asserted an unflagged turn *"can never become a case"*. That is true of the
**automated** path only.

- `add_case` enforces **no precondition on `verdict.status`** — `verdict` is read at exactly
  one place, `corpus/add.py:336-342`, to build the `expected` dict. It will compose a case
  whose `expected.reduced_status` is `"PASS"`.
- `belay corpus add --turn N` **applies no FAIL filter** in its handler (`cli.py:764-845`);
  it verifies whatever turn you name and hands the verdict straight to `add_case`.
- `corpus label --label true-positive --root-cause-key …` (`curate.py:34-83`) then produces
  exactly the shape the FN cell needs.
- `metrics.py` needs **no change at all**: `elif is_bad: fn += 1` (`metrics.py:242-243`) is
  implemented *and already unit-tested* — `tests/test_corpus_metrics.py:95` constructs
  `_case("PASS", "true-positive", "fn")` and asserts `fn == 1`.

**So the storage half is nearly free.** What is actually missing:

1. `phase0/runner.py:255` is the choke point —
   `flagged_turns = [n for n in range(len(calls)) if verdicts[n].status is Status.FAIL]` — and
   it is the *only* automated ingest population.
2. The CLI **help text asserts a precondition the code does not have**: *"compose a
   self-contained, labeled case from one flagged turn"* (`cli.py:1683`) and *"the trace file
   the flagged turn is in"* (`cli.py:1699`), repeated at `add.py:1` and `add.py:272`. The
   manual FN path exists, is undocumented, and is contradicted by its own help.

### The real, deep defect the dig found: **`corpus run` inverts on a stored miss**

A stored FN has `expected.reduced_status == "PASS"`. `classify_case` (`run.py:201-228`)
compares the recomputed verdict against `expected` alone — it never consults `human_label`.
Therefore:

- **today** such a case reports **MATCH** — the regression suite would certify *"the engine
  still misses this"* as a pass;
- **the day the detector is sharpened to catch it**, the case flips to **REGRESSION** and
  `belay corpus run` exits 1 (`cli.py:908-914`) — **CI goes red for a fix**.

`run.py:31-35` pre-emptively forbids the cheap escape (*"Do not add a new SKIP cause to quiet
that"*). An honest fix needs a deliberate decision: either a stored per-case notion of *"this
expected verdict is a recorded MISS, not guarded behaviour"* (a `case.json` field ⇒ **schema
v3**, under the existing fail-closed / omitted-means-undeclared discipline), or a **fourth
outcome** beside MATCH/REGRESSION/SKIP (which touches `CorpusRun`'s counters and the
`has_regression` exit contract, `run.py:145-161`). Classifying on `human_label` inside
`run.py` is **not** an option — it would couple regression detection to the very labels the
metric scores independently.

**This is the hardest design question in the unit, and it did not exist in the card.**

---

## 3. The exposure gap is real, and larger than the card described

`compared` lives only in `_evaluate_content_rule` (`invariants.py:320-468`) — the `read-only`
rule has no exposure concept at all. Of its **nine** return paths, `compared` appears on
**one**, and only inside an English message (`invariants.py:465-466`):

| path | line | `in_scope` | `compared` | reported? |
|---|---|---|---|---|
| 5 early abstains | :359, :365, :371, :382, :388 | not computed | not computed | — (must read **absent**) |
| file-budget abstain | :398 | computed | not initialised | count in prose only |
| **FAIL** | :440 | ✔ | ✔ | **neither** |
| abstain-after-judging | :451 | ✔ | ✔ | only `len(abstentions)` |
| **PASS** | :459 | ✔ (structured, via `observed`) | ✔ | **prose only** |

The FAIL path — the one an under-firing analysis most wants (*"it flagged 1 file; how many did
it even look at?"*) — reports neither. Two semantics worth pinning: `compared` **includes
deletions**, and it counts *judgement attempts*, not decided comparisons (a file whose
pre-state won't parse increments at `:430` then returns UNVERIFIED from `_judge_file`).

**`Verdict` needs no new field**: `expected` is already a free-form dict carrying `"cause"`
(`invariants.py:352`), and `reduce` reads only `.status` (`verdict.py:96-114`). But **no
serializer anywhere writes `observed` or `expected`** — a fact placed there reaches memory and
nothing else (`corpus/add.py:336-342`, `corpus/run.py:164-172`, `interop/report.py:154-190`
are the only three writers, and all three project to `(axis, kind, status)`).

### ⚠ The back-compat hazard is material here, unlike its precedent

`ledger.py:274` reads `not_covered_turns` as `raw.get(..., {})` — **absent collapses into
empty at load**, and the distinction is recovered nowhere in code; it is handled purely by the
report's *wording* (`report.py:173-177`, which refuses to claim either reading).

**That trick does not transfer.** For exposure, *"0 files compared"* is a real and material
finding — it **is** the under-firing claim — while *"not recorded"* is a format gap. Collapsing
them would let every old ledger (i.e. the entire re-measurement population) read as *"the
detector was silent because it compared nothing"*, **fabricating exactly the finding this unit
exists to establish honestly.** The pattern to copy is `detector`: `Optional[…] = None`, absent
→ `None`, and **omit the key from `to_json`** rather than writing null (`ledger.py:228-239`).

Two further traps: never fold exposure into `turn_status_counts` (`total_turns()` sums it
blindly and is the denominator of the FAIL rate, the UNVERIFIED share *and* the coverage
fractions); and `runner.py:157-167` builds the **ERRORED** record positionally, where the
honest answer is *absent*, not *0 compared*. Finally, `belay phase0 combine` renders **no**
coverage section at all (`report.py:404-471`) — and that is the surface the 1/15 headline is
published from, so a per-instance field needs a `Population` accessor written from scratch,
with its merge rule (sum-over-captures vs reduce-over-instances) **chosen and stated**.

---

## 4. ⚠ The decisive finding: the held-out adjudication set is **2 turns**

Static, argument-based survey of all 24 banked captures. Turn counts reproduce
`acceptance.out` **exactly** (20/20/11/130/216 = 392 non-control), so the extraction is sound.

- The filesystem server is the **only** tool surface — no shell tool was ever called, so there
  are no `command_line`-embedded writes.
- **17** real writes land on a `.py` file under a `tests`/`testing` **path segment**, across
  **6 of 15** instances. **9 instances have zero exposure** — their silence carries *no
  information about the rule*, and **no amount of re-verifying this data can change that.**
- Of the 17: **7 flagged** (all `pytest-5227`, the fitted-on instance); **10 passed**.
- Of those 10: 1 is `pytest-5227` s2 turn 8 (fitted-on, the known-correct PASS), and **7 are
  exactly the 7 already-hand-adjudicated false positives** — `flask-4045` t8,
  `flask-4992` t10/12/14/19, `pylint-5859` t6/11, i.e. the corpus's existing negative fixtures.

**That leaves exactly two un-adjudicated held-out exposure turns in the entire banked corpus:**

| instance | stage | ledger turn | file |
|---|---|---|---|
| `pytest-dev__pytest-5692` | s3 | 8 | `testing/test_junitxml.py` |
| `pytest-dev__pytest-6116` | s3 | 15 | `testing/test_collection.py` |

Both on instances never before examined. **n = 2.** That is the entire held-out recall
denominator available without a new mint — and it is an *upper* bound, since a write that
**creates** a test file cannot weaken anything and the survey cannot separate create-from-modify
statically.

**Read this correctly:** it does not make the unit pointless. It makes the unit *cheap and
decisive* — two turns is a tractable adjudication, and the exposure accounting is what turns
*"14 silent instances"* into *"9 never exposed, 5 exposed-and-passed, of which 7 turns were
already adjudicated FP and 2 are new."* But it caps what any result can claim, and the PRD must
pre-register that cap.

---

## 5. ⚠ A separate integrity finding, not in the card

**The v0.11.0 ledgers do not exist.** No `reverify-*.json` is on disk in any worktree; the
`corpus/reverify-20260731` directory is gone; `git ls-files` shows only the planning docs. The
sole surviving record of the published **1/15** is the aggregate prose in
`reverify-measurement/acceptance.out`, which contains **zero** per-turn lines and zero
occurrences of `"file(s) compared"`.

`docs/ROADMAP.md` claims *"the **ledger → report path is fully reproducible** from fixed
traces — anyone given the trace set reproduces the identical number"* and that the number *"is
re-derivable by a stranger from a committed ledger (`belay phase0 report` is a pure
re-render)"*. **No ledger was committed.** A ledger holds only trace ids, counts, dispositions
and causes — no raw data — so committing one does not touch the no-raw-data-egress guardrail.

**Proposed scope addition, for the review gate:** emit and **commit** the ledger this unit's
measurement produces, so the number it publishes is re-derivable from a repo artifact. Cheap,
and it closes a claim the record currently cannot back.

---

## 6. Wedge / axes / guardrail check

- **Harness-side, no drift.** Nothing here authors or orchestrates an agent, and no verdict
  comes from an LLM's opinion — exposure is a count produced by the same deterministic
  comparison that produces the verdict, and adjudication is explicitly a *human* step kept in
  its own evidence grade.
- **Axis: A1 only.** No change to A2/A3 semantics, `verdict.reduce`, or the `NOT_COVERED`
  boundary. `reduce` reads only `.status`, so exposure is invisible to it by construction.
- **Moat #2 compounds:** the corpus gains the ability to hold a miss, which is what makes
  under-firing regression-testable rather than merely narratable.
- **Honesty contract:** the whole unit is an *absent-vs-zero* discipline problem. `UNVERIFIED`
  is untouched; the new risk is a **0 that means "not recorded"** being read as a finding.

---

## 7. Open questions for the requirements interview

1. **`corpus run` on a stored miss** (§2): schema-v3 case field, or a fourth outcome? This is
   the unit's real design decision. A stored FN must not certify blindness as MATCH, and must
   not turn CI red when the detector is fixed.
2. **Merge rule for exposure across `combine`** (§3): sum-over-captures (matches
   `total_turns()`) or reduce-over-instances (matches the violation denominator)? They differ,
   and the headline is published from this surface.
3. **Does `belay verify` surface exposure too**, or `phase0` only? (`cli.py:565-578`, `:597-633`)
4. **Adjudicate the 2 held-out turns inside this unit, or scope it to the instrument?** n=2 is
   cheap, but it is human judgment and belongs in its own evidence grade.
5. **Commit the ledger?** (§5) — in or out of scope.
6. **Should the 9 zero-exposure instances be reported as a named category** in the report, so
   *"silent"* never again reads as *"clean"*?
