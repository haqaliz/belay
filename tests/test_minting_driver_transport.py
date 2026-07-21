"""RED-first tests for `StdioMcp`, the interactive MCP stdio transport (Task 2).

Deterministic and offline: three tiny stdlib fake servers under `tests/fixtures/`
stand in for a real MCP server, and no test waits longer than a short, explicit
timeout. `test_import_guard.py` only walks `src/belay`, so nothing here needs to
avoid `eval/`-only imports beyond the task's own constraint (no `belay.replay`,
no `mcp` SDK) — enforced by inspection in `test_transport_module_is_standalone`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from eval.minting_driver.transport import ReplyTimeout, ServerExited, StdioMcp

FIXTURES = Path(__file__).parent / "fixtures"
ECHO_SERVER = FIXTURES / "minting_driver_echo_server.py"
SILENT_EXIT_SERVER = FIXTURES / "minting_driver_silent_exit_server.py"
HANG_SERVER = FIXTURES / "minting_driver_hang_server.py"

# Short so the suite that hits the timeout paths stays fast.
SHORT_TIMEOUT = 0.3


def _spawn(script: Path) -> StdioMcp:
    return StdioMcp([sys.executable, str(script)], env={})


def test_request_correlates_reply_by_id() -> None:
    transport = _spawn(ECHO_SERVER)
    try:
        reply = transport.request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        assert reply["id"] == 1
        assert reply["result"] == {"echoed": 1}
    finally:
        transport.close()


def test_request_correlates_correctly_past_a_stray_notification_and_a_mismatched_id() -> None:
    """The echo fixture always emits a stray notification AND a wrong-id reply first.

    A transport that returned the first response-shaped line it saw, or the first
    line at all, would fail this: it must keep reading until the id actually
    matches.
    """
    transport = _spawn(ECHO_SERVER)
    try:
        reply = transport.request({"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}})
        assert reply["id"] == 7
        assert reply["result"] == {"echoed": 7}
    finally:
        transport.close()


def test_multiple_requests_correlate_independently_in_order() -> None:
    transport = _spawn(ECHO_SERVER)
    try:
        first = transport.request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        second = transport.request({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        assert (first["id"], second["id"]) == (1, 2)
    finally:
        transport.close()


def test_notify_sends_without_awaiting_a_reply_and_a_later_request_still_works() -> None:
    transport = _spawn(ECHO_SERVER)
    try:
        transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        reply = transport.request({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        assert reply["id"] == 1
    finally:
        transport.close()


def test_request_without_an_id_raises_value_error() -> None:
    transport = _spawn(ECHO_SERVER)
    try:
        with pytest.raises(ValueError):
            transport.request({"jsonrpc": "2.0", "method": "ping", "params": {}})
    finally:
        transport.close()


def test_server_exit_before_replying_raises_an_explicit_error_not_a_hang() -> None:
    transport = _spawn(SILENT_EXIT_SERVER)
    try:
        with pytest.raises(ServerExited):
            transport.request(
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}, timeout=SHORT_TIMEOUT
            )
    finally:
        transport.close()


def test_no_reply_from_a_live_process_times_out_explicitly() -> None:
    """Distinct path from the exit case: the process stays alive (no EOF)."""
    transport = _spawn(HANG_SERVER)
    try:
        with pytest.raises(ReplyTimeout):
            transport.request(
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}, timeout=SHORT_TIMEOUT
            )
    finally:
        transport.close()


def test_close_tears_down_the_subprocess() -> None:
    transport = _spawn(HANG_SERVER)
    transport.close()
    assert transport._proc.poll() is not None


def test_transport_module_is_standalone() -> None:
    """No import of `belay.replay` (or any `belay` module) or the `mcp` SDK.

    The plan's decision: copy the ~30 lines of send/await/correlate logic from
    `belay.replay.client` rather than import it, so `eval/` has no dependency on
    `src/belay` and the isolation contract is unambiguous. Checked structurally
    (AST) rather than trusted by convention.
    """
    source = (Path(__file__).parent.parent / "eval" / "minting_driver" / "transport.py").read_text()
    tree = ast.parse(source)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                roots.add(node.module.split(".")[0])
    assert "belay" not in roots, f"transport.py must not import belay: {roots!r}"
    assert "mcp" not in roots, f"transport.py must not import the mcp SDK: {roots!r}"
