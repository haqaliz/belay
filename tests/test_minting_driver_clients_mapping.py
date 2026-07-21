"""Behavioral response->`ToolCall`/`Done` mapping tests for the BYOK clients (Task 8 fix).

`AnthropicModel` (`clients/anthropic_client.py`) and `LocalOpenAICompatModel`
(`clients/local_client.py`) both accept an injected `client=` — a fake object shaped like
the real SDK's client (`.messages.create(...)` / `.chat.completions.create(...)`) — for
exactly this: exercising the response-parsing and cross-turn bookkeeping logic with zero
network and zero `anthropic`/`openai` import, so these tests run in the DEFAULT CI env
(`tests/test_minting_driver_clients_import.py` proves the SDKs are never imported merely
by importing the client modules; injecting a fake `client=` here never triggers the lazy
`import anthropic`/`import openai` in `__init__` either, since that only runs when
`client` is `None`).

The fakes below are deliberately minimal `SimpleNamespace` trees shaped exactly like the
attributes each client reads off a real response — not full SDK response classes — because
the clients only ever access those specific attributes (`response.content[i].type`, etc.).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from eval.minting_driver.clients.anthropic_client import AnthropicModel
from eval.minting_driver.clients.local_client import LocalOpenAICompatModel
from eval.minting_driver.model import Done, Message, ToolCall

# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


def _anthropic_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _anthropic_tool_use_block(*, id: str, name: str, input: dict) -> SimpleNamespace:  # noqa: A002
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _anthropic_response(
    *, content: list[SimpleNamespace], stop_reason: str = "end_turn"
) -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class _FakeAnthropicMessages:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        # `kwargs["messages"]` is the client's own live list (`self._anthropic_messages`),
        # mutated again right after this call returns (the assistant reply gets appended).
        # Snapshot it now — a shallow copy of the list, not its dict entries, which are
        # never mutated in place once appended — so a test inspecting `calls[i]` later sees
        # the request exactly as it was sent, not as it looks after subsequent turns.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])  # type: ignore[arg-type]
        self.calls.append(snapshot)
        if not self._responses:
            raise AssertionError("FakeAnthropicMessages.create called more times than scripted")
        return self._responses.pop(0)


class FakeAnthropicClient:
    """Shaped like `anthropic.Anthropic()`: exposes `.messages.create(...)`."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.messages = _FakeAnthropicMessages(responses)


# ---------------------------------------------------------------------------
# Fake OpenAI-compat client
# ---------------------------------------------------------------------------


def _openai_tool_call(*, id: str, name: str, arguments: str) -> SimpleNamespace:  # noqa: A002
    return SimpleNamespace(id=id, function=SimpleNamespace(name=name, arguments=arguments))


def _openai_response(
    *,
    content: str | None = None,
    tool_calls: list[SimpleNamespace] | None = None,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


class _FakeOpenAICompletions:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        # Same snapshot reasoning as `_FakeAnthropicMessages.create` above.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])  # type: ignore[arg-type]
        self.calls.append(snapshot)
        if not self._responses:
            raise AssertionError("FakeOpenAICompletions.create called more times than scripted")
        return self._responses.pop(0)


class FakeOpenAIClient:
    """Shaped like `openai.OpenAI()`: exposes `.chat.completions.create(...)`."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.chat = SimpleNamespace(completions=_FakeOpenAICompletions(responses))


# ---------------------------------------------------------------------------
# 1. One tool call -> correct ToolCall(name, arguments as dict)
# ---------------------------------------------------------------------------


def test_anthropic_single_tool_call_maps_to_tool_call_with_dict_arguments() -> None:
    client = FakeAnthropicClient(
        [
            _anthropic_response(
                content=[
                    _anthropic_tool_use_block(
                        id="toolu_1", name="read_file", input={"path": "a.txt"}
                    )
                ]
            )
        ]
    )
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    result = model.propose_next(
        [Message(role="system", content="sys"), Message(role="user", content="go")]
    )

    assert result == ToolCall(name="read_file", arguments={"path": "a.txt"})
    assert isinstance(result.arguments, dict)


def test_local_single_tool_call_maps_to_tool_call_with_dict_arguments() -> None:
    client = FakeOpenAIClient(
        [
            _openai_response(
                tool_calls=[
                    _openai_tool_call(
                        id="call_1", name="read_file", arguments='{"path": "a.txt"}'
                    )
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    result = model.propose_next(
        [Message(role="system", content="sys"), Message(role="user", content="go")]
    )

    assert result == ToolCall(name="read_file", arguments={"path": "a.txt"})
    assert isinstance(result.arguments, dict)


# ---------------------------------------------------------------------------
# 2. No tool call / stop / end_turn -> Done
# ---------------------------------------------------------------------------


def test_anthropic_no_tool_call_maps_to_done() -> None:
    client = FakeAnthropicClient(
        [_anthropic_response(content=[_anthropic_text_block("all finished")], stop_reason="end_turn")]
    )
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    result = model.propose_next(
        [Message(role="system", content="sys"), Message(role="user", content="go")]
    )

    assert isinstance(result, Done)
    assert "all finished" in result.reason


def test_local_no_tool_call_maps_to_done() -> None:
    client = FakeOpenAIClient([_openai_response(content="all finished", finish_reason="stop")])
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    result = model.propose_next(
        [Message(role="system", content="sys"), Message(role="user", content="go")]
    )

    assert isinstance(result, Done)
    assert result.reason == "all finished"


# ---------------------------------------------------------------------------
# 3. Multiple tool calls -> exactly ONE ToolCall (the first), no batching
# ---------------------------------------------------------------------------


def test_anthropic_multiple_tool_calls_takes_only_the_first() -> None:
    client = FakeAnthropicClient(
        [
            _anthropic_response(
                content=[
                    _anthropic_tool_use_block(id="toolu_1", name="first_tool", input={"a": 1}),
                    _anthropic_tool_use_block(id="toolu_2", name="second_tool", input={"b": 2}),
                ]
            )
        ]
    )
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    with pytest.warns(UserWarning, match="2 tool calls"):
        result = model.propose_next(
            [Message(role="system", content="sys"), Message(role="user", content="go")]
        )

    assert result == ToolCall(name="first_tool", arguments={"a": 1})


def test_local_multiple_tool_calls_takes_only_the_first() -> None:
    client = FakeOpenAIClient(
        [
            _openai_response(
                tool_calls=[
                    _openai_tool_call(id="call_1", name="first_tool", arguments='{"a": 1}'),
                    _openai_tool_call(id="call_2", name="second_tool", arguments='{"b": 2}'),
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    with pytest.warns(UserWarning, match="2 tool calls"):
        result = model.propose_next(
            [Message(role="system", content="sys"), Message(role="user", content="go")]
        )

    assert result == ToolCall(name="first_tool", arguments={"a": 1})


# ---------------------------------------------------------------------------
# 4. Malformed tool-call arguments -> a CLEAR error, not a raw JSONDecodeError
# ---------------------------------------------------------------------------


def test_local_malformed_tool_arguments_raises_clear_error_not_raw_json_decode_error() -> None:
    client = FakeOpenAIClient(
        [
            _openai_response(
                tool_calls=[
                    _openai_tool_call(id="call_1", name="read_file", arguments="{not valid json")
                ],
                finish_reason="tool_calls",
            )
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    with pytest.raises(ValueError) as exc_info:
        model.propose_next(
            [Message(role="system", content="sys"), Message(role="user", content="go")]
        )

    # json.JSONDecodeError IS a ValueError subclass, so pytest.raises(ValueError) alone
    # would also accept a raw, unhelpful JSONDecodeError leaking out of the client. Assert
    # it is specifically NOT that raw exception, and that the message names the offending
    # tool and payload so a failure at mint time is actionable, not a bare traceback.
    assert not isinstance(exc_info.value, json.JSONDecodeError)
    assert "read_file" in str(exc_info.value)
    assert "not valid json" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Multi-turn bookkeeping: tool_use/tool_call id correlation across turns
# ---------------------------------------------------------------------------


def test_anthropic_stamps_correct_tool_use_id_onto_next_tool_result() -> None:
    client = FakeAnthropicClient(
        [
            _anthropic_response(
                content=[
                    _anthropic_tool_use_block(id="toolu_abc", name="read_file", input={"path": "a.txt"})
                ]
            ),
            _anthropic_response(content=[_anthropic_text_block("done")], stop_reason="end_turn"),
        ]
    )
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    messages = [Message(role="system", content="sys"), Message(role="user", content="go")]
    first = model.propose_next(messages)
    assert isinstance(first, ToolCall)

    messages.append(Message(role="tool", content="file contents", tool_result={"ok": True}))
    second = model.propose_next(messages)
    assert isinstance(second, Done)

    second_call_kwargs = client.messages.calls[1]
    anthropic_messages = second_call_kwargs["messages"]
    tool_result_message = anthropic_messages[-1]
    assert tool_result_message["content"][0]["tool_use_id"] == "toolu_abc"


def test_local_stamps_correct_tool_call_id_onto_next_tool_result() -> None:
    client = FakeOpenAIClient(
        [
            _openai_response(
                tool_calls=[
                    _openai_tool_call(id="call_abc", name="read_file", arguments='{"path": "a.txt"}')
                ],
                finish_reason="tool_calls",
            ),
            _openai_response(content="done", finish_reason="stop"),
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    messages = [Message(role="system", content="sys"), Message(role="user", content="go")]
    first = model.propose_next(messages)
    assert isinstance(first, ToolCall)

    messages.append(Message(role="tool", content="file contents", tool_result={"ok": True}))
    second = model.propose_next(messages)
    assert isinstance(second, Done)

    second_call_kwargs = client.chat.completions.calls[1]
    openai_messages = second_call_kwargs["messages"]
    tool_result_message = openai_messages[-1]
    assert tool_result_message["tool_call_id"] == "call_abc"


def test_anthropic_raises_clear_error_on_tool_result_with_no_pending_tool_use_id() -> None:
    """A `tool`-role `Message` ingested before any `ToolCall` has been proposed (a caller
    bug, or a desynced/duplicated tool-result) must not silently stamp `tool_use_id: None`
    onto the Anthropic request — that produces a confusing 400 from the API, deep inside a
    live mint. It must raise a clear, local error instead."""
    client = FakeAnthropicClient([])  # must never be reached
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="go"),
        Message(role="tool", content="unexpected result", tool_result={"ok": True}),
    ]

    with pytest.raises(ValueError, match="tool_use_id|pending"):
        model.propose_next(messages)

    assert client.messages.calls == []


def test_local_raises_clear_error_on_tool_result_with_no_pending_tool_call_id() -> None:
    """Same guarantee as the Anthropic test above, for the OpenAI-compat `tool_call_id`."""
    client = FakeOpenAIClient([])  # must never be reached
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="go"),
        Message(role="tool", content="unexpected result", tool_result={"ok": True}),
    ]

    with pytest.raises(ValueError, match="tool_call_id|pending"):
        model.propose_next(messages)

    assert client.chat.completions.calls == []
