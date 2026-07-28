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

#: Sentinel for "do not set this attribute at all", distinct from `None` (which a real
#: SDK does sometimes send as a *value*). `run-accounting`'s whole honesty contract is
#: that an unmeasured quantity stays distinguishable from a measured one, so the fakes
#: have to be able to express "the attribute is not there" without ambiguity.
_ABSENT = object()


# ---------------------------------------------------------------------------
# Fake Anthropic client
# ---------------------------------------------------------------------------


def _anthropic_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _anthropic_tool_use_block(*, id: str, name: str, input: dict) -> SimpleNamespace:  # noqa: A002
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def _anthropic_response(
    *,
    content: list[SimpleNamespace],
    stop_reason: str = "end_turn",
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """The response tree `AnthropicModel.propose_next` reads.

    `usage` is attached ONLY when given, so the default response genuinely has **no
    `usage` attribute at all** — that is the shape the absent-not-zero test needs, and a
    `usage=None` attribute would be a different (and weaker) thing to assert against.
    """
    response = SimpleNamespace(content=content, stop_reason=stop_reason)
    if usage is not None:
        response.usage = usage
    return response


def _anthropic_usage(
    *, input_tokens: object = _ABSENT, output_tokens: object = _ABSENT
) -> SimpleNamespace:
    """Anthropic's `response.usage` shape: `input_tokens` / `output_tokens`.

    A field left at `_ABSENT` is not set at all, so a provider that reports only half of
    the pair can be simulated exactly — `getattr(usage, "output_tokens", None)` is the
    real code path, and a `None`-valued attribute would not exercise it.
    """
    usage = SimpleNamespace()
    if input_tokens is not _ABSENT:
        usage.input_tokens = input_tokens
    if output_tokens is not _ABSENT:
        usage.output_tokens = output_tokens
    return usage


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
    usage: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Same `usage`-only-when-given rule as `_anthropic_response` — see there."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    response = SimpleNamespace(choices=[choice])
    if usage is not None:
        response.usage = usage
    return response


def _openai_usage(
    *, prompt_tokens: object = _ABSENT, completion_tokens: object = _ABSENT
) -> SimpleNamespace:
    """OpenAI's `response.usage` shape: `prompt_tokens` / `completion_tokens`.

    Deliberately the OTHER provider's field names. The two shapes are what make the
    normalization in the clients (`prompt_tokens` -> `input_tokens`) a real behavior with
    a real test, rather than a pass-through nobody would notice breaking.
    """
    usage = SimpleNamespace()
    if prompt_tokens is not _ABSENT:
        usage.prompt_tokens = prompt_tokens
    if completion_tokens is not _ABSENT:
        usage.completion_tokens = completion_tokens
    return usage


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


# ---------------------------------------------------------------------------
# 6. `run-accounting` Phase 1: usage + request counting on the client itself
#
# Nothing recorded what a mint cost. Both clients read `.choices` / `.content` off the
# response and let `.usage` fall out of scope when `response` did
# (`run-accounting/spec.md`: "present and **discarded when `response` goes out of
# scope**"). These tests pin the accumulation, and — the load-bearing one — pin that a
# provider which reports NO usage yields ABSENT, never a measured-looking `0`.
# ---------------------------------------------------------------------------


def test_local_accumulates_openai_shaped_usage_across_calls() -> None:
    """Two calls SUM, and OpenAI's field names are normalized to the recorded ones.

    Summed, not overwritten: one client lives for exactly one instance
    (`entrypoint.make_model_factory` builds a fresh one per instance), so its `usage` is
    that instance's whole token bill, not its last turn's.
    """
    client = FakeOpenAIClient(
        [
            _openai_response(
                tool_calls=[
                    _openai_tool_call(id="call_1", name="read_file", arguments="{}")
                ],
                finish_reason="tool_calls",
                usage=_openai_usage(prompt_tokens=100, completion_tokens=20),
            ),
            _openai_response(
                content="done",
                finish_reason="stop",
                usage=_openai_usage(prompt_tokens=150, completion_tokens=5),
            ),
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    messages = [Message(role="system", content="sys"), Message(role="user", content="go")]
    model.propose_next(messages)
    messages.append(Message(role="tool", content="ok", tool_result={"ok": True}))
    model.propose_next(messages)

    assert model.usage == {"input_tokens": 250, "output_tokens": 25}
    assert model.request_count == 2


def test_anthropic_accumulates_anthropic_shaped_usage_across_calls() -> None:
    client = FakeAnthropicClient(
        [
            _anthropic_response(
                content=[
                    _anthropic_tool_use_block(id="toolu_1", name="read_file", input={})
                ],
                usage=_anthropic_usage(input_tokens=100, output_tokens=20),
            ),
            _anthropic_response(
                content=[_anthropic_text_block("done")],
                usage=_anthropic_usage(input_tokens=150, output_tokens=5),
            ),
        ]
    )
    model = AnthropicModel(model="claude-x", tools=[], client=client)

    messages = [Message(role="system", content="sys"), Message(role="user", content="go")]
    model.propose_next(messages)
    messages.append(Message(role="tool", content="ok", tool_result={"ok": True}))
    model.propose_next(messages)

    assert model.usage == {"input_tokens": 250, "output_tokens": 25}
    assert model.request_count == 2


def test_a_response_with_no_usage_field_yields_absent_usage_not_zero() -> None:
    """**The absent-not-zero test.** The honesty contract in miniature.

    A provider that reports no usage at all (`claude -p --output-format json` may well be
    one) must leave `usage` at `None` — an unmeasured quantity rendered as a measured `0`
    is the same mistake as rendering `UNVERIFIED` as `PASS`, and it would put a fake zero
    into the published cost of the number. The request still happened, so `request_count`
    still increments: *that* is a measured quantity.
    """
    openai_client = FakeOpenAIClient([_openai_response(content="done")])
    local = LocalOpenAICompatModel(model="local-x", tools=[], client=openai_client)
    local.propose_next([Message(role="user", content="go")])

    assert local.usage is None
    assert local.usage != {"input_tokens": 0, "output_tokens": 0}
    assert local.request_count == 1

    anthropic_client = FakeAnthropicClient(
        [_anthropic_response(content=[_anthropic_text_block("done")])]
    )
    claude = AnthropicModel(model="claude-x", tools=[], client=anthropic_client)
    claude.propose_next([Message(role="user", content="go")])

    assert claude.usage is None
    assert claude.request_count == 1


def test_a_partial_usage_records_the_present_field_and_omits_the_missing_one() -> None:
    """Half-reported usage is half-recorded, not half-invented and not an exception.

    Same rule one level down: the KEY is omitted for the field the provider did not send,
    so a later total over `output_tokens` cannot silently absorb a zero that was never
    measured.
    """
    client = FakeOpenAIClient(
        [_openai_response(content="done", usage=_openai_usage(prompt_tokens=42))]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    model.propose_next([Message(role="user", content="go")])

    assert model.usage == {"input_tokens": 42}
    assert "output_tokens" not in model.usage


def test_usage_that_is_not_a_number_is_ignored_rather_than_raising() -> None:
    """A hostile / unexpected usage shape degrades to absent; it never breaks a live mint.

    Everything here is read with `getattr` for this reason: accounting is bookkeeping
    beside the mint, and a bookkeeping error must never be what ends an instance that was
    otherwise about to produce an observation.
    """
    client = FakeOpenAIClient(
        [
            _openai_response(
                content="done",
                usage=_openai_usage(prompt_tokens="lots", completion_tokens=7),
            )
        ]
    )
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    model.propose_next([Message(role="user", content="go")])

    assert model.usage == {"output_tokens": 7}


def test_request_count_starts_at_zero_and_counts_a_request_that_failed() -> None:
    """A request that errored still consumed the provider's quota, so it still counts.

    This is the 2026-07-24 lesson as a counter: the 56 burned instances each spent a real
    request and got a 429 back. An accounting that only counted *successful* calls would
    under-report exactly the spend a stop-loss exists to bound.
    """

    class _Boom:
        def create(self, **kwargs: object) -> object:
            raise RuntimeError("429 rate limited")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Boom()))
    model = LocalOpenAICompatModel(model="local-x", tools=[], client=client)

    assert model.request_count == 0
    with pytest.raises(RuntimeError):
        model.propose_next([Message(role="user", content="go")])
    assert model.request_count == 1
    assert model.usage is None


def test_each_client_names_its_own_model_and_provider() -> None:
    """Per-instance provenance (PRD must-have 16), read off the client itself.

    The 12 banked instances ran on one model and the remainder will not, so the published
    number has to be able to say which model minted which instance. Recorded from the
    object that actually made the calls rather than from the config, so a mint whose
    config and wiring disagree cannot report the config's answer.
    """
    local = LocalOpenAICompatModel(
        model="gemini-flash-latest", tools=[], client=FakeOpenAIClient([])
    )
    claude = AnthropicModel(
        model="claude-x", tools=[], client=FakeAnthropicClient([])
    )

    assert local.model == "gemini-flash-latest"
    assert local.provider == "openai-compat"
    assert claude.model == "claude-x"
    assert claude.provider == "anthropic"
