"""Thin JSON-RPC request builders + reply parsing for the minting-driver loop.

`StdioMcp` (`transport.py`) speaks raw dicts; this module is the small,
pure-function layer that shapes the three requests the loop needs
(`initialize`, `tools/list`, `tools/call`) and turns a `tools/call` reply into
the tool-result `Message` (`model.py`) the loop appends to its running
history. No I/O here — everything is a plain dict in, dict/dataclass out.

**Id generation is explicit, not hidden module state.** Each builder takes the
id it should stamp on the request (`id_: int`) rather than reaching for a
shared global counter; `MonotonicIds` is the allocator a caller (the driver
loop, or a test) holds one instance of per session and calls once per request.
This keeps the request builders pure functions, and keeps id state scoped to
whoever owns a `StdioMcp` session instead of leaking across the whole process
— two sessions never contend over the same counter, and a test can assert on
exact id sequences without resetting global state between runs.
"""

from __future__ import annotations

from typing import Any

from eval.minting_driver.model import Message

#: The MCP protocol version this driver speaks `initialize` with.
PROTOCOL_VERSION = "2025-06-18"


class MonotonicIds:
    """A per-session id allocator: `next()`-style, starting at 1.

    Holds nothing but a counter. One instance belongs to one `StdioMcp`
    session so its ids never collide with another session's.
    """

    def __init__(self, start: int = 1) -> None:
        self._next = start

    def __call__(self) -> int:
        return self.__next__()

    def __iter__(self) -> "MonotonicIds":
        return self

    def __next__(self) -> int:
        value = self._next
        self._next += 1
        return value


def initialize(
    id_: int,
    *,
    client_name: str = "belay-minting-driver",
    client_version: str = "0.1.0",
    protocol_version: str = PROTOCOL_VERSION,
) -> dict:
    """The `initialize` request that opens an MCP session."""
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": client_name, "version": client_version},
        },
    }


def initialized() -> dict:
    """The `notifications/initialized` notification.

    MCP requires the client to send this *after* the `initialize` reply and *before*
    any `tools/list`/`tools/call` — it is the client's acknowledgement that the
    handshake completed and the session is now open for use. A notification carries
    no `id` (nothing replies to it); `loop.run_task` sends it via
    `transport.notify(...)`, not `transport.request(...)`.
    """
    return {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def tools_list(id_: int) -> dict:
    """The `tools/list` request."""
    return {"jsonrpc": "2.0", "id": id_, "method": "tools/list", "params": {}}


def tools_call(id_: int, name: str, arguments: dict | None = None) -> dict:
    """The `tools/call` request invoking tool `name` with `arguments`."""
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments if arguments is not None else {}},
    }


def parse_tools_call_reply(reply: dict) -> Message:
    """Turn a `tools/call` JSON-RPC reply into the tool-result `Message` the
    driver loop appends to its history so the next `propose_next` call can see
    what happened.

    A JSON-RPC error reply becomes a `Message` whose content names the error;
    a successful reply's text content parts (`result.content[*].text`) are
    joined with newlines. Either way `tool_result` carries the full raw
    `result`/`error` payload, so nothing the server returned is lost even
    though `content` only surfaces the human-readable text.
    """
    if "error" in reply:
        error: Any = reply["error"]
        detail = error.get("message", error) if isinstance(error, dict) else error
        return Message(role="tool", content=f"error: {detail}", tool_result=error)

    result = reply.get("result", {})
    parts = result.get("content", []) if isinstance(result, dict) else []
    text = "\n".join(
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    )
    return Message(role="tool", content=text, tool_result=result)


__all__ = [
    "PROTOCOL_VERSION",
    "MonotonicIds",
    "initialize",
    "initialized",
    "parse_tools_call_reply",
    "tools_call",
    "tools_list",
]
