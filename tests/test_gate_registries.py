"""RED contract tests for `eval/scripts/build_gate_registries.py`.

`registry-rescope/spec.md` AC-2..AC-7, pinned on the committed `pool.json` and the real
`controls.py` records: the gate mint's three stage registries must compose exactly as
pre-registered —

* stage1: CTL-1 + CTL-4, 2 records in that order;
* stage4: CTL-2 + CTL-3 + exactly 7 fresh real, 9 records, controls first;
* stage3: 80 fresh real + the 3 controls appended, 83 records, every real id never
  previously minted, seed recorded and draw reproducible;

— with task text taken verbatim from `controls.py` at generation time (AC-3), no real
id reused across stages (AC-4), byte-reproducible regeneration (AC-5), records in the
registry's serialized shape (AC-6), and the >=50 gate denominator expressible on the
artifact (AC-7).

The observed set used here is computed independently of the seam, from the same
committed sources (`EXCLUDED_INSTANCE_IDS` + the stage registries' real ids + the
smoke), so the composition tests cannot be self-confirming: `tests/test_observed_ids.py`
pins the seam's own derivation against the same sources.

No network, no clock: `pool.json` and the controls are committed files.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.instances.controls import (
    CONTROL_RECORDS,
    CONTROL_STEERING_SENTENCE,
    POSITIVE_CONTROL_RECORD,
)
from eval.instances.registry import load_registry, real
from eval.instances.selection import select_instances
from eval.scripts.build_gate_registries import (
    STAGE3_REAL_TARGET,
    STAGE3_SEED,
    build_stage_registries,
    fresh_pool,
    stage3_size,
)
from eval.scripts.build_stage4_registry import EXCLUDED_INSTANCE_IDS

REPO_ROOT = Path(__file__).parent.parent
POOL = REPO_ROOT / "eval" / "instances" / "pool.json"
INSTANCES_DIR = REPO_ROOT / "eval" / "instances"

_STAGE_REGISTRIES = ("stage2.json", "stage4.json", "stage4a.json")
SMOKE_INSTANCE_ID = "pytest-dev__pytest-7432"

#: The generation-time source of task text, by id (AC-3): a stage's control record
#: must carry the controls.py text verbatim.
CONTROLS_BY_ID = {
    record.instance_id: record
    for record in (*CONTROL_RECORDS, POSITIVE_CONTROL_RECORD)
}

#: The fixed composition (spec, AC-2) — order is part of the contract.
STAGE1_CONTROL_IDS = (
    "control__flask-read-only",
    "control__flask-verify-with-command",
)
STAGE4_CONTROL_IDS = (
    "control__flask-write-new-file",
    "control__requests-read-then-write",
)

#: The serialized key shape `dump_registry` accepts (AC-6).
REQUIRED_FIELDS = {
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "task_string",
    "is_control",
}


def _observed_from_committed() -> set[str]:
    """The previously-minted set, computed independently of the seam: the banked
    corpus literal plus the real ids of the committed stage registries plus the smoke.
    """
    ids = set(EXCLUDED_INSTANCE_IDS)
    for name in _STAGE_REGISTRIES:
        for record in real(load_registry(INSTANCES_DIR / name)):
            ids.add(record.instance_id)
    ids.add(SMOKE_INSTANCE_ID)
    return ids


def _built() -> dict[str, list[dict]]:
    return build_stage_registries(load_registry(POOL), _observed_from_committed())


def _real_ids(records: list[dict]) -> list[str]:
    return [record["instance_id"] for record in records if not record["is_control"]]


def _control_ids(records: list[dict]) -> list[str]:
    return [record["instance_id"] for record in records if record["is_control"]]


def test_builder_emits_exactly_three_stages() -> None:
    built = _built()
    assert sorted(built) == ["stage1", "stage3", "stage4"]


def test_stage1_composition() -> None:
    stage1 = _built()["stage1"]
    assert len(stage1) == 2
    assert [record["instance_id"] for record in stage1] == list(STAGE1_CONTROL_IDS), (
        "stage1 must be CTL-1 + CTL-4, in that order"
    )
    assert all(record["is_control"] is True for record in stage1)


def test_stage4_composition() -> None:
    stage4 = _built()["stage4"]
    ids = [record["instance_id"] for record in stage4]

    assert len(stage4) == 9
    assert ids[:2] == list(STAGE4_CONTROL_IDS), (
        "stage4 must lead with CTL-2 + CTL-3, in that order"
    )
    assert all(record["is_control"] for record in stage4[:2])

    real = _real_ids(stage4)
    assert len(real) == 7
    assert not (set(real) & _observed_from_committed()), (
        "stage4's real records must be fresh: never observed in any prior mint"
    )
    assert len(set(ids)) == len(ids), "stage4's 9 records must be distinct"


def test_stage3_composition() -> None:
    stage3 = _built()["stage3"]

    assert len(stage3) == 83
    real = _real_ids(stage3)
    assert len(real) == 80
    assert len(real) >= 50, (
        "AC-7: the >=50 gate denominator must be expressible on stage3's real records"
    )
    assert not (set(real) & _observed_from_committed()), (
        "stage3's real records must be fresh: never observed in any prior mint"
    )
    assert len(set(real)) == len(real), "stage3's 80 real records must be distinct"

    assert _control_ids(stage3) == [
        record.instance_id for record in CONTROL_RECORDS
    ], "the 3 controls must be appended after the draw, in CONTROL_RECORDS order"
    assert all(record["is_control"] for record in stage3[80:])


def test_no_cross_stage_remint() -> None:
    built = _built()
    real_by_stage = {name: set(_real_ids(records)) for name, records in built.items()}
    for first, second in (
        ("stage1", "stage4"),
        ("stage1", "stage3"),
        ("stage4", "stage3"),
    ):
        overlap = real_by_stage[first] & real_by_stage[second]
        assert not overlap, (
            f"no real id may appear in two stage files (AC-4); {first} x {second}: "
            f"{sorted(overlap)}"
        )


def test_control_text_verbatim() -> None:
    built = _built()
    for stage_name, records in built.items():
        for record in records:
            if not record["is_control"]:
                continue
            expected = CONTROLS_BY_ID[record["instance_id"]]
            assert record["task_string"] == expected.task_string, (
                f"{stage_name}: control {record['instance_id']!r} task text must come "
                f"verbatim from controls.py at generation time (AC-3)"
            )
            assert record["problem_statement"] == expected.problem_statement
            assert record["repo"] == expected.repo
            assert record["base_commit"] == expected.base_commit

    for control_id in STAGE4_CONTROL_IDS:
        expected = CONTROLS_BY_ID[control_id]
        assert CONTROL_STEERING_SENTENCE in expected.task_string, (
            f"{control_id} must carry the steering sentence in controls.py (AC-3)"
        )


def test_regeneration_is_reproducible() -> None:
    first = _built()
    second = _built()
    assert first == second
    assert json.dumps(first, indent=2, ensure_ascii=False) == json.dumps(
        second, indent=2, ensure_ascii=False
    ), "building twice from the same pool+observed must yield byte-identical JSON (AC-5)"


def test_stage3_draw_is_seeded_deterministic() -> None:
    pool = load_registry(POOL)
    observed = _observed_from_committed()

    built = build_stage_registries(pool, observed)
    stage3_real = set(_real_ids(built["stage3"]))

    fresh = fresh_pool(pool, observed)
    drawn = select_instances(fresh, target=STAGE3_REAL_TARGET, seed=STAGE3_SEED)
    assert stage3_real == {record.instance_id for record in drawn}, (
        "stage3 must be exactly select_instances(fresh_pool(pool, observed), "
        f"target={STAGE3_REAL_TARGET}, seed={STAGE3_SEED}): the seeded stratified "
        "draw, not an ad-hoc pick"
    )
    redrawn = select_instances(fresh, target=STAGE3_REAL_TARGET, seed=STAGE3_SEED)
    assert redrawn == drawn, "the seeded draw must reproduce itself identically"


def test_stage3_size_clears_the_gate_denominator() -> None:
    pool = load_registry(POOL)
    size = stage3_size(pool, _observed_from_committed())
    assert size >= STAGE3_REAL_TARGET, (
        f"the fresh pool supplies {size} instances, fewer than the stage-3 target of "
        f"{STAGE3_REAL_TARGET}; refusing to draw short"
    )
    assert size >= 50, "AC-7: the >=50 gate denominator must be drawable fresh"


def test_records_are_serialized_registry_shape() -> None:
    for stage_name, records in _built().items():
        for record in records:
            assert set(record) == REQUIRED_FIELDS, (
                f"{stage_name}: {record.get('instance_id')!r} must serialize in the "
                f"registry's key shape so dump_registry accepts it (AC-6)"
            )
            assert isinstance(record["is_control"], bool)
            for field in (
                "instance_id",
                "repo",
                "base_commit",
                "problem_statement",
                "task_string",
            ):
                assert isinstance(record[field], str) and record[field], (
                    f"{stage_name}: field {field!r} must be a non-blank string"
                )
