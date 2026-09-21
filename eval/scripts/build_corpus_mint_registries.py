"""The corpus-filling mint's two stage registries, generated from pool + the registries.

`phase0-corpus-mint/mint-registry/spec.md` fixes the composition of a **non-gate**,
corpus-filling mint: a 2-record probe and a 10-record stage, controls first, n ≈ 12.
Everything here is a pure function of `(pool.json, the committed registries beside it,
the hand-written controls)` — no clock, no network, no module-level `random` — so the
committed stage files regenerate byte-identically and the composition is test-pinned
(`tests/test_corpus_mint_registries.py`, B1–B10):

* **cm-stage1** (probe): CTL-1 + CTL-4 — 2 records, in that order. The gate before any
  real spend: a capture produced, ≥1 verifiable turn, both controls clean, else STOP.
* **cm-stage2**: CTL-2 + CTL-3 + 8 fresh real — 10 records, **controls first** (Rule A;
  a FAILing control VOIDS the run under D-3, and stage 3 of the *gate* mint had zero
  control coverage because all three controls were stranded at the back of the queue).

**Stage 3 is not attempted, and the header says so.** The ≥50 denominator is not safely
reachable (see the exclusion rule below) and is out of scope for a corpus-filling run.
`NOT_A_GATE_RUN` travels in every header so the artifact itself states that it publishes
no violation rate — the number is not withheld in a write-up, it is refused at the source.

**The exclusion set is DERIVED at generation time, never transcribed (B3').** It is
computed by reading every committed `eval/instances/*.json` except `pool.json` and this
generator's own outputs, and collecting every `is_control=False` instance id; `observed.json`
is a bare list of driven ids and contributes all of its entries. A hand-copied id list is
the defect class that broke `test_docker_inimage.py`'s dev-dep list — two lists, and nothing
connecting them — and both `build_stage4_registry.EXCLUDED_INSTANCE_IDS` and
`build_stage6_registries.EXCLUDED_BANKED_IDS` are exactly that shape: literals transcribed
from ledgers, correct on the day they were written and silently stale afterwards.
`observed.json` holds 23 ids and **is** stale (the gate mint drove ~60 more), which is why
this generator reads the registries rather than that file alone.

**Why the generator's own outputs are skipped, and why that is not a loophole.** Were
`cm-stage1.json` / `cm-stage2.json` sources of exclusion, a second run would exclude the
very instances the first run drew, the draw would move, and the committed artifact would
never reproduce — B2 (`git status` clean on a re-run) would be unsatisfiable. Skipping them
is what makes the fixed point exist. It costs nothing: this generator emits exactly one
draw, so there is no second draw for the first to collide with, and any *other* future
registry naming those ids is still picked up by name.

**Why the conservative fresh set (30), not the ledger-derived one (83) — a contract, not
caution.** Measured (`prd.md` §1.2): pool minus every committed registry's reals leaves
**30** (django 23, sympy 7); pool minus `observed.json` ∪ all 12 committed ledgers leaves
**83** (django 53, sympy 30). The gap is attrition — drawn into `s6stage3.json`, never
captured. Some of those were **attempted and failed**, and a failed attempt *is* an
observation: *"an instance that produced an observation is never re-armable"*
(`eval/minting_driver/checkpoint.py:18-21`). Telling attempted-and-failed from
never-reached needs the s6 **checkpoint**, and **measured: no s6 checkpoint survives**
(`~/dev/at/holder/belay/mint/` holds only `s1 s1b s1p s2 s3 live-smoke-claude-cli`). So the
83 hides an **unidentifiable** subset that must not be re-driven, while the 30 is provably
safe — and at n≈12 the difference costs nothing. Registry membership is the conservative
measure precisely because a registry entry may never have been driven.

**The monoculture is STATED, never simulated (B8).** Both measures are ~100% django+sympy:
the small-repo block was exhausted by the gate mint's stage-3 draw, which *"takes every one
of them"* (`build_gate_registries.py`). `select_instances` exists because *"a uniform draw
of 50 would publish a django/sympy rate as an agent rate"* (`selection.py:3-24`) — and on a
single-repo-family residue its rebalance is a no-op dressed as rigor, so it is **not
called** here. The draw is a plain seeded sample over `instance_id`-sorted candidates, and
the composition goes in the header. This is the mechanical reason this run publishes no
violation rate.

**Fail-closed, never fail-quiet.** A fresh pool shorter than the target raises
`InsufficientPoolError` rather than drawing short (a short draw is a short denominator —
the R6 false-zero failure mode one layer up). A drawn instance that already owns a banked
corpus case-id namespace raises `CaseIdCollisionError`: `belay corpus add` has no
`--overwrite` and `CaseExistsError` is fail-closed (`corpus/add.py:364-368`), so such an
instance could not bank at all — the whole point of this mint.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from eval.instances.controls import (
    CONTROL_EXPECTATIONS,
    CONTROL_RECORDS,
    POSITIVE_CONTROL_RECORD,
)
from eval.instances.registry import (
    InstanceRecord,
    controls,
    dump_registry,
    load_registry,
    real,
)
from eval.instances.selection import InsufficientPoolError
from eval.scripts.readd_audited_cases import SOURCES as AUDITED_CASE_SOURCES

#: The stage names. They key the returned registries, the `stage_sizes` header block, and
#: the output filenames, so a stage is named in exactly one place.
CM_STAGE1_NAME = "cm-stage1"
CM_STAGE2_NAME = "cm-stage2"

#: This generator's own outputs. Skipped by the exclusion scan (see the module docstring):
#: a generator that excludes its own draw cannot regenerate byte-identically.
SELF_OUTPUT_FILENAMES: tuple[str, ...] = ("cm-stage1.json", "cm-stage2.json")

#: cm-stage1 (probe): CTL-1 + CTL-4, in that order (spec: 2 records). CTL-4 is the
#: POSITIVE control — it only produces evidence under `--toolset filesystem+shell` and is
#: the trajectory axis's PASS side, the gap named as caveat (4) on the 18.3% result.
CM_STAGE1_RECORDS: tuple[InstanceRecord, ...] = (
    CONTROL_RECORDS[0],
    POSITIVE_CONTROL_RECORD,
)

#: cm-stage2's control head: CTL-2 + CTL-3, in that order. Controls FIRST, so a D-3 void
#: is discovered before the real instances are spent.
CM_STAGE2_CONTROL_RECORDS: tuple[InstanceRecord, ...] = (
    CONTROL_RECORDS[1],
    CONTROL_RECORDS[2],
)

#: cm-stage2's fresh real count. 8 real + 2 controls = 10 records, matching the shape of
#: the gate mint's stage 2 (4 controls + 7 real) closely enough to be legible without
#: claiming its denominator. Deliberately far short of the 30 available: once driven, a
#: fresh instance is gone forever and none can be manufactured, so this run does not
#: exhaust the residue (spec, open question 2 — "lean: do not exhaust").
CM_STAGE2_REAL_TARGET = 8

#: The measured conservative fresh set (`prd.md` §1.2, re-measured 2026-09-19):
#: django 23 + sympy 7. Pinned as a CHECK, never as a target — a different number means
#: the exclusion rule drifted, which is a stop-and-report, not a retune.
EXPECTED_FRESH_COUNT = 30

#: The toolset CTL-4 requires by construction. Published in the probe stage's header so
#: the runbook cannot launch it under a filesystem-only boundary, which is precisely how
#: the re-mint's trajectory FAILs became false positives by construction.
POSITIVE_CONTROL_TOOLSET = "filesystem+shell"

#: The draw seed: the date this composition was fixed. See the no-silent-re-roll rule in
#: `draw_mint_set.py:16-23` — drawn once and committed.
SEED = 20260919

#: Why this seed, published into the header so the number is not a bare integer.
SEED_RATIONALE = (
    "The date the draw was fixed (2026-09-19), chosen before the draw was inspected. A "
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

_SCRIPT_DIR = Path(__file__).resolve().parent
INSTANCES_DIR = _SCRIPT_DIR.parent / "instances"
POOL_PATH = INSTANCES_DIR / "pool.json"

#: The sentence that travels in every header. The artifact states what it is not, rather
#: than leaving that to a write-up nobody reads beside the file (`MH-6`).
NOT_A_GATE_RUN = (
    "This is NOT a gate run and publishes NO violation rate. The pre-registered PROCEED "
    "clause needs a denominator of at least 50 instances minted; this run draws 8 real "
    "instances, so n < 50 by construction. It is also not a base rate: the safely fresh "
    "residue is ~100% django+sympy, so any rate computed from it would be the artifact "
    "eval/instances/selection.py exists to prevent. This mint exists to BANK CORPUS "
    "CASES. 11/60 = 18.3%, precision 0.00, 1/15, 4/16 and recall 0.00 stand unedited."
)

#: Stage 3's absence, recorded rather than merely omitted.
STAGE3_NOT_ATTEMPTED = (
    "Stage 3 (the >=50 denominator) is NOT attempted. It is not safely reachable: the "
    "ledger-derived fresh set of 83 contains an unidentifiable attempted-and-failed "
    "subset (no s6 checkpoint survives), and a failed attempt is an observation, which "
    "is never re-armable. The conservative fresh set is 30. Out of reach safely, and out "
    "of scope for a corpus-filling run."
)

#: How the exclusion set was computed, published beside the counts it produced.
EXCLUSION_RULE = (
    "Derived at generation time, never transcribed: every committed eval/instances/*.json "
    "except pool.json and this generator's own outputs is read, and every is_control=False "
    "instance id is collected (observed.json is a bare list of driven ids and contributes "
    "all of its entries). Registry membership, not ledger membership — the conservative "
    "measure, because a registry entry may never have been driven while a ledger records "
    "only instances that produced a trace."
)

#: The composition fact this run cannot fix and therefore states.
MONOCULTURE_NOTE = (
    "The fresh residue is ~100% django+sympy: the gate mint's stage-3 draw took every "
    "small-repo instance in the pool. select_instances is deliberately NOT called — with "
    "a single-repo-family pool its rebalance is a no-op dressed as rigor. The "
    "concentration is stated here instead, and it is the mechanical reason this run "
    "publishes no violation rate."
)

_CM_STAGE1_DESCRIPTION = (
    "cm-stage1 probe: CTL-1 + CTL-4, controls only. Gate before any real spend — a "
    "capture produced AND >=1 verifiable turn AND both controls clean, else STOP "
    "(instrument or wiring defect)."
)
_CM_STAGE2_DESCRIPTION = (
    "cm-stage2: CTL-2 + CTL-3 + 8 fresh real, controls FIRST. A FAILing control VOIDS "
    "the run (D-3), so the controls are driven before any real instance is spent."
)


class CaseIdCollisionError(ValueError):
    """A drawn instance already owns a banked corpus case-id namespace.

    Raised rather than shipped: `belay corpus add` is fail-closed on a pre-existing case
    (`CaseExistsError`, no `--overwrite` — `corpus/add.py:364-368`), so such an instance
    could not bank, which is the one thing this mint exists to do. Fail here, in a pure
    offline generator, rather than after a live capture has been spent.
    """


@dataclass(frozen=True)
class StageRegistry:
    """One stage: its name, its output filename, its records, and its header.

    The records and the header travel together because `dump_registry` takes both and the
    header is a **claim about the records in the same file** — the counts, the per-repo
    composition, the seed. Splitting them is how a header comes to describe a draw that
    has moved underneath it.
    """

    name: str
    filename: str
    records: tuple[InstanceRecord, ...]
    header: dict


def exclusion_sources(instances_dir: Path) -> list[str]:
    """The filenames the exclusion set is derived FROM, sorted.

    Published in the header so a reader can re-derive the set by hand: the rule names a
    glob, and a glob over a directory that has since grown is not the same set. Skips
    `pool.json` (the universe, not an exclusion) and this generator's own outputs.
    """
    return sorted(
        path.name
        for path in Path(instances_dir).glob("*.json")
        if path.name != "pool.json" and path.name not in SELF_OUTPUT_FILENAMES
    )


def derive_excluded_ids(instances_dir: Path) -> frozenset[str]:
    """Every real instance id named by a committed registry in `instances_dir`.

    Two shapes live in that directory and both are read: a registry (a JSON object with
    an `instances` list, where a record is excluded only when `is_control` is false — a
    control is hand-written, never drawn, and excluding one would be meaningless), and
    `observed.json`, a bare JSON list of previously-driven ids, all of which count.

    **Derived, never transcribed.** Planting a registry here grows the result; a
    hard-coded literal could not, and that is exactly what
    `tests/test_corpus_mint_registries.py::test_the_exclusion_set_is_derived_from_the_registries_on_disk`
    asserts. Malformed JSON raises out of `json.loads` rather than being skipped: an
    unreadable registry means the exclusion set is UNKNOWN, and a silently smaller
    exclusion set re-drives an already-driven instance.
    """
    excluded: set[str] = set()
    for path in sorted(Path(instances_dir).glob("*.json")):
        if path.name == "pool.json" or path.name in SELF_OUTPUT_FILENAMES:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            excluded.update(str(entry) for entry in payload)
            continue
        for entry in payload.get("instances", []):
            if not entry.get("is_control", False):
                excluded.add(entry["instance_id"])
    return frozenset(excluded)


def fresh_pool(
    pool: Iterable[InstanceRecord], excluded: Iterable[str]
) -> tuple[InstanceRecord, ...]:
    """The pool's real records whose ids are not in `excluded` — the drawable universe.

    Preserves pool order. Controls cannot appear in `pool.json` by construction (they are
    hand-written and appended, never drawn), but the `is_control` filter is applied by the
    FIELD anyway rather than trusted to a property of the current file: `registry.real` is
    the one place that decides what a real instance is.
    """
    blocked = set(excluded)
    return tuple(
        record
        for record in real(tuple(pool))
        if record.instance_id not in blocked
    )


def draw_fresh_real(
    fresh: Iterable[InstanceRecord], *, target: int, seed: int
) -> tuple[InstanceRecord, ...]:
    """Draw `target` records from `fresh`, reproducibly. Raises rather than drawing short.

    Pure: a function of `(fresh, target, seed)` only. Candidates are sorted by
    `instance_id` **before** any randomness, so file order, dict order or fetch order
    cannot leak into the result, and the rng is a local `random.Random(seed)` — never the
    module-level `random`, never the clock (`selection.py:20-24`).

    `select_instances` is deliberately not used: its job is to rebalance an 83%
    django+sympy pool, and this pool is ~100% django+sympy, so the stratification would be
    a no-op presented as rigor. Its `InsufficientPoolError` IS reused, because the rule it
    encodes is unchanged — a short draw is a short denominator.

    The result is returned in `instance_id` order so the committed registry reads as a
    sorted list rather than in sample order, which reviews more cleanly and carries no
    information the seed does not already fix.
    """
    candidates = sorted(fresh, key=lambda record: record.instance_id)
    if len(candidates) < target:
        raise InsufficientPoolError(
            f"the fresh pool has {len(candidates)} instances, fewer than the target of "
            f"{target}; refusing to draw short (a short draw is a short denominator)"
        )
    rng = random.Random(seed)
    sampled = rng.sample(candidates, target)
    return tuple(sorted(sampled, key=lambda record: record.instance_id))


def banked_case_ids(corpus_dir: Path | None = None) -> frozenset[str]:
    """The corpus case ids already taken.

    Two sources, because one of them is gitignored: the committed re-add table
    (`readd_audited_cases.SOURCES`, whose keys are case ids established mechanically by
    trace digest, not by eye) and — when `corpus_dir` is given and exists — the case dirs
    actually on this machine. The committed table is what makes the guard meaningful in
    CI, where `corpus/local/` is absent by design.
    """
    ids = set(AUDITED_CASE_SOURCES)
    if corpus_dir is not None and Path(corpus_dir).is_dir():
        ids.update(child.name for child in Path(corpus_dir).iterdir() if child.is_dir())
    return frozenset(ids)


def case_id_collisions(
    records: Iterable[InstanceRecord], case_ids: Iterable[str]
) -> tuple[str, ...]:
    """The ids in `records` that already own a `trace-<instance>-*` case namespace.

    A capture bridges to `trace-<instance_id>.jsonl` (`bridge.py`), whose stem becomes the
    `source_trace_id`, and a case id is that stem plus `-turnN` / `-trajectory` / `-claim`
    (`corpus/add.py:_safe_case_id`). So the prefix test is exact rather than a heuristic:
    any existing case id starting with `trace-<id>-` was banked from this instance.
    Returns ids in `records` order, each at most once.
    """
    known = tuple(case_ids)
    hits: list[str] = []
    for record in records:
        if record.instance_id in hits:
            continue
        prefix = f"trace-{record.instance_id}-"
        if any(case_id.startswith(prefix) for case_id in known):
            hits.append(record.instance_id)
    return tuple(hits)


def _composition(records: Sequence[InstanceRecord]) -> dict:
    """One stage's shape, computed from `records` — never typed by hand.

    `by_repo` covers the **real** instances only: the controls' repos are a property of
    the instrument, not of the sample, and folding them in would quietly inflate flask and
    requests in the published composition (`draw_mint_set._composition`'s rule).
    """
    drawn = real(records)
    by_repo: dict[str, int] = {}
    for record in drawn:
        by_repo[record.repo] = by_repo.get(record.repo, 0) + 1
    return {
        "launched": len(records),
        "real": len(drawn),
        "controls": len(controls(records)),
        "by_repo": dict(sorted(by_repo.items())),
    }


def _published_controls(records: Sequence[InstanceRecord]) -> dict:
    """`CONTROL_EXPECTATIONS` for the controls in THIS stage, as JSON.

    Per-stage rather than all four everywhere: a header is a claim about the file it sits
    in, and publishing an expectation for a control the stage does not carry invites an
    audit to look for an outcome that was never produced. Tuples become lists so the
    payload is JSON, and the ordering follows the records.
    """
    return {
        record.instance_id: {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in CONTROL_EXPECTATIONS[record.instance_id].items()
        }
        for record in controls(records)
    }


def build_registries(
    pool: Iterable[InstanceRecord],
    excluded: Iterable[str],
    *,
    instances_dir: Path | None = None,
    banked: Iterable[str] | None = None,
) -> dict[str, StageRegistry]:
    """The two stage registries — records plus provenance header — keyed by stage name.

    Pure and total given its inputs: the same `(pool, excluded)` yields the identical
    records in the identical order and an identical header, which is what makes the
    committed files regenerate byte-identically (B2).

    `instances_dir` only supplies the header's `exclusion.sources` listing (the excluded
    ids themselves are passed in, already derived, so a caller may test against a planted
    directory). `banked` defaults to the committed banked case ids.

    Raises `InsufficientPoolError` if the fresh pool cannot supply
    `CM_STAGE2_REAL_TARGET`, and `CaseIdCollisionError` if a drawn instance already owns a
    banked case-id namespace. Both are fail-closed by design: the alternative to each is a
    live mint that cannot produce the artifact it was run for.
    """
    pool = tuple(pool)
    blocked = frozenset(excluded)
    fresh = fresh_pool(pool, blocked)
    drawn = draw_fresh_real(fresh, target=CM_STAGE2_REAL_TARGET, seed=SEED)

    known_cases = frozenset(banked) if banked is not None else banked_case_ids()
    collisions = case_id_collisions(drawn, known_cases)
    if collisions:
        raise CaseIdCollisionError(
            f"drawn instance(s) {list(collisions)} already own a banked corpus case-id "
            f"namespace (trace-<instance>-*); `belay corpus add` is fail-closed with no "
            f"--overwrite, so a capture of these could never bank — which is the only "
            f"reason this mint runs. Report the collision; do not re-seed around it."
        )

    fresh_by_repo: dict[str, int] = {}
    for record in fresh:
        fresh_by_repo[record.repo] = fresh_by_repo.get(record.repo, 0) + 1

    exclusion = {
        "rule": EXCLUSION_RULE,
        "sources": exclusion_sources(instances_dir or INSTANCES_DIR),
        "pool_real": len(real(pool)),
        "excluded": len(blocked),
        "fresh": len(fresh),
        "fresh_by_repo": dict(sorted(fresh_by_repo.items())),
        "monoculture": MONOCULTURE_NOTE,
    }

    stage1_records = CM_STAGE1_RECORDS
    stage2_records = (*CM_STAGE2_CONTROL_RECORDS, *drawn)
    stage_sizes = {
        CM_STAGE1_NAME: len(stage1_records),
        CM_STAGE2_NAME: len(stage2_records),
    }

    def header_for(records: tuple[InstanceRecord, ...], description: str) -> dict:
        header: dict = {
            "stage": description,
            "not_a_gate_run": NOT_A_GATE_RUN,
            "stage3": STAGE3_NOT_ATTEMPTED,
            "source_pool": SOURCE_POOL,
            "exclusion": exclusion,
            "seed": SEED,
            "seed_rationale": SEED_RATIONALE,
            "seed_history": [dict(entry) for entry in SEED_HISTORY],
            "target": len(records),
            "control_count": len(controls(records)),
            "stage_sizes": stage_sizes,
            "composition": _composition(records),
            "controls": _published_controls(records),
        }
        if POSITIVE_CONTROL_RECORD in records:
            header["positive_control"] = {
                "instance_id": POSITIVE_CONTROL_RECORD.instance_id,
                "required_toolset": POSITIVE_CONTROL_TOOLSET,
                "note": (
                    "The positive control only produces evidence under --toolset "
                    f"{POSITIVE_CONTROL_TOOLSET}: it requires a replayed exit-0 "
                    "run_process before its verification claim. Launched under a "
                    "filesystem-only boundary it abstains by construction, which is how "
                    "the re-mint's trajectory FAILs became false positives."
                ),
            }
        return header

    return {
        CM_STAGE1_NAME: StageRegistry(
            name=CM_STAGE1_NAME,
            filename=SELF_OUTPUT_FILENAMES[0],
            records=stage1_records,
            header=header_for(stage1_records, _CM_STAGE1_DESCRIPTION),
        ),
        CM_STAGE2_NAME: StageRegistry(
            name=CM_STAGE2_NAME,
            filename=SELF_OUTPUT_FILENAMES[1],
            records=stage2_records,
            header=header_for(stage2_records, _CM_STAGE2_DESCRIPTION),
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Read the committed pool and registries, draw, and write the two stage files.

    No network, no clock. Safe to re-run: with an unchanged pool and an unchanged set of
    committed registries it rewrites the identical bytes, so `git status` staying clean
    *is* the reproducibility check (`draw_mint_set.py:137-142`).
    """
    parser = argparse.ArgumentParser(
        description=(
            "Generate eval/instances/cm-stage1.json and cm-stage2.json — the "
            "corpus-filling mint's stage registries — from pool.json minus every real id "
            "named by a committed registry beside it. Pure and offline; re-running with "
            "unchanged inputs rewrites identical bytes. NOT a gate run: n < 50 and no "
            "violation rate is published."
        )
    )
    parser.add_argument(
        "--pool", type=Path, default=POOL_PATH, help="the committed pool to draw from"
    )
    parser.add_argument(
        "--instances-dir",
        type=Path,
        default=INSTANCES_DIR,
        help="the directory the exclusion set is derived from (default: eval/instances/)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=INSTANCES_DIR,
        help="where the stage registries are written (default: eval/instances/)",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help=(
            "an on-disk corpus of banked cases to check for id collisions, in addition "
            "to the committed re-add table (default: the committed table only)"
        ),
    )
    args = parser.parse_args(argv)

    pool = load_registry(args.pool)
    excluded = derive_excluded_ids(args.instances_dir)
    built = build_registries(
        pool,
        excluded,
        instances_dir=args.instances_dir,
        banked=banked_case_ids(args.corpus_dir),
    )

    out_dir = Path(args.out_dir)
    for stage in built.values():
        path = out_dir / stage.filename
        dump_registry(stage.records, path, header=stage.header)
        composition = stage.header["composition"]
        print(
            f"wrote {path}: {composition['launched']} launched "
            f"({composition['real']} real, {composition['controls']} controls)"
        )
    fresh = built[CM_STAGE2_NAME].header["exclusion"]
    print(
        f"  fresh pool {fresh['fresh']} of {fresh['pool_real']} "
        f"({fresh['excluded']} excluded): {fresh['fresh_by_repo']}"
    )
    print("  NOT a gate run: n < 50, no violation rate is published")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = [
    "CM_STAGE1_NAME",
    "CM_STAGE1_RECORDS",
    "CM_STAGE2_CONTROL_RECORDS",
    "CM_STAGE2_NAME",
    "CM_STAGE2_REAL_TARGET",
    "CaseIdCollisionError",
    "EXPECTED_FRESH_COUNT",
    "EXCLUSION_RULE",
    "MONOCULTURE_NOTE",
    "NOT_A_GATE_RUN",
    "POSITIVE_CONTROL_TOOLSET",
    "SEED",
    "SEED_HISTORY",
    "SEED_RATIONALE",
    "SELF_OUTPUT_FILENAMES",
    "SOURCE_POOL",
    "STAGE3_NOT_ATTEMPTED",
    "StageRegistry",
    "banked_case_ids",
    "build_registries",
    "case_id_collisions",
    "derive_excluded_ids",
    "draw_fresh_real",
    "exclusion_sources",
    "fresh_pool",
    "main",
]
