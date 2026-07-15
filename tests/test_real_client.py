"""A real `mcp` SDK client drives a real handshake THROUGH the proxy.

Everything else in this suite drives a hand-written client over raw pipes. That
proves byte-transparency — deliberately, because a real client would normalise
the hostile bytes the differential depends on — but it cannot prove that an
actual MCP implementation works through us. A proxy that is perfectly
byte-transparent and still unusable by every real client would pass every other
test in this repo.

This test is the other half: it says nothing about bytes and everything about
compatibility. The SDK is a dev/test-only dependency and appears only here;
`tests/test_import_guard.py` is what keeps it out of `src/belay` permanently.

`asyncio.run` rather than a pytest asyncio plugin: the SDK's client is async, and
one `asyncio.run` at the edge of a sync test buys the same thing a plugin would
without adding a dev dependency to run one test.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from conftest import read_trace

CONFORMING = Path(__file__).parent / "fixtures" / "conforming_server.py"

pytestmark = pytest.mark.sdk


async def _drive(trace_dir: Path) -> tuple[str, list[str], str]:
    """Run initialize -> tools/list -> tools/call through the proxy, via the SDK."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env["BELAY_TRACE_DIR"] = str(trace_dir)

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "belay.proxy", sys.executable, str(CONFORMING)],
        env=env,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            listed = await session.list_tools()
            called = await session.call_tool("echo", {"s": "café"})

    assert not called.isError, f"tool reported an error: {called.content!r}"
    return (
        initialized.protocolVersion,
        [tool.name for tool in listed.tools],
        called.content[0].text,
    )


def test_real_sdk_client_completes_a_session_through_the_proxy(tmp_path: Path) -> None:
    trace_dir = tmp_path / "trace"

    protocol_version, tool_names, echoed = asyncio.run(
        asyncio.wait_for(_drive(trace_dir), timeout=30)
    )

    assert protocol_version == "2025-11-25"
    assert tool_names == ["echo"]
    # Round-tripped through the proxy unmangled — a non-ASCII argument is where a
    # naive encoding hop would show up.
    assert echoed == "café"


def test_the_trace_records_the_tools_call_the_real_client_made(tmp_path: Path) -> None:
    """The proxy is transparent AND recording — not transparent by not looking.

    Read back through the real derivation (`belay.index`) rather than by grepping
    `raw`: a substring match would pass on a trace that recorded the bytes but
    could not be indexed, which is the failure this would exist to catch.
    """
    from belay.index import derive_correlation, tool_calls

    trace_dir = tmp_path / "trace"
    asyncio.run(asyncio.wait_for(_drive(trace_dir), timeout=30))

    records = read_trace(trace_dir)
    calls = tool_calls(derive_correlation(records))

    assert len(calls) == 1, f"expected exactly one tools/call, got {calls!r}"
    assert calls[0]["method"] == "tools/call"
    assert calls[0]["origin"] == "c2s"
    assert calls[0]["status"] == "answered", (
        "the real client's tools/call was recorded without its response — the proxy"
        f" saw the request but not the reply: {calls[0]!r}"
    )
