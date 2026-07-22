"""The committed mint entry point: config, provider selection, credentials, model wiring.

`run_mint` (`batch.py`) is real and correct, but until now it was invoked **only from
tests with fakes** — Stage 1 ran from an uncommitted scratchpad script that no longer
exists, so the Stage-1 result could not be reproduced from the repo. This module is the
committed program that calls it.

**Eval-only.** Nothing here is a product surface and none of it may become a `belay`
subcommand (`eval/README.md`, `CLAUDE.md` guardrail #1). It stays thin and sequential:
no planning, no memory, no retry-with-reflection.

Two design rules carry most of the weight, and both exist because getting them wrong
produces an **empty mint**, which `belay phase0 run` reads as `INSTRUMENT SUSPECT` — a
*fake* PIVOT caused by operator setup rather than by the agents under measurement:

1. **The provider is an argument, never an environment sniff.** No branch in this module
   looks at whether some vendor key happens to be exported. A key in the operator's shell
   must not be able to change which model mints, or the published number names the wrong
   model. Environment variables supply *credentials only*.
2. **Credentials are required by name, and never substituted.**
   `LocalOpenAICompatModel` falls back to `LOCAL_SENTINEL_API_KEY` when `OPENAI_API_KEY`
   is unset (`clients/local_client.py`) — correct for Ollama, and wrong for a hosted
   endpoint, where it 401s on the first call of every instance. This module resolves
   both `OPENAI_BASE_URL` and `OPENAI_API_KEY` explicitly and passes them in, so the
   sentinel path is unreachable from the mint.

The third is the timeout: `None` used to fall through to `transport.DEFAULT_TIMEOUT =
10.0`, far too tight for a live model turn plus a cold `node` start under Seatbelt. Here
`request_timeout` is a `float` that cannot be `None` and cannot be non-positive, and
`run_mint` now enforces the same thing for every other caller.

Pure: no filesystem, no subprocess, no network in this module's config/credential/model
layer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from eval.instances.registry import InstanceRecord, load_registry
from eval.minting_driver.batch import (
    BuildServerCommand,
    DiscoverTools,
    ModelFactory,
    PrepareWorkspace,
    run_mint,
)
from eval.minting_driver.checkpoint import Checkpoint
from eval.minting_driver.servers import (
    filesystem_server_command,
    resolve_server_entrypoint,
)
from eval.minting_driver.session import TransportFactory
from eval.minting_driver.workspace import WorkspaceLayout, prepare_workspace

StrPath = Union[str, "os.PathLike[str]"]

#: The mint's request timeout, in seconds. Deliberately NOT
#: `eval.minting_driver.transport.DEFAULT_TIMEOUT` (10.0): a live model turn plus a cold
#: `node` start inside a Seatbelt-gated proxy does not fit in ten seconds, and a batch
#: that inherits that ceiling records `ReplyTimeout` failures for every instance.
DEFAULT_REQUEST_TIMEOUT = 120.0

#: The decided Phase-0 provider/model (`docs/planning/phase0-live-mint/prd.md`). Both are
#: overridable per run, but neither is ever inferred from the environment.
DEFAULT_PROVIDER = "openai-compat"
DEFAULT_MODEL = "gemini-flash-latest"

#: Every provider the entry point knows how to build. A value outside this set is a
#: config error, not a silent fallback.
PROVIDERS = ("openai-compat", "anthropic")

#: Bounded so a misbehaving model cannot loop forever on one instance; generous enough
#: for read -> edit -> read-back on a real repository.
DEFAULT_MAX_STEPS = 12

#: Where the instance selection lives by default. The file is the `instance-pool`
#: aspect's deliverable; its absence must read as "that aspect has not landed / you
#: passed the wrong path", never as an empty mint.
DEFAULT_REGISTRY_PATH = Path("eval/instances/selected.json")

#: Cached bare clones, reused across every instance of a repo.
DEFAULT_CLONES_DIR = Path("eval/clones")

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent. You have access to filesystem tools (read_file, "
    "write_file, edit_file, and related tools) exposed over MCP. Use them to make "
    "exactly the change requested, then confirm the change is present by reading the "
    "file back. When the change is made and confirmed, reply with a short summary and "
    "do not call any more tools."
)

#: The environment variables that carry OpenAI-compatible credentials. Named as data so
#: the error message and the resolution cannot drift apart.
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

#: The literal `belay.replay.engine.WORKSPACE_PLACEHOLDER`, restated rather than imported:
#: `eval/` may not import `belay` (guardrail #1 — this is not a product surface, and the
#: driver must import with `belay` absent). A test pins the two together so they cannot
#: drift silently. Written as ONE argument of the verify command, it makes a single static
#: `--server` command correct for a heterogeneous batch: replay substitutes each trace's
#: OWN recorded `source_root`, which beats restating a root the trace already carries.
WORKSPACE_PLACEHOLDER = "{workspace}"

#: Where the printed verify command writes its run ledger / reads and ingests its corpus.
#: These match `belay phase0 run`'s own documented defaults; they are here so the printed
#: command is copy-pasteable rather than a template with holes in it.
DEFAULT_LEDGER_PATH = Path("runs/phase0.json")
DEFAULT_CORPUS_DIR = Path("corpus/local")


class MintConfigError(ValueError):
    """A mint configuration value is missing, malformed, or out of range."""


class MissingCredentialsError(RuntimeError):
    """The selected provider's credentials are absent from the environment.

    Raised BEFORE any instance is prepped or driven, and it names the variables. The
    alternative — a silent sentinel key — is one 401 per instance and an empty mint.
    """


class RegistryNotFoundError(MintConfigError):
    """The instance registry file does not exist.

    Named, and naming the aspect that produces the file, because the alternative is a
    bare `FileNotFoundError` traceback mid-setup for what is really "that file has not
    been generated yet / you passed the wrong `--registry`".
    """


class UnknownInstanceError(MintConfigError):
    """No record in the registry carries the requested `instance_id`.

    Loud rather than an empty selection: a mint that drives nothing produces an empty
    batch dir, which `belay phase0 run` reads as `INSTRUMENT SUSPECT` — a *fake* PIVOT
    caused by a typo'd id rather than by the agents under measurement.
    """


@dataclass(frozen=True)
class MintConfig:
    """Everything one mint run needs, resolved from arguments — never from a key sniff.

    `root` is required and has no default: a default root is how two mints silently
    share one batch directory. `checkpoint_path` defaults to `<root>/checkpoint.json`,
    so a fresh `--root` is a genuinely fresh attempt with a fresh ledger and re-running
    the same root is an idempotent resume.
    """

    root: Path
    clones_dir: Path = DEFAULT_CLONES_DIR
    registry_path: Path = DEFAULT_REGISTRY_PATH
    checkpoint_path: Optional[Path] = None
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_steps: int = DEFAULT_MAX_STEPS
    system: str = DEFAULT_SYSTEM_PROMPT
    server_root: Optional[Path] = field(default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        object.__setattr__(self, "clones_dir", Path(self.clones_dir))
        object.__setattr__(self, "registry_path", Path(self.registry_path))
        object.__setattr__(
            self,
            "checkpoint_path",
            Path(self.checkpoint_path)
            if self.checkpoint_path is not None
            else self.root / "checkpoint.json",
        )
        if self.server_root is not None:
            object.__setattr__(self, "server_root", Path(self.server_root))

        if self.provider not in PROVIDERS:
            raise MintConfigError(
                f"unknown provider {self.provider!r}; known providers: "
                f"{list(PROVIDERS)}. The provider is an explicit choice — it is never "
                f"inferred from which credentials happen to be exported."
            )
        _validate_request_timeout(self.request_timeout)
        if not isinstance(self.max_steps, int) or self.max_steps <= 0:
            raise MintConfigError(
                f"max_steps must be a positive int, got {self.max_steps!r}"
            )

    @property
    def batch_dir(self) -> Path:
        """The single batch directory this run bridges into — `run_mint`'s convention."""
        return self.root / "batch"


def _validate_request_timeout(value: object) -> float:
    """`request_timeout` must be a positive real number — never `None`.

    `None` is not "no timeout": it falls through `run_session` -> `run_task` ->
    `transport.request`'s `DEFAULT_TIMEOUT = 10.0`, silently capping every live turn at
    ten seconds. Refusing it here is why that ceiling is unreachable by accident.
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MintConfigError(
            f"request_timeout must be a positive number of seconds, got {value!r}. "
            f"`None` is not 'no timeout' — it silently means the transport's 10s "
            f"default, which is too tight for a live model turn plus a cold server "
            f"start under the sandbox."
        )
    if value <= 0:
        raise MintConfigError(f"request_timeout must be > 0 seconds, got {value!r}")
    return float(value)


def resolve_credentials(provider: str) -> dict[str, str]:
    """The credentials for `provider`, read from the environment BY NAME.

    This is the only place the entry point touches the environment, and it never
    branches on *which* keys are present to decide *what* to build — `provider` already
    decided that. For `openai-compat` both the base URL and the API key are required and
    a blank value counts as missing (the sentinel fallback in the client is exactly the
    silent failure this prevents). For `anthropic` the vendor SDK reads its own key from
    the environment and reports its own error, so nothing is resolved here.
    """
    if provider == "anthropic":
        return {}
    if provider != "openai-compat":
        raise MintConfigError(
            f"unknown provider {provider!r}; known providers: {list(PROVIDERS)}"
        )

    base_url = (os.environ.get(OPENAI_BASE_URL_ENV) or "").strip()
    api_key = (os.environ.get(OPENAI_API_KEY_ENV) or "").strip()
    missing = [
        name
        for name, value in (
            (OPENAI_BASE_URL_ENV, base_url),
            (OPENAI_API_KEY_ENV, api_key),
        )
        if not value
    ]
    if missing:
        raise MissingCredentialsError(
            f"provider 'openai-compat' needs both {OPENAI_BASE_URL_ENV} and "
            f"{OPENAI_API_KEY_ENV} to be set and non-empty; missing or blank: "
            f"{missing}. They are NOT optional: with no key the client substitutes a "
            f"local sentinel that a hosted endpoint rejects with 401 on the first call "
            f"of every instance, producing an empty mint that reads as "
            f"INSTRUMENT SUSPECT rather than as a setup mistake."
        )
    return {"base_url": base_url, "api_key": api_key}


def make_model_factory(
    *,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    client: Optional[Any] = None,
    max_tokens: Optional[int] = None,
) -> ModelFactory:
    """A `ModelFactory` for `provider`/`model` — a FRESH model on every call.

    `run_mint` calls the returned factory once per instance. It MUST construct a new
    model each time: the clients accumulate conversation state
    (`LocalOpenAICompatModel._openai_messages`, `AnthropicModel`'s equivalent), so
    reusing one instance would let instance N inherit instance N-1's conversation —
    "cache the client, it's the same config" is the obvious future refactor and it is
    wrong (`batch.py`'s `ModelFactory` docstring says the same).

    Credentials are resolved ONCE, here, so a missing key fails before any instance is
    prepped or driven rather than once per instance. `client` is the test injection seam
    (`clients/local_client.py`): when given, no SDK is imported and no credentials are
    needed.
    """
    if provider not in PROVIDERS:
        raise MintConfigError(
            f"unknown provider {provider!r}; known providers: {list(PROVIDERS)}"
        )

    credentials = resolve_credentials(provider) if client is None else {}

    if provider == "openai-compat":
        from eval.minting_driver.clients.local_client import LocalOpenAICompatModel

        def openai_compat_factory(tools: list[dict]) -> Any:
            # A NEW model object on every call — never hoisted, never cached.
            # `batch.ModelFactory` is documented as "called ONCE PER INSTANCE so no
            # conversation state leaks between instances", and these clients really do
            # accumulate it (`_openai_messages` / `_seen` here; the `tool_use_id`
            # bookkeeping in the Anthropic client). "Cache the client, it's the same
            # config" is the obvious future refactor, and it silently hands instance N
            # instance N-1's conversation.
            kwargs: dict[str, Any] = {"model": model, "tools": list(tools)}
            if client is not None:
                kwargs["client"] = client
            else:
                kwargs.update(credentials)
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            return LocalOpenAICompatModel(**kwargs)

        return openai_compat_factory

    from eval.minting_driver.clients.anthropic_client import AnthropicModel

    def anthropic_factory(tools: list[dict]) -> Any:
        # A NEW model object on every call — never hoisted, never cached.
        # `batch.ModelFactory` is documented as "called ONCE PER INSTANCE so no
        # conversation state leaks between instances", and these clients really do
        # accumulate it (`_openai_messages` / `_seen` here; the `tool_use_id`
        # bookkeeping in the Anthropic client). "Cache the client, it's the same
        # config" is the obvious future refactor, and it silently hands instance N
        # instance N-1's conversation.
        kwargs: dict[str, Any] = {"model": model, "tools": list(tools)}
        if client is not None:
            kwargs["client"] = client
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return AnthropicModel(**kwargs)

    return anthropic_factory


def preflight_servers(cfg: MintConfig) -> Path:
    """Resolve the pinned filesystem server's entrypoint — or fail loudly, once, now.

    **This must run before anything is prepped, driven, or spent.** `run_mint` builds
    each instance's server command *inside* its per-instance `try/except`, which is
    exactly right for a mint (one `ServerExited` must not abort the batch) and exactly
    wrong for a missing install: every one of ~65 instances would be recorded `failed`
    with the same message, the batch dir would be empty, and `belay phase0 run` would
    report `INSTRUMENT SUSPECT` — a *fake* PIVOT produced by an `npm install` that was
    never run, an hour after the operator walked away.

    `MissingServerError` already carries the exact pinned install command
    (`servers.py`), so it propagates unchanged rather than being re-worded here.
    """
    return resolve_server_entrypoint("filesystem", root=cfg.server_root)


def mint_batch(
    records: Sequence[InstanceRecord],
    cfg: MintConfig,
    *,
    model_factory: Optional[ModelFactory] = None,
    build_server_command: Optional[BuildServerCommand] = None,
    prepare: PrepareWorkspace = prepare_workspace,
    transport_factory: Optional[TransportFactory] = None,
    discover_tools: Optional[DiscoverTools] = None,
) -> Checkpoint:
    """Drive `records` sequentially through the gated proxy, per `cfg`.

    Thin by design: preflight, then wire `run_mint`'s seams from the config, then call
    it. **No `try/except` around `run_mint`** — its per-instance containment is the
    contract and wrapping it would either swallow a real setup failure or turn one bad
    instance into an aborted mint.

    The keyword seams (`model_factory`, `prepare`, `transport_factory`,
    `discover_tools`, `build_server_command`) exist so the whole path is testable with
    no subprocess, no git, no network and no spend. They are Python kwargs, never
    command-line flags.
    """
    # FIRST statement — see `preflight_servers`. Before the registry, before prep,
    # before any model or credential resolution, before a single byte is spent.
    preflight_servers(cfg)

    if model_factory is None:
        model_factory = make_model_factory(provider=cfg.provider, model=cfg.model)

    if build_server_command is None:

        def build_server_command_for(layout: WorkspaceLayout) -> list[str]:
            # THIS instance's workspace is the filesystem server's own allowed-directory
            # boundary, passed in its argv — a constant command would point every
            # instance after the first at the first instance's workspace.
            return filesystem_server_command(layout.work_dir, root=cfg.server_root)

        build_server_command = build_server_command_for

    extra: dict[str, Any] = {}
    if discover_tools is not None:
        extra["discover_tools"] = discover_tools

    return run_mint(
        records,
        root=cfg.root,
        clones_dir=cfg.clones_dir,
        model_factory=model_factory,
        build_server_command=build_server_command,
        checkpoint_path=cfg.checkpoint_path,
        request_timeout=cfg.request_timeout,
        max_steps=cfg.max_steps,
        system=cfg.system,
        prepare=prepare,
        transport_factory=transport_factory,
        **extra,
    )


def load_records(cfg: MintConfig) -> tuple[InstanceRecord, ...]:
    """The registry at `cfg.registry_path`, or a named error if it is not there.

    `load_registry` is already fail-closed on *content*; this adds the one case it
    reports as an unreadable-file `ValueError` and which has a specific, actionable
    cause: the file is simply absent because the `instance-pool` aspect that generates
    `eval/instances/selected.json` has not landed (or `--registry` points elsewhere).
    """
    path = Path(cfg.registry_path)
    if not path.is_file():
        raise RegistryNotFoundError(
            f"instance registry not found: {path}\n"
            f"The default registry ({DEFAULT_REGISTRY_PATH}) is the `instance-pool` "
            f"aspect's deliverable — generate it, or pass --registry <path> to an "
            f"existing selection file. A mint with no records drives nothing, and an "
            f"empty batch reads as INSTRUMENT SUSPECT rather than as a missing file."
        )
    return load_registry(path)


def select_record(
    records: Sequence[InstanceRecord], instance_id: str
) -> InstanceRecord:
    """The one record named `instance_id`, or `UnknownInstanceError`."""
    for record in records:
        if record.instance_id == instance_id:
            return record
    raise UnknownInstanceError(
        f"instance {instance_id!r} is not in the registry, which holds "
        f"{len(records)} record(s). Nothing was minted — a typo'd id must never read "
        f"as a run that captured nothing."
    )


def verify_command(
    cfg: MintConfig,
    *,
    entrypoint: Path,
    ledger_path: StrPath = DEFAULT_LEDGER_PATH,
    corpus_dir: StrPath = DEFAULT_CORPUS_DIR,
) -> str:
    """The `belay phase0 run` command that turns this mint's captures into the number.

    Printed on every completion: this line IS the reproduce-the-number artifact. Two
    details are load-bearing:

    * `{workspace}` (`WORKSPACE_PLACEHOLDER`) rather than a per-trace command — replay
      substitutes each trace's own recorded `source_root`, so ONE static command is
      correct for a batch captured from many workspaces.
    * **No `--` separator.** `--server` is `nargs=REMAINDER`, so a separator would be
      handed to `node` as an argument instead of being consumed by argparse.
    """
    return (
        f"belay phase0 run {cfg.batch_dir} "
        f"--ledger {Path(ledger_path)} --corpus-dir {Path(corpus_dir)} "
        f"--server node {entrypoint} '{WORKSPACE_PLACEHOLDER}'"
    )


@dataclass(frozen=True)
class MintReport:
    """What one mint produced: where the artifacts are, and how to score them.

    Counts are derived from the `Checkpoint` (the durable ledger), never from a parallel
    tally kept alongside it — a second counter is free to drift from the file the resume
    actually reads, and then the summary would describe a mint that did not happen.
    """

    batch_dir: Path
    checkpoint_path: Path
    checkpoint: Checkpoint
    instance_ids: tuple[str, ...]
    counts: dict[str, int]
    verify_command: str

    @property
    def captured(self) -> int:
        return self.counts.get("captured", 0)

    @property
    def failed(self) -> int:
        return self.counts.get("failed", 0)

    def render(self) -> str:
        """The operator-facing summary, ending with the verify command."""
        lines = [
            f"minted {self.captured} captured, {self.failed} failed "
            f"of {len(self.instance_ids)} instance(s)",
            f"  batch dir:  {self.batch_dir}",
            f"  checkpoint: {self.checkpoint_path}",
        ]
        failures = [
            (instance_id, self.checkpoint.reason(instance_id))
            for instance_id in self.instance_ids
            if self.checkpoint.status(instance_id) == "failed"
        ]
        for instance_id, reason in failures:
            # Named, not summarised: a mint that quietly loses instances shrinks the
            # denominator of the published rate.
            lines.append(f"  FAILED {instance_id}: {reason}")
        lines.append("")
        lines.append("verify with:")
        lines.append(f"  {self.verify_command}")
        return "\n".join(lines)


def _report_for(
    records: Sequence[InstanceRecord],
    cfg: MintConfig,
    checkpoint: Checkpoint,
    *,
    entrypoint: Path,
) -> MintReport:
    """Fold a finished mint into a `MintReport`, counting straight off the checkpoint."""
    counts = {"captured": 0, "failed": 0}
    for record in records:
        status = checkpoint.status(record.instance_id)
        if status is None:
            # Should be unreachable: `run_mint` records every record it sees. Counted
            # under its own key rather than dropped, because a silently-vanishing
            # instance is exactly how a denominator shrinks unnoticed.
            counts["unrecorded"] = counts.get("unrecorded", 0) + 1
        else:
            counts[status] = counts.get(status, 0) + 1
    return MintReport(
        batch_dir=cfg.batch_dir,
        checkpoint_path=Path(cfg.checkpoint_path or cfg.root / "checkpoint.json"),
        checkpoint=checkpoint,
        instance_ids=tuple(record.instance_id for record in records),
        counts=counts,
        verify_command=verify_command(cfg, entrypoint=entrypoint),
    )


def mint_one(
    instance_id: str,
    cfg: MintConfig,
    **seams: Any,
) -> MintReport:
    """Mint exactly ONE registry instance, by id — the Stage-1 tool.

    Deliberately `mint_batch` over a one-record list rather than a bespoke
    single-instance pipeline. Stage 1's entire value was that it rehearsed the *batch*
    path before the batch was spent on; a separate pipeline would rehearse only itself
    (which is what made the deleted `scratchpad/drive_one.py` worthless the moment it
    was gone) and would let resume, containment, bridge and checkpoint semantics drift
    apart between the two commands.

    **Inherited consequence, by design:** an instance already recorded `captured` in
    `cfg.checkpoint_path` is SKIPPED, and re-bridging into a used batch dir would raise
    `BridgeCollisionError` anyway. Re-minting is therefore a fresh `--root` (a fresh
    ledger for a fresh attempt), not a checkpoint edit — deleting a recorded disposition
    is how a mint double-spends by accident and loses the record of what already ran.
    """
    # The preflight FIRST — before the registry is even opened. See `preflight_servers`.
    entrypoint = preflight_servers(cfg)
    record = select_record(load_records(cfg), instance_id)
    checkpoint = mint_batch([record], cfg, **seams)
    return _report_for([record], cfg, checkpoint, entrypoint=entrypoint)


def mint_from_registry(cfg: MintConfig, **seams: Any) -> MintReport:
    """Mint every instance in `cfg.registry_path` — the batch entry point.

    Thin on purpose: preflight, load the registry, hand the records to `mint_batch`, and
    fold the returned `Checkpoint` into a `MintReport`. There is **no `try/except`
    around `run_mint`**: its per-instance containment is the contract, and wrapping it
    would either swallow a real setup failure or turn one bad instance into an aborted
    mint.

    Resumable by construction — `cfg.checkpoint_path` defaults to
    `<root>/checkpoint.json`, so re-running the same `--root` skips everything already
    recorded (`captured` or `failed`) and a new `--root` is a genuinely fresh attempt
    with a fresh ledger.

    The report counts EVERY registry record, including ones skipped on resume, because
    the operator's question is "where does this whole selection stand", not "what did
    this particular invocation touch".
    """
    entrypoint = preflight_servers(cfg)
    records = load_records(cfg)
    checkpoint = mint_batch(records, cfg, **seams)
    return _report_for(records, cfg, checkpoint, entrypoint=entrypoint)


__all__ = [
    "DEFAULT_CLONES_DIR",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_SYSTEM_PROMPT",
    "MintConfig",
    "MintConfigError",
    "MintReport",
    "MissingCredentialsError",
    "OPENAI_API_KEY_ENV",
    "OPENAI_BASE_URL_ENV",
    "PROVIDERS",
    "RegistryNotFoundError",
    "UnknownInstanceError",
    "WORKSPACE_PLACEHOLDER",
    "load_records",
    "make_model_factory",
    "mint_batch",
    "mint_from_registry",
    "mint_one",
    "preflight_servers",
    "resolve_credentials",
    "select_record",
    "verify_command",
]
