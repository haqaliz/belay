"""Compatibility and the two unguarded edges the Stage-1 re-mint hit for real.

Three small things, one theme — a completed verification must not be thrown away by
something incidental:

1. `belay phase0 run --ledger` wrote to the path with no `mkdir`. It is the only unguarded
   write in the CLI, and it runs AFTER the whole batch has been verified, so a typo'd or
   not-yet-created directory discards every replay that was just paid for. (Hit live.)
2. A corpus case must be able to carry the new `NOT_COVERED` status in its `sub_verdicts`
   — and must still be REFUSED if it claims it as a `reduced_status`, which the verdict
   contract says can never happen.
3. `schema_version` is optional-with-default. `_REQUIRED_FIELDS` is a closed tuple, so a
   required new field would reject every case already on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case, load_case, write_case

# --- 1. `phase0 run --ledger` into a directory that does not exist yet ------------------


def _empty_trace_dir(tmp_path: Path) -> Path:
    """A trace directory with no traces: `run_batch` yields an empty ledger, fast and
    offline. The ledger WRITE is what is under test, not what the batch found."""
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    return trace_dir


def test_phase0_run_creates_the_ledger_parent_dir(tmp_path: Path, capsys) -> None:
    """`--ledger out/nested/ledger.json` must succeed when `out/nested/` does not exist."""
    from belay.cli import main

    ledger_path = tmp_path / "out" / "nested" / "ledger.json"
    code = main(
        [
            "phase0", "run",
            str(_empty_trace_dir(tmp_path)),
            "--corpus-dir", str(tmp_path / "corpus"),
            "--ledger", str(ledger_path),
            "--server", "unused-server",
        ]
    )
    capsys.readouterr()

    assert code == 0, code
    assert ledger_path.exists(), (
        "the ledger was silently discarded because its parent did not exist — after a "
        "full batch had already been verified"
    )
    assert isinstance(json.loads(ledger_path.read_text(encoding="utf-8")), dict)


# --- 2. the corpus round-trips NOT_COVERED as a SUB-verdict, and only as one ------------


def _case(**overrides) -> Case:
    base = dict(
        id="coverage-case-0001",
        target_turn_index=0,
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [
                {"axis": "A2", "kind": "effect", "status": "FAIL"},
                {"axis": "A2", "kind": "effect:network", "status": "NOT_COVERED"},
            ],
        },
        human_label="true-positive",
        invariants=[],
        server_command=["python", "server.py"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-abc", "captured_at": "2026-07-23T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile", "seatbelt"],
    )
    base.update(overrides)
    return Case(**base)  # type: ignore[arg-type]


def test_corpus_case_round_trips_a_not_covered_sub_verdict(tmp_path: Path) -> None:
    """A case whose network sub-verdict is NOT_COVERED writes and loads back unchanged.

    Every case `corpus add` mints against an `openWorldHint: false` server now carries one,
    so a loader that refused it would make the corpus unable to store the common case.
    """
    case = _case()
    write_case(tmp_path, case)

    loaded = load_case(tmp_path)

    assert loaded == case
    statuses = {s["kind"]: s["status"] for s in loaded.expected["sub_verdicts"]}
    assert statuses["effect:network"] == "NOT_COVERED", statuses


def test_a_case_claiming_not_covered_as_its_reduced_status_is_refused(tmp_path: Path) -> None:
    """NOT_COVERED is SUB-VERDICT-ONLY: `reduce` can never return it, so a stored case
    claiming it as a reduced status is not a verdict Belay would ever emit.

    This guard is load-bearing, not pedantry: `corpus/metrics.py` folds any not-FAIL
    reduced status into a DECIDED non-detection, so a leaked NOT_COVERED would score as
    "checked and cleared" — the could-not-check-to-clean fold the corpus must never make.
    """
    write_case(tmp_path, _case())
    path = tmp_path / "case.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["expected"]["reduced_status"] = "NOT_COVERED"
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="reduced_status"):
        load_case(tmp_path)


def test_an_unknown_sub_verdict_status_is_still_refused(tmp_path: Path) -> None:
    """The sub-verdict allowlist stays fail-closed — widened by exactly one status."""
    write_case(tmp_path, _case())
    path = tmp_path / "case.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["expected"]["sub_verdicts"][0]["status"] = "PROBABLY_FINE"
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="PROBABLY_FINE"):
        load_case(tmp_path)


# --- 3. `schema_version` is optional, so no case already on disk breaks -----------------


def test_a_case_carrying_a_schema_version_round_trips(tmp_path: Path) -> None:
    case = _case()
    write_case(tmp_path, case)

    stored = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert "schema_version" in stored, "new cases must record the version they were written at"

    loaded = load_case(tmp_path)
    assert loaded == case
    assert loaded.schema_version == stored["schema_version"]


def test_a_legacy_case_without_a_schema_version_still_loads(tmp_path: Path) -> None:
    """`_REQUIRED_FIELDS` is a CLOSED tuple: a required `schema_version` would reject
    every case already in `corpus/local/`. It defaults instead."""
    write_case(tmp_path, _case())
    path = tmp_path / "case.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["schema_version"]
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

    loaded = load_case(tmp_path)

    assert loaded.schema_version == 1, loaded.schema_version
    assert loaded.id == "coverage-case-0001"


def test_a_malformed_schema_version_is_a_named_error(tmp_path: Path) -> None:
    """The one allowed silent default is the ABSENT field; a present-but-junk one fails closed."""
    write_case(tmp_path, _case())
    path = tmp_path / "case.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["schema_version"] = "one"
    path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_case(tmp_path)
