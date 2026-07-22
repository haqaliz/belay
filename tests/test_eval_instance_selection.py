"""The stratified, deterministic mint draw — `eval.instances.selection`.

Why these tests are the correctness-critical ones for this aspect: the strictly-eligible
SWE-bench-lite pool is ~166 instances, and ~83% of it is django + sympy. A naive draw of
50 would be a django/sympy measurement published as a general one. The stratification —
take *every* small-repo instance first, then top up from the two large repos in balance —
is the whole point of the function, so it is asserted directly rather than inferred from
the shape of the output.

Everything here runs against a **synthetic** pool, never the committed registry: the real
pool is regenerated data, and a test that pinned it would fail the next time the dataset
is refetched for reasons that have nothing to do with the draw.
"""

from __future__ import annotations

import pytest

from eval.instances.registry import InstanceRecord
from eval.instances.selection import (
    LARGE_REPOS,
    PURE_PYTHON_REPOS,
    InsufficientPoolError,
    select_instances,
)

SMALL_REPOS = ("pallets/flask", "psf/requests", "pylint-dev/pylint", "pytest-dev/pytest")
EXCLUDED_REPOS = (
    "matplotlib/matplotlib",
    "scikit-learn/scikit-learn",
    "astropy/astropy",
    "pydata/xarray",
    "mwaskom/seaborn",
)


def _record(repo: str, index: int) -> InstanceRecord:
    """One synthetic instance. Only `repo` and `instance_id` matter to the draw."""
    slug = repo.split("/")[-1]
    return InstanceRecord(
        instance_id=f"{slug}__{slug}-{index:04d}",
        repo=repo,
        base_commit=f"{index:040x}",
        problem_statement=f"synthetic problem statement {index}",
        task_string=f"synthetic task {index}",
    )


def _pool(counts: dict[str, int]) -> tuple[InstanceRecord, ...]:
    """A synthetic pool of `{repo: n}` instances, in a fixed declaration order."""
    return tuple(
        _record(repo, index)
        for repo, count in counts.items()
        for index in range(count)
    )


def _by_repo(records) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.repo] = counts.get(record.repo, 0) + 1
    return counts


def test_selection_is_deterministic_given_a_seed():
    """Same (pool, target, seed) → the identical list, twice. Spec criterion 1."""
    pool = _pool(
        {"django/django": 40, "sympy/sympy": 40, "pallets/flask": 5, "psf/requests": 4}
    )

    first = select_instances(pool, target=25, seed=1234)
    second = select_instances(pool, target=25, seed=1234)

    assert first == second
    assert len(first) == 25
    # A seed that actually seeds: a different one must be able to draw differently.
    assert select_instances(pool, target=25, seed=99) != first


def test_selection_takes_all_small_repo_instances_before_topping_up():
    """Every small-repo instance is drawn, and drawn first. Spec criterion 2."""
    counts = {
        "django/django": 60,
        "sympy/sympy": 60,
        "pallets/flask": 3,
        "psf/requests": 4,
        "pylint-dev/pylint": 2,
        "pytest-dev/pytest": 5,
        "sphinx-doc/sphinx": 6,
    }
    pool = _pool(counts)
    small_ids = {r.instance_id for r in pool if r.repo not in LARGE_REPOS}

    selected = select_instances(pool, target=40, seed=7)

    selected_ids = [r.instance_id for r in selected]
    assert len(selected_ids) == 40
    # every small-repo instance is present...
    assert small_ids <= set(selected_ids)
    # ...and none of them appears after a large-repo top-up.
    first_large = next(
        i for i, r in enumerate(selected) if r.repo in LARGE_REPOS
    )
    assert first_large == len(small_ids)
    assert all(r.repo in LARGE_REPOS for r in selected[first_large:])


def test_selection_balances_the_topup_between_django_and_sympy():
    """The top-up is split between the two large repos, not drawn from one.

    Spec criterion 3 — the concentration mitigation this aspect exists for.
    """
    pool = _pool({"django/django": 50, "sympy/sympy": 50, "pallets/flask": 6})

    selected = select_instances(pool, target=26, seed=11)

    counts = _by_repo(selected)
    assert counts["pallets/flask"] == 6
    # 20 top-ups, alternating → an exact 10/10 split.
    assert counts["django/django"] == 10
    assert counts["sympy/sympy"] == 10

    # An odd top-up splits as evenly as it can, the extra going to the tie-break repo.
    odd = _by_repo(select_instances(pool, target=27, seed=11))
    assert odd["django/django"] == 11
    assert odd["sympy/sympy"] == 10
    assert LARGE_REPOS[0] == "django/django"


def test_selection_excludes_non_pure_python_repos():
    """A C/Cython-toolchain repo can never be selected. Spec criterion 4.

    Allow-list semantics: an unknown repo appearing in a refetched dataset is excluded,
    not admitted by default.
    """
    counts = {repo: 20 for repo in EXCLUDED_REPOS}
    counts["unknown/newcomer"] = 20
    counts["django/django"] = 20
    counts["sympy/sympy"] = 20
    counts["pallets/flask"] = 5
    pool = _pool(counts)

    selected = select_instances(pool, target=30, seed=3)

    assert {r.repo for r in selected} <= PURE_PYTHON_REPOS
    for repo in EXCLUDED_REPOS + ("unknown/newcomer",):
        assert repo not in _by_repo(selected)


def test_selection_raises_when_pool_is_smaller_than_target():
    """An under-sized eligible pool is a loud error, never a short draw.

    Spec criterion 5: a silently short draw becomes a short denominator, which is the R6
    false-zero failure mode one layer up.
    """
    # 12 eligible instances, plus 100 ineligible ones that must not paper over the gap.
    pool = _pool(
        {
            "django/django": 5,
            "sympy/sympy": 4,
            "pallets/flask": 3,
            "matplotlib/matplotlib": 100,
        }
    )

    with pytest.raises(InsufficientPoolError) as excinfo:
        select_instances(pool, target=50, seed=1)

    message = str(excinfo.value)
    assert "12" in message  # the eligible pool size
    assert "50" in message  # the target


def test_selection_is_insensitive_to_input_ordering():
    """Shuffling the input pool cannot change the draw.

    The function sorts by `instance_id` before consuming any randomness, so file order,
    dict order, or fetch order cannot leak into the published set.
    """
    import random

    pool = list(
        _pool({"django/django": 30, "sympy/sympy": 30, "pallets/flask": 5, "psf/requests": 4})
    )
    reordered = list(pool)
    random.Random(2024).shuffle(reordered)
    assert reordered != pool  # the reorder actually reordered

    assert select_instances(tuple(reordered), target=20, seed=5) == select_instances(
        tuple(pool), target=20, seed=5
    )


def test_selection_samples_down_when_small_repos_already_meet_the_target():
    """More small-repo instances than the target → a deterministic sample, no top-up."""
    pool = _pool(
        {"django/django": 30, "sympy/sympy": 30, "pallets/flask": 10, "psf/requests": 10}
    )

    selected = select_instances(pool, target=12, seed=42)

    assert len(selected) == 12
    assert all(r.repo not in LARGE_REPOS for r in selected)
    assert select_instances(pool, target=12, seed=42) == selected
