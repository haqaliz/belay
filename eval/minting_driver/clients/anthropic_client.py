"""`AnthropicModel` — a thin `Model` (`model.py`) adapter over the Anthropic Messages API.

**Import isolation is the point.** `import anthropic` happens *inside* `__init__`, not
at module top, so `import eval.minting_driver.clients.anthropic_client` succeeds even in
an environment where the `anthropic` package is not installed — only *constructing* an
`AnthropicModel` (with no injected `client`) requires the SDK to be present.
`tests/test_minting_driver_clients_import.py` is what proves this.

**This is a mapper, not an agent.** One `propose_next` call issues (at most) one
Anthropic Messages API request and reads back (at most) one tool call — no planning
loop, no retries, no memory beyond the running conversation the caller passes in every
turn plus the tool-use bookkeeping (`tool_use_id` correlation) needed to keep the
Anthropic conversation well-formed across turns. See the `_ingest_new_messages`
docstring for why that bookkeeping has to live here rather than in `model.Message`.
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Optional

from eval.minting_driver.model import Done, Message, ToolCall

#: Anthropic requires a `max_tokens` on every request; the driver's turns are short
#: tool-selection decisions, not long-form generation, so a conservative default is
#: fine and callers can override it.
DEFAULT_MAX_TOKENS = 4096


def _anthropic_tool(mcp_tool: dict) -> dict:
    """One MCP `tools/list` entry (`name` / `description` / `inputSchema`) -> one
    Anthropic tool-use tool definition (`name` / `description` / `input_schema`)."""
    return {
        "name": mcp_tool["name"],
        "description": mcp_tool.get("description", ""),
        "input_schema": mcp_tool.get("inputSchema", {"type": "object", "properties": {}}),
    }


class AnthropicModel:
    """`Model` backed by a real Anthropic client (Claude, tool-use enabled).

    `tools` is the MCP `tools/list` result (a list of `{"name", "description",
    "inputSchema"}` dicts) the loop's transport already fetched — this class does not
    fetch it itself (see the class docstring: it is a mapper, not an orchestrator).

    `api_key` defaults to `ANTHROPIC_API_KEY` from the environment. `client` is an
    injection seam for tests: pass any object exposing `.messages.create(...)` with the
    Anthropic response shape, and the real `anthropic` package is never imported or
    contacted.
    """

    def __init__(
        self,
        *,
        model: str,
        tools: list[dict],
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            import anthropic  # type: ignore[import-not-found]  # lazy: SDK not in core import graph

            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError(
                    "AnthropicModel: no api_key given and ANTHROPIC_API_KEY is not set "
                    "in the environment. Set ANTHROPIC_API_KEY, pass api_key=..., or "
                    "inject a fake client=... for testing."
                )
            self._client = anthropic.Anthropic(api_key=key)

        self._model = model
        self._max_tokens = max_tokens
        self._tools = [_anthropic_tool(t) for t in tools]

        # Anthropic-format conversation state, built incrementally across calls. See
        # `_ingest_new_messages` for why this can't be reconstructed fresh from
        # `messages` alone every call.
        self._system_prompt = ""
        self._anthropic_messages: list[dict] = []
        self._seen = 0
        self._pending_tool_use_id: Optional[str] = None

    def _ingest_new_messages(self, messages: list[Message]) -> None:
        """Fold every `Message` this instance hasn't seen yet into Anthropic-format
        conversation state.

        `model.Message` deliberately carries no `tool_use_id` — it's the generic,
        provider-agnostic seam every `Model` implementation speaks (`model.py`'s
        docstring: "kept to three fields deliberately"). The Anthropic API, however,
        requires every `tool_result` content block to name the `tool_use_id` of the
        `tool_use` block it answers. This class is the one place that gap has to close:
        it remembers the id of the last tool call *it* emitted
        (`self._pending_tool_use_id`, set in `propose_next`) and stamps it onto the
        next `role="tool"` message it ingests. Because the driver loop guarantees at
        most one call in flight (`loop.py`'s in-flight invariant), there is never more
        than one pending id to track.
        """
        for message in messages[self._seen :]:
            if message.role == "system":
                # The loop sends exactly one system message, first (loop.py). Anthropic
                # takes `system` as a request-level string, not a conversation turn.
                self._system_prompt = message.content
            elif message.role == "tool":
                if self._pending_tool_use_id is None:
                    # No tool call is outstanding — either a caller bug (a tool-result
                    # ingested before any ToolCall was proposed) or an internal desync.
                    # Silently stamping `tool_use_id: None` onto the request produces a
                    # confusing 400 from the Anthropic API deep inside a live mint;
                    # raise here instead, where the cause is still clear.
                    raise ValueError(
                        "AnthropicModel: got a tool-result Message but there is no "
                        "pending tool_use_id to correlate it with (no ToolCall was "
                        "proposed since the last one was consumed). This message "
                        "cannot be sent to the Anthropic API without a valid "
                        "tool_use_id."
                    )
                is_error = message.content.startswith("error:")
                self._anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": self._pending_tool_use_id,
                                "content": message.content,
                                "is_error": is_error,
                            }
                        ],
                    }
                )
                self._pending_tool_use_id = None
            else:
                # "user" / "assistant" (or any other role a caller passes) map onto a
                # plain text turn.
                self._anthropic_messages.append({"role": message.role, "content": message.content})
        self._seen = len(messages)

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        self._ingest_new_messages(messages)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system_prompt,
            messages=self._anthropic_messages,
            tools=self._tools,
        )

        tool_use_blocks = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        # Preserve the assistant turn (including any tool_use block) in the running
        # Anthropic conversation, whether or not this turn ends in a tool call —
        # otherwise the next request would be missing what the model just said.
        self._anthropic_messages.append({"role": "assistant", "content": response.content})

        if not tool_use_blocks:
            text_parts = [
                getattr(block, "text", "") for block in response.content if getattr(block, "type", None) == "text"
            ]
            reason = " ".join(part for part in text_parts if part) or (
                getattr(response, "stop_reason", None) or "end_turn"
            )
            return Done(reason=reason)

        if len(tool_use_blocks) > 1:
            # Guardrail: one tool call per turn, never batched. Note it and move on —
            # this must never become a queue the loop has to drain.
            warnings.warn(
                f"AnthropicModel: model requested {len(tool_use_blocks)} tool calls in "
                "one turn; taking the first and ignoring the rest (no batching).",
                stacklevel=2,
            )

        chosen = tool_use_blocks[0]
        self._pending_tool_use_id = chosen.id
        return ToolCall(name=chosen.name, arguments=dict(chosen.input))


__all__ = ["AnthropicModel", "DEFAULT_MAX_TOKENS"]
