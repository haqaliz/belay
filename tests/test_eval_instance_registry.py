"""The Phase-0 instance registry: a typed record and a fail-closed loader.

The live mint is driven from data, not prose: one record per SWE-bench-lite instance,
committed so the run is reproducible from the repo alone. Every later phase (task-string
derivation, the stratified draw, the batch harness) consumes this type, so a silently
`None`-defaulted field here would propagate into the published number — a registry that
loaded wrong would mint the wrong instances and nobody would see it. Hence the loader is
fail-closed in the style of `belay.phase0.ledger.from_json` and `belay.corpus.case
.load_case`: a missing or blank required field is a named `ValueError`, never a default.

Controls (PRD must-have 15) are separated by the `is_control` **field**, never by a
naming convention on `instance_id` — a convention is a string anyone can typo.

This file is written FIRST, before `eval/instances/registry.py` exists, per strict TDD.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.instances.registry import (
    InstanceRecord,
    controls,
    dump_registry,
    load_registry,
    real,
)


def _record(
    instance_id: str = "pallets__flask-4045",
    *,
    repo: str = "pallets/flask",
    base_commit: str = "d8c37f43724cd9fb0870f77877b7c4c7e38a19e0",
    problem_statement: str = "Raise error when blueprint name contains a dot.",
    task_string: str = "Fix the following issue: blueprint names must not contain a dot.",
    is_control: bool = False,
) -> InstanceRecord:
    return InstanceRecord(
        instance_id=instance_id,
        repo=repo,
        base_commit=base_commit,
        problem_statement=problem_statement,
        task_string=task_string,
        is_control=is_control,
    )


def _raw(**overrides) -> dict:
    """One registry entry as raw JSON-able data, before any override."""
    entry = {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "d26b2424437dabeeca94d7900b37d2df4410da0c",
        "problem_statement": "UsernameValidator allows trailing newline in usernames.",
        "task_string": "Fix the following issue: trailing newlines in usernames.",
        "is_control": False,
    }
    entry.update(overrides)
    return entry


def _write_raw(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps({"instances": entries}), encoding="utf-8")


def test_registry_round_trips(tmp_path: Path) -> None:
    """`load_registry(dump_registry(records))` returns the identical records.

    Also pins the two properties that keep a regenerated registry diffing cleanly:
    stable key order within each entry, and a trailing newline on the file.
    """
    records = (
        _record(),
        _record(
            instance_id="django__django-11099",
            repo="django/django",
            base_commit="d26b2424437dabeeca94d7900b37d2df4410da0c",
            problem_statement="UsernameValidator allows a trailing newline.",
            task_string="Fix the following issue: trailing newline in usernames.",
        ),
    )
    path = tmp_path / "pool.json"

    dump_registry(records, path)

    assert load_registry(path) == records

    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n"), "registry file must end with a trailing newline"

    first_entry = json.loads(text)["instances"][0]
    assert list(first_entry) == [
        "instance_id",
        "repo",
        "base_commit",
        "problem_statement",
        "task_string",
        "is_control",
    ], "registry entries must serialize in a stable key order"


def test_missing_field_is_a_named_error(tmp_path: Path) -> None:
    """A missing required field raises a `ValueError` naming the field AND the instance.

    Never a `None`-defaulted record: a registry entry with no `base_commit` would send
    the batch harness to whatever HEAD happens to be, silently changing the task.
    """
    entry = _raw()
    del entry["base_commit"]
    path = tmp_path / "pool.json"
    _write_raw(path, [entry])

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    message = str(excinfo.value)
    assert "base_commit" in message
    assert "django__django-11099" in message


def test_blank_instance_id_is_rejected(tmp_path: Path) -> None:
    """A present-but-blank required field is as bad as an absent one, and named as such."""
    path = tmp_path / "pool.json"
    _write_raw(path, [_raw(instance_id="   ")])

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    message = str(excinfo.value)
    assert "instance_id" in message
    assert "blank" in message


def test_control_instances_are_marked_and_separable(tmp_path: Path) -> None:
    """Controls are told apart by the `is_control` field, not by a naming convention."""
    a_control = _record(
        instance_id="django__django-11099",
        repo="django/django",
        is_control=True,
    )
    a_real = _record()
    path = tmp_path / "selected.json"

    dump_registry((a_real, a_control), path)
    loaded = load_registry(path)

    assert controls(loaded) == (a_control,)
    assert real(loaded) == (a_real,)
    # The split is a partition: nothing lost, nothing counted twice.
    assert len(controls(loaded)) + len(real(loaded)) == len(loaded)
    # And it is driven by the field, not by anything spellable in the id.
    assert "control" not in a_control.instance_id


def test_duplicate_instance_id_is_rejected(tmp_path: Path) -> None:
    """A repeated `instance_id` raises at load, naming the duplicated id.

    A duplicate would be run twice and counted twice, quietly distorting the
    violation-rate denominator the mint exists to publish.
    """
    path = tmp_path / "pool.json"
    _write_raw(path, [_raw(), _raw(task_string="a different task string")])

    with pytest.raises(ValueError) as excinfo:
        load_registry(path)

    message = str(excinfo.value)
    assert "duplicate" in message.lower()
    assert "django__django-11099" in message


# --------------------------------------------------------------------------------------
# The optional provenance header (D3) — strictly ADDITIVE
# --------------------------------------------------------------------------------------
#
# `pool.json` and `selected.json` must carry their own provenance: the dataset revision
# and filter thresholds that produced the pool, and the seed, target and composition that
# produced the draw. That provenance goes THROUGH this writer rather than around it: a
# second writer would have to re-implement the stable key order and the trailing newline
# that exist precisely so a regenerated registry diffs cleanly, and the two would drift.
#
# `load_registry` already ignores unknown top-level keys on purpose. These tests pin the
# other half — that writing a header is optional, ordered, and byte-identical to today
# when absent. `test_registry_round_trips` above must keep passing UNEDITED; if it ever
# needs a change, the seam is not additive and the design is wrong.


def test_header_round_trips_and_precedes_instances(tmp_path: Path) -> None:
    """Header keys are written before `"instances"`, in the caller's order.

    Order is not cosmetic here: the header is what a human reads first when auditing the
    committed pool, and a JSON file whose provenance is buried under 166 records is
    provenance nobody checks.
    """
    path = tmp_path / "pool.json"
    header = {
        "dataset": "princeton-nlp/SWE-bench_Lite",
        "revision": "0f3f5f1b0b2a3c4d5e6f7a8b9c0d1e2f3a4b5c6d",
        "filters": {"max_changed_lines": 15, "max_statement_chars": 2000},
        "counts": {"all": 300, "short_statement": 166},
    }

    dump_registry((_record(),), path, header=header)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload) == [
        "dataset",
        "revision",
        "filters",
        "counts",
        "instances",
    ], "header keys must be emitted in the caller's order, before 'instances'"
    assert payload["filters"] == header["filters"]
    assert payload["counts"] == header["counts"]

    from eval.instances.registry import load_header

    assert load_header(path) == header


def test_load_registry_ignores_the_header(tmp_path: Path) -> None:
    """Records load identically with and without a header.

    The loader's tolerance for unknown top-level keys is what makes this seam additive;
    this asserts the tolerance actually holds against a header the writer produced,
    rather than against a hand-written one that happens to be shaped conveniently.
    """
    records = (_record(),)
    plain = tmp_path / "plain.json"
    with_header = tmp_path / "with_header.json"

    dump_registry(records, plain)
    dump_registry(records, with_header, header={"seed": 20260723, "target": 65})

    assert load_registry(with_header) == load_registry(plain) == records


def test_dump_without_a_header_is_byte_identical_to_today(tmp_path: Path) -> None:
    """`header=None` produces exactly today's bytes. The seam is additive or it is wrong.

    Pinned as bytes, not as a shape: `pool.json` and `selected.json` are committed data,
    so any change in this writer's output is a diff in review. A writer that reformatted
    every record the moment a header appeared would make provenance and content
    indistinguishable in that diff.
    """
    records = (
        _record(),
        _record(instance_id="django__django-11099", repo="django/django"),
    )
    default = tmp_path / "default.json"
    explicit = tmp_path / "explicit.json"

    dump_registry(records, default)
    dump_registry(records, explicit, header=None)

    expected = (
        json.dumps(
            {"instances": [_record_json(record) for record in records]},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    assert default.read_text(encoding="utf-8") == expected
    assert explicit.read_text(encoding="utf-8") == expected


def test_an_empty_header_is_not_the_same_as_no_header(tmp_path: Path) -> None:
    """`header={}` writes no header keys — and still no crash, still valid.

    An empty mapping is a caller saying "I have no provenance to add", which must behave
    like `None` rather than emitting a stray empty object.
    """
    path = tmp_path / "pool.json"
    dump_registry((_record(),), path, header={})

    assert list(json.loads(path.read_text(encoding="utf-8"))) == ["instances"]

    from eval.instances.registry import load_header

    assert load_header(path) == {}


def test_load_header_on_a_headerless_file_is_empty(tmp_path: Path) -> None:
    """A file written before headers existed reads back an empty header, not an error."""
    path = tmp_path / "pool.json"
    dump_registry((_record(),), path)

    from eval.instances.registry import load_header

    assert load_header(path) == {}


def test_a_header_may_not_shadow_the_instances_key(tmp_path: Path) -> None:
    """A header key called `"instances"` raises instead of silently eating the records.

    Last-write-wins here would produce a file that still parses, still loads, and has
    lost every instance — a short denominator with no error anywhere, which is exactly
    the failure mode the fail-closed loader exists to prevent.
    """
    path = tmp_path / "pool.json"

    with pytest.raises(ValueError) as excinfo:
        dump_registry((_record(),), path, header={"instances": "oops"})

    assert "instances" in str(excinfo.value)


def test_a_non_json_serializable_header_raises(tmp_path: Path) -> None:
    """A header that cannot be serialized fails loudly rather than half-writing a file."""
    path = tmp_path / "pool.json"

    with pytest.raises((TypeError, ValueError)):
        dump_registry((_record(),), path, header={"seed": {1, 2, 3}})

    assert not path.exists(), (
        "a failed dump must leave no file behind: a truncated pool.json that still "
        "parses is a short denominator nobody notices"
    )


def _record_json(record: InstanceRecord) -> dict:
    """The expected on-disk shape of one record — restated here on purpose.

    Deliberately not imported from `registry._record_to_json`: a byte-identity test that
    re-uses the implementation's own serializer would follow it wherever it went and
    assert nothing.
    """
    return {
        "instance_id": record.instance_id,
        "repo": record.repo,
        "base_commit": record.base_commit,
        "problem_statement": record.problem_statement,
        "task_string": record.task_string,
        "is_control": record.is_control,
    }
