"""`LocalOpenAICompatModel` — a thin `Model` (`model.py`) adapter over any
OpenAI-compatible chat-completions endpoint (Ollama, llama.cpp's server, vLLM, etc.).

Same import-isolation contract as `anthropic_client.py`: `import openai` happens
*inside* `__init__`, never at module top, so this module stays importable without the
`openai` package installed. `tests/test_minting_driver_clients_import.py` proves it.

**This is a mapper, not an agent.** One `propose_next` call issues (at most) one
`chat.completions.create` request and reads back (at most) one tool call. See
`anthropic_client.py`'s module docstring — the same one-call-per-turn, no-planning
guardrail applies here.
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

        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=self._openai_messages,
            tools=self._tools,
        )

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


__all__ = ["LocalOpenAICompatModel", "LOCAL_SENTINEL_API_KEY", "DEFAULT_MAX_TOKENS"]
