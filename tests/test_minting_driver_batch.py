"""Offline, deterministic tests for the sequential batch driver (`eval/minting_driver/batch.py`).

`run_mint` composes the three Phase 1–3 modules — workspace prep, the gated session, the
rename bridge — and the resume checkpoint into one sequential pass over the registry. These
tests exercise the REAL `run_session`/`run_task` control flow and the REAL `bridge_capture`,
substituting only at the injectable seams so CI never spends, never runs git, never spawns a
real subprocess:

- `prepare` — a stub that makes the layout dirs (no git) and drops a fake trace file, so the
  real bridge finds exactly one capture.
- `model_factory` — a counting factory that returns a FRESH `ScriptedModel` per call (the
  fresh-client seam; `tools` is accepted and ignored).
- `transport_factory` — threaded through `run_session` into `run_task`, a fake transport that
  records call order / timeout / in-flight depth without a real MCP subprocess.
- `discover_tools` — a trivial stub, so the default second-transport tool discovery never runs.

The headline invariant (never more than one `tools/call` in flight) is asserted across
MULTIPLE instances via a shared re-entrancy counter, proving the sequential guarantee holds
batch-wide, not just within one session.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from eval.instances.registry import InstanceRecord
from eval.minting_driver.batch import run_mint
from eval.minting_driver.checkpoint import Checkpoint
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


class StubPrepare:
    """A workspace-prep stand-in: makes the layout dirs (NO git) and drops a fake trace file.

    The fake `trace-*.jsonl` is what the real `bridge_capture` moves — with no gated proxy
    running, nothing else would write one. Records the instances it prepared, in order, so a
    test can assert which instances were driven vs skipped.
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
            (layout.trace_dir / "trace-20260722T000000Z-abcd1234.jsonl").write_text(
                '{"turn": 0}\n', encoding="utf-8"
            )
        self.prepared.append(record.instance_id)
        return layout


class CountingModelFactory:
    """Builds a FRESH `ScriptedModel` per call and counts calls — the fresh-client seam.

    `tools` is accepted (the `model_factory` contract) but ignored: the script is the sole
    source of truth. A fresh model per call is what proves no conversation state bleeds
    between instances.
    """

    def __init__(self, script: list[ToolCall | Done] | None = None) -> None:
        self.calls = 0
        self._script: list[ToolCall | Done] = (
            script if script is not None else [ToolCall(name="read_file"), Done(reason="done")]
        )

    def __call__(self, tools: object) -> ScriptedModel:
        self.calls += 1
        return ScriptedModel(list(self._script))


def _canned_reply(obj: dict) -> dict:
    """A benign JSON-RPC reply for each MCP method the loop issues."""
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


class OkTransport:
    """A benign fake transport: canned replies, no subprocess, no trace side effects."""

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        return _canned_reply(obj)

    def notify(self, obj: dict) -> None:
        pass

    def close(self) -> None:
        pass


class InFlightLedger:
    """A shared counter across every session's transport — proves the batch-wide invariant."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0


class ReentrancyTransport:
    """Shares one `InFlightLedger` across all instances, asserting depth never exceeds one."""

    def __init__(self, ledger: InFlightLedger) -> None:
        self._ledger = ledger

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        self._ledger.in_flight += 1
        self._ledger.max_in_flight = max(self._ledger.max_in_flight, self._ledger.in_flight)
        assert self._ledger.in_flight <= 1, "more than one request in flight at once"
        try:
            return _canned_reply(obj)
        finally:
            self._ledger.in_flight -= 1

    def notify(self, obj: dict) -> None:
        pass

    def close(self) -> None:
        pass


class TimeoutRecordingTransport:
    """Appends the `timeout` each `request` receives to a shared sink."""

    def __init__(self, sink: list[float | None]) -> None:
        self._sink = sink

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        self._sink.append(timeout)
        return _canned_reply(obj)

    def notify(self, obj: dict) -> None:
        pass

    def close(self) -> None:
        pass


class FailingOnInstance:
    """A transport factory that RAISES for one target instance, `OkTransport` for the rest.

    Keys off the instance id embedded in `BELAY_TRACE_DIR` (the per-instance layout puts it
    there), simulating a `ServerExited` at spawn for exactly one instance.
    """

    def __init__(self, fail_id: str) -> None:
        self._fail_id = fail_id

    def __call__(self, server_command: list[str], env: dict) -> OkTransport:
        if self._fail_id in env["BELAY_TRACE_DIR"]:
            raise RuntimeError(f"server exited for {self._fail_id}")
        return OkTransport()


class RecordingBuildServerCommand:
    """Spy for the per-instance `build_server_command` seam.

    Records the `WorkspaceLayout` handed to it on each call, and returns a command that
    embeds THIS instance's `work_dir` — exactly as `filesystem_server_command(layout.work_dir)`
    does. The regression guard for the constant-command bug: with a constant command every
    instance after the first pointed its filesystem server at the wrong workspace.
    """

    def __init__(self) -> None:
        self.layouts: list[object] = []

    def __call__(self, layout: object) -> list[str]:
        self.layouts.append(layout)
        return ["node", "fs.js", str(layout.work_dir)]  # type: ignore[attr-defined]


def test_build_server_command_receives_each_instances_layout(tmp_path: Path) -> None:
    """The seam is called with each instance's OWN layout (per-instance `work_dir`).

    Two instances must yield two DIFFERENT commands reflecting their two different
    workspaces. This is the regression guard: a constant `server_command` would point every
    instance's filesystem server at the first workspace, so the server rejects the model's
    edits and those instances yield no verifiable turns.
    """
    records = [_record("octo__repo-1"), _record("octo__repo-2")]
    root = tmp_path / "mint"
    build = RecordingBuildServerCommand()

    run_mint(
        records,
        root=root,
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=build,
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    # Called once per instance, each with that instance's own layout.
    assert len(build.layouts) == 2
    work_dirs = [layout.work_dir for layout in build.layouts]  # type: ignore[attr-defined]
    assert work_dirs[0] == layout_for("octo__repo-1", root).work_dir
    assert work_dirs[1] == layout_for("octo__repo-2", root).work_dir
    # And the two built commands differ — the whole point of the seam.
    assert work_dirs[0] != work_dirs[1]


def test_drives_instances_sequentially_never_more_than_one_call_in_flight(
    tmp_path: Path,
) -> None:
    """Across MULTIPLE instances, the shared re-entrancy counter never exceeds one in flight."""
    records = [_record("octo__repo-1"), _record("octo__repo-2"), _record("octo__repo-3")]
    prepare = StubPrepare()
    factory = CountingModelFactory(
        [ToolCall(name="read_file"), ToolCall(name="write_file"), Done(reason="done")]
    )
    ledger = InFlightLedger()

    checkpoint = run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: ReentrancyTransport(ledger),
        discover_tools=lambda cmd: [],
    )

    assert ledger.max_in_flight <= 1
    assert prepare.prepared == ["octo__repo-1", "octo__repo-2", "octo__repo-3"]
    for record in records:
        assert checkpoint.status(record.instance_id) == "captured"


def test_a_failing_instance_does_not_abort_the_batch(tmp_path: Path) -> None:
    """One instance's `run_session` raising is recorded `failed`; the rest still run."""
    records = [_record("octo__repo-1"), _record("octo__repo-2"), _record("octo__repo-3")]
    prepare = StubPrepare()
    factory = CountingModelFactory()

    checkpoint = run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=FailingOnInstance("octo__repo-2"),
        discover_tools=lambda cmd: [],
    )

    assert checkpoint.status("octo__repo-1") == "captured"
    assert checkpoint.status("octo__repo-2") == "failed"
    assert checkpoint.reason("octo__repo-2")  # a non-empty failure reason was recorded
    assert checkpoint.status("octo__repo-3") == "captured"


def test_resume_skips_already_captured_instances(tmp_path: Path) -> None:
    """A pre-seeded `captured` instance is neither prepared nor driven on re-entry."""
    ckpt_path = tmp_path / "ckpt.json"
    seed = Checkpoint()
    seed.record("octo__repo-1", "captured", trace_path="already/there.jsonl")
    seed.save(ckpt_path)

    records = [_record("octo__repo-1"), _record("octo__repo-2")]
    prepare = StubPrepare()
    factory = CountingModelFactory()

    checkpoint = run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=ckpt_path,
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    # The already-captured instance was skipped: not prepared, not driven.
    assert prepare.prepared == ["octo__repo-2"]
    assert factory.calls == 1
    assert checkpoint.status("octo__repo-2") == "captured"
    # And its prior disposition is untouched.
    assert checkpoint.status("octo__repo-1") == "captured"
    assert checkpoint.trace_path("octo__repo-1") == "already/there.jsonl"


def test_resume_after_partial_instance_is_retried_or_recorded_failed_not_left_partial(
    tmp_path: Path,
) -> None:
    """An instance not in the checkpoint (a crash mid-run) is retried and ends with a
    definite disposition — never left partial."""
    ckpt_path = tmp_path / "ckpt.json"
    seed = Checkpoint()
    seed.record("octo__repo-1", "captured", trace_path="t1.jsonl")
    seed.save(ckpt_path)

    # Simulate a crash mid-instance-2: its per-instance trace dir exists but holds no trace.
    partial = layout_for("octo__repo-2", tmp_path / "mint")
    partial.trace_dir.mkdir(parents=True)

    records = [_record("octo__repo-1"), _record("octo__repo-2")]
    prepare = StubPrepare()
    factory = CountingModelFactory()

    checkpoint = run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=ckpt_path,
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    # The partial instance was retried and now carries a definite disposition.
    assert checkpoint.is_done("octo__repo-2")
    assert checkpoint.status("octo__repo-2") == "captured"
    assert prepare.prepared == ["octo__repo-2"]  # the done instance-1 was skipped


def test_each_instance_gets_a_fresh_model_client(tmp_path: Path) -> None:
    """The factory is called exactly once per NON-SKIPPED instance."""
    ckpt_path = tmp_path / "ckpt.json"
    seed = Checkpoint()
    seed.record("octo__repo-2", "captured", trace_path="x.jsonl")
    seed.save(ckpt_path)

    records = [_record("octo__repo-1"), _record("octo__repo-2"), _record("octo__repo-3")]
    prepare = StubPrepare()
    factory = CountingModelFactory()

    run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=ckpt_path,
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    # Three records, one already captured -> two fresh model clients built.
    assert factory.calls == 2


def test_request_timeout_is_forwarded_to_run_session(tmp_path: Path) -> None:
    """`request_timeout` reaches every `transport.request` — via run_session -> run_task."""
    records = [_record("octo__repo-1")]
    prepare = StubPrepare()
    factory = CountingModelFactory([ToolCall(name="run_tests"), Done(reason="done")])
    seen: list[float | None] = []

    run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=45.0,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: TimeoutRecordingTransport(seen),
        discover_tools=lambda cmd: [],
    )

    # initialize, tools/list, one tools/call — all three see 45.0.
    assert seen == [45.0, 45.0, 45.0]


def test_two_servers_never_share_a_trace_dir(tmp_path: Path) -> None:
    """One `run_mint` is single-server / single-batch-dir; `root` is required and distinct.

    The batch dir is a pure function of the required `root`, so two run_mint calls (one per
    server) with distinct roots produce disjoint trace dirs — a single call can never mix two
    servers into one.
    """
    # `root` is required per call (no default): the segregation seam, asserted structurally.
    sig = inspect.signature(run_mint)
    assert sig.parameters["root"].default is inspect.Parameter.empty

    records = [_record("octo__repo-1")]
    root_fs = tmp_path / "mint-fs"
    root_shell = tmp_path / "mint-shell"

    ck_fs = run_mint(
        records,
        root=root_fs,
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=lambda layout: ["node", "fs.js"],
        checkpoint_path=tmp_path / "fs.json",
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )
    ck_shell = run_mint(
        records,
        root=root_shell,
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=lambda layout: ["node", "shell.js"],
        checkpoint_path=tmp_path / "shell.json",
        request_timeout=None,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )

    fs_trace = Path(str(ck_fs.trace_path("octo__repo-1")))
    shell_trace = Path(str(ck_shell.trace_path("octo__repo-1")))
    assert fs_trace.parent == root_fs / "batch"
    assert shell_trace.parent == root_shell / "batch"
    assert fs_trace.parent != shell_trace.parent
