"""`LocalOpenAICompatModel` — a thin `Model` (`model.py`) adapter over any
OpenAI-compatible chat-completions endpoint (Ollama, llama.cpp's server, vLLM, etc.).

Same import-isolation contract as `anthropic_client.py`: `import openai` happens
*inside* `__init__`, never at module top, so this module stays importable without the
`openai` package installed. `tests/test_minting_driver_clients_import.py` proves it.

**This is a mapper, not an agent.** One `propose_next` call issues (at most) one
`chat.completions.create` request and reads back (at most) one tool call. See
`anthropic_client.py`'s module docstring — the same one-call-per-turn, no-planning
guardrail applies here.

**It also keeps this instance's accounting** (`run-accounting`): `request_count` and a
running `usage` total. Until now the response's `.usage` was present on every real reply
and **discarded when `response` went out of scope**, so nothing anywhere recorded what a
mint cost — the operator could not set a stop-loss and the write-up could not state the
cost of the number. One client is built per instance (`entrypoint.make_model_factory`
never hoists it), so these counters ARE the per-instance totals.

**Absent is not zero.** `usage` stays `None` until a response actually reports usage, and
a half-reported usage records only the half that was reported. An unmeasured quantity
rendered as a measured `0` is the same mistake as rendering `UNVERIFIED` as `PASS`, and it
would put a fabricated zero into the published cost of the number. Everything is read with
`getattr`, so a provider that omits usage — or sends a shape nobody expected — yields
absent rather than ending an instance that was about to produce an observation.

**No dollar amount is computed or stored, here or anywhere downstream.** Under a
subscription there is no per-token price; inventing one is exactly the kind of invented
precision this project exists to avoid.
"""

from __future__ import annotations

import json
import os
import warnings
from typing import Any, Optional

from eval.minting_driver.model import Done, Message, ToolCall

#: Most local runtimes (Ollama's OpenAI-compat shim, llama.cpp's server) accept any
#: non-empty API key — they don't check it — so a caller running fully local with no
#: `OPENAI_API_KEY` set gets a sentinel that satisfies the SDK's "key is required"
#: check instead of a confusing construction failure.
LOCAL_SENTINEL_API_KEY = "local-no-key-required"

DEFAULT_MAX_TOKENS = 4096

#: The provider name recorded alongside each instance's accounting. A literal on the
#: class rather than something inferred at record time: `entrypoint.PROVIDERS` names the
#: same two strings, and the published number has to say which client actually made the
#: calls, not which one the config believed it had wired up.
PROVIDER_NAME = "openai-compat"

#: OpenAI's `response.usage` field names -> the provider-neutral names recorded in the
#: checkpoint. `anthropic_client.py` has the twin of this mapping with ITS field names
#: (`input_tokens`/`output_tokens`, which happen to already be the recorded ones). The
#: two are deliberately separate: the mapping is the one genuinely provider-specific part
#: of accounting, and a shared table would have to be keyed by provider anyway.
_USAGE_FIELDS = (
    ("prompt_tokens", "input_tokens"),
    ("completion_tokens", "output_tokens"),
)


def _token_count(value: object) -> Optional[int]:
    """A duck-typed token count -> `int`, or `None` if it is not one.

    `bool` is excluded despite being an `int` subclass, mirroring
    `resilience._coerce_seconds`: a `prompt_tokens` of `True` is a flag someone set, not
    one token. A negative count is nonsense and is rejected rather than summed, because a
    total that can go down is worse than a total that is honestly missing a term.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        # A float that is not a whole number is not a token count; refuse rather than
        # truncate, so a strange provider shape reads as absent instead of as data.
        return int(value) if value >= 0 and value.is_integer() else None
    return None


def _accumulate_usage(
    total: Optional[dict[str, int]], response: object
) -> Optional[dict[str, int]]:
    """Fold `response.usage` into `total`, per field, absent-preserving.

    Returns `total` UNCHANGED (including `None`) when the response reports nothing
    usable, so "this provider never reported usage" and "this provider reported zero" stay
    different states all the way to the ledger. A field the provider omits on one call but
    sends on another simply starts accumulating from the call that sent it.

    Never raises: every read is a `getattr` and every value goes through `_token_count`.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return total
    folded = dict(total) if total is not None else {}
    changed = False
    for source_field, recorded_field in _USAGE_FIELDS:
        count = _token_count(getattr(usage, source_field, None))
        if count is None:
            continue
        folded[recorded_field] = folded.get(recorded_field, 0) + count
        changed = True
    if not changed:
        return total
    return folded


def _openai_tool(mcp_tool: dict) -> dict:
    """One MCP `tools/list` entry -> one OpenAI `tools` entry (`type: "function"`)."""
    return {
        "type": "function",
        "function": {
            "name": mcp_tool["name"],
            "description": mcp_tool.get("description", ""),
            "parameters": mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


class LocalOpenAICompatModel:
    """`Model` backed by any OpenAI-compatible `/chat/completions` endpoint.

    `tools` is the MCP `tools/list` result (`{"name", "description", "inputSchema"}`
    dicts), already fetched by the loop's transport — not fetched here.

    `base_url` defaults to `OPENAI_BASE_URL`; `api_key` defaults to `OPENAI_API_KEY`,
    falling back to `LOCAL_SENTINEL_API_KEY` when unset (most local servers don't
    validate it). `client` is an injection seam for tests: pass any object exposing
    `.chat.completions.create(...)` with the OpenAI response shape, and the real
    `openai` package is never imported or contacted.
    """

    def __init__(
        self,
        *,
        model: str,
        tools: list[dict],
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            import openai  # type: ignore[import-not-found]  # lazy: SDK not in core import graph

            resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
            resolved_api_key = (
                api_key or os.environ.get("OPENAI_API_KEY") or LOCAL_SENTINEL_API_KEY
            )
            self._client = openai.OpenAI(base_url=resolved_base_url, api_key=resolved_api_key)

        self._model = model
        self._max_tokens = max_tokens
        self._tools = [_openai_tool(t) for t in tools]

        # OpenAI-format conversation state, built incrementally across calls — same
        # reasoning as `AnthropicModel._ingest_new_messages`: `model.Message` carries
        # no `tool_call_id`, and the OpenAI API requires every `role="tool"` message to
        # name the `tool_call_id` it answers, so this instance tracks the id of the
        # last tool call it emitted and stamps it onto the next tool-result message.
        self._openai_messages: list[dict] = []
        self._seen = 0
        self._pending_tool_call_id: Optional[str] = None

        # This instance's accounting. `None`, not `{}`: no response has reported usage
        # yet, which is a different fact from "the responses reported nothing".
        self._request_count = 0
        self._usage: Optional[dict[str, int]] = None

    @property
    def provider(self) -> str:
        """The provider recorded with this instance's accounting — see `PROVIDER_NAME`."""
        return PROVIDER_NAME

    @property
    def model(self) -> str:
        """The model id these requests actually name.

        Per-instance provenance: the 12 banked instances ran on one model and the
        remainder will not, so the published number must be able to say which model minted
        which instance. Read off the object that made the calls, so a mint whose config
        and wiring disagree cannot report the config's answer.
        """
        return self._model

    @property
    def request_count(self) -> int:
        """Requests ISSUED to the provider across this instance's whole session.

        Incremented before the call, not after: a request that comes back a 429 still
        consumed the day's quota — that is the entire 2026-07-24 lesson — so an accounting
        that counted only successful calls would under-report exactly the spend a
        stop-loss exists to bound.
        """
        return self._request_count

    @property
    def usage(self) -> Optional[dict[str, int]]:
        """Accumulated `{input_tokens, output_tokens}`, or `None` if never reported.

        A key is present only if some response reported that field. `None` means no
        response reported usage at all — never `{"input_tokens": 0, ...}`.
        """
        return None if self._usage is None else dict(self._usage)

    def _ingest_new_messages(self, messages: list[Message]) -> None:
        for message in messages[self._seen :]:
            if message.role == "tool":
                if self._pending_tool_call_id is None:
                    # No tool call is outstanding — same reasoning as
                    # `AnthropicModel._ingest_new_messages`: silently stamping
                    # `tool_call_id: None` produces a confusing rejection from the
                    # OpenAI-compat endpoint deep inside a live mint. Raise here,
                    # where the cause (a caller bug or internal desync) is still clear.
                    raise ValueError(
                        "LocalOpenAICompatModel: got a tool-result Message but there "
                        "is no pending tool_call_id to correlate it with (no ToolCall "
                        "was proposed since the last one was consumed). This message "
                        "cannot be sent to the chat.completions API without a valid "
                        "tool_call_id."
                    )
                self._openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": self._pending_tool_call_id,
                        "content": message.content,
                    }
                )
                self._pending_tool_call_id = None
            else:
                # "system" / "user" / "assistant" all pass through as-is — unlike
                # Anthropic, OpenAI-compat chat-completions takes `system` as a normal
                # message in the list rather than a separate request field.
                self._openai_messages.append({"role": message.role, "content": message.content})
        self._seen = len(messages)

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        self._ingest_new_messages(messages)

        # Counted BEFORE the call: a request that raises (a 429, a timeout) still reached
        # the provider and still cost quota. See the `request_count` docstring.
        self._request_count += 1
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=self._openai_messages,
            tools=self._tools,
        )
        self._usage = _accumulate_usage(self._usage, response)

        choice = response.choices[0]
        reply = choice.message
        tool_calls = getattr(reply, "tool_calls", None) or []

        # Preserve the assistant turn in the running conversation regardless of
        # outcome, mirroring the API's own message shape (content + tool_calls).
        self._openai_messages.append(
            {
                "role": "assistant",
                "content": reply.content,
                **({"tool_calls": tool_calls} if tool_calls else {}),
            }
        )

        if not tool_calls:
            reason = reply.content or getattr(choice, "finish_reason", None) or "stop"
            return Done(reason=reason)

        if len(tool_calls) > 1:
            warnings.warn(
                f"LocalOpenAICompatModel: model requested {len(tool_calls)} tool calls "
                "in one turn; taking the first and ignoring the rest (no batching).",
                stacklevel=2,
            )

        chosen = tool_calls[0]
        self._pending_tool_call_id = chosen.id
        try:
            arguments = json.loads(chosen.function.arguments) if chosen.function.arguments else {}
        except json.JSONDecodeError as exc:
            # A raw JSONDecodeError bubbling up from deep in this client is not
            # actionable at a live mint — it doesn't say which tool or what payload.
            # Raise a clear, local error naming both instead.
            raise ValueError(
                f"LocalOpenAICompatModel: tool call {chosen.function.name!r} "
                f"(id={chosen.id!r}) returned arguments that are not valid JSON: "
                f"{chosen.function.arguments!r}"
            ) from exc
        return ToolCall(name=chosen.function.name, arguments=arguments)


__all__ = [
    "LocalOpenAICompatModel",
    "LOCAL_SENTINEL_API_KEY",
    "DEFAULT_MAX_TOKENS",
    "PROVIDER_NAME",
]
