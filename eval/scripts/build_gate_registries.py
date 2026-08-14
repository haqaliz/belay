"""The gate mint's three stage registries, generated from pool + observed.

`registry-rescope/spec.md` fixes the composition of the gate mint (the run that can
clear the >=50-instance gate): one probe stage, one 9-record stage, and the >=50
denominator stage itself. Everything here is a pure function of `(pool, observed)` plus
the hand-written controls — no clock, no network, no module-level `random` — so the
committed stage files regenerate byte-identically and the composition is test-pinned:

* **stage1** (probe): CTL-1 + CTL-4 — 2 records, in that order;
* **stage4**: CTL-2 + CTL-3 + 7 fresh real — 9 records, controls first;
* **stage3** (the >=50 denominator): a fresh draw of 80 real + the 3 controls appended
  — 83 records. Drawn with `select_instances` on the pool minus `observed` under
  `STAGE3_SEED`, so the 83% django+sympy rebalance, the small-repo block and the
  no-silent-re-roll rules of `selection.py` are preserved unchanged.

`observed` is the previously-minted set (`eval/scripts/derive_observed_ids.py`): every
real id that has ever been driven live. No real id may be drawn twice, and no real id
may be previously-minted — both are asserted by `tests/test_gate_registries.py`
(AC-4/AC-2). Controls are placed exactly as the spec orders them, and their task text
is taken verbatim from `controls.py` at generation time (AC-3).

**Why stage4 draws from stage3's remainder (AC-4, by construction).** The committed
pool has 28 small-repo records and stage3's 80-real draw takes *every* one of them (the
small-repo block is exhausted before the large-repo top-up), so a stage4 draw from the
same fresh pool would collide with stage3's real ids — a cross-stage re-mint. Stage3 is
therefore drawn first on the full fresh pool (the >=50 denominator is the gate's
load-bearing artifact, and the RED test pins its draw exactly), and stage4 draws its 7
fresh real from the pool that draw leaves over, under `STAGE4_SEED`. Disjointness is
then a construction property, not a coincidence. The stage4 remainder is large-repo-only
in this pool — the same shape `build_stage4_registry.py`'s `_select_fresh_real` reaches
when the small-repo block cannot supply 7.
"""

from __future__ import annotations

from typing import Iterable

from eval.instances.controls import CONTROL_RECORDS, POSITIVE_CONTROL_RECORD
from eval.instances.registry import InstanceRecord
from eval.instances.selection import select_instances

#: Stage 1 (probe): CTL-1 + CTL-4, in that order (spec: 2 records).
STAGE1_RECORDS: tuple[InstanceRecord, ...] = (
    CONTROL_RECORDS[0],
    POSITIVE_CONTROL_RECORD,
)

#: Stage 4's control head: CTL-2 + CTL-3, in that order (spec: controls first).
STAGE4_RECORDS: tuple[InstanceRecord, ...] = (
    CONTROL_RECORDS[1],
    CONTROL_RECORDS[2],
)

#: Stage 4's fresh real count (spec: 7 fresh real, 9 records).
STAGE4_REAL_TARGET = 7

#: Stage 3's fresh real count (spec: 80 real + 3 controls = 83 records). 80 clears
#: the >=50 gate denominator through ~37% attrition.
STAGE3_REAL_TARGET = 80

#: The gate draw's committed seed: the date this composition was fixed (2026-08-14).
#: Drawn once and committed; a change must be recorded in the header's seed history,
#: never silent (the no-silent-re-roll rule of `selection.py`).
STAGE3_SEED = 20260814

#: Stage 4's draw seed: the same composition date. The draw runs on the pool stage 3's
#: draw leaves over (see the module docstring), so it is a *different* draw than
#: stage3's — same date, distinct pool and target, both reproducible from
#: `(pool, target, seed)` per `selection.py`.
STAGE4_SEED = 20260814


def fresh_pool(
    pool: Iterable[InstanceRecord], observed: Iterable[str]
) -> tuple[InstanceRecord, ...]:
    """The pool records whose ids are not in `observed` — the drawable universe.

    Preserves pool order. Controls cannot appear in `pool` by construction (they are
    hand-written and appended, never drawn), so the result is entirely real.
    """
    observed_ids = set(observed)
    return tuple(record for record in pool if record.instance_id not in observed_ids)


def stage3_size(pool: Iterable[InstanceRecord], observed: Iterable[str]) -> int:
    """The number of fresh real instances the pool can still supply for stage 3."""
    return len(fresh_pool(pool, observed))


def _serialize(record: InstanceRecord) -> dict:
    """One record in the registry's serialized key shape (`dump_registry`'s)."""
    return {
        "instance_id": record.instance_id,
        "repo": record.repo,
        "base_commit": record.base_commit,
        "problem_statement": record.problem_statement,
        "task_string": record.task_string,
        "is_control": record.is_control,
    }


def build_stage_registries(
    pool: Iterable[InstanceRecord], observed: Iterable[str]
) -> dict[str, list[dict]]:
    """The three stage registries as serialized record dicts, keyed by stage name.

    Returns `{"stage1": [...], "stage4": [...], "stage3": [...]}` where each record is
    a plain JSON-able dict in the registry's serialized key shape (`instance_id`,
    `repo`, `base_commit`, `problem_statement`, `task_string`, `is_control`), ready
    for `dump_registry`. Stage names and record order are part of the contract:
    stage1's controls first, stage4's controls first, stage3's controls appended.

    Stage 3 is drawn first on the full fresh pool; stage 4 draws from the remainder, so
    no real id appears in two stages (AC-4). Raises `InsufficientPoolError` (from
    `select_instances`) rather than drawing short.
    """
    fresh = fresh_pool(pool, observed)

    stage3_drawn = select_instances(fresh, target=STAGE3_REAL_TARGET, seed=STAGE3_SEED)
    stage3_records = [_serialize(record) for record in stage3_drawn] + [
        _serialize(record) for record in CONTROL_RECORDS
    ]

    stage3_ids = {record.instance_id for record in stage3_drawn}
    stage4_pool = [record for record in fresh if record.instance_id not in stage3_ids]
    stage4_drawn = select_instances(
        stage4_pool, target=STAGE4_REAL_TARGET, seed=STAGE4_SEED
    )
    stage4_records = [_serialize(record) for record in (*STAGE4_RECORDS, *stage4_drawn)]

    stage1_records = [_serialize(record) for record in STAGE1_RECORDS]

    return {
        "stage1": stage1_records,
        "stage4": stage4_records,
        "stage3": stage3_records,
    }


__all__ = [
    "STAGE1_RECORDS",
    "STAGE3_REAL_TARGET",
    "STAGE3_SEED",
    "STAGE4_RECORDS",
    "STAGE4_REAL_TARGET",
    "STAGE4_SEED",
    "build_stage_registries",
    "fresh_pool",
    "stage3_size",
]
