"""`belay verify` says what A1 actually judged — per turn and in the aggregate.

Phase 5 of `a1-exposure-accounting`. Tasks 1-4 made the A1 content rule's exposure fact
(`Verdict.expected["exposure"]`) reach the ledger, `belay phase0 report`, and `belay phase0
combine` — all EVAL surfaces. This is the PRODUCT surface: a user running `belay verify`
with no eval tooling in sight must be able to tell a judged PASS from an un-judged one,
without learning a second vocabulary from the one `belay phase0 report` already uses
(judged / no-opportunity / unrecorded — see `src/belay/phase0/report.py`).

The load-bearing tests here drive the REAL `verify_turn`, not a hand-built `TurnVerdict`
passed through the `verify=` stub seam — `CLAUDE.md` records the exact failure mode this
guards against: "a green suite was not evidence here", from a prior unit that built its
verdict through the stub and was green against a live bug. A test that fabricates a
`TurnVerdict` proves the emitter formats a struct; it does not prove `belay verify` shows a
user what A1 actually judged on a real replay.

Two fixtures do the work:

- `weakening_editor_server.py` (already used by `test_verify_cli_invariants.py`) overwrites
  `tests/test_auth.py` with a gutted assertion. The default invariants are `tests` and
  `testing` (`default_invariants()`), so this ONE turn drives two A1 sub-verdicts at once:
  the `tests`-scope rule finds 1 in-scope file, judges it, and FAILs — `judged`. The
  `testing`-scope rule finds ZERO in-scope files on the exact same delta — `no opportunity`.
  One real replay, both non-unrecorded states, in the same turn's output.
- `scope_free_editor_server.py` (new, this task) writes `src/app.py` — outside both default
  scopes entirely. Both A1 sub-verdicts find nothing in scope: the whole RUN's aggregate is
  `no opportunity`, with zero files ever compared.

A few direct unit tests pin the renderer's edge cases (the absent-key and partial-dict
shapes Task 1 enumerated) without claiming they exercise `verify_turn` — they test the pure
formatting helpers in isolation, clearly labeled as such, and exist alongside the two real
end-to-end tests rather than instead of them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION

from belay import cli
from belay.cli import _exposure_prose, _exposure_summary
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
WEAKENING_EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]
SCOPE_FREE_EDITOR_CMD = [sys.executable, str(FIXTURES / "scope_free_editor_server.py")]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"


def _tools_list(tool_name: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [{"name": tool_name, "annotations": {"readOnlyHint": False}}]
            },
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call(tool_name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": {}},
        }
    ).encode()


def _reply(text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _trace(tmp_path: Path, frames: list[tuple]) -> Path:
    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return sorted(trace_dir.glob("*.jsonl"))[0]


def _weakening_trace(tmp_path: Path):
    """One turn: `tests/test_auth.py` STRONG in pre-state, gutted by the editor."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir(parents=True)
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_TEST, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    handle = present_handle(snap)

    trace_path = _trace(
        tmp_path,
        _tools_list("edit_file")
        + [
            ("c2s", _call("edit_file"), handle),
            ("s2c", _reply("edited tests/test_auth.py"), None),
        ],
    )
    return trace_path, manifest_dir


def _scope_free_trace(tmp_path: Path):
    """One turn: an empty workspace, the editor adds `src/app.py` — outside both scopes."""
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir(parents=True)
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    handle = present_handle(snap)

    trace_path = _trace(
        tmp_path,
        _tools_list("edit_file")
        + [
            ("c2s", _call("edit_file"), handle),
            ("s2c", _reply("edited src/app.py"), None),
        ],
    )
    return trace_path, manifest_dir


def test_verify_per_turn_output_carries_exposure(tmp_path, capsys):
    """One real turn, two A1 sub-verdicts: `tests`-scope JUDGES, `testing`-scope finds NO
    OPPORTUNITY — both rendered under the same turn, from one real replay.
    """
    trace_path, manifest_dir = _weakening_trace(tmp_path)

    rc = cli.main(
        [
            "verify",
            str(trace_path),
            "--manifest-dir",
            str(manifest_dir),
            "--server",
            *WEAKENING_EDITOR_CMD,
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1, out  # the tests-scope rule FAILs the corrupt success
    assert "exposure: judged 1 file-comparison(s) (1 file(s) in scope)" in out, out
    assert (
        "exposure: 0 file(s) in scope, 0 file-comparison(s) — this carries no "
        "information about the rule" in out
    ), out


def test_verify_aggregate_distinguishes_judged_from_no_opportunity(tmp_path, capsys):
    """Two separate real runs: one aggregate reads JUDGED, the other NO OPPORTUNITY.

    Same code path (`_emit_exposure`), two different real traces — the weakening editor's
    write lands in scope and gets judged; the scope-free editor's write never does.
    """
    judged_trace, judged_manifests = _weakening_trace(tmp_path / "judged")
    cli.main(
        [
            "verify",
            str(judged_trace),
            "--manifest-dir",
            str(judged_manifests),
            "--server",
            *WEAKENING_EDITOR_CMD,
        ]
    )
    judged_out = capsys.readouterr().out

    no_opportunity_trace, no_opportunity_manifests = _scope_free_trace(
        tmp_path / "no-opportunity"
    )
    cli.main(
        [
            "verify",
            str(no_opportunity_trace),
            "--manifest-dir",
            str(no_opportunity_manifests),
            "--server",
            *SCOPE_FREE_EDITOR_CMD,
        ]
    )
    no_opportunity_out = capsys.readouterr().out

    assert "judged 1 file-comparison(s) across 1/1 turn(s)" in judged_out, judged_out
    assert (
        "0 file-comparison(s)"
        not in judged_out.split("aggregate")[-1].split("exposure (")[0]
    ), judged_out

    assert (
        "0 file-comparison(s) — this carries no information about the rule "
        "(1/1 turn(s) recorded an exposure fact)"
        in no_opportunity_out
    ), no_opportunity_out
    assert "judged" not in no_opportunity_out.split("exposure (A1")[-1], (
        no_opportunity_out
    )


def test_verify_aggregate_reports_unrecorded_when_a1_never_ran(tmp_path, capsys):
    """`--no-default-invariants` with no `--invariants` file: A1 never runs at all.

    The aggregate must say `unrecorded`, never a fabricated "no opportunity" or a silent
    absence of the whole section — an absent A1 axis is a format gap, not a measured zero.
    """
    trace_path, manifest_dir = _weakening_trace(tmp_path)

    cli.main(
        [
            "verify",
            str(trace_path),
            "--manifest-dir",
            str(manifest_dir),
            "--no-default-invariants",
            "--server",
            *WEAKENING_EDITOR_CMD,
        ]
    )
    out = capsys.readouterr().out

    assert "exposure (A1 content-rule judgment coverage" in out, out
    assert (
        "unrecorded — this check carries no exposure fact (a read-only rule, or judgment "
        "never reached content comparison); this is NOT a claim that the rule judged nothing"
        in out
    ), out


def test_verify_per_turn_names_unrecorded_for_a_read_only_rule(tmp_path, capsys):
    """A `read-only` rule invariant declares no exposure concept — the per-turn line says
    `unrecorded`, never `0 file(s)`.
    """
    trace_path, manifest_dir = _weakening_trace(tmp_path)
    inv_file = tmp_path / "policy.json"
    inv_file.write_text(
        json.dumps([{"scope": "tests/", "rule": "read-only"}]), encoding="utf-8"
    )

    rc = cli.main(
        [
            "verify",
            str(trace_path),
            "--manifest-dir",
            str(manifest_dir),
            "--no-default-invariants",
            "--invariants",
            str(inv_file),
            "--server",
            *WEAKENING_EDITOR_CMD,
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "0 file(s)" not in out, out
    assert (
        "unrecorded — this check carries no exposure fact (a read-only rule, or judgment "
        "never reached content comparison); this is NOT a claim that the rule judged nothing"
        in out
    ), out


# --- direct unit tests of the pure renderer, pinning edge cases Task 1 enumerated -------
#
# These do NOT drive `verify_turn` — they test `_exposure_prose`/`_exposure_summary` in
# isolation, on hand-built `expected` dicts shaped exactly as Task 1's report enumerated.
# They exist alongside the real end-to-end tests above, not instead of them.


def test_exposure_prose_reports_judged_from_a_full_dict():
    assert (
        _exposure_prose({"exposure": {"compared": 3, "in_scope": 5}})
        == "exposure: judged 3 file-comparison(s) (5 file(s) in scope)"
    )


def test_exposure_prose_reports_no_opportunity_when_compared_is_zero():
    assert _exposure_prose({"exposure": {"compared": 0, "in_scope": 0}}) == (
        "exposure: 0 file(s) in scope, 0 file-comparison(s) — this carries no "
        "information about the rule"
    )


def test_exposure_prose_reports_in_scope_when_nothing_was_compared():
    """The commonest real shape: the agent ADDS a test under `tests/`, so the file is in
    scope but absent from the task pre-state, and the rule SKIPS it without comparing
    (`invariants.py:417-420`). `in_scope` is already in hand here, and the sentence must
    use it: "the rule was given nothing to judge" contradicts the sub-verdict line printed
    directly above it ("1 file(s) compared, 1 touched") and is false — the rule was given a
    file and correctly found nothing in it to weaken.
    """
    prose = _exposure_prose({"exposure": {"compared": 0, "in_scope": 1}})
    assert prose == (
        "exposure: 1 file(s) in scope, 0 file-comparison(s) — this carries no "
        "information about the rule"
    )
    assert "nothing to judge" not in prose


def test_exposure_prose_does_not_fabricate_compared_for_the_budget_abstain_shape():
    """The partial dict (`{"in_scope": M}`, no `compared` key) is neither judged nor
    no-opportunity — it must say something distinct, never `0 file(s)` and never
    "no opportunity", or it would fabricate the exact zero Task 1 refused to invent.
    """
    prose = _exposure_prose({"exposure": {"in_scope": 600}})
    assert "0 file-comparison(s)" not in prose, prose
    assert "compared" not in prose, prose
    assert "600 file(s) in scope" in prose, prose
    assert "comparison never began" in prose, prose


def test_exposure_prose_reports_unrecorded_when_exposure_key_absent():
    assert _exposure_prose(
        {"rule": "no-assertion-weakening", "scope": "tests", "turn": 3}
    ) == (
        "exposure: unrecorded — this check carries no exposure fact (a read-only rule, or "
        "judgment never reached content comparison); this is NOT a claim that the rule "
        "judged nothing"
    )


def test_exposure_prose_reports_unrecorded_when_expected_is_not_a_dict():
    assert _exposure_prose(None) == (
        "exposure: unrecorded — this check carries no exposure fact (a read-only rule, or "
        "judgment never reached content comparison); this is NOT a claim that the rule "
        "judged nothing"
    )


def test_exposure_summary_is_none_when_no_turn_recorded_exposure():
    class _Sub:
        axis = "A2"
        kind = "result"
        expected = None

    class _Turn:
        sub_verdicts = [_Sub()]

    assert _exposure_summary([_Turn()]) is None


def test_exposure_summary_sums_compared_across_subverdicts_within_one_turn():
    """Two A1 sub-verdicts on the SAME turn (the `tests`+`testing` default shape) contribute
    to `files_compared` additively, but the turn counts once toward `turns_recorded` and
    once toward `turns_judging` — never twice, mirroring `belay.phase0.runner`'s accumulator.
    """

    class _Sub:
        def __init__(self, expected):
            self.axis = "A1"
            self.kind = "invariant"
            self.expected = expected

    class _Turn:
        sub_verdicts = [
            _Sub({"exposure": {"compared": 1, "in_scope": 1}}),
            _Sub({"exposure": {"compared": 0, "in_scope": 0}}),
        ]

    summary = _exposure_summary([_Turn()])
    assert summary == {"files_compared": 1, "turns_judging": 1, "turns_recorded": 1}
