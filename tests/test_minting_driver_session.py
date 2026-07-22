"""RED-first tests for `eval.minting_driver.session.run_session` — transport lifecycle
ownership (Task 4, Part C).

`run_task` (`loop.py`) never constructs or closes a transport; `run_session` is the real
entrypoint that does, and must close it exactly once on every path: normal completion, a
model that exhausts `max_steps`, and `run_task` raising. Fully deterministic — a fake
transport factory stands in for `StdioMcp`, so no real subprocess and no real model are
ever involved here (that's Task 5's manual-gated territory).
"""

from __future__ import annotations

import pytest

from eval.minting_driver.fakes import ScriptedModel
from eval.minting_driver.model import Done, Message, ToolCall
from eval.minting_driver.session import run_session


class FakeCloseCountingTransport:
    """Records every `request`/`notify` method and counts `close()` calls."""

    def __init__(self, tool_replies: dict[str, dict] | None = None) -> None:
        self.calls: list[str] = []
        self.close_count = 0
        self._tool_replies = tool_replies or {}

    def request(self, obj: dict) -> dict:
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

    def notify(self, obj: dict) -> None:
        self.calls.append(obj["method"])

    def close(self) -> None:
        self.close_count += 1


class RaisingTransport(FakeCloseCountingTransport):
    """A transport whose `request` raises on the first `tools/call` — stands in for a
    real transport error (e.g. `ServerExited`) surfacing mid-run."""

    def request(self, obj: dict) -> dict:
        if obj["method"] == "tools/call":
            self.calls.append(obj["method"])
            raise RuntimeError("boom: simulated transport failure")
        return super().request(obj)


def test_run_session_closes_transport_exactly_once_on_normal_completion() -> None:
    transport = FakeCloseCountingTransport()
    model = ScriptedModel([Done(reason="done")])

    transcript = run_session(
        model,
        server_command=["fake-server"],
        env={},
        system="s",
        task="t",
        max_steps=10,
        transport_factory=lambda command, env: transport,
    )

    assert transcript.stop_reason == "done"
    assert transport.close_count == 1


def test_run_session_closes_transport_exactly_once_on_max_steps() -> None:
    transport = FakeCloseCountingTransport()

    class AlwaysCallModel:
        def propose_next(self, messages: list[Message]) -> ToolCall:
            return ToolCall(name="noop", arguments={})

    transcript = run_session(
        AlwaysCallModel(),
        server_command=["fake-server"],
        env={},
        system="s",
        task="t",
        max_steps=3,
        transport_factory=lambda command, env: transport,
    )

    assert transcript.stop_reason == "max_steps"
    assert transport.close_count == 1


def test_run_session_closes_transport_exactly_once_when_run_task_raises() -> None:
    transport = RaisingTransport()
    model = ScriptedModel([ToolCall(name="boom", arguments={})])

    with pytest.raises(RuntimeError, match="boom"):
        run_session(
            model,
            server_command=["fake-server"],
            env={},
            system="s",
            task="t",
            max_steps=10,
            transport_factory=lambda command, env: transport,
        )

    assert transport.close_count == 1


class TimeoutRecordingTransport(FakeCloseCountingTransport):
    """`FakeCloseCountingTransport` that also records the `timeout` each `request`
    receives (`None` when the kwarg is omitted), so a test can assert `run_session`
    forwards its `request_timeout` down into every `run_task` -> `transport.request`."""

    def __init__(self, tool_replies: dict[str, dict] | None = None) -> None:
        super().__init__(tool_replies)
        self.timeouts: list[float | None] = []

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        self.timeouts.append(timeout)
        return super().request(obj)


def test_run_session_forwards_request_timeout_to_run_task() -> None:
    transport = TimeoutRecordingTransport()
    model = ScriptedModel([ToolCall(name="noop", arguments={}), Done(reason="done")])

    run_session(
        model,
        server_command=["fake-server"],
        env={},
        system="s",
        task="t",
        max_steps=10,
        transport_factory=lambda command, env: transport,
        request_timeout=45.0,
    )

    assert transport.timeouts == [45.0, 45.0, 45.0]


def test_run_session_defaults_request_timeout_to_none_omitting_the_kwarg() -> None:
    transport = TimeoutRecordingTransport()
    model = ScriptedModel([ToolCall(name="noop", arguments={}), Done(reason="done")])

    run_session(
        model,
        server_command=["fake-server"],
        env={},
        system="s",
        task="t",
        max_steps=10,
        transport_factory=lambda command, env: transport,
    )

    assert transport.timeouts == [None, None, None]


def test_run_session_passes_server_command_and_env_to_factory() -> None:
    seen: dict = {}

    def factory(command: list[str], env: dict) -> FakeCloseCountingTransport:
        seen["command"] = command
        seen["env"] = env
        return FakeCloseCountingTransport()

    model = ScriptedModel([Done(reason="done")])

    run_session(
        model,
        server_command=["some-server", "--flag"],
        env={"FOO": "bar"},
        system="s",
        task="t",
        max_steps=10,
        transport_factory=factory,
    )

    assert seen["command"] == ["some-server", "--flag"]
    assert seen["env"] == {"FOO": "bar"}
