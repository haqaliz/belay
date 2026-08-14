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
"""

from __future__ import annotations

from typing import Iterable

from eval.instances.controls import CONTROL_RECORDS, POSITIVE_CONTROL_RECORD
from eval.instances.registry import InstanceRecord

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


def fresh_pool(
    pool: Iterable[InstanceRecord], observed: Iterable[str]
) -> tuple[InstanceRecord, ...]:
    """The pool records whose ids are not in `observed` — the drawable universe.

    Preserves pool order. Controls cannot appear in `pool` by construction (they are
    hand-written and appended, never drawn), so the result is entirely real.
    """
    raise NotImplementedError(
        "fresh_pool() is not implemented yet: exclude every record whose instance_id "
        "is in `observed`, preserving pool order"
    )


def stage3_size(pool: Iterable[InstanceRecord], observed: Iterable[str]) -> int:
    """The number of fresh real instances the pool can still supply for stage 3."""
    raise NotImplementedError(
        "stage3_size() is not implemented yet: return len(fresh_pool(pool, observed))"
    )


def build_stage_registries(
    pool: Iterable[InstanceRecord], observed: Iterable[str]
) -> dict[str, list[dict]]:
    """The three stage registries as serialized record dicts, keyed by stage name.

    Returns `{"stage1": [...], "stage4": [...], "stage3": [...]}` where each record is
    a plain JSON-able dict in the registry's serialized key shape (`instance_id`,
    `repo`, `base_commit`, `problem_statement`, `task_string`, `is_control`), ready
    for `dump_registry`. Stage names and record order are part of the contract:
    stage1's controls first, stage4's controls first, stage3's controls appended.
    """
    raise NotImplementedError(
        "build_stage_registries() is not implemented yet: compose STAGE1_RECORDS, "
        "STAGE4_RECORDS + 7 fresh real, and select_instances(fresh_pool(pool, "
        "observed), target=STAGE3_REAL_TARGET, seed=STAGE3_SEED) + CONTROL_RECORDS, "
        "each record serialized in the registry's key shape"
    )


__all__ = [
    "STAGE1_RECORDS",
    "STAGE3_REAL_TARGET",
    "STAGE3_SEED",
    "STAGE4_RECORDS",
    "STAGE4_REAL_TARGET",
    "build_stage_registries",
    "fresh_pool",
    "stage3_size",
]
