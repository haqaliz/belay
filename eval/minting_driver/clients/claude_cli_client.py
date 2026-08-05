"""`ClaudeCliModel` — a thin `Model` (`model.py`) adapter over the `claude` CLI subprocess.

**Why a subprocess at all.** The other two clients (`anthropic_client.py`,
`local_client.py`) both need a metered API key. This one runs the oracle on the
subscription credentials the operator already holds, so a mint can be driven without
billing a per-token key. The boundary is therefore a process, not an SDK client — which
also means this module imports **no SDK at all**, and the import-isolation contract in
this package's `__init__` holds here trivially rather than by a lazy import.

**This is a mapper, not an agent.** One `propose_next` call runs (at most) one
`claude -p` and reads back (at most) one tool call. The planning loop stays `loop.py`'s
job, and the retries stay `RetryingModel`'s — see `anthropic_client.py`'s module
docstring for the same guardrail stated against a different provider.

**The argv grants nothing.** `--tools ""` empties the built-in tool allowlist and
`--strict-mcp-config` refuses to inherit the operator's own MCP servers. Those are two
distinct grants and both have to be closed: an inherited filesystem MCP server would let
the oracle edit files without crossing the proxy that is recording the mint, which is an
R6 hole — the capture would be missing exactly the turns that matter. The MCP tool
schemas travel as **data inside the prompt** instead, so the model can *propose* a call
it cannot *make*.

Three flags are deliberately absent, and each absence is asserted by a test:

* **`--bare`** — its help reads *"OAuth and keychain are never read"*. It reads like the
  isolation flag and it would break the subscription path outright.
* **`--max-turns`** — probed 2026-08-05: absent from `--help`, accepted silently, and
  `--max-turns 1` still produced `num_turns: 2`. It does not bound a run. The bound is
  the harness's `DEFAULT_MAX_STEPS` plus `DEFAULT_TIMEOUT_SECONDS` below.
* **`--dangerously-skip-permissions` / `--add-dir`** — neither is needed under an emptied
  allowlist, and either would re-open a path around the recorded boundary.

**Why our own `--system-prompt`, measured rather than assumed.** One live call each,
2026-08-05, same task and same tool schemas:

|                            | default Claude Code prompt          | our own `--system-prompt` |
|----------------------------|-------------------------------------|---------------------------|
| prefix tokens              | ~39,600 (24,099 created + 15,498 read) | 7,026                  |
| `total_cost_usd`, that call | $0.249                             | $0.0045                   |

Both parsed a tool call correctly. That is a ~5.6x smaller prefix, and it also decouples
the oracle from Claude Code's own system-prompt version — a reproducibility win on top of
the cost one, since a mint driven under one prompt version is not re-runnable under the
next. (The cost figures are the *measurement* that justified the flag; no dollar amount is
computed or stored by this client — `prd.md` D-1.)

**The env carries no key.** `_build_env` copies `os.environ` and removes three variables
by **absence, never by empty string** — an empty value still occupies its precedence slot.
`ANTHROPIC_API_KEY` is set on this operator's box, and a leaked one produces a run that
succeeds and looks identical while silently billing a metered key: the exact failure this
whole path exists to prevent. See `SCRUBBED_ENV_VARS` for the per-variable reason.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable, Optional

#: The provider name recorded alongside this instance's accounting; the third string
#: `entrypoint.PROVIDERS` names, and never selected by sniffing the environment — it is
#: an explicit `--provider` choice, because a path that silently picks itself is a path
#: nobody can state in the write-up.
PROVIDER_NAME = "claude-cli"

#: The default model id: a **full id, never an alias**. `opus` resolves to whatever is
#: newest at call time, so two mints reporting the same string would not have used the
#: same model — the drift criterion 9 forbids, arriving through the constant rather than
#: through the argv.
DEFAULT_CLAUDE_CLI_MODEL = "claude-opus-5"

#: The client owns the bound, because the CLI does not offer one: `--max-turns` is a
#: no-op (see the module docstring). Without this, a wedged child would hang an entire
#: sequential batch with nothing to notice it.
DEFAULT_TIMEOUT_SECONDS = 600.0

#: Removed from the child environment, by absence. All three sit in a credential or
#: routing precedence slot, so scrubbing only the first is insufficient:
#:
#: * `ANTHROPIC_API_KEY`   — the metered key itself.
#: * `ANTHROPIC_AUTH_TOKEN` — the same slot by another name; it *also* shadows the OAuth
#:   profile, so leaving it would break the subscription path even without billing.
#: * `ANTHROPIC_BASE_URL`  — could silently redirect the oracle at a proxy, making a
#:   published run non-reproducible on any other box.
SCRUBBED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)


class ClaudeCliModel:
    """`Model` backed by the `claude` CLI running on subscription credentials.

    `tools` is the MCP `tools/list` result (a list of `{"name", "description",
    "inputSchema"}` dicts) the loop's transport already fetched — as in the sibling
    clients, this class does not fetch it, and here it is serialized into the prompt as
    data rather than granted to the subprocess.

    `runner` is the injection seam, and it is a **callable with `subprocess.run`'s
    shape** rather than an SDK client object, because the boundary here is a process.
    Pass anything returning an object exposing `.returncode` / `.stdout` / `.stderr` and
    no `claude` binary is ever spawned — which is how every test in
    `tests/test_minting_driver_claude_cli.py` runs offline, with no subscription.
    """

    def __init__(
        self,
        *,
        model: str,
        tools: list[dict],
        runner: Optional[Callable[..., Any]] = None,
        binary: str = "claude",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            # Refused here, where the cause is still visible, rather than at argv-build
            # time inside a live mint: `--model ""` would let the CLI fall back to
            # whatever it considers current, which is the implicit default criterion 9
            # forbids wearing a disguise.
            raise ValueError(
                "ClaudeCliModel: `model` must be a non-empty model id (a full id such "
                f"as {DEFAULT_CLAUDE_CLI_MODEL!r}, never an alias); got {model!r}."
            )

        self._model = model
        self._tools = list(tools)
        self._runner = runner if runner is not None else subprocess.run
        self._binary = binary
        self._timeout = timeout

        # This instance's accounting, mirroring `anthropic_client.py`. Populated from
        # Phase 2 onward; `None`, not `{}` — absent is not zero.
        self._request_count = 0
        self._usage: Optional[dict[str, int]] = None

    @property
    def provider(self) -> str:
        """The provider recorded with this instance's accounting — see `PROVIDER_NAME`."""
        return PROVIDER_NAME

    @property
    def model(self) -> str:
        """The model id these invocations actually name — per-instance provenance.

        Read off the object that made the calls rather than from the config, so a mint
        whose config and wiring disagree cannot report the config's answer.
        """
        return self._model

    @property
    def timeout(self) -> float:
        """The per-invocation wall-clock bound handed to the runner.

        Owned here because the CLI has no working equivalent: `--max-turns` is accepted
        and does nothing.
        """
        return self._timeout

    def _build_command(self, *, prompt: str, system_prompt: str) -> list[str]:
        """The exact argv handed to the runner.

        Built as a list, never a shell string — nothing here is re-parsed by a shell, so
        a prompt containing quotes or newlines cannot alter the flags around it.

        `--tools` is followed by an **empty string element**, not omitted: dropping the
        value would leave `--tools` consuming the next flag as its allowlist, and the
        emptiness this argv is supposed to guarantee would quietly stop being true.
        """
        return [
            self._binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self._model,
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--system-prompt",
            system_prompt,
        ]

    def _build_env(self) -> dict[str, str]:
        """The child's environment: this process's, minus `SCRUBBED_ENV_VARS`.

        A **copy** — `os.environ` itself is never mutated, or the scrub would strip the
        operator's key for the rest of the batch and break every later instance running
        on a different provider.

        Removal is by `pop`, so a variable that was never set simply stays absent; it is
        never written back as `""`, which would leave the child holding a present-but-
        empty credential rather than none at all.
        """
        env = dict(os.environ)
        for name in SCRUBBED_ENV_VARS:
            env.pop(name, None)
        return env


__all__ = [
    "ClaudeCliModel",
    "DEFAULT_CLAUDE_CLI_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVIDER_NAME",
    "SCRUBBED_ENV_VARS",
]
