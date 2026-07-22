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
