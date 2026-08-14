"""Phase 1 RED — batch threading + ingest regression for `verify-dual-server`.

The engine-side routing (a `run_process` turn replays against `shell_server_command`,
anything else against `server_command`) is `verify_turn`'s job, pinned in
`test_verify_dual_server.py`. This file pins the RUNNER side of the same design:

- `run_batch` / `_verify_one_trace` gain the optional `shell_server_command` and
  THREAD it to the verifier on every turn (the resolution is `verify_turn`'s — the runner
  must hand the verifier both commands so it can decide per turn), and — RESOLVED PER
  FLAGGED TURN by that turn's `tool_name` — to each `ingester(...)` call, so a corpus case
  stores the command its turn actually replayed against (a shell case stores the shell
  command, an fs case stores the fs command; self-contained cases preserved).
- `shell_server_command=None` must behave byte-for-byte as today (the regression fixture).
- The CLI `--shell-server` flag is Phase 3 of the aspect; absent flag -> `None` -> today's
  behavior is exactly what the regression fixture below pins at the `run_batch` boundary.

What this file pins, with FAKE verifier/ingester seams exactly as
`tests/test_phase0_runner.py` (no Seatbelt, no real replay):

  1. `test_run_batch_shell_server_command_threads_per_turn` — over a 2-trace batch (one
     fs-tool trace, one `run_process` trace), a recording fake verifier captures the
     commands it is offered per turn: the `run_process` turn resolves to the SHELL command
     and the fs turn to the FS command, while the runner threads BOTH commands through on
     every call; a recording fake ingester then proves the runner's OWN per-turn
     resolution — the flagged `run_process` turn's ingest call carries the shell command
     and the fs turn's carries the fs command.
  2. `test_run_batch_without_shell_server_command_is_unchanged` — passing
     `shell_server_command=None` yields an IDENTICAL `RunLedger` to a call without the
     kwarg at all. (Today the kwarg does not exist, so this test is RED with
     `TypeError: run_batch() got an unexpected keyword argument 'shell_server_command'` —
     the missing-feature signature that also proves the kwarg must be OPTIONAL.)
  3. `test_flagging_shell_turn_stores_shell_command_in_case` — with the REAL
     `add_case` ingester over gated traces (synthetic manifests, the platform-independent
     convention from `tests/test_phase0_runner.py`), the stored case's `server_command`
     field carries the shell command for the flagged `run_process` turn and the fs command
     for the flagged fs turn.

RED against today's code: `run_batch` has no such keyword, so tests 1 and 3 fail with
`TypeError: run_batch() got an unexpected keyword argument 'shell_server_command'` and
test 2 fails on its explicit-`None` call with the same signature. Not syntax errors, not
fixture breakage.
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.corpus.add import add_case
from belay.phase0.ledger import Disposition
from belay.phase0.runner import run_batch
from belay.trace import TraceWriter
from belay.verify import turn as turn_module
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

from fixtures.shell_command_server import RUN_TOOL
from test_phase0_runner import _write_gated_trace

CAPTURED_AT = "2026-07-18T00:00:00+00:00"

#: The batch's two commands, as the mint would pass them: the fs server takes the
#: `{workspace}` root token; the shell server is the rootless pinned entrypoint.
FS_CMD = ["node", "/abs/fs-server/build/index.js", "{workspace}"]
SHELL_CMD = ["node", "/abs/mcp-server-commands/build/index.js"]

#: The fs tool of the batch's non-shell trace (the reference filesystem server's read tool).
FS_TOOL = "read_text_file"


# --- synthetic trace + canned-verdict apparatus (mirrors tests/test_phase0_runner.py) ---


def _call_frame(call_id: int, tool: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": {}},
        }
    ).encode()


def _reply_frame(call_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": call_id,
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    ).encode()


def _write_trace(trace_dir: Path, tool: str, n_calls: int) -> Path:
    """Write one `trace-*.jsonl` of `n_calls` `tools/call` turns for `tool`, via the real writer."""
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for i in range(n_calls):
            call_id = 10 + i
            writer.observer("c2s")(_call_frame(call_id, tool), False)
            writer.observer("s2c")(_reply_frame(call_id), False)
    finally:
        writer.close()
    return writer.path


def _verdict(n: int, status: Status, *, tool_name: str) -> TurnVerdict:
    """A canned `TurnVerdict` carrying `tool_name` — the field the runner resolves on."""
    return TurnVerdict(
        turn_index=n,
        tool_name=tool_name,
        status=status,
        sub_verdicts=[Verdict("A2", "replay", status, None, None, "canned")],
        cause=None,
    )


def _canned_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier keyed by the trace's stem, tolerant of the new kwarg.

    Reads the stem back off `manifest_dir`'s name (`<stem>.manifests`), exactly as
    `test_phase0_runner.py`'s `_stem_verifier`. `shell_server_command` is accepted but
    ignored here — the RUNNER's threading of it is what tests 1 asserts, through the
    recording fake, and its resolution is `verify_turn`'s, pinned in the verify file.
    """

    def verifier(
        records, n, *, server_command, manifest_dir, invariants, replays, timeout,
        shell_server_command=None,
    ):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        return canned[stem][n]

    return verifier


def _recording_verifier(canned: dict[str, list[TurnVerdict]]):
    """A fake verifier that records, per turn, the commands the runner offered it.

    Records the RAW kwargs the runner threaded (both `server_command` and
    `shell_server_command` must reach the verifier on EVERY turn — the resolution is
    `verify_turn`'s, and without both commands it cannot decide) and the command the
    design's resolution rule picks for THAT turn (tool name read from `records` the same
    way `verify_turn` reads it), so the test can assert that the `run_process` turn is
    offered the shell command and the fs turn the fs command.
    """
    seen: list[dict] = []

    def verifier(
        records, n, *, server_command, manifest_dir, invariants, replays, timeout,
        shell_server_command=None,
    ):
        stem = Path(manifest_dir).name.removesuffix(".manifests")
        tool = turn_module._tool_name(records, n)
        resolved = (
            shell_server_command
            if tool == RUN_TOOL and shell_server_command is not None
            else server_command
        )
        seen.append(
            {
                "stem": stem,
                "tool": tool,
                "server_command": list(server_command),
                "shell_server_command": (
                    None if shell_server_command is None else list(shell_server_command)
                ),
                "resolved": list(resolved),
            }
        )
        return canned[stem][n]

    return verifier, seen


def _recording_ingester():
    """A fake ingester that records the per-turn resolved command the runner hands it."""
    calls: list[dict] = []

    def ingester(corpus_dir_arg, **kwargs) -> Path:
        calls.append(
            {
                "source_trace_id": kwargs["source_trace_id"],
                "server_command": list(kwargs["server_command"]),
            }
        )
        return Path(corpus_dir_arg) / "unused-case"

    return ingester, calls


def _noop_ingester(corpus_dir, **kwargs) -> Path:
    return Path(corpus_dir) / "unused-case"


# --- 1. the runner threads shell_server_command and resolves per flagged turn ----------


def test_run_batch_shell_server_command_threads_per_turn(tmp_path) -> None:
    """A 2-trace batch (run_process + fs tool): the shell command reaches the shell turn.

    The recording fake verifier sees BOTH commands threaded on every call (the runner must
    not swallow the new kwarg — `verify_turn` resolves per turn and needs both), and the
    design's resolution rule picks the shell command for the `run_process` turn and the fs
    command for the fs turn. The recording fake INGESTER then pins the runner's OWN
    resolution seam (spec requirement 2): the flagged `run_process` turn's ingest call
    carries the SHELL command and the fs turn's carries the FS command — a corpus case
    stores the command its turn actually replayed against.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"

    shell_path = _write_trace(trace_dir, RUN_TOOL, 1)
    fs_path = _write_trace(trace_dir, FS_TOOL, 1)
    canned = {
        shell_path.stem: [_verdict(0, Status.FAIL, tool_name=RUN_TOOL)],
        fs_path.stem: [_verdict(0, Status.FAIL, tool_name=FS_TOOL)],
    }
    verifier, seen = _recording_verifier(canned)
    ingester, ingest_calls = _recording_ingester()

    ledger = run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=FS_CMD,
        shell_server_command=SHELL_CMD,
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=verifier,
        ingester=ingester,
    )

    by_stem = {entry["stem"]: entry for entry in seen}
    assert by_stem[shell_path.stem]["tool"] == RUN_TOOL
    assert by_stem[fs_path.stem]["tool"] == FS_TOOL
    # The resolution rule picks per turn: run_process -> shell, anything else -> fs.
    assert by_stem[shell_path.stem]["resolved"] == SHELL_CMD, by_stem[shell_path.stem]
    assert by_stem[fs_path.stem]["resolved"] == FS_CMD, by_stem[fs_path.stem]
    # The runner threads BOTH commands into the verifier on EVERY turn, verbatim — the fs
    # turn's call must still carry the shell kwarg so verify_turn can decide per turn.
    assert by_stem[shell_path.stem]["server_command"] == FS_CMD
    assert by_stem[fs_path.stem]["server_command"] == FS_CMD
    assert by_stem[shell_path.stem]["shell_server_command"] == SHELL_CMD
    assert by_stem[fs_path.stem]["shell_server_command"] == SHELL_CMD

    # The runner's OWN resolution is the ingest seam: per flagged turn, by tool_name.
    by_src = {call["source_trace_id"]: call["server_command"] for call in ingest_calls}
    assert by_src[shell_path.stem] == SHELL_CMD, by_src
    assert by_src[fs_path.stem] == FS_CMD, by_src

    # And the batch itself is unchanged in shape: both flagged, both addable.
    by_id = {inst.trace_id: inst for inst in ledger.instances}
    assert by_id[shell_path.stem].disposition is Disposition.VERIFIED_FLAGGED
    assert by_id[fs_path.stem].disposition is Disposition.VERIFIED_FLAGGED
    assert by_id[shell_path.stem].flagged_addable == [0]
    assert by_id[fs_path.stem].flagged_addable == [0]


# --- 2. AC-3 regression: shell_server_command=None is byte-for-byte today ------------


def test_run_batch_without_shell_server_command_is_unchanged(tmp_path) -> None:
    """`run_batch(..., shell_server_command=None)` yields an IDENTICAL ledger to no kwarg.

    The kwarg must be OPTIONAL — today it does not exist at all, so the explicit-`None`
    call is the RED signature (`TypeError: unexpected keyword argument`), and once it
    exists `None` must mean "today's behavior": the same fakes, the same traces, the same
    `RunLedger` field for field. This is the fs-only regression fixture AC-3.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"

    fs_path = _write_trace(trace_dir, FS_TOOL, 1)
    canned = {fs_path.stem: [_verdict(0, Status.PASS, tool_name=FS_TOOL)]}

    def run(**extra):
        return run_batch(
            trace_dir,
            corpus_dir=corpus_dir,
            server_command=FS_CMD,
            invariants=(),
            captured_at=CAPTURED_AT,
            verifier=_canned_verifier(canned),
            ingester=_noop_ingester,
            **extra,
        )

    plain = run()
    with_none = run(shell_server_command=None)  # must be optional; None = today's behavior

    assert with_none == plain
    assert [inst.turn_status_counts for inst in with_none.instances] == [
        inst.turn_status_counts for inst in plain.instances
    ]


# --- 3. AC-4: a flagged shell turn's stored case carries the shell command -----------


def test_flagging_shell_turn_stores_shell_command_in_case(tmp_path) -> None:
    """The stored corpus case of a flagged shell turn carries the SHELL command.

    With the REAL `add_case` ingester over two GATED traces (synthetic manifests + fake
    pre-state trees, the platform-independent convention from `tests/test_phase0_runner.py`
    tests 7/8), the runner resolves each flagged turn by its `tool_name` and the stored
    `case.json`'s `server_command` field must be the command that turn actually replayed
    against: the shell command for the `run_process` turn, the fs command for the fs turn.
    Self-contained cases preserved — a case stores ONE command, the one its replay used.
    """
    trace_dir = tmp_path / "traces"
    corpus_dir = tmp_path / "corpus"

    shell_path = _write_gated_trace(trace_dir, RUN_TOOL, 1)
    fs_path = _write_gated_trace(trace_dir, FS_TOOL, 1)
    canned = {
        shell_path.stem: [_verdict(0, Status.FAIL, tool_name=RUN_TOOL)],
        fs_path.stem: [_verdict(0, Status.FAIL, tool_name=FS_TOOL)],
    }

    run_batch(
        trace_dir,
        corpus_dir=corpus_dir,
        server_command=FS_CMD,
        shell_server_command=SHELL_CMD,
        invariants=(),
        captured_at=CAPTURED_AT,
        verifier=_canned_verifier(canned),
        ingester=add_case,
    )

    def stored_command(stem: str) -> list[str]:
        case_dir = corpus_dir / f"{stem}-turn0"
        assert case_dir.is_dir(), f"the case was not stored: {case_dir}"
        payload = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        return payload["server_command"]

    assert stored_command(shell_path.stem) == SHELL_CMD
    assert stored_command(fs_path.stem) == FS_CMD
