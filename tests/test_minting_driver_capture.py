"""RED-first tests for `eval.minting_driver.capture` — the gated proxy/env wiring.

Pure, no subprocess spawn, deterministic: `proxy_command` is a plain argv-shaping
function and `gated_env` is a plain dict-shaping function, so both are fully testable
without ever running `belay.proxy` or a real MCP server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from eval.minting_driver.capture import gated_env, proxy_command


def test_proxy_command_shape_has_no_separator() -> None:
    """No `--` separator: the whole argv after `-m belay.proxy` IS the server command."""
    result = proxy_command(["npx", "-y", "some-mcp-server", "--flag"])

    assert result == [
        sys.executable,
        "-m",
        "belay.proxy",
        "npx",
        "-y",
        "some-mcp-server",
        "--flag",
    ]
    assert "--" not in result


def test_proxy_command_uses_sys_executable() -> None:
    result = proxy_command(["some-server"])

    assert result[0] == sys.executable
    assert result[1:3] == ["-m", "belay.proxy"]


def test_proxy_command_empty_server_command() -> None:
    """Degenerate but well-defined: an empty server command just yields the bare
    proxy invocation, with nothing appended after it."""
    result = proxy_command([])

    assert result == [sys.executable, "-m", "belay.proxy"]


def test_gated_env_sets_all_three_vars() -> None:
    env = gated_env(
        trace_dir="/tmp/traces",
        scope="process",
        snapshot_dir="/tmp/snapshots",
        base={},
    )

    assert env["BELAY_TRACE_DIR"] == "/tmp/traces"
    assert env["BELAY_SANDBOX_SCOPE"] == "process"
    assert env["BELAY_SNAPSHOT_DIR"] == "/tmp/snapshots"


def test_gated_env_coerces_paths_to_str() -> None:
    env = gated_env(
        trace_dir=Path("/tmp/traces"),
        scope="process",
        snapshot_dir=Path("/tmp/snapshots"),
        base={},
    )

    assert env["BELAY_TRACE_DIR"] == str(Path("/tmp/traces"))
    assert isinstance(env["BELAY_TRACE_DIR"], str)
    assert env["BELAY_SNAPSHOT_DIR"] == str(Path("/tmp/snapshots"))
    assert isinstance(env["BELAY_SNAPSHOT_DIR"], str)


def test_gated_env_does_not_mutate_base() -> None:
    base = {"EXISTING": "value"}
    original = dict(base)

    result = gated_env(trace_dir="/tmp/traces", scope=None, snapshot_dir=None, base=base)

    assert base == original
    assert result is not base
    assert result["EXISTING"] == "value"


def test_gated_env_defaults_base_to_os_environ() -> None:
    marker = "BELAY_MINTING_DRIVER_TEST_MARKER"
    os.environ[marker] = "present"
    try:
        env = gated_env(trace_dir="/tmp/traces", scope=None, snapshot_dir=None)
        assert env[marker] == "present"
    finally:
        del os.environ[marker]


def test_gated_env_raises_on_scope_without_snapshot_dir() -> None:
    with pytest.raises(ValueError):
        gated_env(trace_dir="/tmp/traces", scope="process", snapshot_dir=None, base={})


def test_gated_env_raises_on_scope_with_falsy_snapshot_dir() -> None:
    with pytest.raises(ValueError):
        gated_env(trace_dir="/tmp/traces", scope="process", snapshot_dir="", base={})


def test_gated_env_no_scope_no_snapshot_dir_is_fine() -> None:
    env = gated_env(trace_dir="/tmp/traces", scope=None, snapshot_dir=None, base={})

    assert env["BELAY_TRACE_DIR"] == "/tmp/traces"
    assert "BELAY_SANDBOX_SCOPE" not in env
    assert "BELAY_SNAPSHOT_DIR" not in env
