"""RED-first contract tests for `eval/scripts/build_stage6_registries.py`.

The shell-toolset mint needs committed registries for its three stages:
stage 6a (one control probe), stage 6b (4 controls + 7 fresh real, controls at the
head — the positive control included so the trajectory axis has a by-design PASS
signal inside the stage that measures exposure), and stage 6c (the remaining fresh
non-control draw, driving the ≥50 denominator).

The generator reads `eval/instances/pool.json` (166 strict-eligible), excludes every
instance that has ever produced an observation — the 15 s2/s3-era banked ids plus
`pytest-7432` (the `build_stage4_registry` EXCLUDED set) AND the 7 s4/s5 banked real
captures from the committed ledgers — and draws 65 fresh real with a NEW seed
(20260812), superseding the 20260723 draw with the reason in `seed_history`.

Everything asserted here is about the SHAPE contract:

* `stage6a.json` is exactly the one read-only control (`CONTROL_RECORDS[0]`).
* `stage6b.json` is exactly 11 records: the 4 controls at the head in fixed order
  (`CONTROL_RECORDS` then `POSITIVE_CONTROL_RECORD`), then exactly 7 real records.
* `stage6c.json` is the remaining fresh real draw (the 65-draw minus stage 6b's 7),
  non-control only — controls partitioned out of the denominator by construction.
* No record in any stage-6 registry is in the 22-id banked exclusion set (fresh
  instances only).
* The 7 stage-6b real records are the first 7 fresh records of the small-repo block
  in file order — the committed stage-4 selection rule, asserted mechanically.
* Headers carry the provenance shape: `source_pool`, `target`, `seed: 20260812`,
  `seed_history` naming the superseded 20260723 draw, `composition`, `controls`
  (full `CONTROL_EXPECTATIONS`), and a descriptive `stage`.
* Re-running the generator into a second directory produces byte-identical files.
* The exclusion literal is well-formed: every id in it exists in `pool.json`.

Deterministic and offline: `tmp_path` only, no network, no clock.
"""

from __future__ import annotations

from pathlib import Path

from eval.instances.controls import (
    CONTROL_EXPECTATIONS,
    CONTROL_RECORDS,
    POSITIVE_CONTROL_RECORD,
)
from eval.instances.registry import load_header, load_registry
from eval.scripts.build_stage6_registries import (
    EXCLUDED_BANKED_IDS,
    POOL_PATH,
    STAGE_6_SEED,
    build_stage6_registries,
)

#: The repos whose records form the draw's small-repo block (flask, requests,
#: pylint, pytest, sphinx), in file order the generator walks.
SMALL_REPO_BLOCK = {
    "pallets/flask",
    "psf/requests",
    "pylint-dev/pylint",
    "pytest-dev/pytest",
    "sphinx-doc/sphinx",
}

DRAW_TARGET = 65
STAGE_6B_REAL = 7


def _first_fresh_small_repo_ids(draw: tuple, excluded, limit: int = 7) -> list[str]:
    """The selection rule asserted mechanically: the first `limit` records of the
    small-repo block in file order whose id is not in `excluded`."""
    return [
        record.instance_id
        for record in draw
        if record.repo in SMALL_REPO_BLOCK
        and not record.is_control
        and record.instance_id not in excluded
    ][:limit]


def test_excluded_literal_is_well_formed() -> None:
    pool_ids = {record.instance_id for record in load_registry(POOL_PATH)}
    assert EXCLUDED_BANKED_IDS <= pool_ids, (
        "every EXCLUDED id must exist in pool.json — the script's typo guard, "
        "asserted on the imported literal"
    )
    assert EXCLUDED_BANKED_IDS


def test_stage6a_is_exactly_the_read_only_control(tmp_path: Path) -> None:
    stage6a, _, _ = build_stage6_registries(tmp_path)
    records = load_registry(stage6a)
    assert [record.instance_id for record in records] == ["control__flask-read-only"]
    assert records[0].is_control is True


def test_stage6b_is_4_controls_then_7_fresh_real(tmp_path: Path) -> None:
    _, stage6b, _ = build_stage6_registries(tmp_path)
    records = load_registry(stage6b)
    expected_controls = [*CONTROL_RECORDS, POSITIVE_CONTROL_RECORD]
    assert [record.instance_id for record in records[:4]] == [
        record.instance_id for record in expected_controls
    ]
    assert len(records) == 4 + STAGE_6B_REAL
    real_records = [record for record in records if not record.is_control]
    assert len(real_records) == STAGE_6B_REAL
    for record in real_records:
        assert record.instance_id not in EXCLUDED_BANKED_IDS


def test_stage6c_is_the_remaining_fresh_non_control_draw(tmp_path: Path) -> None:
    _, _, stage6c = build_stage6_registries(tmp_path)
    records = load_registry(stage6c)
    assert not any(record.is_control for record in records)
    assert len(records) == DRAW_TARGET - STAGE_6B_REAL
    for record in records:
        assert record.instance_id not in EXCLUDED_BANKED_IDS


def test_stage6b_and_stage6c_are_disjoint_and_cover_the_draw(tmp_path: Path) -> None:
    _, stage6b, stage6c = build_stage6_registries(tmp_path)
    b_ids = {r.instance_id for r in load_registry(stage6b) if not r.is_control}
    c_ids = {r.instance_id for r in load_registry(stage6c)}
    assert not (b_ids & c_ids)
    assert len(b_ids | c_ids) == DRAW_TARGET


def test_stage6b_real_are_first_fresh_small_repo_of_the_draw(tmp_path: Path) -> None:
    """The stage-4 selection rule, asserted against the same inputs the script uses."""
    from eval.scripts.build_stage6_registries import _draw

    _, stage6b, _ = build_stage6_registries(tmp_path)
    drawn_real = [r for r in _draw() if not r.is_control]
    expected = _first_fresh_small_repo_ids(drawn_real, EXCLUDED_BANKED_IDS, limit=7)
    actual = [
        record.instance_id
        for record in load_registry(stage6b)
        if not record.is_control
    ]
    assert actual == expected


def test_headers_carry_the_provenance_shape(tmp_path: Path) -> None:
    stage6a, stage6b, stage6c = build_stage6_registries(tmp_path)
    for path, target, control_count, stage_name in (
        (stage6a, 1, 1, "stage-6a probe: 1 control"),
        (
            stage6b,
            11,
            4,
            "stage-6b: 4 controls + 7 fresh real, controls first, subset of the fresh draw",
        ),
        (
            stage6c,
            DRAW_TARGET - STAGE_6B_REAL,
            0,
            "stage-6c: the remaining fresh non-control draw (≥50 denominator)",
        ),
    ):
        header = load_header(path)
        assert header["source_pool"] == "eval/instances/pool.json"
        assert header["target"] == target
        assert header["seed"] == STAGE_6_SEED
        assert header["control_count"] == control_count
        assert header["stage"] == stage_name
        assert header["composition"]["real"] == target - control_count
        assert header["composition"]["controls"] == control_count
        assert set(header["controls"]) == set(CONTROL_EXPECTATIONS)
        history = header["seed_history"]
        assert any(entry.get("seed") == 20260723 for entry in history), (
            "the superseded 20260723 draw must be recorded in seed_history, never silently replaced"
        )


def test_regeneration_is_byte_identical(tmp_path: Path) -> None:
    first_dir = tmp_path / "a"
    second_dir = tmp_path / "b"
    first_dir.mkdir()
    second_dir.mkdir()
    first = build_stage6_registries(first_dir)
    second = build_stage6_registries(second_dir)
    for a, b in zip(first, second):
        assert a.read_bytes() == b.read_bytes()


def test_stage6b_control_fields_match_the_records(tmp_path: Path) -> None:
    """Records are copied, never rewritten — the round-trip property."""
    _, stage6b, _ = build_stage6_registries(tmp_path)
    pool = load_registry(POOL_PATH)
    by_id = {r.instance_id: r for r in pool}
    for record in load_registry(stage6b):
        if record.is_control:
            continue
        pool_record = by_id[record.instance_id]
        assert record == pool_record
