# Aspect — `a1-exposure-accounting`

**Unit:** `under-firing-measurable` · **Order: FIRST.** Covers PRD must-haves M-1 … M-4 (and M0, M0b).

---

## Problem slice

An A1 verdict of `PASS` today means *"the rule looked and found nothing"* **or** *"the rule was
given nothing to look at"*, and nothing downstream can tell which. `_evaluate_content_rule`
(`src/belay/verify/invariants.py:320-468`) already computes the discriminator — `compared`, the
count of in-scope files it actually judged, incremented at `:430` — and reports it on **one** of
its **nine** return paths, as English prose (`:465-466`). The **FAIL** path (`:440`) reports
neither `compared` nor `in_scope`. `InstanceRecord` (`src/belay/phase0/ledger.py:100-134`) has no
exposure field, and no serializer anywhere writes `Verdict.observed` or `Verdict.expected`.

## User outcome

For every instance in a report, the reader is told **exactly one** of:

1. **judged N file(s) and found nothing** — a decision;
2. **given nothing to judge** — no opportunity, and therefore no information about the rule;
3. **unrecorded** — this ledger predates exposure; the code cannot tell, and says so.

## In scope

- **Exposure as structured data on the A1 verdict.** Both counts: files **compared** (judgement
  attempts) and files **touched in scope** (`in_scope`). Ride the existing free-form `expected`
  dict (`invariants.py:254,352`) — `Verdict` needs no new field and `reduce` needs no change.
- **Absent is a first-class value.** The five early abstains (`:359,365,371,382,388`) and the
  `read-only` rule have **no** exposure concept and emit **absent**, never `0`. The file-budget
  abstain (`:398`) has `in_scope` but no `compared` — it reports what it has and marks the rest
  absent.
- **Serialization that preserves absence.** Copy the `detector` pattern (`ledger.py:228-239`):
  `Optional[…] = None`, absent → `None`, **key omitted from `to_json`** rather than `null`/`{}`.
  Never `_REQUIRED_INSTANCE_FIELDS`. Never folded into `turn_status_counts`.
- **Accumulation** in `phase0/runner.py:203-254`, beside `not_covered_turns`; landed at `:292-302`;
  and the **ERRORED** constructor (`:157-167`) answers **absent**, decided explicitly.
- **Three surfaces:** `phase0 run`'s report (a section modeled on `_coverage_section`,
  `report.py:152-182`), `phase0 combine`'s population report (which today renders **no** coverage
  section at all, `report.py:404-471`) via a new `Population` accessor, and `belay verify`'s
  per-turn and aggregate output (`cli.py:565-578`, `:597-633`).
- **The `combine` merge rule is chosen, and printed in the output** beside the existing
  `(stage, trace_id)` dedup line.
- **Zero-exposure is a named category** in the rendered prose, distinct from *judged-and-clean* and
  from *unrecorded*.

## Out of scope

- Any change to what the rule **decides**. No verdict changes value (M0b).
- `verdict.reduce`, the `NOT_COVERED` boundary, A2/A3 semantics.
- Putting exposure into a corpus case's `expected` blob — PRD open question 4, **default no**
  (it would require changing the two mirrored writers `add.py:336-342` / `run.py:164-172` together
  and could shift what `_divergences` compares).
- Any corpus change → `corpus-recorded-miss`. Any measurement → `miss-measurement`.

## Acceptance criteria (test-first — these are the failing tests, written before the code)

1. **All nine return paths are enumerated by test.** Each of `invariants.py:359, 365, 371, 382,
   388, 398, 440, 451, 459` yields a verdict whose exposure is either the correct pair of counts or
   explicitly **absent**. No path is left unasserted.
2. **The FAIL path reports exposure.** A turn that flags 1 file out of N judged reports **both**
   numbers — today it reports neither.
3. **`read-only` emits absent, not zero.** A `read-only` verdict is distinguishable from a content
   verdict that compared nothing; otherwise the two rules become indistinguishable in the tally.
4. **An old ledger reads `unrecorded`.** Pinned against a **real fixture shaped like
   `runs/s2.json`** — loads unchanged, renders `unrecorded`, and is never rendered as `0`.
5. **`to_json` omits the key when unrecorded** — asserted on the serialized bytes, not on the
   loaded object, because `null` and absent are the same after loading.
6. **Exposure is never inside `turn_status_counts`**, and `total_turns()` is unchanged — asserted
   directly, because `total_turns()` is the denominator of the FAIL rate, the UNVERIFIED share and
   the coverage fractions.
7. **The ERRORED record answers absent.** An `ERRORED` instance reports exposure `unrecorded`,
   never `0 compared` — a zero there would read as *"the detector was silent because it judged
   nothing"*, which is the fabricated finding this unit exists to prevent.
8. **Three states, three renderings** (M0): a fixture set containing one judged-and-clean instance,
   one zero-exposure instance and one legacy instance renders three distinct sentences, and no
   instance renders a bare silence.
9. **`combine` carries exposure** and **prints its merge rule**. A population whose captures
   disagree on exposure is reduced by the stated rule and the rule is visible in the output.
10. **`belay verify` surfaces it** on both the per-turn and aggregate paths, driving the real
    `verify_turn` — **not** a stubbed `verify=` seam (`CLAUDE.md`: *"a green suite was not evidence
    here"*).
11. **Byte-identical default behaviour** (M0b): the existing `phase0` suite passes unchanged, and a
    single-ledger control-free run's verdicts and rates are equal to today's.
12. **Deterministic and offline** — no network, no key, no clock read, no git sha read by the
    library (a version, if any, is injected by the CLI).

## Dependencies & sequencing

- **Depends on:** nothing. First aspect.
- **Blocks:** `miss-measurement` (which reports exposure). Independent of `corpus-recorded-miss`.

## Open questions / risks

- **Merge rule for `combine`:** sum-over-captures (matches `total_turns()`) or reduce-over-instances
  (matches the violation denominator)? Both defensible; **decide in tech-plan and print it**.
- **`compared` counts judgement attempts**, includes deletions, and increments before `_judge_file`
  may return `UNVERIFIED` (`:430` precedes `:431`). Document this where it is reported; do not
  silently redefine it to mean *decided*.
- **Blast radius:** nine return paths, three surfaces, one new accessor. The risk is a partial
  landing where one surface shows exposure and another shows silence — criterion 8 exists to catch
  exactly that.
