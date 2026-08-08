"""Offline, deterministic tests for the driver-side claim record (`batch.py` wiring).

The trajectory rule needs the agent's final success claim to judge, but the
claim never crosses the MCP proxy: `Done` is parsed by the model client inside
the minting driver, the loop returns on it without it ever crossing the wire,
and `run_mint` used to discard the `Transcript`. The format's answer is
`append_claim_record` (`src/belay/trace.py`); these tests pin the driver half
(spec acceptance 7-9): `run_mint` keeps the `Transcript` and, when the session
stopped with a `Done`, appends the claim to the capture trace **before**
`bridge_capture`, so the record rides inside `trace.jsonl` through the bridge
and lands where `belay phase0 run` will read it.

The four behaviors under test:

1. `Done(reason="the fix works")` → a `claim` record with `text == reason`,
   `kind "claim"`, `observation_point "session"`, `seq == last + 1`.
2. `Done(reason="  ")` (whitespace) → the record is written with the `text`
   key **absent** — an empty string would occupy a meaning it doesn't have.
3. `max_steps` termination (no `Done`) → **no** claim record: nothing was
   claimed, and the rule must abstain honestly rather than be fed silence.
4. No capture trace at all (a fake-transport run writes nothing) → the driver
   checks the trace exists first and appends only then: no crash, no claim,
   and the instance fails on the BRIDGE's missing-trace error — never a claim
   append error, which would mean the driver tried to append to nothing.

The tests drive the REAL `run_session`/`run_task` control flow and the REAL
`bridge_capture` with the usual offline seams (stub `prepare` — here writing a
REAL closed trace via `TraceWriter`, because the claim appender needs a
well-formed capture sequence to continue — a counting model factory over
`ScriptedModel`, a fake transport, a stub discovery). Only the trace file that
test 5 hands to the real `bridge_capture` differs from what a real run
produces: it has the claim already appended, which is exactly the state test 1
leaves behind for the bridge to move.

Which tests were RED first: 1 and 2 fail on the unwired driver (no claim
lands); 3 and 4 pass on it (the absence they pin is exactly what no wiring
produces) and stay green as contract pins; 5 pins the bridge's content-
agnosticism, which is what makes appending BEFORE the bridge the right
ordering rather than a hope. The wiring under test is the difference between
"no claim lands" and "the claim lands".
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.trace import TraceWriter, append_claim_record
from eval.instances.registry import InstanceRecord
from eval.minting_driver.batch import run_mint
from eval.minting_driver.bridge import bridge_capture
from eval.minting_driver.fakes import ScriptedModel
from eval.minting_driver.model import Done, ToolCall
from eval.minting_driver.workspace import layout_for


def _record(instance_id: str, *, task: str = "make the edit") -> InstanceRecord:
    """A minimal `InstanceRecord` for the batch (fields the harness reads: id + task)."""
    return InstanceRecord(
        instance_id=instance_id,
        repo="octo/repo",
        base_commit="abc1234",
        problem_statement="an issue to fix",
        task_string=task,
    )


class ClaimTracePrepare:
    """A workspace-prep stand-in that writes a REAL closed trace via `TraceWriter`.

    The claim appender continues the capture's `seq` sequence, which demands a
    well-formed last record — a hand-written fake like `{"turn": 0}` cannot
    carry one. So this stub produces what the gated proxy would: an open + a
    close `connection_window` record (seq 0, 1), closed, ready for the claim.
    """

    def __init__(self, *, write_trace: bool = True) -> None:
        self.prepared: list[str] = []
        self._write_trace = write_trace

    def __call__(self, record: InstanceRecord, *, root: object, clones_dir: object) -> object:
        layout = layout_for(record.instance_id, Path(str(root)))
        layout.work_dir.mkdir(parents=True, exist_ok=True)
        layout.trace_dir.mkdir(parents=True, exist_ok=True)
        layout.snapshot_dir.mkdir(parents=True, exist_ok=True)
        if self._write_trace:
            writer = TraceWriter.in_directory(layout.trace_dir)
            writer.close()
        self.prepared.append(record.instance_id)
        return layout


class ClaimModelFactory:
    """Builds a FRESH `ScriptedModel` per call from one script — the fresh-client seam."""

    def __init__(self, script: list[ToolCall | Done]) -> None:
        self._script = list(script)
        self.calls = 0

    def __call__(self, tools: object) -> ScriptedModel:
        self.calls += 1
        return ScriptedModel(list(self._script))


class OkTransport:
    """A benign fake transport: canned replies, no subprocess, no trace side effects."""

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        method = obj["method"]
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {"tools": []}}
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        pass

    def close(self) -> None:
        pass


def _drive(
    tmp_path: Path,
    records: list[InstanceRecord],
    *,
    prepare: ClaimTracePrepare,
    factory: ClaimModelFactory,
    max_steps: int = 8,
) -> object:
    """`run_mint` with the standard offline seams; the claim tests vary only the script."""
    return run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=max_steps,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )


def records_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_a_done_reason_becomes_a_claim_record_in_the_bridged_trace(tmp_path: Path) -> None:
    """Acceptance 7: `Done(reason=...)` → one `claim` record, text == reason.

    Read at the trace path the checkpoint recorded — the BRIDGED location
    (`<root>/batch/trace-<instance_id>.jsonl`) — because after `run_mint` the
    source capture no longer exists there: the claim was appended before the
    bridge and rode the move.
    """
    prepare = ClaimTracePrepare()
    checkpoint = _drive(
        tmp_path,
        [_record("octo__repo-1")],
        prepare=prepare,
        factory=ClaimModelFactory([Done(reason="the fix works")]),
    )

    assert checkpoint.status("octo__repo-1") == "captured"
    bridged = Path(checkpoint.trace_path("octo__repo-1"))
    records = records_of(bridged)
    claims = [r for r in records if r["kind"] == "claim"]
    assert len(claims) == 1, f"expected exactly one claim record, found {len(claims)}"

    claim = claims[0]
    # The claim continues the capture's own sequence: the record before it is the
    # capture's last record (the bridge renames, never rewrites), and the seqs stay
    # gapless from the writer's first record through the claim.
    assert claim["seq"] == records[-2]["seq"] + 1
    assert [r["seq"] for r in records] == list(range(len(records)))
    assert claim["v"] == 1
    assert claim["kind"] == "claim"
    assert claim["t_in"].endswith("+00:00")
    assert claim["observation_point"] == "session"
    assert claim["text"] == "the fix works"
    # The claim is the last record: nothing may land after it.
    assert claim is records[-1]


def test_a_whitespace_done_reason_yields_a_claim_without_a_text_key(tmp_path: Path) -> None:
    """Acceptance 7: empty/whitespace reason → the record exists, `text` is ABSENT.

    Never `""`: an empty string would occupy a meaning it doesn't have.
    """
    prepare = ClaimTracePrepare()
    checkpoint = _drive(
        tmp_path,
        [_record("octo__repo-1")],
        prepare=prepare,
        factory=ClaimModelFactory([Done(reason="   ")]),
    )

    bridged = Path(checkpoint.trace_path("octo__repo-1"))
    claims = [r for r in records_of(bridged) if r["kind"] == "claim"]
    assert len(claims) == 1
    assert "text" not in claims[0]


def test_a_max_steps_termination_writes_no_claim_record(tmp_path: Path) -> None:
    """Acceptance 8: the step budget ran out → NO claim record.

    `max_steps` means the model never said `Done` — nothing was claimed, so
    nothing may be recorded. The bridged trace is exactly the capture the proxy
    wrote (open + close): no claim, nothing after the close.
    """
    prepare = ClaimTracePrepare()
    checkpoint = _drive(
        tmp_path,
        [_record("octo__repo-1")],
        prepare=prepare,
        factory=ClaimModelFactory(
            [ToolCall(name="read_file"), ToolCall(name="read_file")]
        ),
        max_steps=2,
    )

    assert checkpoint.status("octo__repo-1") == "captured"
    bridged = Path(checkpoint.trace_path("octo__repo-1"))
    records = records_of(bridged)
    assert not any(r["kind"] == "claim" for r in records)
    assert len(records) == 2, "the capture is the proxy's two connection_window records"
    assert records[-1]["phase"] == "close"


def test_no_capture_trace_means_no_crash_and_no_claim_attempt(tmp_path: Path) -> None:
    """A session with no trace (a fake-transport run) is skipped, never crashed on.

    The driver checks the trace exists before appending: with nothing to append
    to, there is no claim and no `TraceClaimError`. The instance still fails on
    the BRIDGE's own missing-trace error (`NoTraceError` — a mint that captured
    nothing is `failed`, never a clean short result), which is exactly what
    discriminates the existence check from a driver that tried to append and
    raised.
    """
    prepare = ClaimTracePrepare(write_trace=False)
    checkpoint = _drive(
        tmp_path,
        [_record("octo__repo-1")],
        prepare=prepare,
        factory=ClaimModelFactory([Done(reason="the fix works")]),
    )

    assert checkpoint.status("octo__repo-1") == "failed"
    reason = str(checkpoint.reason("octo__repo-1"))
    assert "no trace-*.jsonl" in reason, (
        f"expected the bridge's missing-trace failure, got a claim append failure: "
        f"{reason!r}"
    )


def test_a_claim_record_survives_bridge_capture(tmp_path: Path) -> None:
    """Acceptance 9: the claim rides inside `trace.jsonl` through the real bridge.

    The real `bridge_capture` with its real arguments, on a trace that already
    carries a claim — exactly the state `run_mint` hands it. The bridge is
    content-agnostic (it renames, never re-reads), so the claim arrives in the
    bridged trace and the source capture is consumed, not copied.
    """
    layout = layout_for("octo__repo-1", tmp_path / "mint")
    layout.trace_dir.mkdir(parents=True)
    layout.snapshot_dir.mkdir(parents=True)
    writer = TraceWriter.in_directory(layout.trace_dir)
    writer.close()
    append_claim_record(writer.path, text="the fix works")

    dest = bridge_capture(
        instance_id="octo__repo-1",
        trace_dir=layout.trace_dir,
        snapshot_dir=layout.snapshot_dir,
        batch_dir=tmp_path / "batch",
    )

    claims = [r for r in records_of(dest) if r["kind"] == "claim"]
    assert len(claims) == 1
    assert claims[0]["text"] == "the fix works"
    assert claims[0]["observation_point"] == "session"
    # The claim rode the ONE move: the source capture is gone, not duplicated.
    assert not list(layout.trace_dir.glob("trace-*.jsonl"))
