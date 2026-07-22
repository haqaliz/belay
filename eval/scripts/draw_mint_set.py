"""The committed pool -> the committed mint set. Pure, offline, and re-runnable.

`eval/instances/selected.json` is what the Phase-0 mint actually launches, so this script
fixes what the published violation rate covers. Everything here is a pure function of
`(pool, target, seed)` plus the hand-written controls: no clock, no network, no
module-level `random`. That is what lets `tests/test_eval_mint_set.py` re-run the draw
in-process and assert the committed file is reproduced **byte-for-byte** — key order,
trailing newline and all.

**The launched set is 68 records: `TARGET` = 65 drawn + 3 controls.** The controls are not
in `pool.json` (they are hand-written, not fetched) so they cannot be drawn; they are
**appended after** the draw, in `CONTROL_RECORDS` order, and separated downstream by the
`is_control` field rather than by their ids. 65 real instances leaves the >=50 denominator
the PRD requires intact through ~23% attrition.

**The seed, and the rule that makes it honest.** `SEED = 20260723` is the date the draw was
fixed. A seed is only evidence if it was chosen *before* the draw was inspected, and
nothing in a file can prove that after the fact — so the discipline is written down
instead: **draw once, commit. If the seed is ever changed, the superseded seed and the
reason go into the header's `seed_history` list, never silently.** A shopped seed is a
composition lie (redraw until django/sympy look better, or until an awkward instance
falls out), and a committed history is the only defense against it that survives review.
An empty `seed_history` is the claim "drawn once".

The header is a **claim** about the file — the seed, the target, the per-repo composition,
the controls' expected outcomes — and the tests check every part of it against the records
in the same file. `composition` is computed from the records here and never typed by hand,
so the published table is generated rather than asserted.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from eval.instances.controls import CONTROL_EXPECTATIONS, CONTROL_RECORDS
from eval.instances.registry import (
    InstanceRecord,
    controls,
    dump_registry,
    load_registry,
    real,
)
from eval.instances.selection import select_instances

#: Real instances drawn from the pool. A decision (D4), not a measurement: 65 leaves the
#: PRD's >=50 denominator intact through ~23% attrition.
TARGET = 65

#: The draw seed: the date it was fixed. See the module docstring's no-silent-re-roll rule.
SEED = 20260723

#: Why this seed, published into the header so the number is not a bare integer.
SEED_RATIONALE = (
    "The date the draw was fixed (2026-07-23), chosen before the draw was inspected. A "
    "seed is only evidence if it was not shopped, so any change must be recorded in "
    "seed_history with its reason; an empty history is the claim that this set was drawn "
    "once and committed."
)

#: Superseded seeds, newest last: `{"seed": int, "reason": str}`. Empty means never
#: re-rolled. **Appending here is mandatory if the seed ever changes** — a silent re-roll
#: is indistinguishable from seed-shopping.
SEED_HISTORY: tuple[dict[str, object], ...] = ()

#: Repo-relative, so the header reproduces on another machine. An absolute path here would
#: leak one developer's home directory into a committed artifact.
SOURCE_POOL = "eval/instances/pool.json"

_INSTANCES_DIR = Path(__file__).parent.parent / "instances"
POOL_PATH = _INSTANCES_DIR / "pool.json"
SELECTED_PATH = _INSTANCES_DIR / "selected.json"


def _composition(records: Sequence[InstanceRecord]) -> dict[str, object]:
    """The launched set's shape, computed from `records` — never typed by hand.

    `by_repo` covers the **real** instances only: the controls' repos are a property of
    the instrument, not of the sample the number describes, and folding them in would
    quietly inflate flask and requests in the published composition.
    """
    drawn = real(records)
    return {
        "launched": len(records),
        "real": len(drawn),
        "controls": len(controls(records)),
        "by_repo": dict(sorted(Counter(record.repo for record in drawn).items())),
    }


def _published_controls() -> dict[str, dict[str, object]]:
    """`CONTROL_EXPECTATIONS` as JSON: tuples become lists, order fixed by the records."""
    published: dict[str, dict[str, object]] = {}
    for record in CONTROL_RECORDS:
        expectation = dict(CONTROL_EXPECTATIONS[record.instance_id])
        expectation["written_paths"] = list(expectation["written_paths"])  # type: ignore[arg-type]
        published[record.instance_id] = expectation
    return published


def build_selection(
    pool: Iterable[InstanceRecord],
    *,
    target: int = TARGET,
    seed: int = SEED,
) -> tuple[tuple[InstanceRecord, ...], dict[str, object]]:
    """The launched set and its provenance header, from `pool` alone.

    Pure and total: given the same pool, target and seed it returns the identical records
    in the identical order and an identical header. The drawn instances come first, in the
    draw's own (stratified) order, and the controls are appended after them — so the
    committed file reads top-to-bottom as "what was sampled, then what checks the
    instrument".

    Raises `InsufficientPoolError` (from `select_instances`) rather than drawing short: a
    short draw is a short denominator, which is the R6 false-zero failure mode one layer
    up.
    """
    drawn = select_instances(pool, target=target, seed=seed)
    records = tuple(drawn) + CONTROL_RECORDS

    header: dict[str, object] = {
        "source_pool": SOURCE_POOL,
        "target": target,
        "seed": seed,
        "seed_rationale": SEED_RATIONALE,
        "seed_history": [dict(entry) for entry in SEED_HISTORY],
        "control_count": len(CONTROL_RECORDS),
        "composition": _composition(records),
        "controls": _published_controls(),
    }
    return records, header


def main(argv: Sequence[str] | None = None) -> int:
    """Read the committed pool, draw, and write `selected.json`. No network, no clock.

    Safe to re-run: with an unchanged pool, seed and target it rewrites the identical
    bytes, so `git status` staying clean *is* the reproducibility check.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Draw the Phase-0 mint set from the committed pool and write selected.json. "
            "Pure and offline; re-running with an unchanged pool rewrites identical bytes."
        )
    )
    parser.add_argument(
        "--pool", type=Path, default=POOL_PATH, help="the committed pool to draw from"
    )
    parser.add_argument(
        "--out", type=Path, default=SELECTED_PATH, help="where to write the mint set"
    )
    parser.add_argument("--target", type=int, default=TARGET, help="real instances drawn")
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help=(
            "the draw seed. Changing this without recording the previous seed and the "
            "reason in SEED_HISTORY is a silent re-roll; do not."
        ),
    )
    args = parser.parse_args(argv)

    pool = load_registry(args.pool)
    records, header = build_selection(pool, target=args.target, seed=args.seed)
    dump_registry(records, args.out, header=header)

    composition = header["composition"]
    print(
        f"wrote {args.out}: {composition['launched']} launched "  # type: ignore[index]
        f"({composition['real']} drawn, {composition['controls']} controls), "  # type: ignore[index]
        f"seed {args.seed}",
        file=sys.stderr,
    )
    for repo, count in composition["by_repo"].items():  # type: ignore[index]
        print(f"  {repo}: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = [
    "SEED",
    "SEED_HISTORY",
    "SEED_RATIONALE",
    "SOURCE_POOL",
    "TARGET",
    "build_selection",
    "main",
]
