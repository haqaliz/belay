"""Smoke test for the `run_process` shell MCP fixture server.

`shell_command_server.py` is the shell analogue of `abs_path_editor_server.py`,
and the deliberate INVERSE of every whole-value fixture in this repo. The
whole-value fixtures carry an absolute path as a DISTINCT argument value
(`{"path": "/abs/root/x"}`) that replay can relocate by rewriting the whole
value. This server never does that: it addresses files by an absolute path
EMBEDDED inside a command string (`cat /abs/root/tests/seed.txt`), which is the
exact surface `replay-relocation-shell` exists to close.

This self-test proves, unambiguously, that a `run_process` `tools/call` runs the
command it was handed — reading and writing the ABSOLUTE locations named inside
the command string — deterministically. The proof is structural: the server is
spawned with its cwd pointing at a directory that is a SIBLING of (never a parent
of) the absolute root, so an absolute read/write cannot be mistaken for a
cwd-relative one. Deterministic, offline, stdlib only — no proxy, no sandbox, no
network; only `cat`/`printf`-style commands, no timestamps, no sleeps.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fixtures.shell_command_server import (
    CORRUPT_CONTENT,
    ORIGINAL_CONTENT,
    PLAIN_REPLY,
    RUN_TOOL,
    SEED_REL_PATH,
)

FIXTURE = Path(__file__).parent / "fixtures" / "shell_command_server.py"

OUT_REL_PATH = "tests/out.txt"


def _drive(cwd: Path, frames: list[dict]) -> list[dict]:
    """Spawn the fixture over real stdio pipes, feed `frames`, return its replies.

    `cwd` is the process working directory — deliberately distinct from the root
    the commands address by absolute path, so an absolute-vs-relative confusion
    is observable.
    """
    proc = subprocess.Popen(
        [sys.executable, str(FIXTURE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
    )
    payload = ("\n".join(json.dumps(f) for f in frames) + "\n").encode("utf-8")
    stdout, stderr = proc.communicate(payload, timeout=10.0)
    if proc.returncode != 0:
        raise RuntimeError(
            f"fixture exited {proc.returncode}\nstderr:\n{stderr.decode(errors='replace')}"
        )
    return [json.loads(line) for line in stdout.split(b"\n") if line.strip()]


def _seed(root: Path) -> Path:
    """Create the seed file under `root` at SEED_REL_PATH with ORIGINAL_CONTENT."""
    target = root / SEED_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ORIGINAL_CONTENT, encoding="utf-8")
    return target


def test_fixture_initializes(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    replies = _drive(
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25", "capabilities": {}},
            }
        ],
    )

    assert len(replies) == 1
    assert replies[0]["id"] == 1
    assert "protocolVersion" in replies[0]["result"]


def test_fixture_lists_one_run_process_tool_with_no_annotations(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    replies = _drive(
        cwd,
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}],
    )

    tools = replies[0]["result"]["tools"]
    assert [t["name"] for t in tools] == [RUN_TOOL]
    # Matches the real `mcp-server-commands`: NO annotations on `run_process`, so
    # absent-vs-declared-false stays honest (eval/README.md:128-132).
    assert "annotations" not in tools[0]


def test_run_process_command_line_reads_the_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = _seed(root)

    replies = _drive(
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": RUN_TOOL,
                    "arguments": {
                        "command_line": f"cat {target}",
                        "cwd": str(cwd),
                    },
                },
            }
        ],
    )

    result = replies[0]["result"]
    assert result["isError"] is False
    # Default reply shape carries the command's real stdout — the file content.
    assert result["content"][0]["text"] == ORIGINAL_CONTENT


def test_run_process_argv_form_reads_the_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = _seed(root)

    replies = _drive(
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": RUN_TOOL,
                    "arguments": {"argv": ["cat", str(target)]},
                },
            }
        ],
    )

    result = replies[0]["result"]
    assert result["isError"] is False
    assert result["content"][0]["text"] == ORIGINAL_CONTENT


def test_run_process_write_lands_at_the_absolute_location(tmp_path: Path) -> None:
    """An edit-style command writes the absolute path, not a cwd-relative one.

    This is the surface aspect 2's effect/false-negative test builds on: the
    write must land under `root` (addressed absolutely inside the command
    string), and NOT at a cwd-relative tail.
    """
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    # The parent must exist for a plain shell redirect to succeed.
    (root / "tests").mkdir()
    out = root / OUT_REL_PATH

    replies = _drive(
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": RUN_TOOL,
                    "arguments": {
                        "command_line": f"printf '{CORRUPT_CONTENT}' > {out}",
                        "reply_format": "plain",
                    },
                },
            }
        ],
    )

    assert replies[0]["result"]["isError"] is False
    # The plain reply is a fixed literal carrying NO path — the clean case.
    assert replies[0]["result"]["content"][0]["text"] == PLAIN_REPLY

    # The write landed at the ABSOLUTE path under `root` ...
    assert out.read_text(encoding="utf-8") == CORRUPT_CONTENT
    # ... and NOT at a cwd-relative location. `root` is a sibling of `cwd`, so a
    # cwd-relative write of the same tail would have created `cwd/tests/out.txt`.
    assert not (cwd / OUT_REL_PATH).exists()
    assert list(cwd.iterdir()) == []
