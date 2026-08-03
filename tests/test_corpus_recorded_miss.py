"""A corpus case can DECLARE that its stored verdict records a MISS, not a catch.

The failure corpus can only ever be built from FLAGGED turns (`belay phase0 run` ingests
FAIL turns and nothing else), so a violation the detector MISSES can never become a case
by the normal path -- the corpus structurally cannot measure recall. This is the schema
half of fixing that: a case gains a `recorded_miss` field so a human can bank a known-missed
violation as a case whose `expected.reduced_status` is the CLEAN verdict the engine actually
produced, with a declaration recording that the clean verdict is a miss, not a pass.

Presence is the declaration -- `recorded_miss` absent means undeclared, a normal case,
byte-for-byte today's behaviour. This is the same rule `task_prestate` established in
`corpus-task-prestate`, and this file's first test pins that precedent verbatim: nothing
about loading, round-tripping, or the payload of an undeclared case may change.

`CASE_SCHEMA_VERSION` moves 2 -> 3 because a v3 case read by pre-v3 code would silently
misclassify a declared miss as a normal case -- certifying blindness as a pass, the exact
defect this aspect exists to remove.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import CASE_SCHEMA_VERSION, Case, load_case, write_case


def _full_case() -> Case:
    """A case with every pre-existing field populated, nothing left to a default."""
    return Case(
        id="cheat-run-0007",
        target_turn_index=3,
        expected={
            "reduced_status": "PASS",
            "sub_verdicts": [
                {"axis": "A1", "kind": "invariant", "status": "PASS"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
        human_label="true-positive",
        invariants=[{"scope": "tests/", "rule": "no-assertion-weakening"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-08-03T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


def test_a_case_without_the_declaration_loads_and_behaves_exactly_as_today(
    tmp_path: Path,
) -> None:
    """Absent `recorded_miss` -> undeclared, byte-for-byte today's round trip."""
    case = _full_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.recorded_miss is None

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()


def test_declaration_requires_a_non_empty_note(tmp_path: Path) -> None:
    """A `recorded_miss` with a non-empty note round-trips and loads back unchanged."""
    case = Case(
        **{
            **_full_case().__dict__,
            "recorded_miss": {"note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"},
        }
    )
    write_case(tmp_path, case)

    loaded = load_case(tmp_path)
    assert loaded.recorded_miss == {
        "note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"
    }

    stored = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert stored["recorded_miss"] == {
        "note": "pytest-5227 t11/t13: unflagged, testing/ scope miss"
    }


@pytest.mark.parametrize(
    "bad_note",
    [
        pytest.param("", id="empty-string"),
        pytest.param(None, id="missing-key"),
        pytest.param(7, id="non-string"),
    ],
)
def test_declaration_with_missing_or_empty_note_is_rejected(
    tmp_path: Path, bad_note: object
) -> None:
    """A note that is absent, empty, or not a string -> named ValueError.

    Mirrors `curate.py`'s `root_cause` requirement for a `true-positive` label: a human
    asserting "the engine missed something here" must say what."""
    write_case(tmp_path, _full_case())
    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    if bad_note is None:
        data["recorded_miss"] = {}
    else:
        data["recorded_miss"] = {"note": bad_note}
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


@pytest.mark.parametrize(
    "malformed",
    [
        pytest.param("a miss happened", id="bare-string"),
        pytest.param(["a miss happened"], id="a-list"),
        pytest.param(7, id="an-int"),
    ],
)
def test_malformed_declaration_raises_a_named_value_error(
    tmp_path: Path, malformed: object
) -> None:
    """A `recorded_miss` that is not an object at all -> named ValueError."""
    write_case(tmp_path, _full_case())
    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["recorded_miss"] = malformed
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


def test_a_declaration_on_an_already_fail_case_is_a_contradiction(tmp_path: Path) -> None:
    """A "miss" whose recorded verdict is already FAIL was caught, not missed.

    Fail-closed beats a case that means nothing: this must raise at load, not silently
    accept a declaration that contradicts the verdict it decorates.
    """
    case = _full_case()
    case = Case(
        **{
            **case.__dict__,
            "expected": {
                "reduced_status": "FAIL",
                "sub_verdicts": [{"axis": "A1", "kind": "invariant", "status": "FAIL"}],
            },
            "recorded_miss": {"note": "a miss that was actually caught"},
        }
    )
    write_case(tmp_path, case)

    with pytest.raises(ValueError, match="recorded_miss"):
        load_case(tmp_path)


def test_payload_omits_the_declaration_when_unset(tmp_path: Path) -> None:
    """Asserted on serialized BYTES: an unset declaration must not appear as `null`."""
    write_case(tmp_path, _full_case())

    raw_bytes = (tmp_path / "case.json").read_bytes()
    assert b"recorded_miss" not in raw_bytes


def test_declaration_is_not_a_required_field(tmp_path: Path) -> None:
    """A v2 case (schema_version 2, written before `recorded_miss` existed) still loads.

    `_REQUIRED_FIELDS` is closed and fail-closed -- a required new field would reject
    every case already sitting in `corpus/local/`.
    """
    from belay.corpus.case import _REQUIRED_FIELDS

    assert "recorded_miss" not in _REQUIRED_FIELDS

    case = Case(**{**_full_case().__dict__, "schema_version": 2})
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert "recorded_miss" not in data
    assert data["schema_version"] == 2

    loaded = load_case(tmp_path)
    assert loaded.recorded_miss is None
    assert loaded.schema_version == 2


def test_schema_version_is_three_and_absent_still_means_one(tmp_path: Path) -> None:
    """The version bump, and the unversioned-means-1 precedent it must not disturb."""
    assert CASE_SCHEMA_VERSION == 3

    case = _full_case()
    write_case(tmp_path, case)
    assert load_case(tmp_path).schema_version == 3

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    del data["schema_version"]
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    assert load_case(tmp_path).schema_version == 1
