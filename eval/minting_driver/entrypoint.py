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
from typing import Any, Optional, Union

from eval.minting_driver.batch import ModelFactory

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


class MintConfigError(ValueError):
    """A mint configuration value is missing, malformed, or out of range."""


class MissingCredentialsError(RuntimeError):
    """The selected provider's credentials are absent from the environment.

    Raised BEFORE any instance is prepped or driven, and it names the variables. The
    alternative — a silent sentinel key — is one 401 per instance and an empty mint.
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
            # New model object per instance — see the docstring. Do not hoist.
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
        # New model object per instance — see the docstring. Do not hoist.
        kwargs: dict[str, Any] = {"model": model, "tools": list(tools)}
        if client is not None:
            kwargs["client"] = client
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return AnthropicModel(**kwargs)

    return anthropic_factory


__all__ = [
    "DEFAULT_CLONES_DIR",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MODEL",
    "DEFAULT_PROVIDER",
    "DEFAULT_REGISTRY_PATH",
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_SYSTEM_PROMPT",
    "MintConfig",
    "MintConfigError",
    "MissingCredentialsError",
    "OPENAI_API_KEY_ENV",
    "OPENAI_BASE_URL_ENV",
    "PROVIDERS",
    "make_model_factory",
    "resolve_credentials",
]
