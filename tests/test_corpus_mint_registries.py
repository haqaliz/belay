"""RED contract tests for `eval/scripts/build_corpus_mint_registries.py`.

`phase0-corpus-mint/mint-registry/spec.md` B1..B10, pinned on the committed
`pool.json`, the committed registries beside it, and the real `controls.py` records.
The corpus-filling mint's two stage registries must compose exactly as pre-registered —

* `cm-stage1` (probe): CTL-1 + CTL-4, 2 records in that order;
* `cm-stage2`: CTL-2 + CTL-3 + exactly 8 fresh real, 10 records, controls FIRST;
* stage 3 (the >=50 denominator) is **not attempted**, and the header says so;

— drawn from the **conservative fresh set** (pool minus every committed registry's real
ids: measured **30**, django 23 + sympy 7), under a recorded seed, with the exclusion set
**derived at generation time from the registries on disk** rather than transcribed.

**Why the exclusion rule is the load-bearing test here (B3').** A hand-copied id list is
the defect class that broke `test_docker_inimage.py`'s dev-dep list: two lists and nothing
connecting them. So `test_the_exclusion_set_is_derived_from_the_registries_on_disk` plants
a synthetic registry in a tmp dir and asserts the excluded set **grows** — an assertion no
transcribed literal can pass — and, in the same breath, that the generator's own outputs
are skipped, which is what keeps a second run byte-identical instead of excluding the very
instances it just drew.

The exclusion set used for the composition assertions is computed **independently of the
seam**, by this module walking the same committed files, so the tests cannot be
self-confirming.

No network, no clock: `pool.json`, the registries and the controls are committed files.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

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
from eval.scripts.build_corpus_mint_registries import (
    CM_STAGE1_NAME,
    CM_STAGE1_RECORDS,
    CM_STAGE2_CONTROL_RECORDS,
    CM_STAGE2_NAME,
    CM_STAGE2_REAL_TARGET,
    EXPECTED_FRESH_COUNT,
    POSITIVE_CONTROL_TOOLSET,
    SEED,
    SEED_HISTORY,
    SEED_RATIONALE,
    SELF_OUTPUT_FILENAMES,
    banked_case_ids,
    build_registries,
    case_id_collisions,
    derive_excluded_ids,
    fresh_pool,
    main,
)

REPO_ROOT = Path(__file__).parent.parent
INSTANCES_DIR = REPO_ROOT / "eval" / "instances"
POOL = INSTANCES_DIR / "pool.json"
MODULE = REPO_ROOT / "eval" / "scripts" / "build_corpus_mint_registries.py"

#: The measured conservative fresh set (`prd.md` §1.2, re-measured 2026-09-19). Pinned:
#: a different number means the exclusion rule drifted, which is a STOP, not a retune.
EXPECTED_FRESH_BY_REPO = {"django/django": 23, "sympy/sympy": 7}

#: The fixed composition (spec B5/B6) — order is part of the contract.
CM_STAGE1_CONTROL_IDS = (
    "control__flask-read-only",
    "control__flask-verify-with-command",
)
CM_STAGE2_CONTROL_IDS = (
    "control__flask-write-new-file",
    "control__requests-read-then-write",
)

#: Generation-time source of control text, by id.
CONTROLS_BY_ID = {
    record.instance_id: record
    for record in (*CONTROL_RECORDS, POSITIVE_CONTROL_RECORD)
}

#: Module roots the generator may import. `random` is allowed only as a LOCAL
#: `random.Random(seed)` (asserted separately); everything that could reach a network, a
#: clock, a subprocess or the environment is absent.
ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "argparse",
        "collections",
        "dataclasses",
        "json",
        "pathlib",
        "random",
        "sys",
        "typing",
        "eval",
    }
)

FORBIDDEN_IMPORTS = frozenset(
    {
        "socket",
        "ssl",
        "urllib",
        "urllib3",
        "http",
        "requests",
        "httpx",
        "time",
        "datetime",
        "calendar",
        "subprocess",
        "os",
        "secrets",
        "uuid",
    }
)


# --------------------------------------------------------------------------------------
# Independent derivations — never the seam's own
# --------------------------------------------------------------------------------------


def _excluded_from_committed() -> set[str]:
    """Every real instance id in any committed `eval/instances/*.json` but `pool.json`.

    Re-implemented here from `json` alone so the composition assertions do not consult
    the function they are meant to check. Two shapes exist on disk: a registry (a dict
    with `instances`) and `observed.json` (a bare list of driven ids).
    """
    excluded: set[str] = set()
    for path in sorted(INSTANCES_DIR.glob("*.json")):
        if path.name == "pool.json" or path.name in SELF_OUTPUT_FILENAMES:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            excluded.update(str(entry) for entry in payload)
            continue
        for entry in payload["instances"]:
            if not entry.get("is_control", False):
                excluded.add(entry["instance_id"])
    return excluded


def _pool_records() -> tuple[InstanceRecord, ...]:
    return load_registry(POOL)


def _built() -> dict:
    return build_registries(_pool_records(), _excluded_from_committed())


def _serialized(stage) -> list[dict]:
    """A stage's records in the registry's serialized key shape."""
    return [
        {
            "instance_id": record.instance_id,
            "repo": record.repo,
            "base_commit": record.base_commit,
            "problem_statement": record.problem_statement,
            "task_string": record.task_string,
            "is_control": record.is_control,
        }
        for record in stage.records
    ]


# --------------------------------------------------------------------------------------
# B1 — pure and offline
# --------------------------------------------------------------------------------------


def _imported_roots() -> set[str]:
    """The top-level module names the shipped source imports, read with `ast`.

    Never by importing: importing executes the module and reports on this venv rather
    than on the source that runs, which is why `test_forecast_exposure` walks the tree.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_generator_is_pure_and_offline() -> None:
    """B1 — no network, no clock, no ambient randomness; a local `Random(seed)` only."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    source = MODULE.read_text(encoding="utf-8")

    roots = _imported_roots()
    assert roots, "the guard found no imports at all — it is scanning nothing"
    assert "json" in roots, "non-vacuity: the generator does read committed JSON"
    assert not roots & FORBIDDEN_IMPORTS, (
        f"the generator imports {sorted(roots & FORBIDDEN_IMPORTS)}: a registry "
        f"generator that can reach a network, a clock or the environment cannot be "
        f"reproduced from its committed inputs"
    )
    assert roots <= ALLOWED_IMPORTS, f"unexpected imports: {sorted(roots - ALLOWED_IMPORTS)}"

    for forbidden in ("now(", "today(", "monotonic(", "getenv(", "urlopen("):
        assert forbidden not in source, f"{forbidden!r} appears in the generator"

    # Randomness: every `random.X` must be `random.Random`, and every such construction
    # must sit inside a function — a module-level rng is state shared across calls, which
    # is exactly what makes a draw irreproducible.
    inside_a_function: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside_a_function.update(id(child) for child in ast.walk(node))

    seen_local_rng = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not (isinstance(node.value, ast.Name) and node.value.id == "random"):
            continue
        assert node.attr == "Random", (
            f"the generator uses the module-level `random.{node.attr}`; the draw must "
            f"come from a local `random.Random(seed)` (selection.py's rule)"
        )
        assert id(node) in inside_a_function, (
            "a `random.Random` is constructed at module level; it must be local to the "
            "draw so `(pool, target, seed)` alone decides the result"
        )
        seen_local_rng = True

    assert seen_local_rng, (
        "non-vacuity: the generator draws instances, so it must construct a seeded "
        "local rng somewhere"
    )


# --------------------------------------------------------------------------------------
# B2 — byte-identical regeneration
# --------------------------------------------------------------------------------------


def test_regenerating_rewrites_identical_bytes(tmp_path: Path) -> None:
    """B2 — `git status` staying clean on a re-run *is* the reproducibility check."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    assert main(["--out-dir", str(first)]) == 0
    assert main(["--out-dir", str(second)]) == 0

    written = sorted(path.name for path in first.glob("*.json"))
    assert written == sorted(SELF_OUTPUT_FILENAMES), (
        f"the generator must emit exactly {sorted(SELF_OUTPUT_FILENAMES)}, wrote {written}"
    )

    for name in SELF_OUTPUT_FILENAMES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), (
            f"{name} is not byte-identical across two runs (B2)"
        )

    # And re-running into the SAME directory must not perturb it either — that is the
    # exact shape of the Phase-3 `git status` check.
    before = (first / SELF_OUTPUT_FILENAMES[1]).read_bytes()
    assert main(["--out-dir", str(first)]) == 0
    assert (first / SELF_OUTPUT_FILENAMES[1]).read_bytes() == before


# --------------------------------------------------------------------------------------
# B3 — the conservative fresh set
# --------------------------------------------------------------------------------------


def test_every_real_instance_is_in_the_pool() -> None:
    """B3 — a drawn instance that is not in `pool.json` was invented, not selected."""
    pool_ids = {record.instance_id for record in real(_pool_records())}
    assert pool_ids, "non-vacuity: the committed pool is not empty"

    built = _built()
    drawn = [
        record for stage in built.values() for record in real(stage.records)
    ]
    assert drawn, "non-vacuity: the mint draws real instances"
    for record in drawn:
        assert record.instance_id in pool_ids, (
            f"{record.instance_id!r} is not in {POOL.name}: a registry may only contain "
            f"instances the committed pool actually holds"
        )


def test_no_real_instance_appears_in_any_committed_registry() -> None:
    """B3 — the conservative rule: registry membership, never the ledger-derived set.

    Also pins the measurement. The fresh set is **30** (django 23, sympy 7); a different
    number means the exclusion rule drifted, and the instruction is to report it, never
    to retune the target around it.
    """
    pool = _pool_records()
    excluded = _excluded_from_committed()

    fresh = fresh_pool(pool, excluded)
    assert len(fresh) == EXPECTED_FRESH_COUNT == 30, (
        f"the conservative fresh set is {len(fresh)}, not the measured 30: the exclusion "
        f"rule has drifted — report, do not adjust the target"
    )
    by_repo: dict[str, int] = {}
    for record in fresh:
        by_repo[record.repo] = by_repo.get(record.repo, 0) + 1
    assert by_repo == EXPECTED_FRESH_BY_REPO, (
        "the fresh residue is ~100% django+sympy; that monoculture is STATED in the "
        "header, never simulated away by a stratified draw"
    )

    for stage in _built().values():
        for record in real(stage.records):
            assert record.instance_id not in excluded, (
                f"{record.instance_id!r} already appears in a committed registry; a "
                f"drawn instance must never have been drawn before (B3)"
            )


def test_the_exclusion_set_is_derived_from_the_registries_on_disk(tmp_path: Path) -> None:
    """B3' — plant a registry, and the excluded set must GROW.

    A transcribed id list cannot pass this: it would return the same set whatever is on
    disk. The second half is the converse and is what makes regeneration stable — the
    generator's OWN outputs are skipped, so a committed `cm-stage2.json` does not exclude
    the instances it itself drew.
    """
    planted = tmp_path / "instances"
    planted.mkdir()
    for path in INSTANCES_DIR.glob("*.json"):
        (planted / path.name).write_bytes(path.read_bytes())

    baseline = derive_excluded_ids(planted)
    assert baseline == _excluded_from_committed(), (
        "the derivation must reproduce the committed exclusion set exactly"
    )
    assert baseline, "non-vacuity: committed registries do name driven instances"

    fresh_ids = sorted(
        record.instance_id for record in fresh_pool(_pool_records(), baseline)
    )
    assert fresh_ids, "non-vacuity: there are fresh instances to plant"
    victim = fresh_ids[0]

    dump_registry(
        [
            InstanceRecord(
                instance_id=victim,
                repo="django/django",
                base_commit="0" * 40,
                problem_statement="planted",
                task_string="planted",
            )
        ],
        planted / "zz-planted-stage.json",
    )
    grown = derive_excluded_ids(planted)
    assert grown == baseline | {victim}, (
        "planting a registry that names a fresh instance must grow the excluded set by "
        "exactly that id; a transcribed literal could not"
    )

    # The generator's own outputs are NOT a source of exclusions: were they, a committed
    # cm-stage2.json would exclude its own draw and the next run would not reproduce it.
    (planted / "zz-planted-stage.json").unlink()
    dump_registry(
        [
            InstanceRecord(
                instance_id=victim,
                repo="django/django",
                base_commit="0" * 40,
                problem_statement="planted",
                task_string="planted",
            )
        ],
        planted / SELF_OUTPUT_FILENAMES[1],
    )
    assert derive_excluded_ids(planted) == baseline, (
        f"{SELF_OUTPUT_FILENAMES[1]} must be skipped by the exclusion scan: a generator "
        f"that excludes its own output cannot regenerate byte-identically (B2)"
    )


# --------------------------------------------------------------------------------------
# B4 — no collision with a banked corpus case id
# --------------------------------------------------------------------------------------


def test_no_drawn_instance_collides_with_a_banked_corpus_case_id() -> None:
    """B4 — `CaseExistsError` is fail-closed and there is no `--overwrite`.

    A banked case id is `trace-<instance>-turnN` / `-trajectory` / `-claim`, so a drawn
    instance whose id already owns that namespace could not bank at all.
    """
    banked = banked_case_ids()
    assert banked, (
        "non-vacuity: the committed re-add table names the banked cases; an empty set "
        "would make this guard pass on anything"
    )

    drawn = [record for stage in _built().values() for record in real(stage.records)]
    assert not case_id_collisions(drawn, banked), (
        f"a drawn instance owns a banked case-id namespace: "
        f"{case_id_collisions(drawn, banked)}"
    )

    # The predicate fires when it should — otherwise the assertion above is decoration.
    banked_instance = sorted(banked)[0].split("-turn")[0].removeprefix("trace-")
    collider = InstanceRecord(
        instance_id=banked_instance,
        repo="pallets/flask",
        base_commit="0" * 40,
        problem_statement="planted",
        task_string="planted",
    )
    assert case_id_collisions([collider], banked) == (banked_instance,), (
        "the collision predicate does not fire on an already-banked instance"
    )


# --------------------------------------------------------------------------------------
# B5 / B6 — controls
# --------------------------------------------------------------------------------------


def test_controls_are_carried_by_the_is_control_field() -> None:
    """B5 — never a naming convention on the id (`registry.py:18-20`)."""
    built = _built()

    stage1 = built[CM_STAGE1_NAME]
    stage2 = built[CM_STAGE2_NAME]

    assert [record.instance_id for record in controls(stage1.records)] == list(
        CM_STAGE1_CONTROL_IDS
    ), "cm-stage1 must be CTL-1 + CTL-4, in that order"
    assert len(stage1.records) == 2
    assert real(stage1.records) == (), "the probe stage carries no real instance"

    assert len(stage2.records) == 10
    assert [record.instance_id for record in stage2.records[:2]] == list(
        CM_STAGE2_CONTROL_IDS
    ), "cm-stage2 must lead with CTL-2 + CTL-3 — controls FIRST (Rule A / D-3)"
    assert stage2.records[:2] == CM_STAGE2_CONTROL_RECORDS, (
        "the control head must be the controls.py records themselves, not copies"
    )
    assert [record.instance_id for record in controls(stage2.records)] == list(
        CM_STAGE2_CONTROL_IDS
    )
    assert len(real(stage2.records)) == CM_STAGE2_REAL_TARGET == 8

    for stage in built.values():
        for record in stage.records:
            if record.is_control:
                expected = CONTROLS_BY_ID[record.instance_id]
                assert record.task_string == expected.task_string, (
                    f"control {record.instance_id!r} must carry controls.py's text "
                    f"verbatim at generation time"
                )
                assert record.problem_statement == expected.problem_statement
                assert record.repo == expected.repo
                assert record.base_commit == expected.base_commit
            else:
                assert "control" not in record.instance_id, (
                    "a real record must not be distinguishable as a control by name; "
                    "the partition is the `is_control` FIELD"
                )

    # The partition is the field, not the prefix: a control whose id says nothing about
    # being one is still a control.
    disguised = InstanceRecord(
        instance_id="django__django-00000",
        repo="django/django",
        base_commit="0" * 40,
        problem_statement="p",
        task_string="t",
        is_control=True,
    )
    assert controls([disguised]) == (disguised,)
    assert real([disguised]) == ()


def test_the_positive_control_is_present_in_the_probe_stage() -> None:
    """B6 — CTL-4 ships, and the registry records that it needs `filesystem+shell`."""
    stage1 = _built()[CM_STAGE1_NAME]

    ids = [record.instance_id for record in stage1.records]
    assert POSITIVE_CONTROL_RECORD.instance_id in ids
    assert POSITIVE_CONTROL_RECORD in stage1.records, (
        "the positive control must be the record from controls.py, verbatim"
    )
    assert CM_STAGE1_RECORDS[-1] is POSITIVE_CONTROL_RECORD

    toolset = json.dumps(stage1.header)
    assert POSITIVE_CONTROL_TOOLSET == "filesystem+shell"
    assert POSITIVE_CONTROL_TOOLSET in toolset, (
        "the probe stage's header must record that CTL-4 only produces evidence under "
        "--toolset filesystem+shell; it is the trajectory axis's PASS side"
    )

    published = stage1.header["controls"]
    assert set(published) == set(ids), (
        "every control in the stage must publish its expected outcome in the header"
    )
    assert (
        published[POSITIVE_CONTROL_RECORD.instance_id]["expected_trajectory_verdict"]
        == CONTROL_EXPECTATIONS[POSITIVE_CONTROL_RECORD.instance_id][
            "expected_trajectory_verdict"
        ]
        == "PASS"
    )


# --------------------------------------------------------------------------------------
# B7 — the stock loader
# --------------------------------------------------------------------------------------


def test_both_registries_load_through_the_stock_loader(tmp_path: Path) -> None:
    """B7 — fail-closed loader, no error: blank/missing/duplicate would raise."""
    out = tmp_path / "out"
    out.mkdir()
    assert main(["--out-dir", str(out)]) == 0

    for name, stage_name in zip(SELF_OUTPUT_FILENAMES, (CM_STAGE1_NAME, CM_STAGE2_NAME)):
        loaded = load_registry(out / name)
        expected = _built()[stage_name].records
        assert [record.instance_id for record in loaded] == [
            record.instance_id for record in expected
        ]
        assert loaded == expected, (
            f"{name} must round-trip through the stock loader unchanged"
        )

    # Non-vacuity: the loader really is fail-closed on this file's shape.
    tampered = json.loads((out / SELF_OUTPUT_FILENAMES[1]).read_text(encoding="utf-8"))
    tampered["instances"].append(dict(tampered["instances"][0]))
    (out / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate instance_id"):
        load_registry(out / "tampered.json")


# --------------------------------------------------------------------------------------
# B8 / B9 — the provenance header
# --------------------------------------------------------------------------------------


def test_the_header_records_pool_composition_and_non_gate_status() -> None:
    """B8 — the counts, the per-repo composition, and what this run is NOT."""
    pool = _pool_records()
    excluded = _excluded_from_committed()
    built = build_registries(pool, excluded)

    for stage_name, stage in built.items():
        header = stage.header

        exclusion = header["exclusion"]
        assert exclusion["pool_real"] == len(real(pool)) == 166
        assert exclusion["excluded"] == len(excluded)
        assert exclusion["fresh"] == EXPECTED_FRESH_COUNT
        assert exclusion["fresh_by_repo"] == EXPECTED_FRESH_BY_REPO, (
            "the pool composition is published BESIDE the counts (honesty property 5)"
        )
        assert exclusion["sources"] == sorted(
            path.name
            for path in INSTANCES_DIR.glob("*.json")
            if path.name != "pool.json" and path.name not in SELF_OUTPUT_FILENAMES
        ), "the header must name the files the exclusion set was derived FROM"
        assert "derived" in exclusion["rule"].lower()

        assert header["seed"] == SEED
        assert header["seed_rationale"] == SEED_RATIONALE

        sizes = header["stage_sizes"]
        assert sizes[CM_STAGE1_NAME] == 2
        assert sizes[CM_STAGE2_NAME] == 10

        assert header["composition"]["launched"] == len(stage.records)
        assert header["composition"]["real"] == len(real(stage.records))
        assert header["composition"]["controls"] == len(controls(stage.records))
        assert header["composition"]["by_repo"] == {
            repo: sum(1 for r in real(stage.records) if r.repo == repo)
            for repo in sorted({r.repo for r in real(stage.records)})
        }

        statement = header["not_a_gate_run"]
        lowered = statement.lower()
        assert "not a gate run" in lowered, f"{stage_name}: {statement!r}"
        assert "no violation rate" in lowered
        assert "50" in statement, "the >=50 denominator must be named, not alluded to"

        assert "not attempted" in header["stage3"].lower(), (
            "stage 3 must be recorded as NOT attempted, by name"
        )

        assert "instances" not in header, (
            "a header key named 'instances' would shadow the records (dump_registry "
            "raises, but the generator must never construct one)"
        )


def test_seed_history_is_present() -> None:
    """B9 — empty history is the claim 'drawn once'; a change must carry its reason."""
    assert isinstance(SEED_HISTORY, tuple)
    assert isinstance(SEED, int)
    assert "seed" in SEED_RATIONALE.lower()

    for entry in SEED_HISTORY:
        assert set(entry) == {"seed", "reason"}, (
            "a superseded seed is recorded with its reason; a silent re-roll is "
            "indistinguishable from seed-shopping"
        )
        assert isinstance(entry["reason"], str) and entry["reason"].strip()

    for stage in _built().values():
        assert stage.header["seed_history"] == [dict(entry) for entry in SEED_HISTORY]


# --------------------------------------------------------------------------------------
# B10 — never draw short
# --------------------------------------------------------------------------------------


def test_a_short_pool_raises_rather_than_drawing_short() -> None:
    """B10 — a short draw is a short denominator (`selection.py:54-60`)."""
    pool = _pool_records()
    excluded = _excluded_from_committed()
    fresh = fresh_pool(pool, excluded)
    assert len(fresh) > CM_STAGE2_REAL_TARGET

    # Starve the pool: exclude all but one fresh instance.
    starved = set(excluded) | {
        record.instance_id for record in fresh[1:]
    }
    with pytest.raises(InsufficientPoolError):
        build_registries(pool, starved)
