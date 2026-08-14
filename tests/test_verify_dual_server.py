"""Phase 1 RED — dual-server routing + honest shell replay (aspect `verify-dual-server`).

A dual-server capture's `run_process` turns replayed against the filesystem command are
"not expected to reproduce their replies" (`eval/README.md`): the replayed reply carries no
`result.isError`, so `TurnVerdict.replayed_is_error` is `None` and the trajectory rule's
evidence (a replayed exit-0 `run_process`, `trajectory.py:457`) is structurally
unobservable. The design under test adds one keyword to `verify_turn`:

    shell_server_command: Sequence[str] | None = None

Resolution rule, exactly: the turn's recorded tool name is `"run_process"` AND
`shell_server_command` is given -> the turn replays against the shell command; any other
combination -> `server_command`, byte-for-byte today. The resolved command feeds BOTH
`replay_turn` and `classify_determinism` inside `verify_turn` (`turn.py:225-267`).

What this file pins, through the REAL `verify_turn`:

  1. `test_run_process_turn_uses_shell_server_command` — a captured `run_process` turn with
     `shell_server_command` given replays against the SHELL fixture server, so its replayed
     outcome is READABLE (`replayed_is_error is False`, an exit-0 outcome — the trajectory
     evidence becomes observable). Real replay -> darwin-gated, exactly like the shell e2e.
  2. `test_non_run_process_turn_ignores_shell_server_command` — a filesystem `read_abs` turn
     with `shell_server_command` given still replays against `server_command` (routing is by
     exact tool name). Real replay -> darwin-gated.
  3. `test_shell_turn_unreadable_outcome_is_unverified` — a shell turn whose REPLAYED reply
     has no parseable outcome -> UNVERIFIED with a named cause, never PASS.
  4. `test_shell_turn_never_replayed_is_unverified` — a shell turn that can never replay ->
     UNVERIFIED with the engine's cause, never PASS.
  5. `test_shell_turn_never_reduced_to_pass_without_read_outcome` — the honesty PROPERTY
     across both shapes: an unreadable or absent outcome is never PASS and the evidence seam
     is never a fabricated bool.

RED against today's code: `verify_turn` has no such keyword, so every test fails with
`TypeError: verify_turn() got an unexpected keyword argument 'shell_server_command'` — the
missing-feature signature, not a fixture break.

## Why the darwin gate, and where it is NOT needed

Tests 1 and 2 drive REAL re-execution, which re-invokes inside the macOS Seatbelt sandbox —
off-darwin they skip, exactly like `test_replay_relocation_shell_e2e.py`. Tests 3-5 do not
need Seatbelt and are cross-platform: the unreadable-outcome shape is produced by the same
replay-stub seam `tests/test_verify_turn.py` uses (no fixture server can emit an unreadable
outcome on real replay — the shell fixture always wraps a parseable `result.isError`), and
the never-replayed shape short-circuits in the engine BEFORE any restore or spawn (an
`absent` state handle).

The frame-builders and capture helpers are imported from the two relocation e2e suites
(`test_replay_relocation_shell_e2e.py`, `test_replay_relocation_e2e.py`) — the established
convention for not re-deriving them.
"""

from __future__ import annotations

import sys

import pytest

from fixtures.abs_path_editor_server import ORIGINAL_CONTENT as FS_ORIGINAL_CONTENT
from fixtures.abs_path_editor_server import READ_TOOL as FS_READ_TOOL
from fixtures.shell_command_server import ORIGINAL_CONTENT as SHELL_ORIGINAL_CONTENT
from fixtures.shell_command_server import RUN_TOOL

from belay.replay.determinism import DETERMINISTIC, DeterminismResult
from belay.replay.engine import DIVERGED, REPLAYED, TurnReplay
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

from test_replay_relocation_e2e import (
    _abs_capture,
    _abs_path as fs_abs_path,
    _call as fs_call,
    _reply as fs_reply,
    _server_cmd as fs_server_cmd,
)
from test_replay_relocation_shell_e2e import (
    _call as shell_call,
    _reply as shell_reply,
    _server_cmd as shell_server_cmd,
    _shell_capture,
    _tools_list_request,
    _tools_list_response,
    _trace as shell_trace,
)

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

#: The `server_command` for tests 3-5's non-replay assertions: never reached, but must be a
#: plausible command so the resolution rule has both sides to choose between.
FS_CMD = ["python", "fs-server.js", "{workspace}"]


# --- shared trace builders (shell handshake + one run_process turn) --------------------


def _shell_trace(tmp_path, name: str, *, handle=None) -> list[dict]:
    """A recorded run_process trace: real tools/list handshake + one `echo ok` turn.

    `handle=None` records no state_handle at all (the stub tests never replay for real);
    pass `{"status": "absent"}` to record a turn that can never replay.
    """
    return shell_trace(
        tmp_path,
        name,
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", shell_call({"command_line": "echo ok"}), handle),
            ("s2c", shell_reply("ok\n"), None),
        ],
    )


def _unreadable_outcome_verdict(tmp_path, monkeypatch) -> TurnVerdict:
    """Verify a shell turn whose REPLAYED reply is unparseable — via the stub seam.

    No fixture server can produce this on real replay (the shell fixture always emits a
    parseable `result.isError`), so re-execution is stubbed the way `test_verify_turn.py`
    stubs it (its `_stub_replay`): the composition under test is `verify_turn`, and
    re-execution is C3's. The engine folds an unparseable replayed reply into DIVERGED
    (`verify/result.py` docstring), so the stub reports REPLAYED + DIVERGED with a
    non-JSON replayed reply; `classify_determinism` is stubbed to DETERMINISTIC exactly as
    `test_verify_turn.py` does for its divergence test.
    """
    records = _shell_trace(tmp_path, "unreadable")
    monkeypatch.setattr(
        turn_module,
        "replay_turn",
        lambda *a, **k: TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=DIVERGED,
            recorded_reply=shell_reply("ok"),
            replayed_reply=b"not json at all",
            delta=[],
        ),
    )
    monkeypatch.setattr(
        turn_module,
        "classify_determinism",
        lambda *a, **k: DeterminismResult(
            turn_index=0, classification=DETERMINISTIC, replays=3, tool=RUN_TOOL
        ),
    )
    return verify_turn(
        records,
        0,
        server_command=FS_CMD,
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",  # never reached: replay_turn is stubbed
    )


def _never_replayed_verdict(tmp_path) -> TurnVerdict:
    """Verify a shell turn recorded with an ABSENT state handle — REAL engine, no stubs.

    The engine short-circuits to NOT_VERIFIABLE before any restore or spawn
    (`engine.replay_turn`'s `absent` branch), so no Seatbelt is involved and the engine's
    own cause is carried — `manifest_dir` is never read.
    """
    records = _shell_trace(tmp_path, "never-replayed", handle={"status": "absent"})
    return verify_turn(
        records,
        0,
        server_command=FS_CMD,
        shell_server_command=shell_server_cmd(),
        manifest_dir="/nonexistent",  # never reached: the absent handle short-circuits first
    )


# --- 1. AC-1: a run_process turn with shell_server_command replays against the shell ----


@darwin_only
def test_run_process_turn_uses_shell_server_command(tmp_path) -> None:
    """A `run_process` turn + `shell_server_command` replays against the SHELL server.

    REAL gated capture (TraceWriter + take_snapshot + persist_snapshot WITH `source_root`,
    exactly as the shell e2e) of an exit-0 `echo ok` command. `server_command` deliberately
    points at the FILESYSTEM fixture — the wrong server for a shell turn — while
    `shell_server_command` points at the shell fixture. If the turn were routed to the fs
    server, the fs server would answer "unknown tool: run_process" with a JSON-RPC error
    envelope carrying NO `result.isError`, and `replayed_is_error` would be `None`: the
    trajectory rule's evidence stays structurally unobservable. It is `False`, not `True`:
    an exit-0 command's reply carries `isError: false` (`trajectory.py:457` counts a
    replayed outcome as evidence when `is_error is False`) — the point is that the outcome
    was READ.
    """

    def frames_for(_root: str):
        return shell_call({"command_line": "echo ok"}), shell_reply("ok\n")

    records, manifest_dir, _work, root = _shell_capture(
        tmp_path, "dual-shell", SHELL_ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records,
        0,
        server_command=fs_server_cmd(root),  # wrong server for a shell turn: must be ignored
        shell_server_command=shell_server_cmd(),
        manifest_dir=manifest_dir,
        invariants=(),
        timeout=20.0,
    )

    assert verdict.tool_name == RUN_TOOL, verdict
    assert verdict.replayed_is_error is not None, (
        "the replayed outcome must be READABLE — the fs server would leave it None",
        verdict,
    )
    assert verdict.replayed_is_error is False, (
        "an exit-0 command's observed outcome is isError: false — the trajectory evidence",
        verdict,
    )
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


# --- 2. AC-2: a non-run_process turn with shell_server_command ignores it -------------


@darwin_only
def test_non_run_process_turn_ignores_shell_server_command(tmp_path) -> None:
    """A filesystem `read_abs` turn + `shell_server_command` replays against `server_command`.

    Routing is by EXACT tool name: `read_abs` is not `run_process`, so the resolution rule
    picks `server_command` no matter what `shell_server_command` says. The fs turn is a
    REAL gated capture (the fs e2e's `_abs_capture`); `shell_server_command` deliberately
    points at the shell fixture. If the turn were routed to the shell server, the shell
    fixture would answer "unknown tool: read_abs" with an error envelope carrying no
    `result.isError` — `replayed_is_error` would be `None` and the fs reply would not
    reproduce. It is a real fs replay outcome instead.
    """

    def frames_for(root: str):
        abs_path = fs_abs_path(root)
        return fs_call(FS_READ_TOOL, {"path": abs_path}), fs_reply(FS_ORIGINAL_CONTENT)

    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "dual-fs", FS_ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records,
        0,
        server_command=fs_server_cmd(root),
        shell_server_command=shell_server_cmd(),  # deliberately wrong for this turn: ignored
        manifest_dir=manifest_dir,
        invariants=(),
        timeout=20.0,
    )

    assert verdict.tool_name == FS_READ_TOOL, verdict
    assert verdict.replayed_is_error is not None, (
        "the fs server's reply must be the one that was read — the shell server would "
        "leave the outcome None",
        verdict,
    )
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


# --- 3. AC-5: an unreadable replayed outcome is UNVERIFIED, never PASS ---------------


def test_shell_turn_unreadable_outcome_is_unverified(tmp_path, monkeypatch) -> None:
    """A shell turn whose REPLAYED reply has no parseable isError -> UNVERIFIED + cause.

    The engine folds an unparseable replayed reply into DIVERGED; on a DETERMINISTIC tool
    `verify/result.py` still refuses to FAIL it ("replay produced something we could not
    read, which is not a determinable value divergence") and renders UNVERIFIED. The
    un-annotated effect axis is UNVERIFIED too, so the turn reduces to UNVERIFIED with a
    NAMED cause — and `replayed_is_error` stays `None` (an unreadable outcome is
    unobservable, never coerced to a fabricated bool). Never PASS.
    """
    verdict = _unreadable_outcome_verdict(tmp_path, monkeypatch)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    assert verdict.cause is not None, "every unverified turn must name a cause"
    assert verdict.replayed_is_error is None, (
        "an outcome that cannot be read is unobservable — the trajectory seam must not "
        "fabricate a bool",
        verdict,
    )


# --- 4. AC-5: a shell turn that never replays is UNVERIFIED with the engine's cause ---


def test_shell_turn_never_replayed_is_unverified(tmp_path) -> None:
    """A shell turn that cannot replay -> UNVERIFIED with the ENGINE's cause, never PASS.

    The recorded state_handle is `absent` — no snapshot was ever attempted for this turn —
    so the real engine returns NOT_VERIFIABLE with its own cause before any restore or
    spawn. `verify_turn` renders UNVERIFIED carrying that cause verbatim. A turn nobody
    verified is never a pass.
    """
    verdict = _never_replayed_verdict(tmp_path)

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    assert verdict.cause is not None, "every unverified turn must name a cause"
    assert "no snapshot was attempted" in verdict.cause, verdict.cause
    assert verdict.replayed_is_error is None, verdict


# --- 5. The honesty property: never PASS without a read outcome -----------------------


def test_shell_turn_never_reduced_to_pass_without_read_outcome(tmp_path, monkeypatch) -> None:
    """PROPERTY: a shell turn is never PASS unless its replayed outcome was actually read.

    Over BOTH honesty shapes — an unreadable replayed outcome (stub seam) and a turn that
    never replays (real engine, absent handle) — the reduced status is never PASS and the
    evidence seam never carries a fabricated bool. This is the property the trajectory rule
    leans on: `trajectory.assemble_turn_facts` maps `replayed_is_error is None` to
    not-replayed, so an unobservable outcome can never masquerade as evidence.
    """
    for verdict in (
        _unreadable_outcome_verdict(tmp_path / "a", monkeypatch),
        _never_replayed_verdict(tmp_path / "b"),
    ):
        assert verdict.status is not Status.PASS, verdict
        assert verdict.replayed_is_error is None, (
            "unreadable or absent outcomes are unobservable, never a fabricated bool",
            verdict,
        )
