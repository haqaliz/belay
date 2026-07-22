# Aspect spec — `instance-registry`

**Parent PRD:** `docs/planning/phase0-live-mint/prd.md` (must-haves 1, 2; part of 15)
**Sequencing:** first. `batch-harness` consumes this aspect's output type.

## Problem slice

The mint needs `instance_id → (repo, base_commit, problem_statement, task_string)` as
**data**. Today `eval/instances.md` is hand-written prose with exactly one entry
(`pallets__flask-4045`), and there is no loader, no selection logic, and no task-string
generation. A 50-instance mint cannot be driven from prose.

## In scope

1. **A machine-readable registry format** under `eval/` — the selected pool as data, with
   `instance_id`, `repo`, `base_commit`, `problem_statement` (or a truncation of it), and
   the derived `task_string`. Committed, so the mint is reproducible from the repo.
2. **A pure selection function** implementing the stratified draw:
   - eligible pool = pure-Python repos only (django, sympy, pytest, sphinx, requests,
     pylint, flask) — excludes matplotlib, scikit-learn, astropy, xarray, seaborn;
   - take **all** instances from the small repos (flask, requests, pylint, pytest, sphinx);
   - top up to the launch target from django + sympy, **balanced between them**;
   - deterministic given (pool, target, seed) — same inputs, same draw.
3. **Task-string generation** from `problem_statement`: mechanical, truncated, deterministic.
   No LLM in the loop, no hand-tuning per instance.
4. **Control instances** (PRD must-have 15) marked as such in the registry, so the harness
   and the audit can tell a control from a real instance.
5. A documented, re-runnable way to regenerate the registry from the HuggingFace
   datasets-server API — a script or documented procedure, not a one-off paste.

## Out of scope

- Cloning repos or touching the filesystem (that is `batch-harness`).
- Any network call at mint time — the registry is committed data; the fetch is a separate,
  explicit regeneration step.
- Relaxing the pure-Python constraint (PRD: expensive lever, not needed at n=50).
- Any change to `src/belay/`.

## Acceptance criteria (test-first)

1. `test_selection_is_deterministic_given_a_seed` — same (pool, target, seed) yields the
   identical instance list, twice.
2. `test_selection_takes_all_small_repo_instances_before_topping_up` — with a synthetic
   pool, every flask/requests/pylint/pytest/sphinx instance appears before any django or
   sympy top-up.
3. `test_selection_balances_the_topup_between_django_and_sympy` — the top-up is split
   between the two large repos rather than drawn from one.
4. `test_selection_excludes_non_pure_python_repos` — no matplotlib/sklearn/astropy/
   xarray/seaborn instance can be selected, even if present in the input pool.
5. `test_selection_raises_when_pool_is_smaller_than_target` — an under-sized pool is a
   loud error, never a silently short draw (a short draw becomes a short denominator,
   which is the R6 false-zero failure mode one layer up).
6. `test_task_string_is_derived_deterministically_from_the_problem_statement` — same
   statement, same string; and the string is non-empty and bounded in length.
7. `test_registry_round_trips` — the committed registry loads into the expected records
   with every required field present; a missing field is a named error, not a `None`.
8. `test_control_instances_are_marked_and_separable` — controls are distinguishable from
   real instances by a field, not by naming convention.

All deterministic, no network, CI-safe.

## Dependencies

None beyond the existing repo. The dataset facts (300 instances; repo distribution; 166
strict-eligible) are recorded in the parent PRD and `understanding.md`.

## Risks / open questions

- **Truncating `problem_statement` changes the task.** A truncated statement may omit the
  actual requirement, making the agent attempt something different from the benchmark's
  intent. This is a stated coverage caveat in the results, not a bug — but the truncation
  bound should be generous and the behavior documented.
- **`base_commit` availability** — the registry records it, but whether a shallow fetch of
  that commit succeeds is `batch-harness`'s problem and may retire instances at prep time.
  The selection function must therefore be re-runnable to draw replacements.
