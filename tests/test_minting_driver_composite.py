"""RED-first acceptance tests for `CompositeTransport` — aspect `mint-dual-server`.

The trajectory axis cannot measure the mint population until `run_process` is reachable,
but the driver is single-server by construction: one `StdioMcp`, one flat tool list
(`spec.md`). This module pins the composite that fronts TWO proxied sessions on one
boundary before it exists — the tests are written against the planned surface
(`eval/minting_driver/composite.py`), so they fail at import until Phase 2 lands.

The five acceptance cases (spec.md, plan Phase 1):

1. The merged tool list — both sessions' `tools/list` replies, names VERBATIM
   (`run_process` stays `run_process`; no prefixing, or the trajectory evidence gate
   `_EVIDENCE_TOOL` breaks).
2. Routing — a `tools/call` for an fs tool reaches the fs session only, `run_process`
   reaches the shell session only, and the replies round-trip verbatim.
3. One call in flight across the whole composite — a second concurrent `request` raises,
   mirroring `StdioMcp`'s control-flow guarantee (`transport.py:209-215`).
4. Error containment — a session whose process died mid-call surfaces its own error on
   that call; the other session keeps serving.
5. `close()` closes every session, idempotently.

Deterministic and offline: `FakeSession` stands in for `StdioMcp` (no subprocess), and
the shell session's tool list is the REAL fixture contract from
`tests/fixtures/shell_command_server.py` (`RUN_TOOL` verbatim), so the verbatim-name
assertion is anchored to the fixture the replay spine already uses.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import pytest

from eval.minting_driver.composite import (
    BusyError,
    CompositeTransport,
    UnknownToolError,
    parse_toolset,
)
from eval.minting_driver.mcp import initialize, initialized, tools_call, tools_list
from eval.minting_driver.servers import PINNED_SERVERS
from eval.minting_driver.transport import ServerExited
from eval.minting_driver.workspace import layout_for

from fixtures.shell_command_server import RUN_TOOL, TOOLS as SHELL_TOOLS

#: The filesystem server's real tool names (`@modelcontextprotocol/server-filesystem`),
#: kept as plain dicts — the composite must never see more than a list of tool dicts.
FS_TOOLS = [
    {"name": "read_text_file", "description": "Read a text file."},
    {"name": "edit_file", "description": "Edit a file."},
    {"name": "write_file", "description": "Write a file."},
    {"name": "search_files", "description": "Search files."},
]

#: A canned `tools/call` result for the fs session's `read_text_file`.
FS_REPLY = {"content": [{"type": "text", "text": "file body"}]}

#: A canned `tools/call` result for the shell session's `run_process`.
SHELL_REPLY = {"content": [{"type": "text", "text": "ran ok"}]}


class FakeSession:
    """A deterministic `StdioMcp` stand-in: canned replies, every call recorded.

    Implements the three methods the composite uses — `request`, `notify`, `close` —
    and records every call as `(method, params)`. `fail_on` names the tools whose call
    raises `ServerExited` (a session whose process died handling its own call); `gate`
    is an optional `threading.Event` a test holds to keep a `tools/call` genuinely in
    flight (for the one-in-flight assertion).
    """

    def __init__(
        self,
        name: str,
        tools: list[dict],
        *,
        tool_replies: Optional[dict[str, dict]] = None,
        fail_on: tuple[str, ...] = (),
        gate: Optional[threading.Event] = None,
    ) -> None:
        self.name = name
        self.tools = list(tools)
        self.tool_replies = dict(tool_replies or {})
        self.fail_on = set(fail_on)
        self.gate = gate
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def request(self, obj: dict, timeout: float | None = None) -> dict:
        method = obj["method"]
        params = obj.get("params") or {}
        self.calls.append((method, params))
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"serverInfo": {"name": self.name}},
            }
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": obj["id"],
                "result": {"tools": [dict(tool) for tool in self.tools]},
            }
        if method == "tools/call":
            if self.gate is not None:
                self.gate.wait(timeout=10)
            name = params["name"]
            if name in self.fail_on:
                raise ServerExited(
                    f"{self.name} exited while handling {name}"
                )
            reply = self.tool_replies.get(name, {"content": [{"type": "text", "text": "ok"}]})
            return {"jsonrpc": "2.0", "id": obj["id"], "result": reply}
        raise AssertionError(f"unexpected method: {method}")

    def notify(self, obj: dict) -> None:
        self.calls.append((obj["method"], obj.get("params") or {}))

    def close(self) -> None:
        self.closed = True

    def calls_for(self, method: str) -> list[dict]:
        return [params for m, params in self.calls if m == method]


def _handshake(composite: CompositeTransport) -> dict:
    """Drive the MCP handshake the loop performs: initialize, initialized, tools/list."""
    composite.request(initialize(1))
    composite.notify(initialized())
    return composite.request(tools_list(2))


def test_tools_list_merges_both_sessions_with_run_process_verbatim() -> None:
    """One flat list; the shell tool keeps its exact name — never prefixed or renamed.

    The trajectory evidence gate matches `run_process` BY NAME, so any prefixing
    (`shell_run_process`) or translation silently blinds the axis this unit exists to
    arm.
    """
    fs = FakeSession("filesystem", FS_TOOLS)
    shell = FakeSession("shell", SHELL_TOOLS)
    composite = CompositeTransport([fs, shell])
    try:
        reply = _handshake(composite)
        tools = reply["result"]["tools"]
        names = [tool["name"] for tool in tools]
        assert names == ["read_text_file", "edit_file", "write_file", "search_files", RUN_TOOL]
        # One entry per name — nothing prefixed, nothing duplicated.
        assert len(tools) == len(set(names)) == 5
        assert RUN_TOOL == "run_process"  # the fixture's contract, asserted verbatim
        # The shell entry is the fixture's own declaration, byte for byte.
        assert tools[-1] == SHELL_TOOLS[0]
        # Every session saw the handshake too: broadcast, not a single winner.
        assert len(fs.calls_for("initialize")) == 1
        assert len(shell.calls_for("initialize")) == 1
    finally:
        composite.close()


def test_duplicate_tool_names_dedupe_with_first_session_precedence() -> None:
    """A name both sessions declare resolves to ONE entry — the first session's.

    Both the merged list and the routing map keep first-wins (documented in the module
    docstring): a collision must never manufacture two entries for one name, and must
    never silently re-route the call to the later session.
    """
    fs_read = {"name": "read_text_file", "description": "fs declaration"}
    fs = FakeSession("filesystem", [fs_read, {"name": "edit_file"}])
    shell = FakeSession(
        "shell", [{"name": "read_text_file", "description": "shell declaration"}, *SHELL_TOOLS]
    )
    composite = CompositeTransport([fs, shell])
    try:
        reply = _handshake(composite)
        tools = reply["result"]["tools"]
        read_entries = [tool for tool in tools if tool["name"] == "read_text_file"]
        assert len(read_entries) == 1
        assert read_entries[0] == fs_read  # the FIRST session's declaration wins
        # Routing for the collided name goes to the first session as well.
        composite.request(tools_call(3, "read_text_file", {"path": "/x"}))
        assert fs.calls_for("tools/call") == [{"name": "read_text_file", "arguments": {"path": "/x"}}]
        assert shell.calls_for("tools/call") == []
    finally:
        composite.close()


def test_tools_call_routes_by_name_and_replies_round_trip_verbatim() -> None:
    """An fs tool reaches ONLY the fs session, `run_process` ONLY the shell session.

    The reply is the owning session's reply, verbatim — the composite adds nothing,
    re-shapes nothing, and never lets a call cross to the wrong session (a mis-wire
    here reads as `INSTRUMENT SUSPECT` in a mint). An unknown name raises a clear
    error naming the tool, never routing anywhere.
    """
    fs = FakeSession("filesystem", FS_TOOLS, tool_replies={"read_text_file": FS_REPLY})
    shell = FakeSession("shell", SHELL_TOOLS, tool_replies={RUN_TOOL: SHELL_REPLY})
    composite = CompositeTransport([fs, shell])
    try:
        _handshake(composite)

        read_reply = composite.request(tools_call(3, "read_text_file", {"path": "/x"}))
        assert read_reply == {"jsonrpc": "2.0", "id": 3, "result": FS_REPLY}
        assert fs.calls_for("tools/call") == [{"name": "read_text_file", "arguments": {"path": "/x"}}]
        assert shell.calls_for("tools/call") == []

        run_reply = composite.request(tools_call(4, RUN_TOOL, {"command_line": "pwd"}))
        assert run_reply == {"jsonrpc": "2.0", "id": 4, "result": SHELL_REPLY}
        assert shell.calls_for("tools/call") == [
            {"name": "run_process", "arguments": {"command_line": "pwd"}}
        ]
        # The fs session saw exactly its own call, before and after the shell call.
        assert fs.calls_for("tools/call") == [{"name": "read_text_file", "arguments": {"path": "/x"}}]

        with pytest.raises(UnknownToolError) as excinfo:
            composite.request(tools_call(5, "no_such_tool", {}))
        assert "no_such_tool" in str(excinfo.value)
        assert fs.calls_for("tools/call") == [
            {"name": "read_text_file", "arguments": {"path": "/x"}}
        ]
        assert shell.calls_for("tools/call") == [
            {"name": "run_process", "arguments": {"command_line": "pwd"}}
        ]
    finally:
        composite.close()


def test_a_second_request_while_one_is_in_flight_raises() -> None:
    """One `tools/call` in flight across the WHOLE composite — a second concurrent
    `request` raises `BusyError` rather than interleaving on a second session.

    Mirrors `StdioMcp`'s sequential control-flow guarantee at the composite level
    (`transport.py:209-215`): the loop is sequential, and the composite must keep it
    that way across sessions even if a caller tried to overlap.
    """
    gate = threading.Event()
    fs = FakeSession(
        "filesystem", FS_TOOLS, tool_replies={"read_text_file": FS_REPLY}, gate=gate
    )
    shell = FakeSession("shell", SHELL_TOOLS)
    composite = CompositeTransport([fs, shell])
    _handshake(composite)

    results: dict[str, object] = {}

    def slow_call() -> None:
        results["reply"] = composite.request(tools_call(3, "read_text_file", {"path": "/x"}))

    thread = threading.Thread(target=slow_call)
    thread.start()
    try:
        # Wait until the first call is demonstrably in flight (blocked inside the fs
        # session, which can only happen while the composite's mutex is held).
        deadline = time.monotonic() + 5
        while not fs.calls_for("tools/call") and time.monotonic() < deadline:
            time.sleep(0.01)
        assert fs.calls_for("tools/call"), "the slow call never reached its session"

        with pytest.raises(BusyError):
            composite.request(tools_call(4, "edit_file", {}))
    finally:
        gate.set()
        thread.join(timeout=5)
    assert results["reply"] == {"jsonrpc": "2.0", "id": 3, "result": FS_REPLY}
    assert not thread.is_alive()
    # Only the first call was ever served.
    assert fs.calls_for("tools/call") == [{"name": "read_text_file", "arguments": {"path": "/x"}}]
    assert shell.calls_for("tools/call") == []


def test_a_dead_session_errors_its_own_call_and_the_other_still_serves() -> None:
    """A session whose process died surfaces `ServerExited` on ITS call only.

    The composite adds nothing and kills nothing: the healthy session keeps serving
    before and after, and the dead session keeps failing on its own tool.
    """
    fs = FakeSession("filesystem", FS_TOOLS, tool_replies={"read_text_file": FS_REPLY})
    shell = FakeSession("shell", SHELL_TOOLS, fail_on=(RUN_TOOL,))
    composite = CompositeTransport([fs, shell])
    try:
        _handshake(composite)

        with pytest.raises(ServerExited):
            composite.request(tools_call(3, RUN_TOOL, {"command_line": "pwd"}))

        reply = composite.request(tools_call(4, "read_text_file", {"path": "/x"}))
        assert reply == {"jsonrpc": "2.0", "id": 4, "result": FS_REPLY}

        with pytest.raises(ServerExited):
            composite.request(tools_call(5, RUN_TOOL, {"command_line": "ls"}))
        # The healthy session served exactly one call the whole time.
        assert fs.calls_for("tools/call") == [{"name": "read_text_file", "arguments": {"path": "/x"}}]
    finally:
        composite.close()


def test_close_closes_every_session_and_is_idempotent() -> None:
    fs = FakeSession("filesystem", FS_TOOLS)
    shell = FakeSession("shell", SHELL_TOOLS)
    composite = CompositeTransport([fs, shell])

    composite.close()

    assert fs.closed is True
    assert shell.closed is True
    composite.close()  # idempotent: a second close is a no-op, never an error
    assert fs.closed is True
    assert shell.closed is True


def test_a_session_that_errors_on_tools_list_fails_the_composite_loudly() -> None:
    """A session whose `tools/list` reply is an error must NOT read as "no tools".

    Silently dropping the session would hand the model a merged list missing its tools —
    e.g. no `run_process` — which is exactly the blind-boundary failure this unit exists
    to prevent. The composite raises a named error instead.
    """

    class ErroringSession(FakeSession):
        def request(self, obj: dict, timeout: float | None = None) -> dict:
            if obj["method"] == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": obj["id"],
                    "error": {"code": -32000, "message": "boom"},
                }
            return super().request(obj, timeout=timeout)

    fs = FakeSession("filesystem", FS_TOOLS)
    broken = ErroringSession("shell", SHELL_TOOLS)
    composite = CompositeTransport([fs, broken])
    try:
        with pytest.raises(Exception, match="tools/list"):
            _handshake(composite)
    finally:
        composite.close()


# --------------------------------------------------------------------------------------
# Toolset selection — `parse_toolset` (aspect R6: freeze-able toolset, spec.md AC3)
# --------------------------------------------------------------------------------------


def _install_fake_server(root: Path, name: str) -> Path:
    """An empty entrypoint at the pinned path — CI never installs or spawns node."""
    entrypoint = root / PINNED_SERVERS[name].entrypoint
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("// fake\n", encoding="utf-8")
    return entrypoint


def test_parse_toolset_filesystem_is_one_fs_spec_without_cwd(tmp_path: Path) -> None:
    """`filesystem` -> exactly today's single-server composition: one fs spec, no cwd."""
    server_root = tmp_path / "servers"
    entrypoint = _install_fake_server(server_root, "filesystem")
    layout = layout_for("octo__repo-1", tmp_path / "mint")

    specs = parse_toolset("filesystem", layout, root=server_root)

    assert len(specs) == 1
    assert specs[0].cwd is None
    assert specs[0].command == ["node", str(entrypoint.resolve()), str(layout.work_dir)]


def test_parse_toolset_filesystem_plus_shell_carries_the_instance_cwd(
    tmp_path: Path,
) -> None:
    """`filesystem+shell` -> fs spec (no cwd) + shell spec with `cwd=layout.work_dir`."""
    server_root = tmp_path / "servers"
    fs_entrypoint = _install_fake_server(server_root, "filesystem")
    shell_entrypoint = _install_fake_server(server_root, "shell")
    layout = layout_for("octo__repo-1", tmp_path / "mint")

    specs = parse_toolset("filesystem+shell", layout, root=server_root)

    assert len(specs) == 2
    fs_spec, shell_spec = specs
    assert fs_spec.cwd is None
    assert fs_spec.command == ["node", str(fs_entrypoint.resolve()), str(layout.work_dir)]
    assert shell_spec.cwd == str(layout.work_dir)
    assert shell_spec.command == ["node", str(shell_entrypoint.resolve())]


def test_parse_toolset_bogus_names_the_valid_values(tmp_path: Path) -> None:
    """An invalid toolset is a clear error naming the valid values — before any server
    command is built (so it fails even with no install present)."""
    layout = layout_for("octo__repo-1", tmp_path / "mint")

    with pytest.raises(ValueError) as excinfo:
        parse_toolset("bogus", layout)

    message = str(excinfo.value)
    assert "filesystem" in message
    assert "filesystem+shell" in message
