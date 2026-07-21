"""The stratified, deterministic draw that decides which instances the mint runs.

**This function is what keeps the published number from being a lie of composition.**
SWE-bench-lite under the strict Phase-0 filters leaves ~166 eligible instances, and about
83% of them are `django/django` + `sympy/sympy`. Drawing 50 uniformly would produce a
django/sympy violation rate presented as an agent violation rate. So the draw is
stratified:

1. filter to `PURE_PYTHON_REPOS` — an **allow-list**, so a repo that appears in a refetched
   dataset and is in neither list is excluded rather than silently admitted. The excluded
   repos (matplotlib, scikit-learn, astropy, xarray, seaborn) need a C/Cython/OpenMP
   toolchain and Debian-only system packages, which the mint substrate does not provide;
2. take **every** small-repo instance — they are the scarce diversity, so none is wasted;
3. top up from django and sympy **alternating**, so the concentration in the source dataset
   does not become concentration in the sample;
4. if the eligible pool is smaller than the target, **raise** — never draw short. A short
   draw is a short denominator, which is exactly the R6 false-zero failure mode the Phase-0
   runner exists to defend against one layer up.

Determinism is a hard requirement: the draw fixes what the published number covers, so it
must be reproducible from `(pool, target, seed)` alone. Randomness comes only from a local
`random.Random(seed)`; never the module-level `random`, never the clock. Candidates are
sorted by `instance_id` before any shuffle, so file order, dict order, or fetch order
cannot leak into the result.
"""

from __future__ import annotations

import random
from typing import Iterable, Sequence

from eval.instances.registry import InstanceRecord

#: The repos a Phase-0 instance may be drawn from. Allow-list semantics: anything absent
#: is excluded, including a repo that shows up in a future refetch of the dataset.
PURE_PYTHON_REPOS = frozenset(
    {
        "django/django",
        "sympy/sympy",
        "pytest-dev/pytest",
        "sphinx-doc/sphinx",
        "psf/requests",
        "pylint-dev/pylint",
        "pallets/flask",
    }
)

#: The two over-represented repos. They are the top-up pool only — never drawn before the
#: small repos are exhausted. Tuple, not a set: the order is the tie-break when an odd
#: top-up cannot be split evenly, and a set's iteration order is not a promise.
LARGE_REPOS = ("django/django", "sympy/sympy")


class InsufficientPoolError(ValueError):
    """The eligible pool cannot supply `target` instances.

    Raised instead of returning a short draw: a short draw silently shrinks the
    denominator of the published violation rate, which is the failure mode that makes a
    Phase-0 number wrong rather than merely small.
    """


def _sorted_by_id(records: Iterable[InstanceRecord]) -> list[InstanceRecord]:
    """Records in `instance_id` order — the canonical order before any randomness."""
    return sorted(records, key=lambda record: record.instance_id)


def _alternating_topup(
    candidates_by_repo: Sequence[list[InstanceRecord]], count: int
) -> list[InstanceRecord]:
    """Round-robin `count` records across the per-repo candidate lists, in list order.

    One pass takes at most one record from each repo, so the split stays balanced for any
    `count`; an odd remainder goes to the earlier repo (the `LARGE_REPOS` tie-break). A
    repo that runs out is skipped and the rest keep supplying — a shortfall in one large
    repo degrades the balance rather than the size of the draw. The caller has already
    guaranteed enough candidates exist in total.
    """
    picked: list[InstanceRecord] = []
    cursors = [0] * len(candidates_by_repo)
    while len(picked) < count:
        progressed = False
        for repo_index, candidates in enumerate(candidates_by_repo):
            if len(picked) >= count:
                break
            cursor = cursors[repo_index]
            if cursor >= len(candidates):
                continue
            picked.append(candidates[cursor])
            cursors[repo_index] = cursor + 1
            progressed = True
        if not progressed:  # pragma: no cover - unreachable given the caller's check
            break
    return picked


def select_instances(
    pool: Iterable[InstanceRecord], *, target: int, seed: int
) -> tuple[InstanceRecord, ...]:
    """Draw `target` instances from `pool`, stratified and reproducible.

    Pure: a function of `(pool, target, seed)` only. The returned tuple lists the
    small-repo instances first (in `instance_id` order), then the large-repo top-up in the
    order it was alternated, so the stratification is legible in the committed file.

    Raises `InsufficientPoolError` if fewer than `target` instances survive the
    pure-Python filter.
    """
    eligible = [record for record in pool if record.repo in PURE_PYTHON_REPOS]
    if len(eligible) < target:
        raise InsufficientPoolError(
            f"eligible pool has {len(eligible)} instances, fewer than the target of "
            f"{target}; refusing to draw short (a short draw is a short denominator)"
        )

    rng = random.Random(seed)

    small = _sorted_by_id(
        record for record in eligible if record.repo not in LARGE_REPOS
    )

    if len(small) >= target:
        # More diversity than we need: sample down rather than take a prefix, so the draw
        # is not biased toward whatever sorts first alphabetically.
        sampled = rng.sample(small, target)
        return tuple(_sorted_by_id(sampled))

    # Order the two large repos' candidates by a seeded shuffle. `LARGE_REPOS` order fixes
    # which repo is shuffled first, so the rng is consumed identically on every run.
    candidates_by_repo: list[list[InstanceRecord]] = []
    for repo in LARGE_REPOS:
        candidates = _sorted_by_id(
            record for record in eligible if record.repo == repo
        )
        rng.shuffle(candidates)
        candidates_by_repo.append(candidates)

    topup = _alternating_topup(candidates_by_repo, target - len(small))
    return tuple(small) + tuple(topup)


__all__ = [
    "PURE_PYTHON_REPOS",
    "LARGE_REPOS",
    "InsufficientPoolError",
    "select_instances",
]
