"""Case schema v5: a corpus case can express an INSTANCE-LEVEL A3 claim expected.

The A3 claim re-derivation verdict is instance-level — "the check the author wrote ran
against the materialized final state and exited non-zero" is not any turn's verdict, so
the turn-shaped `expected` field cannot express it. v5 adds an OPTIONAL `claim` field on
the case: absent means NOT a claim case (every existing case reads byte-for-byte as
today), present means the case declares an instance-level claim expected of shape

    {"status": <FAIL|WARN|UNVERIFIED>, "cause": <named cause or null>,
     "check": {"source": str, "exit_code": int or null}}

Presence is the declaration, exactly the rule `task_prestate`, `recorded_miss` and
`trajectory` established: absent is omitted from `case.json` entirely, never written as
`null`. Fail-closed: a `claim` that is not a dict, lacks any of `status`/`cause`/`check`,
carries a `status` outside the A3 vocabulary (note: `PASS` is NOT in it — A3 never emits
PASS), or whose `check` is malformed is a NAMED `ValueError` at load — never a silent
drop, which would regress the run against a case that is not the one captured.

`CASE_SCHEMA_VERSION` moves 4 -> 5 because a v5 case read by pre-v5 code would silently
ignore the claim declaration and recompute the case through the turn path — certifying an
instance-level (A3) regression as a per-turn agreement, the exact defect this aspect
exists to remove.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from belay.corpus import case as case_module
from belay.corpus.case import CASE_SCHEMA_VERSION, Case, load_case, write_case

CLAIM_FAIL = {
    "status": "FAIL",
    "cause": None,
    "check": {"source": "pytest -q", "exit_code": 3},
}
CLAIM_UNVERIFIED = {
    "status": "UNVERIFIED",
    "cause": "NO_CLAIM_RECORDED",
    "check": {"source": "", "exit_code": None},
}


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


def _claim_case(**claim: object) -> Case:
    return Case(**{**_full_case().__dict__, "claim": claim})


# --- round-trips: a claim case survives write->load byte-for-byte ----------------------


def test_claim_fail_case_round_trips_byte_identical(tmp_path: Path) -> None:
    """A FAIL claim (the intent-drift shape) survives write->load equal, bytes and all.

    `cause: null` is the declared absence of a named cause and `exit_code` the real
    observed one — both must round-trip as themselves, never invented away.
    """
    case = _claim_case(**CLAIM_FAIL)
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.claim == CLAIM_FAIL

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()

    stored = json.loads((dir_a / "case.json").read_text(encoding="utf-8"))
    assert stored["claim"] == CLAIM_FAIL


def test_claim_unverified_with_cause_round_trips_exit_code_null(tmp_path: Path) -> None:
    """An UNVERIFIED claim naming its cause round-trips with `exit_code: null`.

    `null` is "the check did not execute" (the CheckResult contract) — it must round-trip
    as null, absent-never-zero: a fabricated 0 would read as a check that ran and passed.
    """
    case = _claim_case(**CLAIM_UNVERIFIED)
    write_case(tmp_path, case)

    loaded = load_case(tmp_path)
    assert loaded == case
    assert loaded.claim == CLAIM_UNVERIFIED
    assert loaded.claim["check"]["exit_code"] is None


@pytest.mark.parametrize(
    "status",
    ["FAIL", "WARN", "UNVERIFIED"],
)
def test_every_a3_status_is_a_legal_claim_status(tmp_path: Path, status: str) -> None:
    """The claim status vocabulary IS the A3 verdict contract's decided set.

    A claim verdict is a verdict; a status the A3 axis never emits is rejected. Note the
    vocabulary deliberately EXCLUDES `PASS` — A3 never emits PASS, so a stored claim
    status of PASS would be a verdict this axis could not have produced.
    """
    case = _claim_case(status=status, cause=None,
                       check={"source": "pytest -q", "exit_code": 1})
    write_case(tmp_path, case)
    assert load_case(tmp_path).claim["status"] == status


# --- absent means NOT a claim case -----------------------------------------------------


def test_a_case_without_the_key_loads_with_claim_absent(tmp_path: Path) -> None:
    """No `claim` key -> not a claim case, byte-for-byte today's round trip.

    This is the shape of every existing case: untouched, `claim` None.
    """
    case = _full_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case
    assert loaded.claim is None

    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()


def test_a_v4_era_case_loads_unchanged_and_is_not_a_claim_case(tmp_path: Path) -> None:
    """A case stamped schema_version 4 — v4's full shape, `trajectory` included — still
    loads clean with the version preserved, and is NOT a claim case.

    This is the additive-compat contract: the bump must not reject or restamp old cases,
    and a v4 trajectory case must keep reading as exactly the trajectory case it is.
    """
    case = Case(**{**_full_case().__dict__, "trajectory": {"status": "FAIL", "cause": None}})
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["schema_version"] = 4
    assert "claim" not in data
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    loaded = load_case(tmp_path)
    assert loaded.schema_version == 4
    assert loaded.trajectory == {"status": "FAIL", "cause": None}
    assert loaded.claim is None


def test_a_v3_era_case_loads_unchanged(tmp_path: Path) -> None:
    """A v3-era case (schema_version 3, no trajectory, no claim) still loads clean."""
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["schema_version"] = 3
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    loaded = load_case(tmp_path)
    assert loaded.schema_version == 3
    assert loaded.claim is None
    assert loaded.trajectory is None


def test_unset_claim_is_omitted_from_the_payload_not_written_as_null(
    tmp_path: Path,
) -> None:
    """Asserted on serialized BYTES: an unset claim must not appear as `null`."""
    write_case(tmp_path, _full_case())
    raw_bytes = (tmp_path / "case.json").read_bytes()
    assert b"claim" not in raw_bytes


def test_claim_is_not_a_required_field(tmp_path: Path) -> None:
    """`claim` does not join `_REQUIRED_FIELDS`.

    That tuple is closed and fail-closed -- a required new field would reject every case
    already sitting in `corpus/local/`, the same reasoning case.py already records for
    `schema_version`, `task_prestate`, `recorded_miss` and `trajectory`.
    """
    assert "claim" not in case_module._REQUIRED_FIELDS

    case = _full_case()
    write_case(tmp_path, case)
    assert load_case(tmp_path).claim is None


# --- fail-closed: a malformed claim is a load error, never a silent drop ---------------


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("flagged", id="bare-string"),
        pytest.param([{"status": "FAIL", "cause": None}], id="a-list"),
        pytest.param(7, id="an-int"),
        pytest.param({"cause": None, "check": {"source": "pytest -q", "exit_code": 1}},
                     id="missing-status"),
        pytest.param({"status": "FAIL", "check": {"source": "pytest -q", "exit_code": 1}},
                     id="missing-cause-key"),
        pytest.param({"status": "FAIL", "cause": None}, id="missing-check-key"),
        pytest.param({"status": "PASS", "cause": None,
                      "check": {"source": "pytest -q", "exit_code": 1}},
                     id="pass-status-never-a3"),
        pytest.param({"status": "BOGUS", "cause": None,
                      "check": {"source": "pytest -q", "exit_code": 1}},
                     id="unknown-status"),
        pytest.param({"status": "FAIL", "cause": 7,
                      "check": {"source": "pytest -q", "exit_code": 1}},
                     id="non-string-cause"),
        pytest.param({"status": "FAIL", "cause": ["named"],
                      "check": {"source": "pytest -q", "exit_code": 1}},
                     id="list-cause"),
        pytest.param({"status": "FAIL", "cause": None, "check": "flagged"},
                     id="string-check"),
        pytest.param({"status": "FAIL", "cause": None, "check": {"exit_code": 1}},
                     id="check-missing-source"),
        pytest.param({"status": "FAIL", "cause": None,
                      "check": {"source": 7, "exit_code": 1}},
                     id="non-string-check-source"),
        pytest.param({"status": "FAIL", "cause": None, "check": {"source": "pytest -q"}},
                     id="check-missing-exit-code"),
        pytest.param({"status": "FAIL", "cause": None,
                      "check": {"source": "pytest -q", "exit_code": "1"}},
                     id="string-exit-code"),
        pytest.param({"status": "FAIL", "cause": None,
                      "check": {"source": "pytest -q", "exit_code": 1.5}},
                     id="float-exit-code"),
        pytest.param({"status": "FAIL", "cause": None,
                      "check": {"source": "pytest -q", "exit_code": True}},
                     id="bool-exit-code"),
    ],
)
def test_malformed_claim_raises_a_named_value_error(tmp_path: Path, bad: object) -> None:
    """A malformed `claim` is a NAMED ValueError, never a silent default.

    A swallowed malformed claim would regress the run against a case that is not the one
    captured -- the exact false result this loader refuses -- so it must break the load,
    loud, naming the field.
    """
    write_case(tmp_path, _full_case())

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["claim"] = bad
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="claim"):
        load_case(tmp_path)


def test_recorded_miss_on_a_claim_fail_is_a_contradiction(tmp_path: Path) -> None:
    """The v3 declaration refuses a miss that was caught — extended to the claim
    dimension: `recorded_miss` beside a stored claim `status: FAIL` is a contradiction
    ("the engine caught it, and it is a miss") and refuses to load, exactly like the
    per-turn `expected.reduced_status == FAIL` refusal."""
    case = _claim_case(**CLAIM_FAIL)
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["recorded_miss"] = {"note": "the check was too weak to catch the drift"}
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="contradiction"):
        load_case(tmp_path)


# --- the version bump and its rationale ----------------------------------------------


def test_schema_version_is_five_and_the_rationale_docstring_names_v5() -> None:
    """The version reads 5, and the version-rationale comment states what v5 adds.

    The rationale is a `#:` comment on the constant (not reachable via `__doc__` -- that
    would be `int.__doc__`), so it is pinned on the module SOURCE: the block preceding
    the assignment must name the v5 addition.
    """
    assert CASE_SCHEMA_VERSION == 5

    source = inspect.getsource(case_module)
    rationale = source.split("CASE_SCHEMA_VERSION = ", 1)[0]
    assert "Version 5" in rationale, rationale
    assert "claim" in rationale, rationale