# Aspect — `corpus-recorded-miss`

**Unit:** `under-firing-measurable` · **Order: SECOND.** Covers PRD must-haves M-5 … M-9.

---

## Problem slice

`FN 0` is an artifact of construction. `phase0/runner.py:255` —
`flagged_turns = [n for n in range(len(calls)) if verdicts[n].status is Status.FAIL]` — is the only
automated ingest population, so a violation the detector **misses** never becomes a case, and the
corpus cannot measure recall (`CLAUDE.md`; `phase0-record-correction/spec.md:41`).

**Two corrections to the assumed shape, both verified:**

1. **The store already supports it.** `add_case` enforces no precondition on verdict status
   (`verdict` is read once, at `add.py:336`); `belay corpus add --turn N` applies no FAIL filter
   (`cli.py:764-845`); `metrics.py:242-243`'s FN branch is implemented **and unit-tested**
   (`tests/test_corpus_metrics.py:95`). The manual path exists — undocumented, and contradicted by
   its own help text, which asserts *"one flagged turn"* (`cli.py:1683`, `:1699`, `add.py:1,272`).
2. **The real defect is that `corpus run` inverts on a stored miss.** A recorded miss has
   `expected.reduced_status == "PASS"`; `classify_case` (`run.py:201-228`) compares against
   `expected` alone. So it reports **MATCH** — *the regression suite certifies that the engine still
   misses it* — and flips to **REGRESSION**, exit 1 (`cli.py:908-914`), **the day the detector is
   sharpened to catch it. CI goes red for a fix.**

## User outcome

A violation the engine missed can be recorded as evidence, scored as a false negative, and watched
over time — and the day the engine starts catching it, that is reported as **progress**, not as a
regression.

## Design decision (settled at the review gate, 2026-08-03)

**A schema-v3 declaration read by `classify_case`, plus a distinct reported outcome that does not
count as a regression.** The rejected alternative — a fourth outcome derived purely from the
comparison, with no schema change — was declined because it would have to *infer* "this PASS is a
recorded miss" from the shape of the diff, and inference is exactly what `case.py`'s
*"a default is never a declaration"* discipline forbids.

**`classify_case` must not read `human_label`** — that would couple regression detection to the very
labels `corpus score` scores independently.

## In scope

- **Case schema v3:** an **optional** declaration that this case's `expected` verdict is a
  **recorded miss**, not guarded behaviour. Omitted ⇒ undeclared (a normal case), exactly as
  `task_prestate` / `root_cause` do it (`case.py:233-249`); a malformed value raises a **named**
  `ValueError`; **never** added to `_REQUIRED_FIELDS` — *"a required new field would reject every
  case already sitting in `corpus/local/`"*.
- **The engine never sets it.** It is a human declaration, arriving the way a label does — the D3
  boundary of `add.py:34-42` (*"no code path from `verdict` to `human_label`"*) applied to a second
  field.
- **`classify_case` stops inverting**, for declared recorded-miss cases only:
  - recomputed still misses ⇒ **not `MATCH`** (a MATCH would certify blindness as a pass);
  - recomputed now catches it ⇒ a distinct outcome that **does not set `has_regression`** and does
    **not** exit 1;
  - any other divergence ⇒ **`REGRESSION`**, unchanged.
- **`_SKIP_CAUSES` is NOT widened** (`run.py:31-35`) — a SKIP means *"this box could not evaluate
  the case"*, an environment gap; a recorded miss is identical on every box.
- **An opt-in ingest population on `phase0 run`:** explicitly named turn indices, landing in **new**
  `InstanceRecord` buckets, routed through the same `except ValueError` discipline so a collision
  stays a `CaseExistsError` and can never become `ERRORED`.
- **`corpus score` names FN's provenance** so a recorded miss cannot be mistaken for a detection;
  `_ratio`/`_rate` keep rendering a zero denominator as `n/a`.
- **Help text corrected** at `cli.py:1683`, `:1699`, `add.py:1`, `add.py:272`.
- **`corpus list` / `show` surface the declaration** (should-have).

## Out of scope

- Changing `metrics.py`'s matrix — it is already correct.
- Auto-labeling anything. A miss-case still lands `pending` and is adjudicated through
  `belay corpus label`, which requires a human `root_cause` key for `true-positive`
  (`curate.py:74-79`).
- Any `--overwrite` / `--force` on `corpus add` — *"the engine must not have a supported path to
  overwrite a human adjudication"* (`corpus-collision-guard/spec.md:72-75`).
- Exposure accounting → `a1-exposure-accounting`. The measurement → `miss-measurement`.

## Acceptance criteria (test-first)

1. **A case without the declaration behaves exactly as today** — every existing corpus test passes
   unchanged; a v2 case loads and classifies identically.
2. **A malformed declaration raises a named `ValueError`**, fail-closed, matching every other field
   in `case.py`.
3. **The declaration is never inferred.** No code path sets it from a verdict, a status, or a
   label — asserted structurally, in the spirit of `add.py:34-42`.
4. **A declared recorded miss that is still missed does NOT classify `MATCH`**, and `corpus run`
   exits **0** — the state is known, not a regression, but it must be visible.
5. **A declared recorded miss that is now caught does NOT classify `REGRESSION`** and does **not**
   exit 1. *This is the criterion that stops CI going red for a fix.*
6. **Any other divergence on a declared case still classifies `REGRESSION`** — the escape is narrow
   and does not become a blanket exemption.
7. **`classify_case` never reads `human_label`** — asserted, because coupling classification to the
   labels the metric scores would corrupt both.
8. **`_SKIP_CAUSES` is unchanged** — asserted as a closed set, so a recorded miss cannot be quietly
   filed as an environment gap.
9. **An opt-in ingested non-flagged turn produces a case** whose `expected.reduced_status` is
   `PASS`.
10. **…and it does not move the numerator.** `flagged_turns`, the disposition,
    `violation_denominator()` and `violating_instances()` are **provably unchanged** by the opt-in
    ingest — asserted directly, not inspected.
11. **A collision on the opt-in path is a `CaseExistsError`**, bucketed like the existing path,
    never `ERRORED`, and never shrinks the denominator.
12. **`corpus score` produces a non-zero FN** from a stored `PASS` case labeled `true-positive`, and
    recall renders with its real denominator; a zero denominator still renders `n/a`, never `1.00`
    and never `0.00`.
13. **The help text no longer asserts a precondition the code does not have** — asserted on the
    parser's help strings, since the wrong claim is what sent a reader looking for a filter that
    was never there.
14. **Deterministic and offline** — no network, no key, `captured_at` stays injected.

## Dependencies & sequencing

- **Depends on:** nothing in code; sequenced after `a1-exposure-accounting` to keep the diff
  reviewable. **Blocks:** `miss-measurement` (which stores an adjudicated miss).

## Open questions / risks

- **Declaration shape:** boolean, or an object naming *why* the case is stored (miss / guarded /
  fixture)? A boolean is smaller; an object ages better and matches `root_cause`'s precedent.
  → tech-plan.
- **Outcome naming** for criteria 4 and 5 — they are user-visible strings and land in the release
  notes. Pick names that read correctly to someone who has never seen this spec.
- **The escape must stay narrow.** Criterion 6 is the guard: a recorded-miss declaration must
  exempt exactly one transition, not disable regression detection for the case.
- **What a green `corpus run` means changes again**, and that must be stated on the surface —
  `CLAUDE.md` has had to correct this reading twice already.
