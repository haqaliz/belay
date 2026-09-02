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
from pathlib import Path

import pytest

from belay import cli
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status

#: The A3 line every surface renders at trace close — asserted absent wherever a run
#: must not emit an A3 verdict.
A3_LINE_HEAD = "claim re-derivation"


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