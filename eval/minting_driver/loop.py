"""The sequential minting-driver loop — the shippable proof for this unit.

`run_task` ties `Model` (`model.py`) and a transport (`transport.py`'s `StdioMcp`, or any
object structurally matching `Transport` below — see `tests/test_minting_driver_loop.py`'s
`FakeTransport`) together into the smallest possible agent loop: send `initialize`, send
`tools/list`, then repeat "ask the model for the next step; if it is a tool call, send it
and await the reply before asking again" until the model says `Done` or `max_steps` is
reached.

**This is not an agent framework.** One call in flight at a time, no planning, no memory
strategy beyond a flat running message list, no multi-tool batching, no retries. The
in-flight invariant — never issue a second `tools/call` before the first's reply is in
hand — falls out of the control flow itself: `transport.request(...)` is a blocking call
that returns the reply, and `model.propose_next(...)` is only ever invoked after the
previous `request(...)` call has returned. There is nowhere in this function a second
request could be sent while the first is outstanding; `tests/test_minting_driver_loop.py`
makes that structural fact an explicit, testable assertion via a re-entrancy counter on a
fake transport.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from eval.minting_driver.mcp import (
    MonotonicIds,
    initialize,
    initialized,
    parse_tools_call_reply,
    tools_call,
    tools_list,
)
from eval.minting_driver.model import Done, Message, Model, ToolCall


class Transport(Protocol):
    """The two methods the loop needs from a transport: `request` sends a JSON-RPC
    request dict and blocks until its matching reply comes back; `notify` sends a
    JSON-RPC notification (no reply expected) — used for `notifications/initialized`,
    which MCP requires between the `initialize` reply and the first `tools/list`.
    `StdioMcp` (`transport.py`) and any test fake satisfy this structurally — no
    inheritance required.
    """

    def request(self, obj: dict) -> dict: ...

    def notify(self, obj: dict) -> None: ...


@dataclass(frozen=True)
class Transcript:
    """The minimal record of one `run_task` call — just enough to inspect what happened.

    `messages` is the final running history (system + task + each tool result, in the
    order the model saw them). `tool_calls` is every `ToolCall` issued, in order.
    `stop_reason` is `"done"` when the model returned `Done`, or `"max_steps"` when the
    step budget was reached first; `done` carries the model's `Done` value when that is
    why the loop stopped, `None` otherwise.
    """

    messages: list[Message]
    tool_calls: list[ToolCall]
    stop_reason: str
    done: Optional[Done] = None


def run_task(
    model: Model,
    transport: Transport,
    *,
    system: str,
    task: str,
    max_steps: int,
) -> Transcript:
    """Drive one sequential MCP agent turn-loop to completion.

    Sequence: `initialize` (awaited), `notifications/initialized` (sent, not awaited —
    MCP requires this notification after the `initialize` reply and before any
    `tools/list`/`tools/call`), `tools/list` (awaited), then up to `max_steps`
    iterations of "propose -> if `Done`, stop; else send exactly one `tools/call`, await
    its reply, append the parsed result to `messages`, repeat." The model is never asked
    for a step beyond the budget: the loop calls `propose_next` at most `max_steps`
    times, so a model that never says `Done` still only issues `max_steps` tool calls.
    """
    next_id = MonotonicIds()
    transport.request(initialize(next_id()))
    transport.notify(initialized())
    transport.request(tools_list(next_id()))

    messages: list[Message] = [
        Message(role="system", content=system),
        Message(role="user", content=task),
    ]
    tool_calls: list[ToolCall] = []

    for _ in range(max_steps):
        step = model.propose_next(messages)
        if isinstance(step, Done):
            return Transcript(
                messages=messages, tool_calls=tool_calls, stop_reason="done", done=step
            )
        tool_calls.append(step)
        reply = transport.request(tools_call(next_id(), step.name, step.arguments))
        messages.append(parse_tools_call_reply(reply))

    return Transcript(messages=messages, tool_calls=tool_calls, stop_reason="max_steps")


__all__ = ["Transcript", "Transport", "run_task"]
