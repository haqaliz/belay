"""A real MCP filesystem server, and a client that drives it — both sandboxed.

## Why this is not `@modelcontextprotocol/server-filesystem`

The npm reference server is the thing we would rather test against, and it cannot
be used here: it is not in the npm cache and resolving it needs the network
(measured: `npx --offline` fails `ENOTCACHED`). A test that reaches the registry
is a test that fails on a train, and the sandbox it would run under is
`deny-all`. So this is a stand-in — but a stand-in built on the **real `mcp`
SDK**, speaking the real protocol over real stdio pipes, not a hand-rolled
imitation. What it is not is the reference server's exact syscall pattern, and
`tests/test_default_scope.py` should be read with that substitution in mind.

## The shape, and why this shape

Two roles in one file:

- `filesystem_server.py <root>` is the **driver**: the MCP client. It spawns the
  server below and calls its tool.
- `filesystem_server.py --serve <root>` is the **server**.

Both run inside the same sandbox, because the driver is what
`tests/test_default_scope.py` puts under `sandbox-exec`. That is deliberate: it
makes the server a **grandchild** of the sandboxed process, which is the case an
MCP shell server actually is — mostly a process spawner — and it is only contained
because Seatbelt is inherited across fork/exec.

## The one thing that is easy to get wrong here

`env=dict(os.environ)` is passed explicitly, and it is load-bearing. With
`env=None` the SDK substitutes `get_default_environment()`, which on posix
inherits **only** `HOME, LOGNAME, PATH, SHELL, TERM, USER` — `TMPDIR` is not on
the list and would be dropped on the way to the server. This fixture would then
be measuring the SDK's env filter rather than Belay's default scope, and the
zero-config test would fail for a reason that has nothing to do with the thing it
claims to test. Belay's own proxy spawns its server by plain inheritance
(`proxy.py` passes no `env`), so explicit inheritance here is also the faithful
mirror of the deployed shape.

The tool writes via a temp file and renames it into place — the pattern that needs
`$TMPDIR` to exist and to be writable, and therefore the pattern that fails
without the sandboxed TMPDIR. `test_the_filesystem_server_fixture_would_notice_a_tight_scope`
is what holds that true.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

WRITTEN_NAME = "written.txt"
WRITTEN_BODY = "written by the server"


def _serve(root: str) -> None:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("belay-filesystem-fixture")

    @server.tool()
    def write_file(name: str, body: str) -> str:
        """Write `body` to `name` under the root, atomically, via $TMPDIR."""
        # The temp file lands in $TMPDIR — NOT alongside the destination. That is
        # what makes this fixture sensitive to the default scope at all.
        handle, staged = tempfile.mkstemp(prefix="fs-server-")
        with os.fdopen(handle, "w") as fh:
            fh.write(body)
        # `move`, not `replace`: TMPDIR and the destination are only guaranteed to
        # be on one filesystem when the sandboxed TMPDIR is in use, and an EXDEV
        # here would look like a sandbox failure while being an fs boundary.
        shutil.move(staged, os.path.join(root, name))
        return f"wrote {name}"

    @server.tool()
    def list_directory() -> list[str]:
        return sorted(entry.name for entry in Path(root).iterdir())

    server.run()


async def _drive(root: str) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--serve", root],
        # Load-bearing. See the module docstring: env=None would drop TMPDIR.
        env=dict(os.environ),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool(
                "write_file", {"name": WRITTEN_NAME, "body": WRITTEN_BODY}
            )
            if result.isError:
                print(f"tool call failed: {result.content}", file=sys.stderr)
                return 1
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--serve"]:
        _serve(argv[1])
        return 0
    return asyncio.run(_drive(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
