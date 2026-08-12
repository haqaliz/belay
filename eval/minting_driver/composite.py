"""A composite transport: one MCP boundary fronting several proxied `StdioMcp` sessions.

The mint's boundary used to be single-server by construction (one `StdioMcp`, one flat
tool list in the prompt). This module is the composite that fronts the pinned filesystem
server AND the pinned shell server on one boundary — the trajectory axis cannot measure
the mint population until `run_process` is reachable, and this is how it becomes so
(`docs/planning/trajectory-toolset-rescope/mint-dual-server/spec.md`).

## Routing map, built from each session's own `tools/list`

`CompositeTransport` knows nothing about servers, tools, or Belay's proxy: it is given
already-spawned sessions (each one a proxied `StdioMcp` the driver built — gating stays
per-session by construction). It learns what to route where from the sessions' own
`tools/list` replies, forwarded through the composite like any other request:

- `initialize` (and any method other than `tools/list`/`tools/call`) is **broadcast** to
  every session — each session must complete its own MCP handshake — and the first
  session's reply is returned.
- `tools/list` is broadcast; every session's tools are merged into ONE list and the
  routing map (tool name -> session) is rebuilt from the replies. The reply the loop
  sees carries the merged list, so the model is offered exactly the union of the two
  servers' tools.
- `tools/call` is routed by tool name to the single owning session and its reply is
  returned **verbatim** — the composite adds nothing and re-shapes nothing. An unknown
  name raises `UnknownToolError` (never routed to the wrong session — a mis-wire here
  reads as `INSTRUMENT SUSPECT` in a mint).

**Tool names are merged VERBATIM — no prefixing.** `run_process` stays `run_process`,
because the trajectory evidence gate matches that name exactly; `shell_run_process`
would silently blind the axis this module exists to arm. A name declared by more than
one session (e.g. both servers declaring `read_text_file`) is deduplicated with
**first-session precedence**: the merged list keeps the earlier declaration and the
routing map keeps the earlier session. That is a documented decision, not an accident —
see `merge_tool_lists`.

## One request in flight across the whole composite

Every `request` holds a single non-reentrant mutex for the whole duration of the call
(including the inner session's blocking wait), and a second concurrent `request` raises
`BusyError` rather than interleaving on a second session — the composite-level form of
`StdioMcp`'s sequential control-flow guarantee (`transport.py:209-215`). Notifications
are fanned out without the mutex (a notification has no reply and no in-flight slot).

## Error containment

A session that dies mid-call surfaces its OWN error (`ServerExited`, `ReplyTimeout`, ...)
on that call only. The composite adds nothing, kills nothing, and the other sessions
keep serving — the mint's per-instance containment in `run_mint` then records the
instance `failed` and moves on. `close()` is idempotent and closes every session.

## Toolset selection (`parse_toolset`)

`parse_toolset(toolset, layout, root)` turns the CLI's `--toolset` choice into the raw
(unproxied) `ServerSpec` list for ONE instance:

- `filesystem` -> exactly the pre-existing single-server composition: one filesystem
  spec whose allowed-directory is this instance's workspace, **no cwd** (behavior-
  identical to the direct `StdioMcp` path);
- `filesystem+shell` -> that spec PLUS the pinned shell server carrying
  `cwd=layout.work_dir`, so the shell's working directory IS the instance workspace at
  spawn. Replay restores its own scratch cwd, so this is a capture-side fact only
  (`replay-relocation-shell` already handles `cwd` relocation).

An unknown toolset raises a `ValueError` naming the valid values BEFORE any server
command is built. The spec builders are the pinned, untouched `servers.py` functions,
so `MissingServerError` propagates unchanged when a server is not installed.

Stdlib only; imports nothing under `src/belay` (eval-only, same isolation contract as
`transport.py`).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Optional, Sequence, Union

from eval.minting_driver.servers import (
    filesystem_server_command,
    shell_server_command,
)
from eval.minting_driver.transport import DEFAULT_TIMEOUT, StdioMcp, TransportError
from eval.minting_driver.workspace import WorkspaceLayout

StrPath = Union[str, "os.PathLike[str]"]

#: The toolsets the CLI accepts. `filesystem` is the default and is exactly today's
#: single-server path; `filesystem+shell` offers both pinned servers on one boundary.
VALID_TOOLSETS = ("filesystem", "filesystem+shell")


class BusyError(TransportError):
    """Another request is already in flight across the composite.

    Raised instead of interleaving: one `tools/call` at a time is the R7 invariant the
    composite enforces across all its sessions (`transport.py:209-215` documents the
    single-session guarantee this generalizes).
    """


class UnknownToolError(TransportError):
    """A `tools/call` named a tool no session in the composite declares.

    Raised rather than routed: a call for an unknown name must never reach a session
    that does not own it.
    """


@dataclass(frozen=True)
class ServerSpec:
    """One raw (unproxied) server to spawn: its command and optional working directory.

    `cwd` is `None` for the filesystem server (its boundary is the absolute
    `allowed_dir` argv) and the instance workspace for the shell server — the shell's
    working directory at spawn IS the per-instance workspace (`spec.md` R5).
    """

    command: list[str]
    cwd: Optional[StrPath] = None


def toolset_names(toolset: str) -> tuple[str, ...]:
    """The pinned server names a toolset composes, or a clear error naming the valid values.

    Pure name resolution, shared by `parse_toolset` (spec building) and the entry
    point's preflight (which must resolve every server a toolset names BEFORE any
    instance is prepped). One place decides validity, so the error text and the
    accepted values cannot drift apart.
    """
    if toolset == "filesystem":
        return ("filesystem",)
    if toolset == "filesystem+shell":
        return ("filesystem", "shell")
    raise ValueError(
        f"unknown toolset {toolset!r}; valid toolsets: {list(VALID_TOOLSETS)}"
    )


def parse_toolset(
    toolset: str,
    layout: WorkspaceLayout,
    *,
    root: Optional[StrPath] = None,
) -> list[ServerSpec]:
    """The raw (unproxied) server specs a toolset composes for ONE instance's layout.

    `filesystem` -> one filesystem spec whose allowed-directory is `layout.work_dir`,
    no cwd — exactly today's single-server composition. `filesystem+shell` -> that spec
    plus the pinned shell server with `cwd=layout.work_dir`, so the shell's working
    directory is the instance workspace at spawn. Any other toolset raises a
    `ValueError` naming the valid values before any server command is built. A missing
    install raises `MissingServerError` unchanged, naming the exact `npm install`.
    """
    specs: list[ServerSpec] = []
    for name in toolset_names(toolset):
        if name == "filesystem":
            specs.append(
                ServerSpec(command=filesystem_server_command(layout.work_dir, root=root))
            )
        elif name == "shell":
            specs.append(
                ServerSpec(
                    command=shell_server_command(root=root),
                    cwd=str(layout.work_dir),
                )
            )
    return specs


def merge_tool_lists(lists: Sequence[Sequence[dict]]) -> list[dict]:
    """Merge several `tools/list` results into one flat list, FIRST-WINS by tool name.

    A tool name keeps its EARLIEST declaration across `lists` (session order); later
    declarations of the same name are dropped from the merged list — and, by the same
    rule, route to the earlier session. Names are kept VERBATIM: nothing is prefixed,
    renamed, or namespaced, because the trajectory evidence gate matches `run_process`
    by its exact name. Non-dict entries are skipped defensively (a server's malformed
    tool entry must not corrupt the whole boundary).
    """
    merged: list[dict] = []
    seen: set[str] = set()
    for tools in lists:
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            if not isinstance(name, str) or name in seen:
                continue
            seen.add(name)
            merged.append(tool)
    return merged


class CompositeTransport:
    """Fronts several `StdioMcp` sessions as ONE transport; routes by tool name.

    See the module docstring for the routing, in-flight, and containment semantics.
    Constructed with already-spawned sessions (never spawns one itself); `close()`
    closes every session and is idempotent.
    """

    def __init__(self, sessions: Sequence[StdioMcp]) -> None:
        if not sessions:
            raise ValueError("CompositeTransport requires at least one session")
        self._sessions = list(sessions)
        # Non-reentrant on purpose: a second `request` while one is in flight must
        # RAISE (`BusyError`), not queue — see the module docstring.
        self._lock = threading.Lock()
        self._tool_sessions: dict[str, StdioMcp] = {}
        self._merged_tools: list[dict] = []
        self._closed = False

    def _acquire(self) -> None:
        if self._closed:
            raise TransportError("CompositeTransport is closed")
        if not self._lock.acquire(blocking=False):
            raise BusyError(
                "another request is already in flight across the composite; one "
                "tools/call at a time is the R7 invariant this transport enforces"
            )

    def request(self, obj: dict, timeout: float = DEFAULT_TIMEOUT) -> dict:
        """Send `obj` to the owning session(s) and await its matching reply.

        `tools/list` fans out to every session and returns the merged reply (rebuilding
        the routing map); `tools/call` is routed by tool name to exactly one session and
        its reply is returned verbatim; anything else is broadcast and the first reply
        returned. Never more than one request in flight across the composite: a second
        concurrent call raises `BusyError`.
        """
        self._acquire()
        try:
            method = obj.get("method")
            if method == "tools/list":
                return self._tools_list(obj, timeout)
            if method == "tools/call":
                return self._tools_call(obj, timeout)
            return self._broadcast(obj, timeout)
        finally:
            self._lock.release()

    def _broadcast(self, obj: dict, timeout: float) -> dict:
        first = None
        for session in self._sessions:
            reply = session.request(obj, timeout=timeout)
            if first is None:
                first = reply
        assert first is not None  # `__init__` guarantees at least one session
        return first

    def _tools_list(self, obj: dict, timeout: float) -> dict:
        """Fan out `tools/list`, merge first-wins, rebuild the routing map."""
        lists: list[list[dict]] = []
        routing: dict[str, StdioMcp] = {}
        for index, session in enumerate(self._sessions):
            reply = session.request(obj, timeout=timeout)
            if "error" in reply:
                raise TransportError(
                    f"session {index} errored on tools/list: {reply['error']!r}"
                )
            result = reply.get("result")
            if not isinstance(result, dict):
                raise TransportError(
                    f"session {index} replied to tools/list without a dict result: "
                    f"{reply!r}"
                )
            tools = result.get("tools")
            if not isinstance(tools, list):
                raise TransportError(
                    f"session {index} replied to tools/list without a list of tools: "
                    f"{tools!r}"
                )
            lists.append(tools)
            for tool in tools:
                if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                    routing.setdefault(tool["name"], session)
        self._tool_sessions = routing
        self._merged_tools = merge_tool_lists(lists)
        return {
            "jsonrpc": "2.0",
            "id": obj.get("id"),
            "result": {"tools": list(self._merged_tools)},
        }

    def _tools_call(self, obj: dict, timeout: float) -> dict:
        params = obj.get("params") or {}
        name = params.get("name")
        session = self._tool_sessions.get(name)
        if session is None:
            raise UnknownToolError(
                f"unknown tool {name!r} — no session in the composite declares it; "
                f"known tools: {sorted(self._tool_sessions)}"
            )
        return session.request(obj, timeout=timeout)

    def notify(self, obj: dict) -> None:
        """Send `obj` (a notification) to every session, no reply awaited."""
        for session in self._sessions:
            session.notify(obj)

    def close(self) -> None:
        """Close every session. Idempotent: a second call is a no-op."""
        if self._closed:
            return
        self._closed = True
        for session in self._sessions:
            session.close()

    def tools_list(self) -> list[dict]:
        """The merged tool list from the last `tools/list` fan-out.

        Raises `TransportError` if no `tools/list` has been served through this
        composite yet — the routing map is built from the sessions' own replies, so
        there is nothing to return before one.
        """
        if not self._tool_sessions:
            raise TransportError(
                "no tools/list has been served through this composite yet; the routing "
                "map is built from each session's own tools/list reply"
            )
        return list(self._merged_tools)


__all__ = [
    "BusyError",
    "CompositeTransport",
    "ServerSpec",
    "UnknownToolError",
    "VALID_TOOLSETS",
    "merge_tool_lists",
    "parse_toolset",
    "toolset_names",
]
