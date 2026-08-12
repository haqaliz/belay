"""Deterministic, offline generator for the stage-6 registries (shell-toolset mint).

The shell-toolset mint needs committed registries for its three stages:

* `stage6a.json` — 1 control (the read-only probe), mirroring `stage4a.json`.
* `stage6b.json` — 4 controls at the head (the 3 `CONTROL_RECORDS` + the positive
  control `POSITIVE_CONTROL_RECORD`, per `controls-rescope/composition-note.md`)
  + 7 fresh real, controls first.
* `stage6c.json` — the remaining fresh non-control draw (65 drawn − 7 in stage 6b
  = 58), driving the ≥50 denominator. Controls are partitioned out by construction,
  never driven in stage 3.

Selection: this mint draws FRESH from `pool.json` (166 strict-eligible) with a NEW
seed (20260812), because the stage-4 subset of the 20260723 draw cannot supply the
≥50 denominator after the s4/s5 banked captures — the superseded draw and the reason
are recorded in each header's `seed_history`, never silently replaced.

Exclusion: every instance that has ever produced an observation — the 15
s2/s3-era banked ids plus `pytest-7432` (the `build_stage4_registry` EXCLUDED set)
AND the 7 s4/s5 banked real captures transcribed from the committed ledgers
(`docs/planning/phase0-mint-run/mint-run/ledgers/s4b.json`,
`docs/planning/phase0-remint/mint-run/ledgers/s5b.json`). The EXCLUDED literal is a
committed frozenset: a transcription error is visible in the diff, and the script
fails loud if any id in it is absent from `pool.json`.

The 7 stage-6b real records are the first 7 fresh records of the small-repo block in
file order — the committed stage-4 selection rule — topped up from django/sympy in
file order only if the block cannot supply 7. Fewer than 7 anywhere is a loud
AssertionError, never a silently shorter registry.

No network, no clock, no module-level randomness. Deterministic output:
`dump_registry` owns key order and the trailing newline.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.instances.controls import (
    CONTROL_EXPECTATIONS,
    CONTROL_RECORDS,
    POSITIVE_CONTROL_RECORD,
)
from eval.instances.registry import InstanceRecord, dump_registry, load_registry
from eval.instances.selection import select_instances
from eval.scripts.build_stage4_registry import (
    EXCLUDED_INSTANCE_IDS as BANKED_S2_S3_IDS,
    SMALL_REPO_BLOCK,
)

_SCRIPT_DIR = Path(__file__).resolve().parent

#: The strict-eligible pool the fresh draw is made from.
POOL_PATH = _SCRIPT_DIR.parent / "instances" / "pool.json"

#: The fresh draw seed. Chosen 2026-08-12 (the day the draw was fixed), BEFORE any
#: inspection of the draw: the stage-4 subset of the 20260723 draw has ~43 fresh
#: instances left after the s4/s5 exclusions — short of the ≥50 denominator — so a
#: new draw is required, and its seed is recorded as a supersession, never silently.
STAGE_6_SEED = 20260812

#: The superseded draw and why, recorded in every stage-6 header's `seed_history`.
SUPERSEDED_SEED_HISTORY: list[dict[str, object]] = [
    {
        "seed": 20260723,
        "reason": (
            "The stage-4 subset of this draw supplies ~43 fresh non-control instances "
            "after the s4/s5 banked captures — short of the ≥50 denominator. Stage 6 "
            "draws fresh from pool.json (seed 20260812)."
        ),
    }
]

#: The drawn real-instance target — the draw_mint_set TARGET decision (D4): 65 leaves
#: the ≥50 denominator intact through ~23% attrition.
DRAW_TARGET = 65

#: Stage-6b takes 7 fresh real (the committed stage-4 rule).
STAGE_6B_REAL = 7

#: Every instance that has ever produced an observation. The 15 s2/s3-era ids are
#: `build_stage4_registry.EXCLUDED_INSTANCE_IDS` (transcribed 2026-08-09 from
#: PHASE0_RESULTS.md, verified against the miss-measurement ledgers). The 7 s4/s5 ids
#: are the union of the real captures in the committed ledgers
#: `docs/planning/phase0-mint-run/mint-run/ledgers/s4b.json` and
#: `docs/planning/phase0-remint/mint-run/ledgers/s5b.json` (transcribed 2026-08-12).
EXCLUDED_BANKED_IDS: frozenset[str] = frozenset(
    {
        *BANKED_S2_S3_IDS,
        # s4b + s5b (phase0-mint-run, phase0-remint)
        "pytest-dev__pytest-8365",
        "pytest-dev__pytest-8906",
        "sphinx-doc__sphinx-11445",
        "sphinx-doc__sphinx-7738",
        "sphinx-doc__sphinx-7975",
        "sphinx-doc__sphinx-8273",
        "sphinx-doc__sphinx-8282",
    }
)

_STAGE_6A_STAGE_NAME = "stage-6a probe: 1 control"
_STAGE_6B_STAGE_NAME = (
    "stage-6b: 4 controls + 7 fresh real, controls first, subset of the fresh draw"
)
_STAGE_6C_STAGE_NAME = "stage-6c: the remaining fresh non-control draw (≥50 denominator)"

_SEED_RATIONALE = (
    "Fresh draw from pool.json (seed 20260812): the stage-4 subset of the 20260723 "
    "draw cannot supply the ≥50 denominator after the s4/s5 banked captures."
)


def _select_fresh_real(draw: tuple[InstanceRecord, ...], limit: int = 7) -> list[InstanceRecord]:
    """The first `limit` fresh real records of `draw` in file order, small-repo block
    first with a django/sympy top-up only if the block cannot supply them.

    Raises `AssertionError` (loud, never silent) if fewer than `limit` fresh real
    records exist in the whole draw.
    """
    fresh_small = [
        record
        for record in draw
        if record.repo in SMALL_REPO_BLOCK
        and not record.is_control
        and record.instance_id not in EXCLUDED_BANKED_IDS
    ]
    chosen = list(fresh_small[:limit])
    if len(chosen) < limit:
        top_up = [
            record
            for record in draw
            if record.repo not in SMALL_REPO_BLOCK
            and not record.is_control
            and record.instance_id not in EXCLUDED_BANKED_IDS
        ]
        chosen.extend(top_up[: limit - len(chosen)])
    assert len(chosen) == limit, (
        f"cannot build a stage-6 registry: fewer than {limit} fresh real instances "
        f"exist in the draw after excluding {len(EXCLUDED_BANKED_IDS)} banked ids "
        f"(small-repo block supplied {len(fresh_small)}, got {len(chosen)} total)"
    )
    return chosen


def _draw() -> tuple[InstanceRecord, ...]:
    """The fresh 65-real draw from `pool.json` minus every banked id.

    Pure and deterministic: a function of `(pool.json bytes, seed)`. Excluded ids are
    removed BEFORE the draw — a banked instance is never even a candidate.
    """
    pool = load_registry(POOL_PATH)

    pool_ids = {record.instance_id for record in pool}
    missing = sorted(EXCLUDED_BANKED_IDS - pool_ids)
    assert not missing, (
        f"EXCLUDED ids absent from {str(POOL_PATH)!r} — transcription typo in "
        f"EXCLUDED_BANKED_IDS: {missing}"
    )

    candidates = [
        record for record in pool if record.instance_id not in EXCLUDED_BANKED_IDS
    ]
    return select_instances(candidates, target=DRAW_TARGET, seed=STAGE_6_SEED)


def _composition(records: list[InstanceRecord]) -> dict[str, object]:
    real_records = [record for record in records if not record.is_control]
    by_repo: dict[str, int] = {}
    for record in real_records:
        by_repo[record.repo] = by_repo.get(record.repo, 0) + 1
    return {
        "launched": len(records),
        "real": len(real_records),
        "controls": len(records) - len(real_records),
        "by_repo": by_repo,
    }


def build_stage6_registries(out_dir: Path) -> tuple[Path, Path, Path]:
    """Emit `stage6a.json` (1 control), `stage6b.json` (4 controls + 7 fresh real)
    and `stage6c.json` (the remaining fresh non-control draw) into `out_dir`,
    returning their paths.

    Pure and deterministic. Raises `AssertionError` if an EXCLUDED id is missing from
    `pool.json` (transcription typo) or if fewer than 7 fresh real records exist.
    """
    out_dir = Path(out_dir)
    draw = _draw()

    fresh_real_6b = _select_fresh_real(draw, limit=STAGE_6B_REAL)
    stage6b_records = [*CONTROL_RECORDS, POSITIVE_CONTROL_RECORD, *fresh_real_6b]

    stage6b_real_ids = {record.instance_id for record in fresh_real_6b}
    stage6c_records = [
        record for record in draw if record.instance_id not in stage6b_real_ids
    ]
    assert not any(record.is_control for record in stage6c_records)
    assert len(stage6c_records) == DRAW_TARGET - STAGE_6B_REAL

    base_header = {
        "source_pool": "eval/instances/pool.json",
        "seed": STAGE_6_SEED,
        "seed_rationale": _SEED_RATIONALE,
        "seed_history": SUPERSEDED_SEED_HISTORY,
        "controls": dict(CONTROL_EXPECTATIONS),
    }

    stage6a_header = {
        **base_header,
        "target": 1,
        "control_count": 1,
        "composition": _composition(list(CONTROL_RECORDS[:1])),
        "stage": _STAGE_6A_STAGE_NAME,
    }
    stage6b_header = {
        **base_header,
        "target": len(stage6b_records),
        "control_count": 4,
        "composition": _composition(stage6b_records),
        "stage": _STAGE_6B_STAGE_NAME,
    }
    stage6c_header = {
        **base_header,
        "target": len(stage6c_records),
        "control_count": 0,
        "composition": _composition(stage6c_records),
        "stage": _STAGE_6C_STAGE_NAME,
    }

    stage6a_path = out_dir / "stage6a.json"
    stage6b_path = out_dir / "stage6b.json"
    stage6c_path = out_dir / "stage6c.json"
    dump_registry(CONTROL_RECORDS[:1], stage6a_path, header=stage6a_header)
    dump_registry(stage6b_records, stage6b_path, header=stage6b_header)
    dump_registry(stage6c_records, stage6c_path, header=stage6c_header)
    return stage6a_path, stage6b_path, stage6c_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate eval/instances/stage6a.json, stage6b.json and stage6c.json "
            "from pool.json minus the 22 banked instance ids."
        )
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_SCRIPT_DIR.parent / "instances",
        help="output directory (default: eval/instances/)",
    )
    args = parser.parse_args(argv)
    paths = build_stage6_registries(args.out_dir)
    for path in paths:
        records = load_registry(path)
        print(f"wrote {path} ({len(records)} records)")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
