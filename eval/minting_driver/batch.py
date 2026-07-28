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

**But containment is wrong for one class of error, and that mistake cost 56 instances.** On
2026-07-24 a Stage-3 mint hit a 250-requests-per-day cap on instance 3 of 68; the bare
`except Exception` recorded it `failed` and moved on, and the remaining 56 were fed into the
same wall in 3m48s — one wasted request each, all `failed`, and `checkpoint.is_done` counts
`failed` as done, so a resume would have skipped every one of them forever. Nothing crashed.
So two handlers now sit AHEAD of that bare `except` (`resilience.py` decides which errors
reach them):

- `QuotaExhausted` — the wait is hours, so the batch **stops**. The instance records
  `no_observation`; every later instance stays **absent** from the checkpoint and therefore
  still eligible. Containment is exactly backwards here: continuing is what destroys the
  denominator.
- `TransientExhausted` — bounded retries were spent and nothing was observed, so the
  instance records `no_observation` (re-armable) and the batch **continues**, because the
  next instance has no reason to fail.

Everything else is unchanged, byte for byte: `failed`, with `str(exc)` as the reason, and on
to the next instance.

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

**Every terminal disposition also records what the instance COST** (`run-accounting`).
Nothing recorded that before: the model was built inline at the `run_session` call and
never bound, so there was nowhere to read accounting from even once the clients kept it,
and `run_session`'s return value was discarded. Now the model is bound, and each recorded
disposition carries `{wall_clock_seconds, model_requests, retry_count, input_tokens,
output_tokens, model, provider}`. Three rules travel with it:

- **The clock is INJECTED and lives here** (`clock`, default `time.monotonic`), never in
  `entrypoint.py`, whose stated design rule is *"No clock, no randomness"*. It is
  `monotonic` rather than `time.time` so an NTP step during a 15-minute instance cannot
  produce a negative duration. It is started before `prepare` and read again after
  `bridge_capture`: workspace prep and the bridge are real wall-clock a stop-loss has to
  account for, so timing only the model session would under-report every instance.
- **Absent is not zero.** A field nothing reported is OMITTED, never written as `0` — the
  same contract as `UNVERIFIED` never rendering as `PASS`. The one measured zero is
  `model_requests` when no model object was ever built (prep failed): nobody made a
  request, and we know it.
- **Accounting is recorded on `captured`, `failed` AND `no_observation` alike.** A
  quota-stopped instance still consumed requests — the 2026-07-24 run spent one on each of
  56 instances and observed nothing — so a stop-loss blind to failed attempts under-counts
  spend by exactly the failures it exists to notice.

**No dollar amount is computed or stored.** Under a subscription there is no per-token
price; inventing one would be fabricated precision. Requests + tokens + wall-clock only.

Eval-only. Touches nothing under `src/belay/`; composes `bridge`, `checkpoint`, `workspace`,
`session`, `capture`, and the instance registry, and changes none of them.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, Union

from eval.instances.registry import InstanceRecord
from eval.minting_driver.bridge import bridge_capture
from eval.minting_driver.capture import gated_env, proxy_command
from eval.minting_driver.checkpoint import Checkpoint, load_checkpoint
from eval.minting_driver.model import Model
from eval.minting_driver.resilience import QuotaExhausted, TransientExhausted
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

#: Reads a monotonically-increasing number of seconds. The ONLY clock in the mint's
#: config/drive path, injected so wall-clock is asserted against a scripted fake rather
#: than against real elapsed time. See the module docstring for why it lives here and why
#: it is `monotonic`.
Clock = Callable[[], float]

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


def _int_or_none(value: object) -> Optional[int]:
    """A duck-typed counter -> `int`, or `None` if it is not one.

    `bool` is excluded despite subclassing `int` (a flag is not a count), mirroring
    `resilience._coerce_seconds` and the clients' `_token_count`. Anything unusable reads
    as absent, so a model object with a surprising attribute yields a missing field rather
    than a wrong one.
    """
    if isinstance(value, bool) or value is None:
        return None
    return value if isinstance(value, int) else None


def _accounting_for(model: Optional[Model], wall_clock_seconds: float) -> dict:
    """What this instance cost, read DUCK-TYPED off the model that actually ran.

    Duck-typed on purpose: `run_mint` must stay usable with any `Model` — the protocol has
    exactly one method (D1), and adding a second so accounting could be "properly" fetched
    would make every implementation, fakes included, owe an accounting surface it cannot
    fill in honestly. So a model that reports nothing yields an accounting with nothing but
    the wall-clock this layer measured itself, which is the truthful answer.

    `request_count` / `retry_count` are read off the OUTERMOST object (`RetryingModel`
    counts every attempt, retries included); token usage and provenance come from
    `.inner`, the concrete client that is the only layer that sees `response.usage`.

    **A field is omitted, never zeroed.** The single exception is `model` being `None` —
    prep failed before any model was built, so `model_requests: 0` is a measurement, not a
    guess. What is still unknown then (which model, what tokens) stays absent.
    """
    accounting: dict = {"wall_clock_seconds": wall_clock_seconds}

    if model is None:
        accounting["model_requests"] = 0
        accounting["retry_count"] = 0
        return accounting

    for recorded_field, attribute in (
        ("model_requests", "request_count"),
        ("retry_count", "retry_count"),
    ):
        count = _int_or_none(getattr(model, attribute, None))
        if count is not None:
            accounting[recorded_field] = count

    # `getattr(model, "inner", model)` unwraps `RetryingModel` without importing it and
    # without the caller having to know whether the breaker is installed: an unwrapped
    # client is its own accounting source.
    client = getattr(model, "inner", model)

    usage = getattr(client, "usage", None)
    if isinstance(usage, dict):
        # Only the keys the client actually put there — a client that reported no usage
        # exposes `None`, and one that reported half exposes half. Neither becomes a zero.
        for token_field in ("input_tokens", "output_tokens"):
            count = _int_or_none(usage.get(token_field))
            if count is not None:
                accounting[token_field] = count

    for provenance_field in ("model", "provider"):
        value = getattr(client, provenance_field, None)
        if isinstance(value, str) and value:
            accounting[provenance_field] = value

    return accounting


def run_mint(
    records: Sequence[InstanceRecord],
    *,
    root: StrPath,
    clones_dir: StrPath,
    model_factory: ModelFactory,
    build_server_command: BuildServerCommand,
    checkpoint_path: StrPath,
    request_timeout: float,
    max_steps: int,
    system: str,
    prepare: PrepareWorkspace = prepare_workspace,
    transport_factory: Optional[TransportFactory] = None,
    discover_tools: DiscoverTools = _discover_tools,
    clock: Clock = time.monotonic,
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

    **Two errors are not contained that way, because containing them is what burned the
    queue on 2026-07-24.** A `QuotaExhausted` (a provider day/period cap, whose retry hint
    was 39043s) records the current instance `no_observation` and **STOPS THE LOOP**: the
    remaining records are never touched, so they stay absent from the checkpoint and remain
    eligible on the next run — a quota event costs one instance, not the rest of the queue.
    A `TransientExhausted` (bounded retries spent, nothing observed) records the same
    `no_observation` — re-armable, unlike `failed` — but the loop continues. Neither is a
    re-roll: `is_done` is true for `captured` and `failed`, so an instance that produced an
    observation is never re-driven, here or on any later resume.

    A short return is therefore normal and is NOT an error: the returned `Checkpoint` simply
    has fewer entries than `records`, and that visible absence is the honest signal. The
    signature and return type are unchanged.

    Every recorded disposition — `captured`, `failed` and `no_observation` alike — carries
    that instance's **accounting**: wall-clock measured with the injected `clock` from
    before `prepare` to after `bridge_capture`, plus whatever the bound model reports
    (requests, retries, tokens, model, provider). Fields nothing reported are OMITTED, not
    zeroed. `clock` defaults to `time.monotonic` so an NTP step mid-instance cannot make a
    duration negative, and it lives here rather than in `entrypoint.py`, whose design rule
    is "no clock, no randomness".

    `build_server_command` names ONE raw server (per-instance workspace baked into its argv);
    `root/"batch"` is this call's single batch dir. Run once per server into distinct roots to
    keep two servers from ever sharing a trace dir. `transport_factory` (default: real
    `StdioMcp`) and `discover_tools` are injectable seams so tests exercise the real
    `run_session`/`bridge` path with no subprocess, no git, no spend.
    """
    # `None` is NOT "no timeout": it falls through `run_session` -> `run_task` ->
    # `transport.request`'s `DEFAULT_TIMEOUT = 10.0`, silently capping every live turn at
    # ten seconds — too tight for a model turn plus a cold `node` start under Seatbelt,
    # so an unconfigured batch would record `ReplyTimeout` for every instance and read as
    # INSTRUMENT SUSPECT. Refused here, for every caller, not just at the entry point.
    if request_timeout is None or isinstance(request_timeout, bool) or not isinstance(
        request_timeout, (int, float)
    ):
        raise ValueError(
            f"run_mint: request_timeout must be a positive number of seconds, got "
            f"{request_timeout!r}. `None` silently means the transport's 10s default."
        )
    if request_timeout <= 0:
        raise ValueError(
            f"run_mint: request_timeout must be > 0 seconds, got {request_timeout!r}"
        )

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

        # Started BEFORE `prepare`: a real `git worktree add` against a cached bare clone
        # is wall-clock the operator pays for whether or not the model is ever reached.
        started = clock()
        # Bound so it is still in scope in the handlers below — an instance that failed
        # mid-session still made the requests it made. `None` until built, which is what
        # distinguishes "no model existed" (a measured 0 requests) from "the model
        # reported nothing" (absent).
        model: Optional[Model] = None

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
            # BOUND, not inline. `run_session(model_factory(tools), ...)` constructed the
            # model and discarded it, so the object that knows what this instance cost was
            # unreachable the moment the call returned — which is why no mint has ever
            # reported a spend figure. Still a FRESH model per instance: the binding is
            # per-iteration, so no conversation state bleeds between instances.
            model = model_factory(tools)
            run_session(
                model,
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
            checkpoint.record(
                record.instance_id,
                "captured",
                trace_path=str(trace_path),
                accounting=_accounting_for(model, clock() - started),
            )
            checkpoint.save(checkpoint_path)
        except QuotaExhausted as exc:
            # Provider quota/period cap. The wait is HOURS (the observed retryDelay was
            # 39043s, ~10h50m), so retrying is useless and CONTINUING is actively harmful:
            # on 2026-07-24 the Stage-3 mint hit a daily cap on instance 3 of 68 and then
            # fed the remaining 56 into the same wall in 3m48s, burning one request each
            # and recording every one `failed` -- which `is_done` then treated as done,
            # permanently. Nothing crashed; the denominator simply vanished.
            #
            # So: record THIS instance as having produced no observation, and STOP. The
            # `break` is the whole fix. Every later record stays ABSENT from the checkpoint
            # -- not `failed`, not anything -- and therefore still eligible on the next
            # run. Do not "improve" this into a `continue` with a nicer status: any
            # recorded disposition is a disposition, and the resume rule reads the ledger.
            #
            # The accounting is recorded too: the rejected request was still SPENT. Each
            # of the 56 burned instances cost one real request and produced nothing, and a
            # stop-loss blind to those attempts under-counts by exactly the failures it
            # exists to notice.
            checkpoint.record(
                record.instance_id,
                "no_observation",
                reason=str(exc),
                accounting=_accounting_for(model, clock() - started),
            )
            checkpoint.save(checkpoint_path)
            break
        except TransientExhausted as exc:
            # Retries were spent and nothing was observed. Re-armable (unlike `failed`),
            # but not a reason to stop the batch. Its spent attempts are still recorded.
            checkpoint.record(
                record.instance_id,
                "no_observation",
                reason=str(exc),
                accounting=_accounting_for(model, clock() - started),
            )
            checkpoint.save(checkpoint_path)
            continue
        except Exception as exc:
            # Per-instance containment: one instance failing (a bad checkout, a ServerExited,
            # a bridge error) records `failed` and moves on. The mint of dozens of instances
            # must not die on instance #37; it must SAY #37 broke and keep going. It cost
            # wall-clock (and possibly requests) on the way to failing, so that is
            # recorded too.
            checkpoint.record(
                record.instance_id,
                "failed",
                reason=str(exc),
                accounting=_accounting_for(model, clock() - started),
            )
            checkpoint.save(checkpoint_path)
            continue

    return checkpoint


__all__ = [
    "BuildServerCommand",
    "Clock",
    "DiscoverTools",
    "ModelFactory",
    "PrepareWorkspace",
    "run_mint",
]
