"""A3 surfaces Phase 1 (RED): the `--no-claim-axis` surface and its parity declaration.

The C8 capstone's surface contract, pinned BEFORE the wiring exists (strict TDD):

1. `--no-claim-axis` is accepted by all three commands that can evaluate a claim —
   `belay verify`, `belay phase0 run`, `belay corpus run` (the `--no-default-invariants`
   precedent, `cli.py:2248-2255`) — and an unknown flag on any command still fails
   cleanly.
2. `--turn N` runs NEVER emit an A3 verdict — with the flag AND with an author
   configured. A3 is instance-level by construction, so a per-turn run would be
   evaluated on partial facts, which is fabrication (`cli.py:738-742` rule).
3. `--claim-author CMD` is the interactive author surface on `belay verify` (the batch
   surfaces are env-only, `BELAY_CLAIM_AUTHOR`); an un-lexable command is a fail-closed
   exit 2, never a silently degraded run.
4. `--no-claim-axis` + `--claim-author` both given -> the FLAG wins (the axis is
   disabled; an operator must be able to turn A3 off without unsetting anything).
5. The CLI parity guard (`tests/test_cli_flag_parity.py`) declares both shared flags
   before any parser carries them — the guard is RED until the wiring lands.

The parity guard's declaration is updated HERE, in the same RED phase as the surface
tests, because the guard's discovery half would otherwise only start failing once the
flags exist — which is precisely the late failure this guard exists to prevent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status

#: The A3 line every surface renders at trace close — asserted absent wherever a run
#: must not emit an A3 verdict. The em-dash disambiguates from the coverage block's
#: own "A3 (claim re-derivation) is the ONE place..." clause, which IS always present.
A3_LINE_HEAD = "claim re-derivation (A3 —"


def _canned_verifier(status: Status = Status.PASS, *, is_error: bool = False):
    """A fake `verify_turn` that answers the configured status for any turn.

    `shell_server_command` is accepted because the CLI always passes it (it is `None`
    unless `--shell-server` was given); a stub that refused it would turn a routing
    parity change into three unrelated CLI-rendering failures.
    """

    def verifier(
        records, n, *, server_command, manifest_dir, replays, invariants, timeout,
        shell_server_command=None,
    ):
        return TurnVerdict(
            turn_index=n,
            tool_name="edit_file",
            status=status,
            replayed_is_error=is_error,
        )

    return verifier


def _tool_list_frames(tool: str) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": name, "annotations": {"readOnlyHint": False}}
                    for name in (tool, "run_process")
                ]
            },
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call_frame(msg_id: int, tool: str, arguments: dict) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()


def _reply_frame(msg_id: int, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _edit_trace(tmp_path: Path, *, claim: str | None) -> Path:
    writer = TraceWriter.in_directory(tmp_path / "traces")
    try:
        for direction, raw, handle in _tool_list_frames("edit_file"):
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
        writer.observer("c2s")(_call_frame(2, "edit_file", {"path": "/repo/src/a.py"}), False)
        writer.observer("s2c")(_reply_frame(2), False)
    finally:
        writer.close()
    if claim is not None:
        append_claim_record(writer.path, text=claim)
    return writer.path


# --- (1) the flag parses on all three commands -----------------------------------------


def test_no_claim_axis_flag_parses_on_all_three_commands() -> None:
    """`--no-claim-axis` is accepted by `verify`, `phase0 run` and `corpus run`.

    The three surfaces that can evaluate a claim (the instance-level A3 site) carry
    the one flag that disables the axis everywhere. Parse-level: the wiring phases
    assert the BEHAVIOUR; this pins the surface before any of it exists.
    """
    parser = cli._parser()
    parser.parse_args(
        ["verify", "t", "--manifest-dir", "m", "--no-claim-axis", "--server", "x"]
    )
    parser.parse_args(["phase0", "run", "d", "--ledger", "l", "--no-claim-axis"])
    parser.parse_args(["corpus", "run", "d", "--no-claim-axis"])


def test_unknown_flag_on_any_command_fails_cleanly() -> None:
    """Acceptance 1's fail-closed half: an unknown flag is an argparse error (exit 2),
    never silently accepted."""
    parser = cli._parser()
    for argv in (
        ["verify", "t", "--manifest-dir", "m", "--no-claim-axiz", "--server", "x"],
        ["phase0", "run", "d", "--ledger", "l", "--no-claim-axiz"],
        ["corpus", "run", "d", "--no-claim-axiz"],
    ):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(argv)
        assert exc.value.code == 2, argv


# --- (2) `--turn N` never emits an A3 verdict ------------------------------------------


def test_turn_n_with_the_flag_never_emits_an_a3_verdict(tmp_path, monkeypatch, capsys):
    """`--turn N --no-claim-axis`: the A3 line never renders — the axis is off AND the
    run is per-turn (either rule alone suffices; the pair is the pinned contract)."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--no-claim-axis",
            "--turn", "0",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert A3_LINE_HEAD not in out, out


def test_turn_n_never_evaluates_a3_even_with_an_author(tmp_path, monkeypatch, capsys):
    """`--turn N` with an author configured: STILL no A3 verdict — a per-turn run has
    partial facts, and an instance-level verdict computed from them would be
    fabricated (`cli.py:738-742` rule, the trajectory seam's own)."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--turn", "0",
            "--claim-author", "python3 -c 'print(1)'",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert A3_LINE_HEAD not in out, out


# --- (3) --claim-author: the interactive author surface, fail-closed ------------------


def test_claim_author_parses_on_verify_only() -> None:
    """`--claim-author` is the VERIFY surface's flag (the interactive one); the batch
    surfaces are env-only (`BELAY_CLAIM_AUTHOR`) and refuse the flag cleanly."""
    parser = cli._parser()
    parser.parse_args(
        [
            "verify", "t", "--manifest-dir", "m",
            "--claim-author", "python3 -c 'print(1)'",
            "--server", "x",
        ]
    )
    for argv in (
        ["phase0", "run", "d", "--ledger", "l", "--claim-author", "x"],
        ["corpus", "run", "d", "--claim-author", "x"],
    ):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(argv)
        assert exc.value.code == 2, argv


def test_unlexable_claim_author_is_fail_closed_exit_2(tmp_path, capsys):
    """An un-lexable `--claim-author` (an unterminated quote) is a HARD error: exit 2
    naming the flag — Belay must never half-execute a command it could not parse, and
    must never quietly degrade the run to "no claim axis" (`--shell-server`'s rule)."""
    trace_path = _edit_trace(tmp_path, claim=None)

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--claim-author", "'unterminated",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "--claim-author" in out, out
    assert "could not be parsed" in out, out


# --- (4) the flag wins over --claim-author ---------------------------------------------


def test_flag_wins_when_no_claim_axis_and_claim_author_are_both_given(
    tmp_path, monkeypatch, capsys
):
    """`--no-claim-axis` + `--claim-author` together: the FLAG wins — the axis is
    disabled, the author is never even built, and no A3 verdict exists. An operator
    must be able to turn A3 off without unsetting their configuration."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--no-claim-axis",
            "--claim-author", "python3 -c 'print(1)'",
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert A3_LINE_HEAD not in out, out


# --- the deterministic A3 seams (a REAL subprocess author, stubbed engine) -------------


def _claim_author_cmd(*, source: str = "pytest -q", argv: list[str] | None = None,
                      error: bool = False) -> str:
    """A real `--claim-author` command (a real subprocess): answers the check JSON, or
    `{"error": ...}` for the no-check abstention. Deterministic, cross-platform."""
    payload = {"error": "no check this run"} if error else {
        "source": source, "argv": argv or ["pytest", "-q"]
    }
    code = f"import json,sys;json.dump({json.dumps(payload)},sys.stdout)"
    return f"{sys.executable} -c '{code}'"


class _FixedRunner:
    """The check-runner seam, deterministic: the configured exit code — never a model."""

    def __init__(self, exit_code):
        self._exit_code = exit_code

    def run(self, check, *, workspace, timeout):
        from belay.verify.claims import CheckResult

        return CheckResult(self._exit_code, "captured output", "captured stderr")


def _stub_claim_seams(monkeypatch, tmp_path, *, exit_code: int) -> None:
    """Stub the two A3 engine seams: the final-state replay and the check runner.

    The author stays REAL (a subprocess); only the re-execution machinery is
    deterministic, so the A3 verdict is decided by the same evaluator the product
    runs, at a fraction of the cost.
    """
    from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
    from belay.verify import claims

    workspace = tmp_path / "stub-workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    def fake_replay(records, n, **kwargs):
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
            }
        ).encode()
        return TurnReplay(
            turn_index=n,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=reply,
            replayed_reply=reply,
            delta=[],
            workspace=str(workspace),
        )

    monkeypatch.setattr(claims, "replay_turn", fake_replay)
    monkeypatch.setattr(claims, "runner", _FixedRunner(exit_code))


# --- (5) the A3 line: FAIL with source + exit code, UNVERIFIED, silence, absent --------


def test_verify_renders_the_a3_fail_line_with_source_and_exit_code(
    tmp_path, monkeypatch, capsys
):
    """The instance-level A3 line at trace close: FAIL carries the check source and
    the real exit code — the artifacts A3 surfaces. The author is a REAL subprocess;
    the check's exit decides."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=1)
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--claim-author", _claim_author_cmd(),
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert A3_LINE_HEAD in out, out
    assert "FAIL — pytest -q · exit 1" in out, out


def test_verify_json_carries_the_a3_record_after_trajectory(
    tmp_path, monkeypatch, capsys
):
    """`--json` carries the A3 record after the trajectory record, with the check
    source and the OBSERVED exit code — the pinned machine shape."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=1)
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--claim-author", _claim_author_cmd(),
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert doc["claim"] == {
        "axis": "A3",
        "kind": "claim",
        "status": "FAIL",
        "cause": None,
        "check": {"source": "pytest -q", "exit_code": 1},
    }
    keys = list(doc)
    assert keys.index("trajectory") < keys.index("claim") < keys.index("error"), keys


def test_verify_renders_a3_unverified_with_its_named_cause(tmp_path, monkeypatch, capsys):
    """An author that answers `{"error": ...}` abstains with NO_CHECK_AUTHOR — the A3
    line names the cause and says never PASS, in text and JSON (check exit null: did
    not execute)."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=1)
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--claim-author", _claim_author_cmd(error=True),
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out
    doc = json.loads(out)

    assert rc == 0
    assert doc["claim"] == {
        "axis": "A3",
        "kind": "claim",
        "status": "UNVERIFIED",
        "cause": "NO_CHECK_AUTHOR",
        "check": {"source": "", "exit_code": None},
    }


def test_verify_renders_silence_never_pass_when_the_check_exits_zero(
    tmp_path, monkeypatch, capsys
):
    """D3 on the surface: the check exits 0 -> NO verdict. The text line says silence
    (never a PASS, never a fabricated clean); the JSON document omits the claim key —
    silence is not a verdict, and absent-never-zero keeps the pinned fixture green."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    _stub_claim_seams(monkeypatch, tmp_path, exit_code=0)
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--claim-author", _claim_author_cmd(),
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert A3_LINE_HEAD in out, out
    assert "silence" in out, out
    assert "no verdict at all" in out, out

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--claim-author", _claim_author_cmd(),
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "claim" not in doc, doc


def test_verify_without_an_author_omits_the_a3_line_and_json_key(
    tmp_path, monkeypatch, capsys
):
    """No author configured (env unset, no --claim-author): the axis is ABSENT — no A3
    line in the text (the coverage block names the absence), and no claim key in the
    JSON document. This is the absent-never-zero rule that keeps the pinned `--json`
    fixture green for every trace without a claim/author."""
    monkeypatch.setattr(turn_module, "verify_turn", _canned_verifier())
    monkeypatch.delenv("BELAY_CLAIM_AUTHOR", raising=False)
    trace_path = _edit_trace(tmp_path, claim="all tests pass")

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--json",
            "--server", "unused",
        ]
    )
    doc = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "claim" not in doc, doc

    rc = cli.main(
        [
            "verify", str(trace_path),
            "--manifest-dir", str(tmp_path / "m"),
            "--server", "unused",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert A3_LINE_HEAD not in out, out
    assert "ABSENT" in out, "the coverage block must name the absent axis"


# --- (6) canonical_cause maps the A3/claim prefix ahead of the catch-all --------------

AUTHOR_ENV_VAR = "BELAY_CLAIM_AUTHOR"


def test_canonical_cause_maps_every_a3_claim_prefix_ahead_of_the_catch_all() -> None:
    """Acceptance 5, asserted on the FUNCTION (the boundary entries' pattern): an A3
    cause routed under the `A3/claim` prefix — either bare or in the replayed-cause
    shape — resolves to the named bucket, NEVER the bland `REPLAYED_UNVERIFIED`
    catch-all, and the table orders both prefixes ahead of it (a prefix written after
    the catch-all it starts with is permanently dead)."""
    from belay.replay.report import (
        A3_CLAIM_UNVERIFIED,
        REPLAYED_SUB_VERDICT,
        REPLAYED_UNVERIFIED,
        _PREFIX_LABELS,
        canonical_cause,
    )

    for cause in (
        "A3/claim NO_CLAIM_RECORDED",
        f"{REPLAYED_SUB_VERDICT} A3/claim NO_CLAIM_RECORDED",
    ):
        assert canonical_cause(cause) == A3_CLAIM_UNVERIFIED, cause
        assert canonical_cause(cause) != REPLAYED_UNVERIFIED, cause

    positions = {prefix: i for i, (prefix, _label) in enumerate(_PREFIX_LABELS)}
    assert positions["A3/claim"] < positions[REPLAYED_SUB_VERDICT]
    assert positions[f"{REPLAYED_SUB_VERDICT} A3/claim"] < positions[REPLAYED_SUB_VERDICT]