"""RED-first tests for the minting-driver's sequential loop (Task 3) — the CI
acceptance test for this whole unit.

Deterministic, offline, no LLM, no real subprocess: `ScriptedModel` supplies the model
side and `FakeTransport` (defined here) stands in for `StdioMcp`, recording call order
and enforcing — via an in-flight counter — that the loop never has more than one
`tools/call` outstanding at once. That invariant is the headline assertion; the rest lock
down strict `initialize` -> `tools/list` -> call ordering, `Done` termination, `max_steps`
capping a model that never stops, and that each tool result reaches the model before its
next proposal.
"""

from __future__ import annotations

from eval.minting_driver.fakes import ScriptedModel
from eval.minting_driver.loop import Transcript, run_task
from eval.minting_driver.model import Done, Message, ToolCall


class FakeTransport:
    """Records every `request` call's method in order and enforces the
    one-call-in-flight invariant with a re-entrancy counter.

    `tools/call` replies are canned per tool name via `tool_replies`;
    `initialize`/`tools/list` get fixed canned replies. Every `request` call appends its
    JSON-RPC `method` to `calls`, so a test can assert exact ordering against it.
    """

    def __init__(self, tool_replies: dict[str, dict] | None = None) -> None:
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._tool_replies = tool_replies or {}

    def request(self, obj: dict) -> dict:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        assert self.in_flight <= 1, "more than one request in flight at once"
        try:
            self.calls.append(obj["method"])
            if obj["method"] == "initialize":
                return {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
            if obj["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": obj["id"], "result": {"tools": []}}
            if obj["method"] == "tools/call":
                name = obj["params"]["name"]
                result = self._tool_replies.get(
                    name, {"content": [{"type": "text", "text": f"ran {name}"}]}
                )
                return {"jsonrpc": "2.0", "id": obj["id"], "result": result}
            raise AssertionError(f"unexpected method: {obj['method']}")
        finally:
            self.in_flight -= 1

    def notify(self, obj: dict) -> None:
        self.calls.append(obj["method"])

    def close(self) -> None:
        self.calls.append("close")


def test_never_more_than_one_tool_call_in_flight() -> None:
    steps: list[ToolCall | Done] = [
        ToolCall(name="read_file", arguments={"path": "a.py"}),
        ToolCall(name="run_tests", arguments={}),
        Done(reason="done"),
    ]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    run_task(model, transport, system="s", task="t", max_steps=10)

    assert transport.max_in_flight <= 1


def test_strict_ordering_initialize_then_initialized_then_tools_list_then_calls() -> None:
    steps: list[ToolCall | Done] = [ToolCall(name="read_file", arguments={}), Done(reason="done")]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    run_task(model, transport, system="s", task="t", max_steps=10)

    assert transport.calls[0] == "initialize"
    assert transport.calls[1] == "notifications/initialized"
    assert transport.calls[2] == "tools/list"
    assert transport.calls[3] == "tools/call"


def test_done_terminates_the_loop_without_issuing_a_tool_call() -> None:
    steps: list[ToolCall | Done] = [Done(reason="nothing to do")]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    transcript = run_task(model, transport, system="s", task="t", max_steps=10)

    assert transcript.stop_reason == "done"
    assert transcript.done == Done(reason="nothing to do")
    assert transcript.tool_calls == []
    assert transport.calls == ["initialize", "notifications/initialized", "tools/list"]


class AlwaysCallModel:
    """A model that never says `Done` — the fake that exercises `max_steps`."""

    def __init__(self) -> None:
        self.calls = 0

    def propose_next(self, messages: list[Message]) -> ToolCall:
        self.calls += 1
        return ToolCall(name="noop", arguments={})


def test_max_steps_caps_a_model_that_never_says_done() -> None:
    model = AlwaysCallModel()
    transport = FakeTransport()

    transcript = run_task(model, transport, system="s", task="t", max_steps=3)

    assert transcript.stop_reason == "max_steps"
    assert len(transcript.tool_calls) == 3
    assert model.calls == 3
    assert transport.calls.count("tools/call") == 3


def test_scripted_model_budget_stop_does_not_exhaust_the_script() -> None:
    """A script with more steps than `max_steps` never raises `ScriptExhausted` — the
    loop must stop at the budget rather than calling the model past it."""
    steps: list[ToolCall | Done] = [ToolCall(name="noop", arguments={}) for _ in range(5)]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    transcript = run_task(model, transport, system="s", task="t", max_steps=2)

    assert transcript.stop_reason == "max_steps"
    assert len(transcript.tool_calls) == 2


class RecordingModel:
    """Captures a snapshot of `messages` at each `propose_next` call, so a test can
    assert the prior tool result was appended before this call was made."""

    def __init__(self, steps: list[ToolCall | Done]) -> None:
        self._steps = list(steps)
        self.snapshots: list[list[Message]] = []

    def propose_next(self, messages: list[Message]) -> ToolCall | Done:
        self.snapshots.append(list(messages))
        return self._steps.pop(0)


def test_each_tool_result_is_appended_before_the_next_proposal() -> None:
    steps: list[ToolCall | Done] = [
        ToolCall(name="read_file", arguments={}),
        ToolCall(name="run_tests", arguments={}),
        Done(reason="done"),
    ]
    model = RecordingModel(steps)
    transport = FakeTransport(
        tool_replies={"read_file": {"content": [{"type": "text", "text": "file contents"}]}}
    )

    run_task(model, transport, system="s", task="t", max_steps=10)

    # First proposal: only the system + task messages, no tool results yet.
    assert len(model.snapshots[0]) == 2
    # Second proposal: the first tool's result must already be appended.
    assert len(model.snapshots[1]) == 3
    assert model.snapshots[1][-1].role == "tool"
    assert model.snapshots[1][-1].content == "file contents"
    # Third proposal: both tool results present.
    assert len(model.snapshots[2]) == 4


def test_transcript_shape_is_minimal_and_inspectable() -> None:
    steps: list[ToolCall | Done] = [
        ToolCall(name="read_file", arguments={"path": "a.py"}),
        Done(reason="done"),
    ]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    transcript = run_task(model, transport, system="s", task="t", max_steps=10)

    assert isinstance(transcript, Transcript)
    assert transcript.tool_calls == [ToolCall(name="read_file", arguments={"path": "a.py"})]
    assert transcript.stop_reason == "done"
    assert any(m.role == "tool" for m in transcript.messages)


def test_notifications_initialized_sent_after_initialize_before_tools_list() -> None:
    """MCP requires `notifications/initialized` after the `initialize` reply and before
    any `tools/list`/`tools/call`. `FakeTransport.notify` records into the same ordered
    `calls` list as `request`, so this is a direct assertion on the merged sequence."""
    steps: list[ToolCall | Done] = [Done(reason="done")]
    model = ScriptedModel(steps)
    transport = FakeTransport()

    run_task(model, transport, system="s", task="t", max_steps=10)

    assert "notifications/initialized" in transport.calls
    initialize_idx = transport.calls.index("initialize")
    initialized_idx = transport.calls.index("notifications/initialized")
    tools_list_idx = transport.calls.index("tools/list")
    assert initialize_idx < initialized_idx < tools_list_idx


class StrictHandshakeTransport:
    """A server-ish fake that RAISES if `tools/list` (or `tools/call`) arrives before
    `notifications/initialized` was sent — proving the loop actually satisfies the MCP
    handshake ordering, not just that a lenient fake happens to record it in order."""

    def __init__(self) -> None:
        self._initialized_sent = False
        self.calls: list[str] = []

    def request(self, obj: dict) -> dict:
        method = obj["method"]
        self.calls.append(method)
        if method != "initialize" and not self._initialized_sent:
            raise AssertionError(
                f"{method} arrived before notifications/initialized was sent"
            )
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {"tools": []}}
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        self.calls.append(obj["method"])
        if obj["method"] == "notifications/initialized":
            self._initialized_sent = True


def test_strict_handshake_server_accepts_the_loops_ordering() -> None:
    """A fake that would raise on premature `tools/list`/`tools/call` does not raise —
    the loop sends `notifications/initialized` before either."""
    steps: list[ToolCall | Done] = [ToolCall(name="read_file", arguments={}), Done(reason="done")]
    model = ScriptedModel(steps)
    transport = StrictHandshakeTransport()

    transcript = run_task(model, transport, system="s", task="t", max_steps=10)

    assert transcript.stop_reason == "done"
    assert "notifications/initialized" in transport.calls


class TimeoutRecordingTransport:
    """Records the `timeout` each `request` call receives — `None` when the loop omits
    the kwarg entirely, a float when `request_timeout` is threaded through. Lets a test
    assert exactly what per-request ceiling reaches `transport.request` for every call
    (`initialize`, `tools/list`, `tools/call`)."""

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        self.timeouts.append(timeout)
        method = obj["method"]
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": obj["id"], "result": {"tools": []}}
        if method == "tools/call":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        pass


def test_request_timeout_reaches_every_transport_request() -> None:
    """`run_task(..., request_timeout=45.0)` threads 45.0 into every `transport.request`
    call — `initialize` (the cold-start ceiling) and each shell `tools/call` alike."""
    steps: list[ToolCall | Done] = [ToolCall(name="run_tests", arguments={}), Done(reason="done")]
    model = ScriptedModel(steps)
    transport = TimeoutRecordingTransport()

    run_task(model, transport, system="s", task="t", max_steps=10, request_timeout=45.0)

    # initialize, tools/list, one tools/call — all three see 45.0.
    assert transport.timeouts == [45.0, 45.0, 45.0]


def test_request_timeout_none_omits_the_kwarg_preserving_default_behavior() -> None:
    """With no `request_timeout` the loop passes no `timeout` kwarg at all, so the
    transport falls back to its own `DEFAULT_TIMEOUT` — today's behavior, byte-identical.
    The recording fake reports `None` for a call it received without the kwarg."""
    steps: list[ToolCall | Done] = [ToolCall(name="run_tests", arguments={}), Done(reason="done")]
    model = ScriptedModel(steps)
    transport = TimeoutRecordingTransport()

    run_task(model, transport, system="s", task="t", max_steps=10)

    assert transport.timeouts == [None, None, None]
