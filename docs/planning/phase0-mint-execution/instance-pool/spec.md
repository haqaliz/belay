# Aspect — `instance-pool`

**Unit:** `phase0-mint-execution` · **Sequence:** 3 of 5 (parallel with `mint-entrypoints`)
**Placement:** `eval/instances/` + committed data files

---

## Problem slice

The stratified draw (`eval/instances/selection.py:97`) is built and tested — and has **no pool
to draw from**. `pool.json`, `selected.json`, and the dataset fetch script **do not exist**
anywhere in the repo. The only committed instance data is one prose entry for
`pallets__flask-4045` in `eval/instances.md`.

Without a committed, seeded selection there is no denominator and no reproducible composition
to publish beside the number.

**User outcome:** the mint set is a committed artifact anyone can inspect, and the draw is
reproducible from `(pool, target, seed)`.

---

## In scope

1. **A dataset fetch** producing `pool.json` — SWE-bench-lite instances with
   `instance_id, repo, base_commit, problem_statement`, filtered to the strict-eligible pool
   (pure-Python repos, ≤15 changed lines, problem statement ≤2000 chars → 166 instances per
   `understanding.md:49-60`). `repo` is the **`owner/name` slug**, never a URL —
   `workspace.py:99` builds the clone URL and a URL double-prefixes.
2. **`selected.json`** = `select_instances(pool, target=~65-70, seed=<committed>)`, with the
   **seed committed beside it** so the draw is reproducible. Composition: all 28 small-repo
   instances (flask 1 / requests 4 / pylint 3 / pytest 7 / sphinx 13), topped up balanced from
   django+sympy.
3. **3 clean control instances**, marked by the `is_control` field
   (`eval/instances/registry.py:65`) — **a field, not a naming convention** — drawn into the
   same batch as the real instances. A control is a hand-written, trivially-correct task whose
   expected outcome is known and which violates nothing.
4. **Task strings** derived mechanically via `derive_task_string(problem_statement)`
   (`eval/instances/tasks.py:86`), except the controls', which are hand-written.

---

## Out of scope

- Hand-optimizing task strings for the real instances. Truncation changes the task; that is a
  **stated coverage caveat** in the results, not a bug.
- Relaxing the eligibility filters — ≥50 is reachable ~3× over at the strictest tier.
- Running SWE-bench evaluation. We never check whether the agent *solved* the instance.

---

## Acceptance criteria (test-first)

1. **`test_pool_fetch_produces_valid_registry`** — every fetched record passes registry
   validation; `repo` is a slug, not a URL.
2. **`test_draw_is_reproducible_from_seed`** — same `(pool, target, seed)` → identical
   `selected.json`. Byte-identical, committed.
3. **`test_draw_composition_is_stratified`** — all small-repo instances present; django/sympy
   top-up balanced; the published composition matches the file.
4. **`test_controls_are_marked_by_field_and_separable`** — `controls()` / `real()` partition
   the selection; 3 controls present.
5. **`test_control_task_is_trivially_correct`** — each control's task is hand-written and its
   expected outcome is stated in the file.
6. **`test_insufficient_pool_raises_rather_than_drawing_short`** — a short draw is a short
   denominator; `InsufficientPoolError` already enforces this and must stay.

Deterministic and offline: the fetch is a separate, network-touching script whose **output is
committed**, so the tests read the committed artifact rather than the network.

---

## Dependencies and sequencing

- **Depends on:** nothing in this unit (can run parallel with `mint-entrypoints`).
- **Blocks:** `mint-execution`.

---

## Open questions / risks

- **Concentration bias is not eliminated, only bounded.** Even stratified, django+sympy
  dominate the top-up. The composition **must be published beside the number** — an honesty
  property, not a footnote.
- Whether the fetch should pin a dataset revision so `pool.json` is re-derivable later.
  Strongly preferred; decide in the plan.
