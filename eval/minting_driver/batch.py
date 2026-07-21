"""The sequential batch driver: prep → drive → bridge → checkpoint, one instance at a time.

`run_mint` is the harness that turns a registry of `InstanceRecord`s into a directory of
bridged captures `belay phase0 run` can score. For each instance, in registry order, it:

1. skips it if the resume checkpoint already records a disposition (`captured` or `failed`);
2. else materializes its workspace at `base_commit` (`prepare`, default `prepare_workspace`);
3. builds THIS instance's raw server command from its layout (`build_server_command`), then
   the gated env (`gated_env`) and the proxied argv (`proxy_command`);
4. drives ONE `run_session` (a fresh model per instance — no conversation state bleed);
5. bridges the resulting capture into this call's single batch dir (`bridge_capture`);
6. records `captured` and saves the checkpoint.

**Sequential, one call in flight, errors contained — never an agent framework.** There is no
planning, no memory, no retry-with-reflection, no threads. The one-`tools/call`-in-flight
invariant is inherited wholesale from `run_task`'s control flow (`loop.py`); driving instances
one after another in a plain `for` loop keeps it batch-wide. A per-instance `try/except`
records a failing instance `failed` (with the exception message) and CONTINUES — one
`ServerExited` never aborts the mint, mirroring `run_batch`'s `ERRORED` discipline
(`src/belay/phase0/runner.py:123-135`). Retrying a *failed instance* is a later, explicit
choice; making the *agent* smarter is out of scope (guardrail #1).

**One `run_mint` call is single-server and single-batch-dir.** `build_server_command` names one
server; the batch dir is `root/"batch"`, a pure function of the REQUIRED, per-call-distinct
`root`. The caller runs the mint once per server (filesystem, shell) into two different roots,
so two servers can never mix into one trace dir — a structural invariant, not a convention.

**Why a `build_server_command(layout)` seam, not a constant command.** The pinned filesystem
server enforces its OWN allowed-directory boundary, passed as an argv element:
`filesystem_server_command(allowed_dir)` returns `["node", "<entrypoint>", str(allowed_dir)]`
(`servers.py`). Every instance has a DIFFERENT `layout.work_dir`, so a single constant command
would point every instance after the first at the first instance's workspace; the server then
rejects paths outside its allowed dir, the model's edits fail, and those instances yield no
verifiable turns (the Seatbelt scope does not save this — the MCP server rejects the path
before the OS sandbox is consulted). The seam produces THIS instance's raw command from its
prepared layout: the caller passes `lambda layout: filesystem_server_command(layout.work_dir)`
for the fs batch and `lambda layout: shell_server_command()` (which takes no per-instance arg)
for the shell batch — both handled uniformly.

**The tool-discovery seam.** `run_task` fetches `tools/list` but discards it, yet a real
`Model` needs the tool list at construction. Rather than hardcode a second transport into the
core flow, discovery is an injectable seam (`discover_tools`, default `_discover_tools`): a
short-lived UNPROXIED handshake against the raw command, run ONCE (the tool list is constant
across the batch for a given server), exactly as the single-instance smoke does it
(`tests/test_minting_driver_smoke.py`'s `_fetch_tools_list`). Because the raw command now
depends on the per-instance layout, discovery runs on the first *successfully-prepped*
instance's command, and it lives INSIDE the per-instance `try/except`: if discovery fails it
fails only that instance (recorded `failed`) and the loop tries the next, so one bad first
instance never aborts the whole mint. Tests inject a trivial stub and a `model_factory` that
ignores the tools, so CI never spawns a server. An integrator wanting per-instance discovery
overrides the seam rather than editing this module.

Eval-only. Touches nothing under `src/belay/`; composes `bridge`, `checkpoint`, `workspace`,
`session`, `capture`, and the instance registry, and changes none of them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, Sequence, Union

from eval.instances.registry import InstanceRecord
from eval.minting_driver.bridge import bridge_capture
from eval.minting_driver.capture import gated_env, proxy_command
from eval.minting_driver.checkpoint import Checkpoint, load_checkpoint
from eval.minting_driver.model import Model
from eval.minting_driver.session import TransportFactory, run_session
from eval.minting_driver.workspace import WorkspaceLayout, prepare_workspace

StrPath = Union[str, "os.PathLike[str]"]

#: Builds one `Model` for one instance, given that instance's tool list. Called ONCE PER
#: INSTANCE so no conversation state leaks between instances (`anthropic_client.py:84-87`).
ModelFactory = Callable[[list[dict]], Model]

#: Fetches the downstream server's `tools/list`, given the RAW (unproxied) server command.
#: The injectable discovery seam — see the module docstring.
DiscoverTools = Callable[[list[str]], list[dict]]

#: Builds THIS instance's RAW (unproxied) server command from its prepared layout. The seam
#: that carries the per-instance workspace boundary into the filesystem server's argv; see
#: the module docstring. Callers pass `lambda layout: filesystem_server_command(layout.work_dir)`
#: (fs) or `lambda layout: shell_server_command()` (shell — no per-instance arg).
BuildServerCommand = Callable[[WorkspaceLayout], list[str]]

#: Materializes one instance's workspace; default `prepare_workspace`. Injected in tests so
#: no git runs. Kept as `Callable[..., WorkspaceLayout]` because the default carries an extra
#: `runner=` seam of its own.
PrepareWorkspace = Callable[..., WorkspaceLayout]


def _discover_tools(server_command: list[str]) -> list[dict]:
    """A short-lived, UNPROXIED MCP handshake purely to read `tools/list`.

    Mirrors the single-instance smoke's `_fetch_tools_list`: open a raw `StdioMcp` straight to
    the downstream server, `initialize` → `notifications/initialized` → `tools/list`, return
    the tool list, and always close. This is the default second transport; it is deliberately
    kept behind the `discover_tools` seam so tests never reach it. Imports are lazy so this
    module imports with no `subprocess`/server dependency in a pure-fakes environment.
    """
    from eval.minting_driver.mcp import (
        MonotonicIds,
        initialize,
        initialized,
        tools_list,
    )
    from eval.minting_driver.transport import StdioMcp

    transport = StdioMcp(server_command, dict(os.environ))
    try:
        next_id = MonotonicIds()
        transport.request(initialize(next_id()))
        transport.notify(initialized())
        reply = transport.request(tools_list(next_id()))
        result = reply.get("result", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return list(tools)
    finally:
        transport.close()


def run_mint(
    records: Sequence[InstanceRecord],
    *,
    root: StrPath,
    clones_dir: StrPath,
    model_factory: ModelFactory,
    build_server_command: BuildServerCommand,
    checkpoint_path: StrPath,
    request_timeout: Optional[float],
    max_steps: int,
    system: str,
    prepare: PrepareWorkspace = prepare_workspace,
    transport_factory: Optional[TransportFactory] = None,
    discover_tools: DiscoverTools = _discover_tools,
) -> Checkpoint:
    """Drive `records` sequentially through the gated proxy, one instance at a time.

    Loads the resume checkpoint at `checkpoint_path` (fail-closed; absent means first run),
    then for each instance in registry order: skip if already done; else prep the workspace,
    build THIS instance's raw server command from its layout (`build_server_command`), discover
    the tool list once (on the first successfully-prepped instance), build the gated env +
    proxied argv, run one `run_session` with a FRESH model, bridge the capture into
    `root/"batch"`, and record `captured`. Any exception in that per-instance body — a bad
    checkout, a discovery failure, a `ServerExited`, a bridge error — is recorded `failed`
    (with the reason) and the loop continues; discovery lives inside the guard so one bad first
    instance never aborts the mint. Returns the final in-memory `Checkpoint` (also persisted
    after every recorded disposition).

    `build_server_command` names ONE raw server (per-instance workspace baked into its argv);
    `root/"batch"` is this call's single batch dir. Run once per server into distinct roots to
    keep two servers from ever sharing a trace dir. `transport_factory` (default: real
    `StdioMcp`) and `discover_tools` are injectable seams so tests exercise the real
    `run_session`/`bridge` path with no subprocess, no git, no spend.
    """
    checkpoint = load_checkpoint(checkpoint_path)
    batch_dir = Path(root) / "batch"

    # The tool list is constant across the batch, so it is discovered once. But the raw command
    # now depends on the per-instance layout, so discovery runs on the first successfully-prepped
    # instance's command (a full resume drives nothing and spawns no discovery server). `None` is
    # the "not yet discovered" sentinel — an empty list is a valid, distinct discovered result.
    tools: Optional[list[dict]] = None

    for record in records:
        if checkpoint.is_done(record.instance_id):
            continue

        try:
            layout = prepare(record, root=root, clones_dir=clones_dir)
            # This instance's raw command carries its own workspace boundary (fs server) or is
            # workspace-independent (shell server) — either way, built from THIS layout.
            raw_command = build_server_command(layout)
            if tools is None:
                # Discover on the first prepped instance's command. Inside the try/except so a
                # discovery failure fails only this instance and the loop tries the next.
                tools = list(discover_tools(raw_command))
            env = gated_env(
                trace_dir=layout.trace_dir,
                scope=str(layout.work_dir),
                snapshot_dir=layout.snapshot_dir,
            )
            run_session(
                model_factory(tools),
                server_command=proxy_command(raw_command),
                env=env,
                system=system,
                task=record.task_string,
                max_steps=max_steps,
                transport_factory=transport_factory,
                request_timeout=request_timeout,
            )
            trace_path = bridge_capture(
                instance_id=record.instance_id,
                trace_dir=layout.trace_dir,
                snapshot_dir=layout.snapshot_dir,
                batch_dir=batch_dir,
            )
            checkpoint.record(record.instance_id, "captured", trace_path=str(trace_path))
            checkpoint.save(checkpoint_path)
        except Exception as exc:
            # Per-instance containment: one instance failing (a bad checkout, a ServerExited,
            # a bridge error) records `failed` and moves on. The mint of dozens of instances
            # must not die on instance #37; it must SAY #37 broke and keep going.
            checkpoint.record(record.instance_id, "failed", reason=str(exc))
            checkpoint.save(checkpoint_path)
            continue

    return checkpoint


__all__ = [
    "BuildServerCommand",
    "DiscoverTools",
    "ModelFactory",
    "PrepareWorkspace",
    "run_mint",
]
