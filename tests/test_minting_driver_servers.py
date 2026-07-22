"""Locating the pre-installed MCP servers — deterministic, offline, CI-safe.

`npx -y <pkg>` cannot be used behind Belay's gated proxy: the Seatbelt profile denies
network by default and confines writes to the workspace scope, so `npx` can neither reach
the registry nor write `~/.npm` and simply hangs (npm misreports the write denial as a
bogus "your cache folder contains root-owned files" error). The mint therefore
pre-installs each pinned server OUTSIDE the sandbox and invokes it by absolute path with
`node`. `eval.minting_driver.servers` is the helper that finds those installs and, when
one is missing, says exactly which `npm install` to run and why `npx` is not an option.

Every test here fakes an install root under `tmp_path`: nothing touches the real
`eval/servers`, nothing spawns a process, nothing reaches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.minting_driver import servers


def _fake_install(root: Path, name: str) -> Path:
    """Create an empty entrypoint file for `name` under a fake install `root`."""
    entrypoint = root / servers.PINNED_SERVERS[name].entrypoint
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text("// fake\n", encoding="utf-8")
    return entrypoint


def test_resolve_returns_absolute_path_when_entrypoint_exists(tmp_path: Path) -> None:
    expected = _fake_install(tmp_path, "filesystem")

    resolved = servers.resolve_server_entrypoint("filesystem", root=tmp_path)

    assert resolved.is_absolute()
    assert resolved == expected.resolve()


def test_resolve_raises_named_error_naming_npm_install_when_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(servers.MissingServerError) as excinfo:
        servers.resolve_server_entrypoint("filesystem", root=tmp_path)

    message = str(excinfo.value)
    assert "npm install" in message
    assert "@modelcontextprotocol/server-filesystem" in message
    assert str(tmp_path) in message
    # The *why*: the operator must understand npx is not an alternative here.
    assert "npx" in message
    assert "network" in message.lower()


def test_pinned_version_appears_in_the_install_command_in_the_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(servers.MissingServerError) as excinfo:
        servers.resolve_server_entrypoint("shell", root=tmp_path)

    assert "mcp-server-commands@0.8.2" in str(excinfo.value)


def test_filesystem_server_command_starts_with_node_and_never_uses_npx(
    tmp_path: Path,
) -> None:
    entrypoint = _fake_install(tmp_path, "filesystem")
    allowed_dir = tmp_path / "workspace"
    allowed_dir.mkdir()

    command = servers.filesystem_server_command(allowed_dir, root=tmp_path)

    assert command[0] == "node"
    assert command[1] == str(entrypoint.resolve())
    assert command[2] == str(allowed_dir)
    assert "npx" not in command
    assert not any("npx" in part for part in command)


def test_server_root_env_var_override_is_honored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrypoint = _fake_install(tmp_path, "filesystem")
    monkeypatch.setenv(servers.SERVER_ROOT_ENV, str(tmp_path))

    assert servers.server_root() == tmp_path.resolve()
    assert servers.resolve_server_entrypoint("filesystem") == entrypoint.resolve()


def test_default_server_root_is_eval_servers_in_the_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(servers.SERVER_ROOT_ENV, raising=False)

    root = servers.server_root()

    assert root.name == "servers"
    assert root.parent.name == "eval"
