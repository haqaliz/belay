"""C6 corpus case format: a labeled, replayable case round-trips, and fails closed.

The corpus is moat #2 — every caught A1/A2 failure becomes a labeled datum that the
regression suite re-replays. This file pins the on-disk `case.json` format: a fully
populated case survives write->load byte-for-byte, the ONE documented default
(`human_label` omitted -> `pending`) holds, and every other malformed input is a NAMED
`ValueError` rather than a silent default. The fail-closed shape mirrors
`belay.verify.invariants.load_invariants`: an operator (or a later `corpus add`) who
declared a case Belay then swallowed would be regressing against a case that is not the
one they wrote.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case, load_case, write_case


def _full_case() -> Case:
    """A case with every field populated, nothing left to a default."""
    return Case(
        id="cheat-run-0007",
        target_turn_index=3,
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [
                {"axis": "A1", "kind": "invariant", "status": "FAIL"},
                {"axis": "A2", "kind": "effect", "status": "PASS"},
            ],
        },
        human_label="true-positive",
        invariants=[{"scope": "tests/", "rule": "read-only"}],
        server_command=["python", "editor_server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-07-18T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )


def test_full_case_round_trips_and_is_byte_stable(tmp_path: Path) -> None:
    """(a) A fully-populated case survives write->load equal, and case.json is stable."""
    case = _full_case()
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    write_case(dir_a, case)
    loaded = load_case(dir_a)
    assert loaded == case

    # Byte-stable: writing the loaded case again produces identical bytes (sorted keys).
    write_case(dir_b, loaded)
    assert (dir_a / "case.json").read_bytes() == (dir_b / "case.json").read_bytes()

    # And the persisted form is real JSON carrying the values, not a truthy blob.
    stored = json.loads((dir_a / "case.json").read_text(encoding="utf-8"))
    assert stored["human_label"] == "true-positive"
    assert stored["expected"]["reduced_status"] == "FAIL"
    assert stored["target_turn_index"] == 3


def test_omitted_human_label_defaults_to_pending(tmp_path: Path) -> None:
    """(b) `human_label` absent from case.json -> `pending`, the one allowed default."""
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    del data["human_label"]
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    loaded = load_case(tmp_path)
    assert loaded.human_label == "pending"


def test_unknown_human_label_is_rejected(tmp_path: Path) -> None:
    """(c) An unknown `human_label` string -> ValueError naming the field."""
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    data["human_label"] = "definitely-a-bug"
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="human_label"):
        load_case(tmp_path)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    """(d) A missing required field (target_turn_index) -> ValueError naming it."""
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    del data["target_turn_index"]
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="target_turn_index"):
        load_case(tmp_path)


def test_expected_missing_sub_verdicts_is_rejected(tmp_path: Path) -> None:
    """(e) `expected` without `sub_verdicts` -> ValueError naming it."""
    case = _full_case()
    write_case(tmp_path, case)

    data = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    del data["expected"]["sub_verdicts"]
    (tmp_path / "case.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="sub_verdicts"):
        load_case(tmp_path)


def test_not_json_is_rejected(tmp_path: Path) -> None:
    """A case.json that is not valid JSON -> ValueError, never a raw JSONDecodeError."""
    (tmp_path / "case.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_case(tmp_path)
