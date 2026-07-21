"""RED-first tests for the thin MCP request builders + reply parser (Task 2).

Pure functions over dicts — no I/O, no subprocess — so these are plain unit
tests, unlike `test_minting_driver_transport.py`.
"""

from __future__ import annotations

from eval.minting_driver.mcp import (
    MonotonicIds,
    initialize,
    parse_tools_call_reply,
    tools_call,
    tools_list,
)
from eval.minting_driver.model import Message


def test_monotonic_ids_start_at_one_and_increment() -> None:
    next_id = MonotonicIds()
    assert [next_id(), next_id(), next_id()] == [1, 2, 3]


def test_monotonic_ids_instances_are_independent() -> None:
    a, b = MonotonicIds(), MonotonicIds()
    assert next(a) == 1
    assert next(a) == 2
    assert next(b) == 1  # a fresh allocator restarts at 1, unaffected by `a`


def test_initialize_builds_a_jsonrpc_request_carrying_the_given_id() -> None:
    request = initialize(1)
    assert request["jsonrpc"] == "2.0"
    assert request["id"] == 1
    assert request["method"] == "initialize"
    assert request["params"]["protocolVersion"]
    assert request["params"]["clientInfo"]["name"]


def test_tools_list_builds_a_jsonrpc_request_carrying_the_given_id() -> None:
    request = tools_list(2)
    assert request == {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def test_tools_call_builds_a_jsonrpc_request_with_name_and_arguments() -> None:
    request = tools_call(3, "read_file", {"path": "a.txt"})
    assert request["jsonrpc"] == "2.0"
    assert request["id"] == 3
    assert request["method"] == "tools/call"
    assert request["params"] == {"name": "read_file", "arguments": {"path": "a.txt"}}


def test_tools_call_defaults_arguments_to_an_empty_dict() -> None:
    request = tools_call(4, "list_files")
    assert request["params"]["arguments"] == {}


def test_parse_tools_call_reply_extracts_text_content_into_a_message() -> None:
    reply = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"content": [{"type": "text", "text": "hello"}], "isError": False},
    }
    message = parse_tools_call_reply(reply)
    assert isinstance(message, Message)
    assert message.role == "tool"
    assert message.content == "hello"
    assert message.tool_result == reply["result"]


def test_parse_tools_call_reply_joins_multiple_text_parts() -> None:
    reply = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]
        },
    }
    message = parse_tools_call_reply(reply)
    assert message.content == "first\nsecond"


def test_parse_tools_call_reply_surfaces_a_jsonrpc_error() -> None:
    reply = {"jsonrpc": "2.0", "id": 3, "error": {"code": -32000, "message": "boom"}}
    message = parse_tools_call_reply(reply)
    assert message.role == "tool"
    assert "boom" in message.content
    assert message.tool_result == reply["error"]
