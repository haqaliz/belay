"""Deterministic, offline generator for the stage-4 registries.

The funded mint needs committed registries for its stage 1 (one control) and stage 2
(3 controls + 7 real, controls at the head). This script reads the committed draw
`eval/instances/selected.json` plus a hardcoded EXCLUDED set — the instances the old
s2/s3 live mint already captured — and emits two registries through the shipped
`dump_registry` writer, so the records round-trip through `load_registry` by
construction and regenerate byte-identically.

Selection rule (`stage-registries/spec.md`, S-1): the 7 real records are the first 7
fresh records of the small-repo block (flask, requests, pylint, pytest, sphinx) in file
order — `selected.json` interleaves django/sympy *after* that block — topped up from
django/sympy in file order only if the block cannot supply 7. Fewer than 7 fresh real
records anywhere is a loud AssertionError, never a silently shorter registry.

The EXCLUDED literal is a committed frozenset (S-2): a transcription error is visible in
the diff, and the script fails loud if any id in it is absent from `selected.json` — a
typo would otherwise be silently dropped and re-mint a banked instance.

No network, no clock, no randomness. Deterministic output: `dump_registry` owns key
order and the trailing newline.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.instances.controls import CONTROL_EXPECTATIONS, CONTROL_RECORDS
from eval.instances.registry import InstanceRecord, dump_registry, load_registry

_SCRIPT_DIR = Path(__file__).resolve().parent

#: The committed draw stage 4 is a subset of. Controls are NOT drawn from it — they are
#: appended to the draw (see `eval/instances/controls.py`) — but they were copied into
#: `selected.json` at draw time, so the typo guard below checks the whole record set.
SELECTED_PATH = _SCRIPT_DIR.parent / "instances" / "selected.json"

#: The draw seed of `selected.json`. Stage 4 is a subset of that committed draw, not a
#: new draw, so this is the seed that identifies the records' provenance.
SELECTED_SEED = 20260723

#: The repos of `selected.json`'s small-repo block. `selected.json` orders records as:
#: the small-repo block first (flask, requests, pylint, pytest, sphinx in file order),
#: then django/sympy interleaved. Selection walks that file order.
SMALL_REPO_BLOCK = frozenset(
    {"pallets/flask", "psf/requests", "pylint-dev/pylint", "pytest-dev/pytest", "sphinx-doc/sphinx"}
)

#: The instances already captured by the old live mint — the stage-2 and stage-3 banked
#: set, transcribed 2026-08-09 from `docs/technical/PHASE0_RESULTS.md` (the 15 named
#: s2/s3 instances) and verified against the committed ledgers
#: `docs/planning/under-firing-measurable/miss-measurement/ledgers/miss-{s2,s3}.json`.
#:
#: The union of the two ledgers' real instances is 14 ids; the 15th banked instance is
#: `pallets__flask-4045` (s1 only), which is NOT in `selected.json` and is therefore
#: excluded from this set — it is excluded from the pool by construction, and the typo
#: guard would reject it here. `pytest-dev__pytest-7432` is the 2026-08-05 live smoke
#: capture (`subscription-model-client`, `prd.md:136`), banked after the exposure table
#: in `PHASE0_RESULTS.md` was written; it is included so the fresh-only rule holds for
#: every instance that has ever been driven live.
#:
#: AMBIGUITY NOTE (transcribed 2026-08-09): the stage-registries task brief named a
#: "15 known ids" list containing `sphinx-doc__sphinx-7555` and `django__django-15400`.
#: Neither is banked: `sphinx-7555` appears in no ledger and is not in `selected.json`
#: (the sphinx banked capture is `sphinx-10325`); `django-15400` is in `stage2.json` but
#: its s2 capture FAILED at `git clone --bare` (`STAGE2_FINDINGS.md:46`) and it is in no
#: ledger, so it stays a fresh candidate. The ids below are the ledger-confirmed
#: captures only.
EXCLUDED_INSTANCE_IDS: frozenset[str] = frozenset(
    {
        "pallets__flask-4992",  # s2 + s3 (miss-s2, miss-s3)
        "psf__requests-1963",  # s2 + s3
        "psf__requests-2317",  # s3
        "psf__requests-2674",  # s3
        "psf__requests-863",  # s3
        "pylint-dev__pylint-5859",  # s2 + s3
        "pylint-dev__pylint-6506",  # s3
        "pylint-dev__pylint-7114",  # s3
        "pytest-dev__pytest-5221",  # s2 + s3
        "pytest-dev__pytest-5227",  # s2 + s3
        "pytest-dev__pytest-5692",  # s3
        "pytest-dev__pytest-6116",  # s3
        "pytest-dev__pytest-7432",  # live smoke 2026-08-05 (subscription-model-client)
        "sphinx-doc__sphinx-10325",  # s2
        "sympy__sympy-21627",  # s2
    }
)

_STAGE_4A_STAGE_NAME = "stage-4a probe: 1 control"
_STAGE_4_STAGE_NAME = "stage-4b: 3 controls + 7 fresh real, controls first, subset of selected.json"

_SEED_RATIONALE = (
    "Inherited from the selected.json draw (seed 20260723): stage 4 is a subset of that "
    "committed draw, not a new draw, and seed_history is empty because no draw was "
    "repeated or altered."
)


def _select_fresh_real(selected: tuple[InstanceRecord, ...], limit: int = 7) -> list[InstanceRecord]:
    """The first `limit` fresh real records of `selected` in file order, small-repo block
    first with a django/sympy top-up only if the block cannot supply them.

    Raises `AssertionError` (loud, never silent) if fewer than `limit` fresh real
    records exist in the whole pool.
    """
    fresh_small = [
        record
        for record in selected
        if record.repo in SMALL_REPO_BLOCK
        and not record.is_control
        and record.instance_id not in EXCLUDED_INSTANCE_IDS
    ]
    chosen = list(fresh_small[:limit])
    if len(chosen) < limit:
        top_up = [
            record
            for record in selected
            if record.repo not in SMALL_REPO_BLOCK
            and not record.is_control
            and record.instance_id not in EXCLUDED_INSTANCE_IDS
        ]
        chosen.extend(top_up[: limit - len(chosen)])
    assert len(chosen) == limit, (
        f"cannot build a stage-4 registry: fewer than {limit} fresh real instances "
        f"exist in selected.json after excluding {len(EXCLUDED_INSTANCE_IDS)} banked "
        f"ids (small-repo block supplied {len(fresh_small)}, got {len(chosen)} total)"
    )
    return chosen


def _composition(records: list[InstanceRecord], launched: int) -> dict[str, object]:
    real_records = [record for record in records if not record.is_control]
    by_repo: dict[str, int] = {}
    for record in real_records:
        by_repo[record.repo] = by_repo.get(record.repo, 0) + 1
    controls_count = len(records) - len(real_records)
    return {
        "launched": launched,
        "real": len(real_records),
        "controls": controls_count,
        "by_repo": by_repo,
    }


def build_stage4_registries(
    out_dir: Path, *, selected_path: Path = SELECTED_PATH
) -> tuple[Path, Path]:
    """Emit `stage4a.json` (1 control) and `stage4.json` (3 controls + 7 fresh real)
    into `out_dir`, returning their paths.

    Pure and deterministic: reads `selected_path`, writes exactly two files. Raises
    `AssertionError` if an EXCLUDED id is missing from the pool (transcription typo) or
    if fewer than 7 fresh real records exist.
    """
    out_dir = Path(out_dir)
    selected = load_registry(selected_path)

    selected_ids = {record.instance_id for record in selected}
    missing = sorted(EXCLUDED_INSTANCE_IDS - selected_ids)
    assert not missing, (
        f"EXCLUDED ids absent from {str(selected_path)!r} — transcription typo in "
        f"EXCLUDED_INSTANCE_IDS: {missing}"
    )

    fresh_real = _select_fresh_real(selected, limit=7)
    stage4_records = [*CONTROL_RECORDS, *fresh_real]

    stage4a_header = {
        "source_pool": "eval/instances/selected.json",
        "target": 1,
        "seed": SELECTED_SEED,
        "seed_rationale": _SEED_RATIONALE,
        "seed_history": [],
        "control_count": 1,
        "composition": _composition([CONTROL_RECORDS[0]], launched=1),
        "controls": dict(CONTROL_EXPECTATIONS),
        "stage": _STAGE_4A_STAGE_NAME,
    }
    stage4_header = {
        "source_pool": "eval/instances/selected.json",
        "target": 10,
        "seed": SELECTED_SEED,
        "seed_rationale": _SEED_RATIONALE,
        "seed_history": [],
        "control_count": 3,
        "composition": _composition(stage4_records, launched=10),
        "controls": dict(CONTROL_EXPECTATIONS),
        "stage": _STAGE_4_STAGE_NAME,
    }

    stage4a_path = out_dir / "stage4a.json"
    stage4_path = out_dir / "stage4.json"
    dump_registry(CONTROL_RECORDS[:1], stage4a_path, header=stage4a_header)
    dump_registry(stage4_records, stage4_path, header=stage4_header)
    return stage4a_path, stage4_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate eval/instances/stage4a.json and stage4.json from selected.json "
            "minus the s2/s3-banked instances."
        )
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_SCRIPT_DIR.parent / "instances",
        help="output directory (default: eval/instances/)",
    )
    args = parser.parse_args(argv)
    stage4a_path, stage4_path = build_stage4_registries(args.out_dir)
    print(f"wrote {stage4a_path} ({len(CONTROL_RECORDS[:1])} record)")
    print(f"wrote {stage4_path} ({len(CONTROL_RECORDS) + 7} records)")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
