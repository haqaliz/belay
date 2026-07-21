"""The model seam: the injectable contract the minting-driver loop speaks to.

Pure data + a `Protocol` — no I/O, no network, no LLM client lives here. Task 3's driver
loop calls `Model.propose_next` once per turn and acts on what comes back; this module
only defines the shapes involved, so the loop can be built and tested (via
`fakes.ScriptedModel`) before any real model is wired in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass(frozen=True)
class Message:
    """One entry in the running conversation handed to the model each turn.

    `role` is the conventional chat-role string (e.g. "system" / "user" / "assistant" /
    "tool"). `content` is the human-readable text. `tool_result` is the optional
    structured payload of a tool call's outcome — set on the message the loop appends
    after executing a `ToolCall`, so the next `propose_next` call can see what happened.
    Kept to three fields deliberately: the loop's history is a flat list of these.
    """

    role: str
    content: str
    tool_result: Optional[Any] = None


@dataclass(frozen=True)
class ToolCall:
    """A model's request to invoke one MCP tool."""

    name: str
    arguments: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Done:
    """A model's declaration that the task is finished — the loop's stop signal."""

    reason: str


class Model(Protocol):
    """The injectable seam between the driver loop and whatever proposes the next step.

    One method: given the running message history, propose either the next tool call or
    a `Done`. A real implementation wraps an LLM client; `fakes.ScriptedModel` replays a
    fixed script instead, so the loop is testable without a live model or network access.
    """

    def propose_next(self, messages: list[Message]) -> ToolCall | Done: ...
