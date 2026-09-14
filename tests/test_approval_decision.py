"""The approval gate's pure decision core: parse a frame, decide, hold.

Aspect `approval-gate/decision-model` (spec.md). Everything here is a pure
function of bytes and dicts — no I/O, no proxy coupling, no trace writes — so
the tests below drive plain frames and plain facts.

The two honesty rules that shape this module:

- **Never hold on doubt.** A frame that is not a single `tools/call` REQUEST
  (notification, response, batch, garbage) is forwarded untouched, and a
  `params.name` that is not a string yields no tool name. A hold is a state
  change the proxy makes; doubt must never manufacture one.
- **A default is not a declaration.** `triggers_for` reads the tri-state
  vocabulary from `belay.declared` — only `declared-true` on `destructiveHint`
  or `openWorldHint` triggers a hold. The MCP spec's fail-safe defaults
  (`destructiveHint: true`, `openWorldHint: true` when omitted) are exactly the
  declarations that must NOT trigger one.

Batch JSON-RPC frames (arrays) are never held: holding one would require
rewriting the frame to split it, which the proxy cannot do — they are
forwarded untouched.
"""

from __future__ import annotations

import json

import pytest

from belay.approval.gate import is_tools_call, request_id, tool_name


def tools_call(**overrides: object) -> bytes:
    """A single `tools/call` REQUEST, as the wire would carry it (bytes)."""
    frame = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "write_file", "arguments": {"path": "/tmp/x"}},
        "id": 1,
    }
    frame.update(overrides)
    return json.dumps(frame).encode()


def test_is_tools_call_true_for_single_tools_call_requests():
    """String, int, and null ids are all valid JSON-RPC request ids."""
    assert is_tools_call(tools_call(id="abc"))
    assert is_tools_call(tools_call(id=7))
    assert is_tools_call(tools_call(id=None))


def test_is_tools_call_false_for_a_notification():
    """A `tools/call` without an `id` is a notification, never a hold candidate."""
    notification = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "write_file"},
    }
    assert not is_tools_call(json.dumps(notification).encode())


def test_is_tools_call_false_for_other_methods():
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": 1}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": None}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 2}).encode())


def test_is_tools_call_false_for_response_frames():
    """A response carries `result`/`error`, never a `method` — structurally not a call."""
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode())
    assert not is_tools_call(json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "nope"}}).encode())


def test_is_tools_call_false_for_a_batch():
    """Batch frames are arrays; the gate never holds one (see the module docstring)."""
    batch = [tools_call(id=1), tools_call(id=2)]
    assert not is_tools_call(b"[" + b",".join(batch) + b"]")


def test_is_tools_call_never_raises_on_garbage():
    """The hook runs on every c2s frame; a raise would kill the direction it guards."""
    for garbage in (b"", b"{", b"not json", b"\x00\xff\xfe", b"[]", b"null", b"42"):
        assert is_tools_call(garbage) is False


def test_tool_name_extracts_the_string_name():
    assert tool_name(tools_call()) == "write_file"
    assert tool_name(tools_call(params={"name": "read_file"})) == "read_file"


def test_tool_name_non_string_name_yields_none():
    """`params.name: 42` is not a tool name; doubt yields no hold."""
    assert tool_name(tools_call(params={"name": 42})) is None
    assert tool_name(tools_call(params={"name": None})) is None
    assert tool_name(tools_call(params={"name": {"nested": True}})) is None


def test_tool_name_absent_or_unreadable_params_yields_none():
    assert tool_name(tools_call(params={})) is None
    assert tool_name(tools_call(params=None)) is None
    # JSON-RPC 2.0 permits positional params (a list); a list has no `name`.
    assert tool_name(tools_call(params=["write_file", {}])) is None
    assert tool_name(b"garbage") is None


def test_request_id_extracts_the_json_rpc_id():
    assert request_id(tools_call(id=1)) == 1
    assert request_id(tools_call(id="abc")) == "abc"


def test_request_id_null_is_distinct_from_absent():
    """`"id": null` is a request id the wire really carried; absence is None too,
    but the pair is only ever read together with `is_tools_call`, which
    guarantees the key was present."""
    assert request_id(tools_call(id=None)) is None
    assert request_id(b"garbage") is None