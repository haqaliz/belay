"""Case schema v4: a corpus case can express an INSTANCE-LEVEL expected verdict.

The new `suite-before-success-claim` rule produces whole-INSTANCE verdicts — a
trajectory FAIL is not any turn's verdict, so the turn-shaped `expected` field
cannot express it. v4 adds an OPTIONAL `trajectory` field on the case: absent
means NOT a trajectory case (every existing case reads byte-for-byte as today),
present means the case's expected verdict is instance-level, of shape
`{"status": <reduced-verdict status>, "cause": <named cause or null>}`.

Presence is the declaration, exactly the rule `task_prestate` and `recorded_miss`
established: absent is omitted from `case.json` entirely, never written as `null`.
Fail-closed: a `trajectory` that is not a dict, lacks a known `status`, or carries
a `cause` that is neither null nor a string is a NAMED `ValueError` at load —
never a silent drop, which would regress the run against a case that is not the
one captured.

`CASE_SCHEMA_VERSION` moves 3 -> 4 because a v4 case read by pre-v4 code would
silently ignore the trajectory declaration and recompute the case through the
turn path — certifying an instance-level regression as a per-turn agreement, the
exact defect this aspect exists to remove.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from belay.corpus import case as case_module
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
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-08-09T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


def _trajectory_case(**trajectory: object) -> Case:
    return Case(**{**_full_case().__dict__, "trajectory": trajectory})


# --- round-trips: a trajectory case survives write->load byte-for-byte ---------------


def test_trajectory_fail_case_round_trips_byte_identical(tmp_path: Path) -> None:
    """A FAIL trajectory (the corrupt-success shape) survives write->load equal, bytes and all.

    `cause: null` is the declared absence of a named cause — it must round-trip as
    null, not be invented away or rejected.
    """
    case = _trajectory_case(status="FAIL", cause=None)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.trajectory == {"status": "FAIL", "cause": None}

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()

    stored = json.loads((dir_a / "case.json").read_text(encoding="utf-8"))
    assert stored["trajectory"] == {"status": "FAIL", "cause": None}


def test_trajectory_unverified_with_cause_round_trips(tmp_path: Path) -> None:
    """An UNVERIFIED trajectory naming its cause (e.g. NO_CLAIM_RECORDED) round-trips."""
    case = _trajectory_case(status="UNVERIFIED", cause="NO_CLAIM_RECORDED")
    write_case(tmp_path, case)

    loaded = load_case(tmp_path)
    assert loaded == case
    assert loaded.trajectory == {"status": "UNVERIFIED", "cause": "NO_CLAIM_RECORDED"}


@pytest.mark.parametrize(
    "status",
    ["PASS", "WARN", "FAIL", "UNVERIFIED"],
)
def test_every_reduced_verdict_status_is_a_legal_trajectory_status(
    tmp_path: Path, status: str
) -> None:
    """The trajectory status vocabulary IS the verdict contract's reduced set.

    A trajectory verdict is a verdict; a status the verdict contract would never
    emit is rejected, and every status it CAN emit loads.
    """
    case = _trajectory_case(status=status, cause=None)
    write_case(tmp_path, case)
    assert load_case(tmp_path).trajectory == {"status": status, "cause": None}


# --- absent means NOT a trajectory case ----------------------------------------------


def test_a_case_without_the_key_loads_with_trajectory_absent(tmp_path: Path) -> None:
    """No `trajectory` key -> not a trajectory case, byte-for-byte today's round trip.

    This is the shape of every existing case (the 7 banked FP cases, every
    recorded-miss declaration, every v3-era case): untouched, `trajectory` None.
    """
    case = _full_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.trajectory is None

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()


def test_a_v3_era_case_loads_unchanged_and_is_not_a_trajectory_case(tmp_path: Path) -> None:
    """A case stamped schema_version 3 (written before v4 existed) still loads clean.

    The version is preserved as read; the case is NOT a trajectory case. This is
    the additive-compat contract: the bump must not reject or restamp old cases.
    """
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["schema_version"] = 3
    assert "trajectory" not in data
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    loaded = load_case(tmp_path)
    assert loaded.schema_version == 3
    assert loaded.trajectory is None


def test_unset_trajectory_is_omitted_from_the_payload_not_written_as_null(
    tmp_path: Path,
) -> None:
    """Asserted on serialized BYTES: an unset trajectory must not appear as `null`."""
    write_case(tmp_path, _full_case())
    raw_bytes = (tmp_path / "case.json").read_bytes()
    assert b"trajectory" not in raw_bytes


def test_trajectory_is_not_a_required_field(tmp_path: Path) -> None:
    """`trajectory` does not join `_REQUIRED_FIELDS`.

    That tuple is closed and fail-closed -- a required new field would reject
    every case already sitting in `corpus/local/`, the same reasoning case.py
    already records for `schema_version`, `task_prestate` and `recorded_miss`.
    """
    assert "trajectory" not in case_module._REQUIRED_FIELDS

    case = _full_case()
    write_case(tmp_path, case)
    assert load_case(tmp_path).trajectory is None


# --- fail-closed: a malformed trajectory is a load error, never a silent drop ---------


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("flagged", id="bare-string"),
        pytest.param([{"status": "FAIL", "cause": None}], id="a-list"),
        pytest.param(7, id="an-int"),
        pytest.param({"cause": None}, id="missing-status"),
        pytest.param({"status": "FAIL"}, id="missing-cause-key"),
        pytest.param({"status": "BOGUS", "cause": None}, id="unknown-status"),
        pytest.param({"status": "FAIL", "cause": 7}, id="non-string-cause"),
        pytest.param({"status": "FAIL", "cause": ["named"]}, id="list-cause"),
    ],
)
def test_malformed_trajectory_raises_a_named_value_error(tmp_path: Path, bad: object) -> None:
    """A malformed `trajectory` is a NAMED ValueError, never a silent default.

    A swallowed malformed trajectory would regress the run against a case that is
    not the one captured -- the exact false result this loader refuses -- so it
    must break the load, loud, naming the field.
    """
    write_case(tmp_path, _full_case())

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["trajectory"] = bad
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="trajectory"):
        load_case(tmp_path)


# --- the version bump and its rationale ----------------------------------------------


def test_schema_version_is_five_and_the_rationale_docstring_names_v5() -> None:
    """The version reads 5, and the version-rationale comment states what v5 adds.

    The rationale is a `#:` comment on the constant (not reachable via
    `__doc__` -- that would be `int.__doc__`), so it is pinned on the module
    SOURCE: the block preceding the assignment must name the v5 addition (and
    still name the v4 one -- the rationale documents every version).
    """
    assert CASE_SCHEMA_VERSION == 5

    source = inspect.getsource(case_module)
    rationale = source.split("CASE_SCHEMA_VERSION = ", 1)[0]
    assert "Version 5" in rationale, rationale
    assert "claim" in rationale, rationale
    assert "Version 4" in rationale, rationale
    assert "trajectory" in rationale, rationale
