# Aspect spec — `root-cause-independence`

**Feature:** `phase0-corpus-audit` · **PRD:** `../prd.md` · **Aspect 1 of 2** (before `gate-audit`)

## Problem slice

The pre-registered gate criteria require *"≥3 **independent** hand-audited true positives"* with
*"each TP's root cause recorded beside it"* (`PHASE0_RESULTS.md:38,135`). The corpus can record
neither: `Case` has no root-cause field (`case.py:89-113`) and `Metrics` has no independence
notion (`metrics.py:92-102`). This aspect makes the criteria **evaluable from the corpus**.

It is pure engine work, test-first, and assigns **no labels** — adjudication is aspect 2.

## User outcome

`belay corpus score` prints the independent TP count with its grouping rule named, and
`belay corpus label --label true-positive` refuses to record a TP the gate could not evaluate.

## In scope

| Req | Behaviour |
|---|---|
| **M1** | `Case.root_cause: dict \| None` — `{"key": <kebab-case>, "note": <str>}`. Optional on load, **not** in `_REQUIRED_FIELDS`, **key omitted from `case.json` when absent**. Malformed shape → named `ValueError`. |
| **M3** | `Case.target_tool: str \| None` — optional, same absent-is-omitted rule. |
| **M2** | `set_label` rejects `true-positive` with no root cause, fail-closed, before touching disk. `false-positive`/`unverifiable` unaffected. |
| **M4** | `score()` returns primary + strict independent TP counts; CLI prints both with the grouping rule named; strict is `None` → `n/a` when any TP lacks `target_tool`. |
| **M5** | `score()` stays pure — no I/O, no clock, and reads nothing the engine computed. |
| **S1** | `corpus show` renders `root_cause` and `target_tool`. |
| **S2** | `corpus list` gains a root-cause-key column. |
| **S3** | `corpus add` records `target_tool` on newly ingested cases. |

### The independence rule, as implemented

- **Primary** — count distinct `root_cause.key` among TPs.
- **Strict** — a group is independent only if it differs in **both** instance and tool
  (the pre-registered gloss: *"three flags from one mis-annotated tool count as one finding"*).
  Instance derives from `provenance.source_trace_id`; tool from `target_tool`.
- Both print. The chosen strict reading is named in the output. See `../prd.md` → M4 for why the
  harder reading was chosen over the permissive one.

## Out of scope

- **Assigning any label or root cause to a real case** — aspect 2.
- Backfilling `target_tool` for the 7 existing cases — aspect 2 (it needs their traces).
- `corpus score --by-root-cause` (N1, nice-to-have).
- Any change to `expected`, `verdict.reduce`, the axes, or `NOT_COVERED`.
- A controlled root-cause vocabulary — rejected in the PRD as a guess from 7 cases.

## Acceptance criteria (written as failing tests FIRST)

**Schema — `tests/test_corpus_case.py`**
1. A case with `root_cause={"key": "k", "note": "n"}` round-trips byte-stably.
2. A case with `root_cause=None` **omits the key entirely** from `case.json` — asserted as
   `"root_cause" not in json.loads(...)`, not as `is None`.
3. An existing `case.json` with **neither** new key loads, and both fields read back `None`.
4. `root_cause` present but malformed → named `ValueError`, one test each: a bare string; a dict
   missing `key`; a `key` that is not kebab-case; a non-dict.
5. Same omit-when-absent and round-trip assertions for `target_tool`.
6. **Neither field appears in `_REQUIRED_FIELDS`** — a case lacking both is valid.

**Adjudication — `tests/test_corpus_label.py`**
7. `set_label(..., "true-positive")` with no root cause raises a named `ValueError` **and leaves
   `case.json` byte-identical** (fail-closed before touching disk).
8. `set_label(..., "true-positive", root_cause={...})` writes both label and root cause.
9. `set_label(..., "false-positive")` with no root cause succeeds.
10. **Regression guard:** labeling a case that already carries a `root_cause` preserves it — the
    round-trip-through-the-dataclass hazard (`curate.py:50-52`) that would silently erase it.
11. `expected` stays byte-identical across every labeling path (extends the existing test).
12. CLI: `--label true-positive` without `--root-cause` exits non-zero with a message naming the
    gate requirement.

**Metrics — `tests/test_corpus_metrics.py`**
13. Hand-computed: 3 TPs over 2 distinct root-cause keys → `independent == 2`.
14. 3 TPs, 3 instances, all one tool → **strict `== 1`** (the implemented reading), asserted
    against the hand-computed value with the rule named in the test docstring.
15. A TP lacking `target_tool` → strict is `None` (`n/a`), never a guess, never 0.
16. Zero TPs → both counts `0`, and `precision == 0.0` when FP > 0 (**not** `None` — this is the
    anticipated modal outcome and must be a real number).
17. FP/`unverifiable`/`pending` root causes are **ignored** by both counts.
18. `score()` performs no I/O — asserted by calling it with a `Case` whose paths do not exist.

**Rendering — `tests/test_coverage_rendering.py` or the CLI test module**
19. `corpus score` prints both counts, each with its grouping rule.
20. `corpus show` renders `root_cause.key`, `root_cause.note` and `target_tool`; a case without
    them renders them as absent, never as empty strings.

**Whole-suite**
21. `uv run pytest` green (baseline **966 passed, 1 skipped, 1 deselected**).
22. `belay corpus run` against the real 7-case corpus still reports MATCH for every case — the
    schema change must not perturb `expected`.

## Dependencies & sequencing

C1–C6 built and merged; nothing else blocks. **Must land before `gate-audit`**, which needs
`--root-cause` to exist in order to record adjudications.

## Risks specific to this aspect

| Risk | Mitigation |
|---|---|
| `root_cause` silently erased by `set_label`'s dataclass round-trip — the single most likely way to build this wrong | Criterion 10 exists solely to catch it |
| Adding a required field would reject all 7 banked cases | Criterion 6; follows the `schema_version` precedent (`case.py:64-69`) |
| A root cause derived from engine output would recreate the label-trap one level up | Criterion 18 plus review; `root_cause` is only ever set through `set_label` by a human |
| `corpus run` REGRESSION | Criterion 22; only `A2 / effect:network` diffs are expected (`PHASE0_RESULTS.md:149`) |

## Open question

Kebab-case validation for `root_cause.key`: strict `^[a-z0-9]+(-[a-z0-9]+)*$`. Chosen so a
typo'd key is a loud error rather than a silently split independence group. Flag if it proves
too strict during aspect 2.
