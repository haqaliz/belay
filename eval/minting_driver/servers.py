"""Locating the pre-installed MCP servers the mint drives — and why not `npx`.

`npx -y <pkg>@<version>` **cannot be used behind Belay's gated proxy.** A contained run
(`BELAY_SANDBOX_SCOPE` + `BELAY_SNAPSHOT_DIR`) applies a Seatbelt profile that

1. denies network by default (`src/belay/sandbox/launch.py`), and
2. confines writes to the workspace scope,

so `npx` can neither reach the npm registry nor write its `~/.npm` cache, and simply
hangs. Worse, npm misreports the write denial as a bogus *"your cache folder contains
root-owned files"* message — a red herring (`find ~/.npm -user root` returns nothing).
Both defaults are deliberate and correct; the eval harness was wrong to use `npx`.

The fix, verified by hand: **pre-install each pinned server OUTSIDE the sandbox, then
invoke it by absolute path with `node`.** That replies to `initialize` instantly under
full gating, because a resolved `dist/index.js` needs no registry and no cache write.

This module is the (stdlib-only, no-network, no-subprocess) helper that finds those
installs. When one is missing it raises `MissingServerError` naming the exact
`npm install` to run — that message is the point of the module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

StrPath = Union[str, "os.PathLike[str]"]

#: Environment variable that overrides the install root (absolute or relative to cwd).
SERVER_ROOT_ENV = "BELAY_EVAL_SERVER_ROOT"


@dataclass(frozen=True)
class PinnedServer:
    """One pinned MCP server: what to install, and where its entrypoint lands."""

    #: npm package name, unversioned.
    package: str
    #: Exact pinned version — never a range, never implicit "latest". A mint that
    #: silently drifts to a different server version is not reproducible.
    version: str
    #: Path to the entrypoint JS *relative to the install root*, taken from the
    #: package's own `package.json` "bin" field (verified against real installs of
    #: these exact versions).
    entrypoint: str

    @property
    def spec(self) -> str:
        """The `pkg@version` spec as it appears in the `npm install` command."""
        return f"{self.package}@{self.version}"


#: The servers `eval/README.md` documents for the Phase-0 mint, pinned exactly.
#: Entrypoints come from each package's `package.json` "bin" (note the shell server
#: uses `build/`, not `dist/`):
#:   @modelcontextprotocol/server-filesystem@2026.7.10 -> {"mcp-server-filesystem": "dist/index.js"}
#:   mcp-server-commands@0.8.2                         -> {"mcp-server-commands": "./build/index.js"}
PINNED_SERVERS: dict[str, PinnedServer] = {
    "filesystem": PinnedServer(
        package="@modelcontextprotocol/server-filesystem",
        version="2026.7.10",
        entrypoint=(
            "node_modules/@modelcontextprotocol/server-filesystem/dist/index.js"
        ),
    ),
    "shell": PinnedServer(
        package="mcp-server-commands",
        version="0.8.2",
        entrypoint="node_modules/mcp-server-commands/build/index.js",
    ),
}

#: Repo root = two levels up from `eval/minting_driver/servers.py`.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Default install root: `eval/servers` in the repo (gitignored — third-party JS is
#: pinned but never vendored).
DEFAULT_SERVER_ROOT = _REPO_ROOT / "eval" / "servers"


class MissingServerError(RuntimeError):
    """A pinned MCP server is not installed at the resolved install root.

    The message carries the exact `npm install` command to fix it, plus why `npx` is
    not an alternative.
    """


def server_root(root: Optional[StrPath] = None) -> Path:
    """The install root: explicit `root`, else `$BELAY_EVAL_SERVER_ROOT`, else the default.

    Always returned resolved and absolute — the whole point of this module is that the
    server is launched by absolute path, never resolved through `$PATH` or a cache.
    """
    if root is not None:
        return Path(root).resolve()
    from_env = os.environ.get(SERVER_ROOT_ENV)
    if from_env:
        return Path(from_env).resolve()
    return DEFAULT_SERVER_ROOT.resolve()


def install_command(*names: str, root: Optional[StrPath] = None) -> str:
    """The copy-pasteable `npm install` that puts `names` under the install root.

    With no `names`, covers every pinned server.
    """
    selected = names or tuple(PINNED_SERVERS)
    specs = " ".join(PINNED_SERVERS[name].spec for name in selected)
    return f"npm install --prefix {server_root(root)} {specs}"


def resolve_server_entrypoint(name: str, *, root: Optional[StrPath] = None) -> Path:
    """Absolute path to `name`'s installed entrypoint JS.

    Raises `MissingServerError` — with the exact `npm install` command and the reason
    `npx` cannot substitute for it — when the entrypoint is not present. No network, no
    subprocess: this only looks at the filesystem.
    """
    if name not in PINNED_SERVERS:
        raise KeyError(
            f"unknown pinned MCP server {name!r}; known servers: "
            f"{sorted(PINNED_SERVERS)}"
        )

    server = PINNED_SERVERS[name]
    root_path = server_root(root)
    entrypoint = (root_path / server.entrypoint).resolve()
    if entrypoint.is_file():
        return entrypoint

    raise MissingServerError(
        f"MCP server {server.spec!r} is not installed: expected its entrypoint at\n"
        f"    {entrypoint}\n"
        f"Install it (outside the sandbox, once) with:\n"
        f"    {install_command(name, root=root)}\n"
        f"Then re-run. Override the install root with "
        f"{SERVER_ROOT_ENV}=<dir> if you keep it elsewhere.\n"
        f"\n"
        f"Why not `npx -y {server.spec}`? Belay's gated proxy runs the server under a "
        f"Seatbelt profile that denies network by default and confines writes to the "
        f"workspace scope, so npx can neither fetch from the registry nor write its "
        f"~/.npm cache — it hangs, and npm reports the write denial as a misleading "
        f"'your cache folder contains root-owned files' error. Pre-installing and "
        f"launching `node <abs entrypoint>` needs neither."
    )


def filesystem_server_command(
    allowed_dir: StrPath, *, root: Optional[StrPath] = None
) -> list[str]:
    """The raw (unproxied) argv for the pinned filesystem server.

    `["node", "<abs entrypoint>", str(allowed_dir)]`. `allowed_dir` should be absolute —
    it is the filesystem server's own sandbox boundary (see `eval/README.md`'s "macOS
    gotchas"). Raises `MissingServerError` if the server is not installed.
    """
    entrypoint = resolve_server_entrypoint("filesystem", root=root)
    return ["node", str(entrypoint), str(allowed_dir)]


def shell_server_command(*, root: Optional[StrPath] = None) -> list[str]:
    """The raw (unproxied) argv for the pinned shell server (`mcp-server-commands`).

    Takes no arguments of its own. Raises `MissingServerError` if not installed.
    """
    entrypoint = resolve_server_entrypoint("shell", root=root)
    return ["node", str(entrypoint)]


__all__ = [
    "DEFAULT_SERVER_ROOT",
    "MissingServerError",
    "PINNED_SERVERS",
    "PinnedServer",
    "SERVER_ROOT_ENV",
    "filesystem_server_command",
    "install_command",
    "resolve_server_entrypoint",
    "server_root",
    "shell_server_command",
]
