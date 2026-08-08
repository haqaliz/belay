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

The second headline invariant — added by the quota circuit breaker — is that a provider
**quota** error stops the batch instead of burning the queue through it. Those tests inject
the fault through `FaultOnNthInstance`, a `CountingModelFactory` that hands one chosen
instance a `FlakyModel`, because the error the breaker reacts to arrives from the *model*,
not from the transport (`FailingOnInstance` simulates the other half — a server that never
starts). See `test_a_quota_error_stops_the_batch_and_leaves_the_rest_eligible`.
"""

from __future__ import annotations

import inspect
import json
import time
from pathlib import Path
from types import SimpleNamespace

from eval.instances.registry import InstanceRecord
from eval.minting_driver.batch import run_mint
from eval.minting_driver.checkpoint import Checkpoint, load_checkpoint
from eval.minting_driver.fakes import FlakyModel, ScriptedModel
from eval.minting_driver.model import Done, ToolCall
from eval.minting_driver.resilience import QuotaExhausted, TransientExhausted
from eval.minting_driver.workspace import layout_for

#: An excerpt of the VERBATIM `reason` string the 2026-07-24 Stage-3 mint recorded for all
#: 56 burned instances (`eval/mint/s3/checkpoint.json`), kept short here because these tests
#: do not classify it — `tests/test_minting_driver_resilience.py:STAGE3_QUOTA_ERROR` holds
#: the full, character-exact fixture and is where classification is pinned. What matters at
#: THIS layer is only that whatever the provider said survives into the checkpoint, so the
#: operator reading the ledger tomorrow morning learns *when* it is worth trying again —
#: hence the `'retryDelay': '39043s'` tail (10h50m43s) is kept.
STAGE3_QUOTA_REASON = (
    "Error code: 429 - Quota exceeded for metric: generativelanguage.googleapis.com/"
    "generate_requests_per_model_per_day, limit: 250, model: gemini-3.1-pro. "
    "'status': 'RESOURCE_EXHAUSTED', 'retryDelay': '39043s'"
)


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

    The fake `trace-*.jsonl` is what the real `bridge_capture` moves — with no gated
    proxy running, nothing else would write one. Its one record carries a `seq` (0),
    because `run_mint` now appends the claim record to a captured session's trace and
    `append_claim_record` numbers it as `last seq + 1` — a seq-less line would read as
    a malformed capture and flip the instance to `failed`. Records the instances it
    prepared, in order, so a test can assert which instances were driven vs skipped.
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
                '{"v": 1, "kind": "connection_window", "phase": "open", '
                '"seq": 0, "t_in": "2026-07-22T00:00:00+00:00", '
                '"observation_point": "proxy"}\n',
                encoding="utf-8",
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


class FaultOnNthInstance(CountingModelFactory):
    """A `CountingModelFactory` whose Nth model raises `fault` on its first `propose_next`.

    The instance is selected by FACTORY CALL ORDER, which is exactly instance order among
    the non-skipped instances: `run_mint` builds one model per driven instance, in registry
    order (`batch.py:203`), and the factory is handed only the tool list — never the record
    — so call order is the only thing there is to key on. (`FailingOnInstance` can key off
    the instance id because a transport factory receives the env; a model factory does not.)

    Everything after the fault delegates to the ordinary `ScriptedModel` this factory would
    have built anyway, so a batch whose fault is contained keeps driving real sessions
    rather than silently degrading into a different script.
    """

    def __init__(
        self,
        fault: BaseException,
        *,
        on_call: int,
        script: list[ToolCall | Done] | None = None,
    ) -> None:
        super().__init__(script)
        self._fault = fault
        self._on_call = on_call

    def __call__(self, tools: object) -> ScriptedModel | FlakyModel:  # type: ignore[override]
        model = super().__call__(tools)
        if self.calls == self._on_call:
            return FlakyModel([self._fault], model)
        return model


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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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
        request_timeout=30.0,
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


# ---------------------------------------------------------------------------
# The quota circuit breaker
# ---------------------------------------------------------------------------


def _ten_records() -> list[InstanceRecord]:
    """A ten-instance registry — the smallest queue that makes "the rest" visible."""
    return [_record(f"octo__repo-{n}") for n in range(1, 11)]


def _drive(
    tmp_path: Path,
    records: list[InstanceRecord],
    *,
    prepare: StubPrepare,
    factory: CountingModelFactory,
    checkpoint_path: Path | None = None,
) -> object:
    """`run_mint` with the standard offline seams; the breaker tests vary only the fault.

    Factored out on purpose: these tests differ from one another ONLY in which exception
    the model raises and on which instance, so spelling out ten identical keyword arguments
    six times would bury the one line that matters in each.
    """
    return run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=checkpoint_path or (tmp_path / "ckpt.json"),
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
    )


def test_a_quota_error_stops_the_batch_and_leaves_the_rest_eligible(tmp_path: Path) -> None:
    """THE regression test for the 2026-07-24 Stage-3 loss of 56 instances of denominator.

    What happened: at 16:35:31 the mint hit Google's 250-requests-per-day cap on an early
    instance. `batch.py`'s single bare `except Exception` recorded the rejection `failed`
    and moved to the next instance, which hit the same wall — **56 remaining instances
    burned in 3m48s, one wasted request each, all recorded `failed`**. Nothing crashed;
    that is what made it lethal. `checkpoint.is_done` counts `failed` as done, so a resume
    would have skipped all 56 forever, and the denominator was gone. The provider's own
    `retryDelay` was 39043s (≈10h50m): no retry, at any backoff, could have helped. What
    was lost was the QUEUE.

    So the assertion that matters here is the one about instances 4–10, and it is
    deliberately `status(...) is None` — ABSENT from the ledger, not merely "not captured".
    A recorded-anything is a recorded disposition, and `is_done` is the resume rule; only
    absence keeps them eligible. `prepare` never being called for them proves no work was
    even attempted, which is the difference between a stop and a fast failure.
    """
    records = _ten_records()
    prepare = StubPrepare()
    factory = FaultOnNthInstance(
        QuotaExhausted(STAGE3_QUOTA_REASON, retry_after_seconds=39043.0), on_call=3
    )
    ckpt_path = tmp_path / "ckpt.json"

    checkpoint = _drive(
        tmp_path, records, prepare=prepare, factory=factory, checkpoint_path=ckpt_path
    )

    # The instances that ran before the cap keep their observations.
    assert checkpoint.status("octo__repo-1") == "captured"
    assert checkpoint.status("octo__repo-2") == "captured"
    # The instance the cap fired on produced NO observation — distinguishable from `failed`.
    assert checkpoint.status("octo__repo-3") == "no_observation"
    assert checkpoint.is_done("octo__repo-3") is False

    # The 56-instance defect, encoded: everything after the stop is ABSENT, not `failed`.
    for n in range(4, 11):
        instance_id = f"octo__repo-{n}"
        assert checkpoint.status(instance_id) is None, (
            f"{instance_id} was recorded; a recorded disposition is what stranded the "
            f"56 instances on 2026-07-24"
        )

    # No work was even attempted past the stop — not a request, not a checkout.
    assert prepare.prepared == ["octo__repo-1", "octo__repo-2", "octo__repo-3"]
    assert factory.calls == 3, "a model was built for an instance past the quota stop"

    # And the same is true of the DURABLE ledger, which is what a resume actually reads.
    persisted = load_checkpoint(ckpt_path)
    assert persisted.status("octo__repo-3") == "no_observation"
    assert persisted.is_done("octo__repo-3") is False
    assert [persisted.status(f"octo__repo-{n}") for n in range(4, 11)] == [None] * 7


def test_the_quota_stop_records_the_providers_own_retry_hint(tmp_path: Path) -> None:
    """The recorded reason carries whatever the provider said, verbatim.

    `retryDelay: 39043s` is the operator's entire plan for the rest of the day — it is the
    difference between "resume in a minute" and "resume tomorrow". Losing it to a tidy
    generic message would make the ledger unactionable.
    """
    records = _ten_records()
    factory = FaultOnNthInstance(
        QuotaExhausted(STAGE3_QUOTA_REASON, retry_after_seconds=39043.0), on_call=3
    )

    checkpoint = _drive(tmp_path, records, prepare=StubPrepare(), factory=factory)

    # Asserted on the no-observation entry specifically: the hint has to survive on the
    # disposition the breaker writes, not merely on some entry for that instance.
    assert checkpoint.status("octo__repo-3") == "no_observation"
    reason = str(checkpoint.reason("octo__repo-3"))
    assert "39043s" in reason
    assert "RESOURCE_EXHAUSTED" in reason


def test_resume_after_a_quota_stop_re_drives_from_the_stopped_instance(
    tmp_path: Path,
) -> None:
    """The recovery half of the headline: tomorrow's run picks up at 3 and finishes 4–10.

    Together with the test above this is the whole user outcome — a quota event costs ONE
    instance, not the remaining queue. Instances 1–2 are never re-driven (they produced
    observations), and 3 is, because it did not.
    """
    records = _ten_records()
    ckpt_path = tmp_path / "ckpt.json"

    _drive(
        tmp_path,
        records,
        prepare=StubPrepare(),
        factory=FaultOnNthInstance(QuotaExhausted(STAGE3_QUOTA_REASON), on_call=3),
        checkpoint_path=ckpt_path,
    )

    # The quota has since cleared: re-run the same registry against the same ledger.
    resumed_prepare = StubPrepare()
    resumed_factory = CountingModelFactory()
    checkpoint = _drive(
        tmp_path,
        records,
        prepare=resumed_prepare,
        factory=resumed_factory,
        checkpoint_path=ckpt_path,
    )

    assert resumed_prepare.prepared == [f"octo__repo-{n}" for n in range(3, 11)]
    assert resumed_factory.calls == 8
    assert all(
        checkpoint.status(f"octo__repo-{n}") == "captured" for n in range(1, 11)
    )
    # The re-armed instance keeps the record of what already happened to it — including,
    # since `run-accounting`, what that superseded attempt COST. The quota-rejected
    # request was really spent; dropping its accounting on re-arm would under-report the
    # cost of the number by exactly the attempts that failed.
    superseded = checkpoint.history("octo__repo-3")
    assert len(superseded) == 1
    assert superseded[0]["status"] == "no_observation"
    assert superseded[0]["reason"] == STAGE3_QUOTA_REASON
    assert "wall_clock_seconds" in superseded[0]["accounting"]


def test_an_instance_that_produced_an_observation_is_never_re_armed(
    tmp_path: Path,
) -> None:
    """The anti-re-roll contract, in code: only `no_observation` is re-drivable.

    `mint-execution/spec.md:52` puts "retrying instances to improve the number" out of
    scope, and `:90-92` says why: *"silently re-rolling until the number looks good is
    precisely the dishonesty this project exists to prevent."* So a `captured` instance is
    never re-spent on, and — just as important — a genuinely `failed` one is not either:
    it errored, that IS an observation, and quietly re-rolling it until it stops erroring
    would launder a broken instance into a clean denominator.

    The three seeded statuses are driven through ONE run so the discrimination is visible
    in a single assertion: two skipped, one re-armed.
    """
    ckpt_path = tmp_path / "ckpt.json"
    seed = Checkpoint()
    seed.record("octo__repo-1", "captured", trace_path="already/there.jsonl")
    seed.record("octo__repo-2", "failed", reason="a real ServerExited")
    seed.record("octo__repo-3", "no_observation", reason=STAGE3_QUOTA_REASON)
    seed.save(ckpt_path)

    records = [_record(f"octo__repo-{n}") for n in range(1, 5)]
    prepare = StubPrepare()
    factory = CountingModelFactory()

    checkpoint = _drive(
        tmp_path, records, prepare=prepare, factory=factory, checkpoint_path=ckpt_path
    )

    # Only the no-observation instance and the never-recorded one were driven.
    assert prepare.prepared == ["octo__repo-3", "octo__repo-4"]
    assert factory.calls == 2, "an instance that produced an observation was re-spent on"
    # The two prior observations survive untouched — same status, same reason, no history
    # entry (a history entry would mean they were re-recorded).
    assert checkpoint.status("octo__repo-1") == "captured"
    assert checkpoint.trace_path("octo__repo-1") == "already/there.jsonl"
    assert checkpoint.history("octo__repo-1") == []
    assert checkpoint.status("octo__repo-2") == "failed"
    assert checkpoint.reason("octo__repo-2") == "a real ServerExited"
    assert checkpoint.history("octo__repo-2") == []
    # And the re-armed one now carries an observation.
    assert checkpoint.status("octo__repo-3") == "captured"


def test_a_transient_exhausted_instance_is_re_armable_but_does_not_stop_the_batch(
    tmp_path: Path,
) -> None:
    """Spent retries cost one instance's observation, not the queue's remaining instances.

    `TransientExhausted` means the bounded retries in `RetryingModel` are gone and nothing
    was observed — so the instance is re-armable exactly like a quota stop — but unlike a
    quota cap there is no reason to believe the NEXT instance will fail too, so the batch
    continues. That asymmetry (same status, different control flow) is the whole reason
    the two handlers are separate.
    """
    records = _ten_records()
    prepare = StubPrepare()
    factory = FaultOnNthInstance(
        TransientExhausted("gave up after 3 attempt(s); last error: 503"), on_call=3
    )

    checkpoint = _drive(tmp_path, records, prepare=prepare, factory=factory)

    assert checkpoint.status("octo__repo-3") == "no_observation"
    assert checkpoint.is_done("octo__repo-3") is False
    assert "gave up after 3 attempt(s)" in str(checkpoint.reason("octo__repo-3"))
    # The queue is NOT burned: every later instance ran and produced an observation.
    assert prepare.prepared == [f"octo__repo-{n}" for n in range(1, 11)]
    assert all(checkpoint.status(f"octo__repo-{n}") == "captured" for n in range(4, 11))


def test_a_terminal_model_error_is_still_recorded_failed_and_the_batch_continues(
    tmp_path: Path,
) -> None:
    """Containment is not weakened: an ordinary exception behaves exactly as it did.

    The two new handlers sit AHEAD of the bare `except Exception`, and they catch two
    exception types nothing else raises. Everything else — a bad checkout, a `ServerExited`,
    a malformed reply — still lands `failed` with `str(exc)` as its reason and still lets
    the loop carry on. `failed` remains a real observation, so it is done for good.
    """
    records = _ten_records()
    prepare = StubPrepare()
    factory = FaultOnNthInstance(ValueError("could not decode the model's reply"), on_call=3)

    checkpoint = _drive(tmp_path, records, prepare=prepare, factory=factory)

    assert checkpoint.status("octo__repo-3") == "failed"
    assert checkpoint.reason("octo__repo-3") == "could not decode the model's reply"
    assert checkpoint.is_done("octo__repo-3") is True
    assert prepare.prepared == [f"octo__repo-{n}" for n in range(1, 11)]
    assert all(checkpoint.status(f"octo__repo-{n}") == "captured" for n in range(4, 11))


# ---------------------------------------------------------------------------
# `run-accounting`: what each instance cost
#
# `batch.py:201` called `run_session(model_factory(tools), ...)` — the model was built
# INLINE and never bound, so there was nowhere to read accounting from even once the
# clients recorded it. Binding it is the whole reason accounting is reachable (D2).
#
# The clock is INJECTED and lives in this layer (D5), and it is `time.monotonic`, not
# `time.time`: a 15-minute sympy instance must not report a negative duration because NTP
# stepped the wall clock underneath it.
# ---------------------------------------------------------------------------


class FakeClock:
    """A scripted monotonic clock: each read returns the next value, in order.

    Wall-clock is asserted against THIS, never against real elapsed time — a test that
    measured the real thing would be slow, flaky, and would not actually pin that the
    duration spans prep through bridge rather than just the model session.
    """

    def __init__(self, readings: list[float]) -> None:
        self._readings = list(readings)
        self.reads = 0

    def __call__(self) -> float:
        if self.reads >= len(self._readings):
            raise AssertionError(
                f"FakeClock read {self.reads + 1} time(s) but only "
                f"{len(self._readings)} reading(s) were scripted"
            )
        value = self._readings[self.reads]
        self.reads += 1
        return value


class AccountingModel:
    """A `Model` that also reports accounting, exactly as the real stack does.

    Shaped like `RetryingModel` wrapping a client: `request_count`/`retry_count` on the
    outside, `usage`/`model`/`provider` on `.inner`. Used instead of the real pair so
    these tests stay offline and free of SDK response fakes — what is under test here is
    that `run_mint` READS accounting off the model it bound, not how a client parses a
    response (that is `tests/test_minting_driver_clients_mapping.py`).
    """

    def __init__(
        self,
        script: list[ToolCall | Done],
        *,
        request_count: int,
        retry_count: int,
        usage: dict | None,
        model: str,
        provider: str,
    ) -> None:
        self._scripted = ScriptedModel(list(script))
        self.request_count = request_count
        self.retry_count = retry_count
        self.inner = SimpleNamespace(usage=usage, model=model, provider=provider)

    def propose_next(self, messages: list) -> ToolCall | Done:
        return self._scripted.propose_next(messages)


class AccountingModelFactory:
    """Builds one `AccountingModel` per instance, from a per-call list of accountings."""

    def __init__(self, accountings: list[dict]) -> None:
        self._accountings = list(accountings)
        self.calls = 0

    def __call__(self, tools: object) -> AccountingModel:
        spec = self._accountings[min(self.calls, len(self._accountings) - 1)]
        self.calls += 1
        return AccountingModel(
            [ToolCall(name="read_file"), Done(reason="done")],
            request_count=spec.get("request_count", 0),
            retry_count=spec.get("retry_count", 0),
            usage=spec.get("usage"),
            model=spec.get("model", "some-model"),
            provider=spec.get("provider", "openai-compat"),
        )


def _accounting_spec(**overrides: object) -> dict:
    spec = {
        "request_count": 3,
        "retry_count": 1,
        "usage": {"input_tokens": 900, "output_tokens": 120},
        "model": "gemini-flash-latest",
        "provider": "openai-compat",
    }
    spec.update(overrides)
    return spec


def test_wall_clock_is_measured_with_the_injected_clock(tmp_path: Path) -> None:
    """The duration spans PREP through BRIDGE — the instance's whole cost, not the
    model's.

    Workspace prep (a real `git worktree add` against a cached bare clone) and the bridge
    are real wall-clock a stop-loss has to account for; timing only the model session
    would under-report every instance by the part that does not depend on the provider.
    """
    clock = FakeClock([100.0, 112.5])

    checkpoint = run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory([_accounting_spec()]),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=clock,
    )

    assert checkpoint.accounting("octo__repo-1")["wall_clock_seconds"] == 12.5
    assert clock.reads == 2, "one read before prep and one after the bridge, per instance"


def test_the_batch_clock_is_monotonic_by_default(tmp_path: Path) -> None:
    """D5, asserted structurally: `time.monotonic`, never `time.time`.

    A wall clock that NTP steps mid-instance can produce a negative duration; a monotonic
    one cannot. The default is what a real mint runs with, so it is the one that matters.
    """
    assert inspect.signature(run_mint).parameters["clock"].default is time.monotonic


def test_model_requests_and_retries_are_recorded_from_the_model_that_ran(
    tmp_path: Path,
) -> None:
    """Read off the BOUND model object (D2) — there was previously nowhere to read from."""
    checkpoint = run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory(
            [_accounting_spec(request_count=5, retry_count=2)]
        ),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 1.0]),
    )

    accounting = checkpoint.accounting("octo__repo-1")
    assert accounting["model_requests"] == 5
    assert accounting["retry_count"] == 2


def test_tokens_are_recorded_when_reported_and_ABSENT_when_not(tmp_path: Path) -> None:
    """**The absent-not-zero test, at the ledger.**

    Instance 1's provider reports usage; instance 2's does not. The second entry must have
    NO token keys at all — not `0`. `claude -p --output-format json` may well be a provider
    that reports nothing, and a fabricated zero would put an invented measurement into the
    published cost of the number.
    """
    checkpoint = run_mint(
        [_record("octo__repo-1"), _record("octo__repo-2")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory(
            [
                _accounting_spec(usage={"input_tokens": 900, "output_tokens": 120}),
                _accounting_spec(usage=None),
            ]
        ),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 1.0, 1.0, 3.0]),
    )

    reported = checkpoint.accounting("octo__repo-1")
    assert reported["input_tokens"] == 900
    assert reported["output_tokens"] == 120

    unreported = checkpoint.accounting("octo__repo-2")
    assert "input_tokens" not in unreported
    assert "output_tokens" not in unreported
    # The rest of the accounting is still there — absent tokens are not absent accounting.
    assert unreported["model_requests"] == 3


def test_model_and_provider_are_recorded_per_instance(tmp_path: Path) -> None:
    """Provenance per instance, not per batch: a mint may span two models.

    The 12 banked instances ran on one model and the remainder will not, so the published
    number must be able to name which model minted which instance.
    """
    checkpoint = run_mint(
        [_record("octo__repo-1"), _record("octo__repo-2")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory(
            [
                _accounting_spec(model="gemini-3.1-pro-preview", provider="openai-compat"),
                _accounting_spec(model="claude-x", provider="anthropic"),
            ]
        ),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 1.0, 1.0, 3.0]),
    )

    assert checkpoint.accounting("octo__repo-1")["model"] == "gemini-3.1-pro-preview"
    assert checkpoint.accounting("octo__repo-1")["provider"] == "openai-compat"
    assert checkpoint.accounting("octo__repo-2")["model"] == "claude-x"
    assert checkpoint.accounting("octo__repo-2")["provider"] == "anthropic"


def test_accounting_is_recorded_on_a_no_observation_instance_too(tmp_path: Path) -> None:
    """A quota-stopped instance still consumed requests — so its cost is still recorded.

    This is the half that is easy to leave out and expensive to get wrong: the 2026-07-24
    run spent one real request on each of 56 instances and produced no observation for any
    of them. A stop-loss blind to those attempts under-counts spend by exactly the failures
    it exists to notice.
    """
    records = _ten_records()
    factory = FaultOnNthInstance(
        QuotaExhausted(STAGE3_QUOTA_REASON, retry_after_seconds=39043.0), on_call=1
    )

    checkpoint = run_mint(
        records,
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=factory,
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([10.0, 14.0]),
    )

    assert checkpoint.status("octo__repo-1") == "no_observation"
    assert checkpoint.accounting("octo__repo-1")["wall_clock_seconds"] == 4.0


def test_accounting_is_recorded_on_a_failed_instance_too(tmp_path: Path) -> None:
    """A `failed` instance spent wall-clock (and possibly requests) before it errored."""
    checkpoint = run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=FailingOnInstance("octo__repo-1"),
        discover_tools=lambda cmd: [],
        clock=FakeClock([100.0, 101.5]),
    )

    assert checkpoint.status("octo__repo-1") == "failed"
    assert checkpoint.accounting("octo__repo-1")["wall_clock_seconds"] == 1.5


def test_an_instance_that_died_before_any_model_call_records_zero_requests(
    tmp_path: Path,
) -> None:
    """Prep failed, so no model was ever built: `model_requests` is a measured 0.

    Distinct from the absent-token case on purpose. Nobody made a request, and we KNOW
    nobody did — that is a measurement. What we do not know (which model, what tokens)
    stays absent.
    """

    def exploding_prepare(record: InstanceRecord, *, root: object, clones_dir: object):
        raise RuntimeError("git checkout failed")

    checkpoint = run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=exploding_prepare,
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([5.0, 5.25]),
    )

    accounting = checkpoint.accounting("octo__repo-1")
    assert accounting["model_requests"] == 0
    assert accounting["retry_count"] == 0
    assert accounting["wall_clock_seconds"] == 0.25
    assert "model" not in accounting
    assert "input_tokens" not in accounting


def test_accounting_survives_the_save_load_round_trip(tmp_path: Path) -> None:
    """Through the DURABLE ledger — the `_validate_entry` fixed-key-set trap, end to end.

    `run_mint` saves after every disposition, so what a later resume (and the summary)
    reads is the file, not the in-memory object.
    """
    ckpt_path = tmp_path / "ckpt.json"

    run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory([_accounting_spec()]),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=ckpt_path,
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 7.0]),
    )

    persisted = load_checkpoint(ckpt_path).accounting("octo__repo-1")
    assert persisted == {
        "wall_clock_seconds": 7.0,
        "model_requests": 3,
        "retry_count": 1,
        "input_tokens": 900,
        "output_tokens": 120,
        "model": "gemini-flash-latest",
        "provider": "openai-compat",
    }


def test_a_model_that_reports_nothing_still_yields_an_honest_accounting(
    tmp_path: Path,
) -> None:
    """A plain `ScriptedModel` exposes no counters, so those fields are ABSENT.

    Not zero: this model was called, so "0 requests" would be false. Wall-clock is still
    recorded, because the batch layer measured that itself.
    """
    checkpoint = run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=CountingModelFactory(),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=tmp_path / "ckpt.json",
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 2.0]),
    )

    accounting = checkpoint.accounting("octo__repo-1")
    assert accounting == {"wall_clock_seconds": 2.0}


def test_no_dollar_figure_is_ever_recorded(tmp_path: Path) -> None:
    """D4 at the batch boundary: nothing money-shaped reaches the ledger.

    Under a subscription there is no per-token price. Asserted here as well as in
    `tests/test_minting_driver_checkpoint.py` because this is the layer that BUILDS the
    accounting dict, and a helpful "estimated cost" added here is the change this test
    exists to fail.
    """
    ckpt_path = tmp_path / "ckpt.json"

    run_mint(
        [_record("octo__repo-1")],
        root=tmp_path / "mint",
        clones_dir=tmp_path / "clones",
        model_factory=AccountingModelFactory([_accounting_spec()]),
        build_server_command=lambda layout: ["node", "server.js"],
        checkpoint_path=ckpt_path,
        request_timeout=30.0,
        max_steps=8,
        system="sys",
        prepare=StubPrepare(),
        transport_factory=lambda cmd, env: OkTransport(),
        discover_tools=lambda cmd: [],
        clock=FakeClock([0.0, 7.0]),
    )

    # Asserted on the accounting record itself, not on the whole file: `tmp_path` embeds
    # the test's own name, so a whole-file scan for "dollar" would match this test.
    accounting = load_checkpoint(ckpt_path).accounting("octo__repo-1")
    serialized = json.dumps(accounting).lower()
    assert "$" not in serialized
    for word in ("cost", "price", "usd", "dollar"):
        assert word not in serialized
