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

import json
import os
import subprocess
import warnings
from typing import Any, Callable, Optional

from eval.minting_driver.model import Done, Message, ToolCall

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

#: The system prompt handed to `--system-prompt`. A stub until Phase 3 writes the real
#: response contract; `_build_prompt` states the shape inline for now.
RESPONSE_CONTRACT_SYSTEM_PROMPT = "Reply with only a JSON object."

#: The envelope's `usage` field names -> the recorded ones, exactly as
#: `anthropic_client._USAGE_FIELDS` does it. Identity here too, and written out anyway so
#: the recorded vocabulary is stated rather than implied.
#:
#: The cache meters (`cache_creation_input_tokens` / `cache_read_input_tokens`) are
#: deliberately **not** folded in: `batch.py:229` records exactly these two names, and
#: summing three different meters into `input_tokens` would report a number no envelope
#: ever stated. Absent beats conflated.
_USAGE_FIELDS = (
    ("input_tokens", "input_tokens"),
    ("output_tokens", "output_tokens"),
)

#: The two decision kinds this client recognises. Anything else is *unparsed*, never a
#: completion — see `ClaudeCliParseError`.
_TOOL_CALL_KIND = "tool_call"
_DONE_KIND = "done"


class ClaudeCliError(RuntimeError):
    """Base for every failure this client names.

    A `RuntimeError`, which means `resilience.classify_error` rule 6 lands the whole family
    on **`terminal`** unless a subclass deliberately opts into another rule. That is the
    fail-safe direction (criterion 6): a `terminal` verdict costs one instance, while a
    wrong `transient` costs the retry ladder on every instance behind it.
    """


class ClaudeCliInvocationError(ClaudeCliError):
    """The CLI reported the call itself failed — `is_error: true`, or a non-`success`
    `subtype`, or a non-zero exit.

    Never parsed for a decision: reading `result` out of a failed envelope would turn the
    CLI's own error text into a model turn.
    """


class ClaudeCliToolAttemptError(ClaudeCliError):
    """The envelope reported a non-empty `permission_denials` — the oracle attempted a tool.

    Under `--tools ""` plus `--strict-mcp-config` this should be impossible, so it is an
    **instrument fault**, not a model verdict (criterion 19): it says the emptied allowlist
    is not doing what the argv tests claim, and therefore that edits could be reaching the
    workspace without crossing the proxy that is recording the mint. Discarding it would
    hide the one signal that the capture is incomplete.
    """


class ClaudeCliParseError(ClaudeCliError):
    """The reply could not be read as a decision.

    Raised instead of returning a `Done`, always (criterion 3). A fabricated `Done` ends
    the trajectory silently *and successfully*: the instance is recorded as captured, and
    every verdict downstream is computed over a run that stopped for a reason nobody can
    see.
    """


class ClaudeCliUnknownToolError(ClaudeCliError):
    """The model named a tool the supplied schemas do not contain (criterion 4).

    Not passed through: a `tools/call` for a tool the server does not have produces a
    JSON-RPC error the capture records as a real turn — noise shaped like agent behaviour.
    """


def _token_count(value: object) -> Optional[int]:
    """A duck-typed token count -> `int`, or `None`. Twin of `anthropic_client._token_count`.

    `bool` excluded (an `int` subclass, but a flag is not a token), negatives refused (a
    total that can go down is worse than one honestly missing a term), non-integral floats
    refused rather than truncated.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 and value.is_integer() else None
    return None


def _accumulate_usage(
    total: Optional[dict[str, int]], usage: object
) -> Optional[dict[str, int]]:
    """Fold an envelope's `usage` object into `total`, per field, absent-preserving.

    Twin of `anthropic_client._accumulate_usage`, reading a **dict** rather than an SDK
    response attribute — the envelope is JSON, so there is no object to `getattr` through.
    `total` comes back unchanged (including `None`) when nothing usable is reported, so
    "this path never reported usage" and "it reported zero" stay different states all the
    way to the ledger. Never raises.
    """
    if not isinstance(usage, dict):
        return total
    folded = dict(total) if total is not None else {}
    changed = False
    for source_field, recorded_field in _USAGE_FIELDS:
        count = _token_count(usage.get(source_field))
        if count is None:
            continue
        folded[recorded_field] = folded.get(recorded_field, 0) + count
        changed = True
    if not changed:
        return total
    return folded


def _decision_objects(text: str) -> list[dict]:
    """Every JSON object in `text` that declares a `kind`, in order of appearance.

    Models narrate, fence, and occasionally emit a scratch object before the decision, so
    the payload has to be *found* rather than assumed to be the whole reply. The search is
    exact, not regex-shaped: `json.JSONDecoder.raw_decode` is attempted at every `{`, which
    means a brace in the prose (`the set {a, b}`) simply fails to decode and is skipped
    rather than being mistaken for the payload's start.

    Requiring a `kind` key is what makes the tolerance safe: the *kind* is always read off
    an object the model wrote, never inferred from the prose around it. An object without
    one is not a decision, so it is passed over rather than rejected — and if none of them
    carries a `kind`, the caller raises rather than guessing.
    """
    decoder = json.JSONDecoder()
    found: list[dict] = []
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict) and "kind" in value:
            found.append(value)
        # Past the whole decoded object either way, never into it: a `kind` *nested inside*
        # a larger object the model wrote is that object's data, not a decision, and
        # descending into it would let a quoted example become the turn.
        index = text.find("{", max(end, index + 1))
    return found


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

    @property
    def usage(self) -> Optional[dict[str, int]]:
        """Accumulated `{input_tokens, output_tokens}`, or `None` if never reported.

        A key is present only if some envelope reported that field; `None` means no envelope
        reported usage at all — never a manufactured `0` (criterion 18). No dollar amount
        is ever part of this: `total_cost_usd` is read by nothing (criterion 17).
        """
        return None if self._usage is None else dict(self._usage)

    def _build_prompt(self, messages: list[Message]) -> str:
        """The single `-p` string. Minimal until Phase 3 gives it a stated layout."""
        return "\n\n".join(message.content for message in messages)

    def _parse_envelope(self, stdout: str) -> ToolCall | Done:
        """One `--output-format json` envelope -> one decision, or a named error.

        The order of the checks is the contract, not an implementation detail (plan §1):

        1. the envelope itself has to parse, and be an object;
        2. `is_error` / `subtype` — the CLI's own verdict on the call, believed before
           anything inside it is read;
        3. `permission_denials` — an instrument fault, checked before the decision so a
           perfectly usable-looking turn cannot bury it;
        4. `usage` folded in;
        5. the decision extracted from `result`.

        `total_cost_usd` is not read at any step. It is not in this method, it is not stored
        on the instance, and it is not surfaced anywhere downstream (criterion 17).
        """
        try:
            envelope = json.loads(stdout)
        except ValueError as exc:
            raise ClaudeCliParseError(
                "ClaudeCliModel: the CLI's stdout is not JSON, so there is no envelope to "
                f"read a decision out of; got {stdout[:400]!r}."
            ) from exc
        if not isinstance(envelope, dict):
            raise ClaudeCliParseError(
                "ClaudeCliModel: the CLI's stdout parsed as JSON but is not an object; got "
                f"{type(envelope).__name__}."
            )

        subtype = envelope.get("subtype")
        if envelope.get("is_error") is True or subtype != "success":
            # Absent `subtype` lands here too, deliberately: an envelope shape we do not
            # recognise is one we cannot read a decision out of, and the other default
            # would silently promote every future CLI change to a passing turn.
            raise ClaudeCliInvocationError(
                "ClaudeCliModel: the CLI reported a failed call — "
                f"is_error={envelope.get('is_error')!r}, subtype={subtype!r}; "
                f"result={str(envelope.get('result'))[:400]!r}."
            )

        denials = envelope.get("permission_denials")
        if denials:
            raise ClaudeCliToolAttemptError(
                "ClaudeCliModel: the envelope reports a tool attempt "
                f"({len(denials) if isinstance(denials, (list, tuple)) else 1} denial(s)): "
                f"{denials!r}. Under `--tools \"\"` and `--strict-mcp-config` no tool is "
                "granted, so this is an instrument fault: the oracle may be reaching the "
                "workspace without crossing the recorded MCP boundary."
            )

        self._usage = _accumulate_usage(self._usage, envelope.get("usage"))

        result = envelope.get("result")
        if not isinstance(result, str):
            raise ClaudeCliParseError(
                "ClaudeCliModel: the envelope's `result` is not a string, so there is no "
                f"reply to read; got {type(result).__name__}."
            )
        return self._parse_decision(result)

    def _parse_decision(self, result: str) -> ToolCall | Done:
        """The `result` text -> `ToolCall` | `Done`, or a `ClaudeCliParseError`.

        **Never fabricates a `Done`.** A `Done` is returned only when the model explicitly
        wrote `kind == "done"`; every other outcome — no object, an unknown kind, a nameless
        tool call — raises.
        """
        decisions = _decision_objects(result)
        if not decisions:
            raise ClaudeCliParseError(
                "ClaudeCliModel: the reply contains no JSON object declaring a `kind`, so "
                "it states no decision. Raising rather than returning a Done: a fabricated "
                f"Done would end this trajectory silently. Reply was {result[:400]!r}."
            )
        if len(decisions) > 1:
            # Guardrail, mirroring `anthropic_client.py:270-277`: one decision per turn,
            # never batched. Noted and dropped — this must never become a queue the loop
            # has to drain, because one-call-in-flight (R7) is a property of `loop.py`'s
            # control flow and it holds only while no client hands it more than one.
            warnings.warn(
                f"ClaudeCliModel: reply stated {len(decisions)} tool call/decision objects "
                "in one turn; taking the first and ignoring the rest (no batching).",
                stacklevel=2,
            )

        decision = decisions[0]
        kind = decision.get("kind")

        if kind == _DONE_KIND:
            reason = decision.get("reason")
            # An explicit `done` with no reason is still an explicit `done` — the model said
            # it, so this is not a fabricated stop. Only the *text* falls back.
            return Done(reason=reason if isinstance(reason, str) and reason else _DONE_KIND)

        if kind != _TOOL_CALL_KIND:
            raise ClaudeCliParseError(
                f"ClaudeCliModel: reply declared kind={kind!r}, which is neither "
                f"{_TOOL_CALL_KIND!r} nor {_DONE_KIND!r}. An unrecognised kind is unparsed, "
                "never a completion."
            )

        name = decision.get("name")
        if not isinstance(name, str) or not name:
            raise ClaudeCliParseError(
                "ClaudeCliModel: reply stated a tool call with no usable `name`, so there "
                f"is nothing to invoke; got name={name!r}."
            )

        arguments = decision.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ClaudeCliParseError(
                f"ClaudeCliModel: tool call {name!r} stated `arguments` that are not a JSON "
                f"object ({type(arguments).__name__}). `loop.py` puts this straight into the "
                "JSON-RPC params, so a non-object is a malformed request, not a turn."
            )

        known = [tool.get("name") for tool in self._tools]
        if name not in known:
            raise ClaudeCliUnknownToolError(
                f"ClaudeCliModel: reply named tool {name!r}, which is not in the schemas it "
                f"was given ({known!r}). Not passed through — an unknown name is either a "
                "hallucination or a mis-wired `tools/list`, and those want opposite fixes."
            )

        return ToolCall(name=name, arguments=dict(arguments))

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        completed = self._runner(
            self._build_command(
                prompt=self._build_prompt(messages),
                system_prompt=RESPONSE_CONTRACT_SYSTEM_PROMPT,
            ),
            capture_output=True,
            text=True,
            env=self._build_env(),
            timeout=self._timeout,
        )
        return self._parse_envelope(completed.stdout)

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
    "ClaudeCliError",
    "ClaudeCliInvocationError",
    "ClaudeCliModel",
    "ClaudeCliParseError",
    "ClaudeCliToolAttemptError",
    "ClaudeCliUnknownToolError",
    "DEFAULT_CLAUDE_CLI_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "PROVIDER_NAME",
    "RESPONSE_CONTRACT_SYSTEM_PROMPT",
    "SCRUBBED_ENV_VARS",
]
