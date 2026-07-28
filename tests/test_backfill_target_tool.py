"""Backfill `target_tool` onto cases banked before the field existed.

The seven Phase-0 cases were composed before `corpus add` recorded the target
turn's tool, so the gate's STRICT independence clause ("distinct instances AND
distinct tools") is unevaluable for them — `corpus score` correctly reports it
`n/a` rather than guessing. Every case ships its own `trace.jsonl`, so the tool
is recoverable exactly, without network and without re-running anything.

This is a one-off migration in the shape of `eval/scripts/rearm_checkpoint.py`,
and it REUSES `corpus.add._target_tool_name` — the same reader `corpus add` now
uses for new cases — so a backfilled case and a freshly-composed one cannot
disagree about what the tool was.

The load-bearing property is that it touches ONLY `target_tool`: a migration
that perturbed `expected` would corrupt the very verdicts the corpus regresses
against, and the labels are scored against those verdicts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.corpus.case import Case, load_case, write_case
from eval.scripts.backfill_target_tool import backfill_case, backfill_corpus


def _trace_records() -> list[dict]:
    """Two `tools/call` turns, so the index actually has to select."""
    import base64

    def frame(seq: int, payload: dict) -> dict:
        return {
            "v": 1,
            "kind": "frame",
            "dir": "c2s",
            "seq": seq,
            "raw": base64.b64encode(json.dumps(payload).encode()).decode(),
        }

    return [
        frame(1, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "read_text_file", "arguments": {}}}),
        frame(2, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": "edit_file", "arguments": {}}}),
    ]


def _case(target_turn_index: int = 1) -> Case:
    return Case(
        id="c",
        target_turn_index=target_turn_index,
        expected={
            "reduced_status": "FAIL",
            "sub_verdicts": [{"axis": "A1", "kind": "invariant", "status": "FAIL"}],
        },
        human_label="pending",
        invariants=[{"scope": "tests/", "rule": "read-only"}],
        server_command=["node", "server.js"],
        replays=2,
        timeout=30.0,
        provenance={"source_trace_id": "trace-x", "captured_at": "2026-07-18T00:00:00Z"},
        capture_platform="darwin",
        capture_capabilities=["clonefile"],
    )


def _write(case_dir: Path, case: Case) -> None:
    write_case(case_dir, case)
    (case_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _trace_records()), encoding="utf-8"
    )


def test_backfill_recovers_the_tool_for_the_target_turn(tmp_path: Path) -> None:
    """The tool comes off the TARGET turn, not the first one."""
    _write(tmp_path, _case(target_turn_index=1))

    assert backfill_case(tmp_path) == "edit_file"
    assert load_case(tmp_path).target_tool == "edit_file"


def test_backfill_selects_by_turn_index(tmp_path: Path) -> None:
    """A different target index yields that turn's tool."""
    _write(tmp_path, _case(target_turn_index=0))

    assert backfill_case(tmp_path) == "read_text_file"


def test_backfill_touches_only_target_tool(tmp_path: Path) -> None:
    """`expected` and every other field are byte-identical after the migration.

    A migration that perturbed the recorded verdict would corrupt what the
    corpus regresses against, and the human labels are scored against it.
    """
    _write(tmp_path, _case())
    before = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))

    backfill_case(tmp_path)

    after = json.loads((tmp_path / "case.json").read_text(encoding="utf-8"))
    assert json.dumps(before["expected"], sort_keys=True) == json.dumps(
        after["expected"], sort_keys=True
    )
    assert {k: v for k, v in after.items() if k != "target_tool"} == before


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    """Re-running produces identical bytes — a migration you can run twice."""
    _write(tmp_path, _case())

    backfill_case(tmp_path)
    once = (tmp_path / "case.json").read_bytes()
    backfill_case(tmp_path)

    assert (tmp_path / "case.json").read_bytes() == once


def test_backfill_leaves_an_unreadable_turn_absent(tmp_path: Path) -> None:
    """An out-of-range target turn yields None and writes nothing — never a guess.

    Absent-never-guessed: a fabricated tool name would silently change the
    strict count the gate is read against.
    """
    _write(tmp_path, _case(target_turn_index=99))
    before = (tmp_path / "case.json").read_bytes()

    assert backfill_case(tmp_path) is None
    assert (tmp_path / "case.json").read_bytes() == before


def test_backfill_corpus_reports_each_case(tmp_path: Path) -> None:
    """The corpus-level pass returns a per-case mapping, sorted and complete."""
    for name in ("b-case", "a-case"):
        _write(tmp_path / name, _case())

    assert backfill_corpus(tmp_path) == {"a-case": "edit_file", "b-case": "edit_file"}


def test_backfill_corpus_fails_closed_on_a_corrupt_case(tmp_path: Path) -> None:
    """A case that will not load is an error, never a silently skipped row."""
    _write(tmp_path / "good", _case())
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "case.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        backfill_corpus(tmp_path)
