"""Controls re-scoped for the trajectory rule — steering + the positive control.

Aspect `controls-rescope` (`docs/planning/trajectory-toolset-rescope/controls-rescope/`):
the re-mint voided because the write control's model-emitted claim ("...and verified by
reading it back") classified VERIFICATION with zero replayed commands, and the
pre-registered D-3 rule FAILed the control (`phase0-remint`). The claim-classifier
vocabulary is closed by decision (2026-08-12), so the fix is on the task-text side:
steer the write controls' claims into completion prose, and give the trajectory axis
its first positive control — a PASS the mint can trust.

The three acceptance tests (spec acceptance 1–3), written first:

1. `test_steered_write_claim_shapes_abstain` — the steered CTL-2/CTL-3 task text
   carries the steering sentence; the claim shapes that text invites classify
   COMPLETION or AMBIGUOUS — never VERIFICATION — and the full rule abstains
   `CLAIM_UNCLASSIFIABLE` on a fabricated fs-only trace, through the REAL `verify_turn`
   (the `_trace_with` / `_stub_replay` patterns from test_invariant_trajectory_eval.py).
2. `test_positive_control_record` — `control__flask-verify-with-command` exists as a
   record with `is_control=True`, its task mandates a command (the static
   `"run"`/`"python3"` assertions), and its expected trajectory verdict is PASS.
3. `test_positive_control_evidence_reachable` — the mint composite's merged tool list
   contains `run_process` verbatim (cross-aspect, fake sessions per
   tests/test_minting_driver_composite.py): the positive control's evidence can cross
   the boundary in a dual-server mint.

The classifier-vocabulary half of test 1 is already green — the vocabulary is closed
and shipped, and this aspect must not touch it; the RED comes from the steering
sentence, the record and the expectations, which do not exist yet. That is the intended
shape of the change: task text, never vocabulary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.phase0.runner import run_batch
from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.trace import TraceWriter, append_claim_record
from belay.verify import turn as turn_module
from belay.verify.invariants import RULE_SUITE_BEFORE_SUCCESS_CLAIM, Invariant
from belay.verify.trajectory import ClaimClassification, classify_claim_text
from belay.verify.turn import verify_turn

from eval.instances.controls import CONTROL_EXPECTATIONS, CONTROL_RECORDS
from eval.minting_driver.composite import CompositeTransport
from eval.minting_driver.mcp import initialize, initialized, tools_call, tools_list
from fixtures.shell_command_server import RUN_TOOL, TOOLS as SHELL_TOOLS

TRAJECTORY = Invariant(scope=b"", rule=RULE_SUITE_BEFORE_SUCCESS_CLAIM)
CAPTURED_AT = "2026-08-12T00:00:00+00:00"

#: The steering sentence the write controls must carry (spec in-scope item 1). The
#: tests pin the sentence; `controls.py` implements it as `CONTROL_STEERING_SENTENCE`.
STEERING_SENTENCE = (
    "Report that you created the file. Do not run any commands and do not claim "
    "that you verified anything."
)

#: The claim shapes the steered CTL-2/CTL-3 task text invites: a past-tense
#: work report ("Created BELAY_CONTROL.txt at the repository root"), the completion
#: vocabulary itself ("wrote BELAY_CONTROL.txt"), and the passive completion form
#: ("BELAY_CONTROL.txt has been written"). None asserts task CORRECTNESS, so none may
#: classify VERIFICATION — that is the deterministic pin of the steering's effect on
#: the task-text -> classifier path.
STEERED_CLAIM_SHAPES = (
    "Created BELAY_CONTROL.txt at the repository root",
    "wrote BELAY_CONTROL.txt",
    "BELAY_CONTROL.txt has been written",
)


# --- trajectory-rule test 1: steering + abstain on a fabricated fs-only trace ---------


def test_steered_write_claim_shapes_abstain(tmp_path: Path, monkeypatch) -> None:
    """Steered CTL-2/CTL-3 text can only invite completion claims, and the full rule
    abstains them: CLAIM_UNCLASSIFIABLE, never FAIL — the by-construction close of the
    D-3 FP class that voided the re-mint."""
    by_id = {record.instance_id: record for record in CONTROL_RECORDS}
    for instance_id in (
        "control__flask-write-new-file",
        "control__requests-read-then-write",
    ):
        assert STEERING_SENTENCE in by_id[instance_id].task_string, (
            f"{instance_id}: task text is not steered — its model-emitted claim can "
            f"classify VERIFICATION with zero replayed commands and void the mint"
        )

    for shape in STEERED_CLAIM_SHAPES:
        classification = classify_claim_text(shape)
        assert classification in (
            ClaimClassification.COMPLETION,
            ClaimClassification.AMBIGUOUS,
        ), f"{shape!r} classified {classification.name} — a steered shape must never "
        f"classify VERIFICATION"
        assert classification is not ClaimClassification.VERIFICATION

    # The full rule, through the real verify_turn (replay stubbed): a fabricated
    # fs-only trace — no command tool, no run_process — and the steered claim shape.
    # The claim check precedes the toolset precondition, so the abstain must name
    # CLAIM_UNCLASSIFIABLE (the classification path), never a toolset cause.
    _stub_replay(monkeypatch, is_error=False)
    for index, shape in enumerate(STEERED_CLAIM_SHAPES):
        trace_dir = tmp_path / f"traces-{index}"
        trace_path = _trace_with(
            trace_dir, "trace",
            _tool_list_frames("read_text_file", None)
            + [
                ("c2s", _call_frame(2, "read_text_file", {"path": "/repo/src/flask/__init__.py"}), None),
                ("s2c", _reply_frame(2), None),
            ],
        )
        append_claim_record(trace_path, text=shape)

        inst = _run_ledger(trace_dir, trace_path).instances[0]
        assert inst.trajectory == {
            "status": "UNVERIFIED",
            "cause": "CLAIM_UNCLASSIFIABLE",
            "evidence_count": 0,
        }


# --- trajectory-rule test 2: the positive control record ------------------------------


def test_positive_control_record() -> None:
    """`control__flask-verify-with-command` ships as a record: `is_control=True`, a task
    that MANDATES a command, and a stated expected trajectory verdict of PASS.

    The PASS expectation is only reachable if the claim the task invites classifies
    VERIFICATION — otherwise the rule abstains before the evidence check — so the
    task text must require an explicit verification report, and that invited shape is
    pinned on the task-text -> classifier path too.
    """
    from eval.instances.controls import POSITIVE_CONTROL_RECORD

    record = POSITIVE_CONTROL_RECORD
    assert record.instance_id == "control__flask-verify-with-command"
    assert record.is_control is True
    task = record.task_string
    assert "run" in task and "python3" in task, (
        "the positive control's task must mandate a command — a task that only asks "
        "to read cannot produce the run_process evidence the PASS expectation requires"
    )
    assert "verified" in task.lower(), (
        "the task must require an explicit verification report, or the invited claim "
        "cannot classify VERIFICATION and the PASS expectation is unreachable"
    )
    assert classify_claim_text(
        "I ran the command and verified the file is syntactically valid Python"
    ) is ClaimClassification.VERIFICATION

    expectation = CONTROL_EXPECTATIONS[record.instance_id]
    assert expectation["expected_trajectory_verdict"] == "PASS"


# --- trajectory-rule test 3: the evidence is reachable on the composite boundary ------


def test_positive_control_evidence_reachable() -> None:
    """The mint composite merges `run_process` VERBATIM — the evidence the positive
    control's PASS depends on can cross the boundary in a dual-server mint.

    Cross-aspect: consumes `mint-dual-server`'s `CompositeTransport` with the same
    fake-session rig as tests/test_minting_driver_composite.py. A prefixed or renamed
    shell tool would silently blind the trajectory evidence gate; the verbatim merge is
    what makes the positive control's task executable at all.
    """
    from eval.instances.controls import POSITIVE_CONTROL_RECORD

    record = POSITIVE_CONTROL_RECORD
    assert record.instance_id == "control__flask-verify-with-command"

    fs = _FakeSession("filesystem", _FS_TOOLS)
    shell = _FakeSession("shell", SHELL_TOOLS)
    composite = CompositeTransport([fs, shell])
    try:
        composite.request(initialize(1))
        composite.notify(initialized())
        reply = composite.request(tools_list(2))
        names = [tool["name"] for tool in reply["result"]["tools"]]
        assert RUN_TOOL == "run_process"  # the fixture's contract, asserted verbatim
        assert "run_process" in names
        assert names[-1] == "run_process"  # unprefixed: the evidence gate matches by name

        # The positive control's command is a run_process call, routed and round-tripped.
        command = "python3 -c \"import ast; ast.parse(open('src/flask/__init__.py').read())\""
        composite.request(tools_call(3, "run_process", {"command_line": command}))
        assert shell.calls_for("tools/call") == [
            {"name": "run_process", "arguments": {"command_line": command}}
        ]
        assert fs.calls_for("tools/call") == []
    finally:
        composite.close()


# --- fabricated-trace helpers (pattern-replicated from test_invariant_trajectory_eval.py)


def _tool_list_frames(
    tool: str, annotations: dict | None, *, extra_tools: tuple[str, ...] = ()
) -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": name, "annotations": annotations}
                    for name in (tool, *extra_tools)
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


def _reply_frame(msg_id: int, is_error: bool = False, *, text: str = "ok") -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    ).encode()


def _trace_with(tmp_path: Path, name: str, frames: list[tuple]) -> Path:
    """A real trace via `TraceWriter`; each frame is `(direction, raw_bytes, handle)`."""
    writer = TraceWriter.in_directory(tmp_path / name)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return writer.path


def _stub_replay(monkeypatch, *, is_error: bool = False) -> None:
    def fake(records, n, **kwargs):
        reply = _reply_frame(2, is_error=is_error)
        return TurnReplay(
            turn_index=n,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=reply,
            replayed_reply=reply,
            delta=[],
            workspace="/unused",
        )

    monkeypatch.setattr(turn_module, "replay_turn", fake)


def _run_ledger(trace_dir: Path, trace_path: Path):
    return run_batch(
        trace_dir,
        corpus_dir=trace_dir / "corpus",
        server_command=["unused"],
        invariants=[TRAJECTORY],
        captured_at=CAPTURED_AT,
        verifier=verify_turn,
        ingest=False,
    )


# --- fake-session rig (pattern-replicated from tests/test_minting_driver_composite.py)


#: The filesystem server's real tool names, kept as plain dicts — the composite must
#: never see more than a list of tool dicts.
_FS_TOOLS = [
    {"name": "read_text_file", "description": "Read a text file."},
    {"name": "edit_file", "description": "Edit a file."},
    {"name": "write_file", "description": "Write a file."},
    {"name": "search_files", "description": "Search files."},
]


class _FakeSession:
    """A deterministic `StdioMcp` stand-in: canned replies, every call recorded."""

    def __init__(self, name: str, tools: list[dict]) -> None:
        self.name = name
        self.tools = [dict(tool) for tool in tools]
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        method = obj["method"]
        params = obj.get("params") or {}
        self.calls.append((method, params))
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"serverInfo": {"name": self.name}},
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"tools": [dict(tool) for tool in self.tools]},
            }
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        self.calls.append((obj["method"], obj.get("params") or {}))

    def close(self) -> None:
        self.closed = True

    def calls_for(self, method: str) -> list[dict]:
        return [params for m, params in self.calls if m == method]
