"""RED-first contract tests for `eval/scripts/build_stage4_registry.py`.

The funded mint needs committed registries for stage 1 (one control) and stage 2 (3
controls + 7 real, controls at the head). The generator reads `selected.json` plus the
hardcoded EXCLUDED set (the s2/s3-banked instances) and emits both registries
deterministically, offline, through the shipped `dump_registry` writer so the records
round-trip through `load_registry` by construction.

Everything asserted here is about the SHAPE contract (`stage-registries/spec.md`):

* `stage4a.json` is exactly the one read-only control, `is_control` true, fields
  identical to `CONTROL_RECORDS[0]`.
* `stage4.json` is exactly 10 records: the 3 controls at the head in `CONTROL_RECORDS`
  order, then exactly 7 real records.
* Each of the 7 real records exists in `selected.json` with identical fields (records
  are copied, never rewritten).
* None of the 7 real ids is in the EXCLUDED set (fresh instances only).
* The 7 real records are the first 7 fresh records of the small-repo block in file
  order — the selection rule, asserted mechanically against the same inputs.
* Both headers carry the stage2.json provenance shape: `source_pool`, `target`,
  `seed: 20260723`, `seed_history: []`, `composition`, `controls` with
  `CONTROL_EXPECTATIONS`, and a descriptive `stage`.
* Re-running the generator into a second directory produces byte-identical files.
* The EXCLUDED literal is well-formed: every id in it exists in `selected.json` (the
  script's own typo guard, asserted here on the imported constant).

Deterministic and offline: `tmp_path` only, no network, no clock.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.instances.controls import CONTROL_EXPECTATIONS, CONTROL_RECORDS
from eval.instances.registry import load_header, load_registry
from eval.scripts.build_stage4_registry import (
    EXCLUDED_INSTANCE_IDS,
    SELECTED_PATH,
    build_stage4_registries,
)

#: The repos whose records form selected.json's small-repo block, in file order the
#: generator walks (flask, requests, pylint, pytest, sphinx).
SMALL_REPO_BLOCK = {
    "pallets/flask",
    "psf/requests",
    "pylint-dev/pylint",
    "pytest-dev/pytest",
    "sphinx-doc/sphinx",
}


def _first_fresh_small_repo_ids(selected_path: Path, excluded, limit: int = 7) -> list[str]:
    """The selection rule asserted mechanically: the first `limit` records of the
    small-repo block in file order whose id is not in `excluded`."""
    selected = load_registry(selected_path)
    return [
        record.instance_id
        for record in selected
        if record.repo in SMALL_REPO_BLOCK
        and not record.is_control
        and record.instance_id not in excluded
    ][:limit]


def test_excluded_literal_is_well_formed() -> None:
    selected_ids = {record.instance_id for record in load_registry(SELECTED_PATH)}
    assert EXCLUDED_INSTANCE_IDS <= selected_ids, (
        "every EXCLUDED id must exist in selected.json — the script's typo guard, "
        "asserted on the imported literal"
    )
    assert EXCLUDED_INSTANCE_IDS


def test_stage4a_is_exactly_the_read_only_control(tmp_path: Path) -> None:
    stage4a, _ = build_stage4_registries(tmp_path)
    records = load_registry(stage4a)
    assert [record.instance_id for record in records] == ["control__flask-read-only"]
    assert records[0].is_control is True
    assert records[0] == CONTROL_RECORDS[0]


def test_stage4_has_controls_first_then_exactly_seven_real(tmp_path: Path) -> None:
    _, stage4 = build_stage4_registries(tmp_path)
    records = load_registry(stage4)
    assert len(records) == 10
    assert [record.instance_id for record in records[:3]] == [
        control.instance_id for control in CONTROL_RECORDS
    ]
    assert all(record.is_control for record in records[:3])
    real = records[3:]
    assert len(real) == 7
    assert not any(record.is_control for record in real)


def test_control_records_match_control_records(tmp_path: Path) -> None:
    _, stage4 = build_stage4_registries(tmp_path)
    records = load_registry(stage4)
    assert records[:3] == CONTROL_RECORDS
    assert [record.is_control for record in records[:3]] == [True, True, True]


def test_seven_real_are_fresh_and_byte_identical_to_selected(tmp_path: Path) -> None:
    _, stage4 = build_stage4_registries(tmp_path)
    records = load_registry(stage4)
    real = records[3:]

    selected_records = {record.instance_id: record for record in load_registry(SELECTED_PATH)}
    selected_raw = {
        record["instance_id"]: record
        for record in json.loads(SELECTED_PATH.read_text(encoding="utf-8"))["instances"]
    }
    emitted_raw = {
        record["instance_id"]: record
        for record in json.loads(stage4.read_text(encoding="utf-8"))["instances"]
    }

    for record in real:
        assert record.instance_id not in EXCLUDED_INSTANCE_IDS, (
            "a real instance in stage4.json must be fresh (never captured in s2/s3)"
        )
        assert record == selected_records[record.instance_id], (
            "real records must be copied from selected.json with identical fields"
        )
        assert emitted_raw[record.instance_id] == selected_raw[record.instance_id], (
            "real records must be byte-identical to their selected.json counterpart"
        )


def test_seven_real_are_the_first_fresh_small_repo_records_in_file_order(tmp_path: Path) -> None:
    _, stage4 = build_stage4_registries(tmp_path)
    real_ids = [record.instance_id for record in load_registry(stage4)[3:]]
    expected = _first_fresh_small_repo_ids(SELECTED_PATH, EXCLUDED_INSTANCE_IDS, limit=7)
    assert real_ids == expected
    assert len(expected) == 7, "the small-repo block must be able to supply 7 fresh records"


def test_headers_carry_seed_and_controls_expectations(tmp_path: Path) -> None:
    stage4a, stage4 = build_stage4_registries(tmp_path)

    for path, target in ((stage4a, 1), (stage4, 10)):
        header = load_header(path)
        assert header["seed"] == 20260723
        assert header["seed_history"] == []
        assert header["target"] == target
        assert header["source_pool"] == "eval/instances/selected.json"
        assert isinstance(header["stage"], str) and header["stage"]
        assert header["controls"] == json.loads(json.dumps(CONTROL_EXPECTATIONS))

    composition = load_header(stage4)["composition"]
    assert composition["launched"] == 10
    assert composition["real"] == 7
    assert composition["controls"] == 3
    assert composition["by_repo"] == {"pytest-dev/pytest": 2, "sphinx-doc/sphinx": 5}

    composition_a = load_header(stage4a)["composition"]
    assert composition_a["launched"] == 1
    assert composition_a["real"] == 0
    assert composition_a["controls"] == 1


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    first_out = tmp_path / "first"
    second_out = tmp_path / "second"
    first_out.mkdir()
    second_out.mkdir()

    stage4a_first, stage4_first = build_stage4_registries(first_out)
    stage4a_second, stage4_second = build_stage4_registries(second_out)

    assert stage4a_first.read_bytes() == stage4a_second.read_bytes()
    assert stage4_first.read_bytes() == stage4_second.read_bytes()
