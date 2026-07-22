"""Smoke test for the absolute-path MCP fixture server.

`abs_path_editor_server.py` is the INVERSE of every other fixture in this repo:
each existing fixture addresses files RELATIVE to its cwd (which replay sets to the
restored scratch), which is exactly why an absolute-path replay bug could survive
CI. This fixture takes an absolute root as `argv[1]` and addresses files by
ABSOLUTE path — so this smoke test's whole job is to prove, unambiguously, that a
`tools/call` operates on the ABSOLUTE location the argument names and NOT on a
cwd-relative one.

The proof is structural: the server is spawned with its cwd pointing at a directory
that is a SIBLING of (never a parent of) the absolute root. A write that lands under
the root therefore cannot be a cwd-relative write, and the cwd is asserted to stay
empty. Deterministic, offline, stdlib only — no proxy, no sandbox, no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fixtures.abs_path_editor_server import (
    CORRUPT_CONTENT,
    EDIT_REPLY,
    EDIT_TOOL,
    ORIGINAL_CONTENT,
    READ_TOOL,
    SEED_REL_PATH,
)

FIXTURE = Path(__file__).parent / "fixtures" / "abs_path_editor_server.py"


def _drive(root: Path, cwd: Path, frames: list[dict]) -> list[dict]:
    """Spawn the fixture over real stdio pipes, feed `frames`, return its replies.

    `root` becomes the server's allowed absolute root (argv[1]); `cwd` is the
    process working directory — deliberately distinct so an absolute-vs-relative
    confusion is observable.
    """
    proc = subprocess.Popen(
        [sys.executable, str(FIXTURE), str(root)],
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
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    replies = _drive(
        root,
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


def test_fixture_lists_its_two_absolute_path_tools(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    replies = _drive(
        root,
        cwd,
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}],
    )

    tools = {t["name"] for t in replies[0]["result"]["tools"]}
    assert tools == {READ_TOOL, EDIT_TOOL}


def test_read_abs_reads_the_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = _seed(root)

    replies = _drive(
        root,
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": READ_TOOL, "arguments": {"path": str(target)}},
            }
        ],
    )

    result = replies[0]["result"]
    assert result["isError"] is False
    assert result["content"][0]["text"] == ORIGINAL_CONTENT


def test_edit_abs_writes_the_absolute_location_not_a_cwd_relative_one(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = _seed(root)

    # A corrupt edit: overwrite the seed with the gutted body.
    replies = _drive(
        root,
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": EDIT_TOOL,
                    "arguments": {"path": str(target), "new_content": CORRUPT_CONTENT},
                },
            }
        ],
    )

    assert replies[0]["result"]["isError"] is False
    assert replies[0]["result"]["content"][0]["text"] == EDIT_REPLY

    # The write landed at the ABSOLUTE path under `root` ...
    assert target.read_text(encoding="utf-8") == CORRUPT_CONTENT
    # ... and NOT at a cwd-relative location. `root` is a sibling of `cwd`, so a
    # cwd-relative write of the same tail would have created `cwd/<SEED_REL_PATH>`.
    assert not (cwd / SEED_REL_PATH).exists()
    assert list(cwd.iterdir()) == []


def test_edit_abs_diff_reply_embeds_the_absolute_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = _seed(root)

    replies = _drive(
        root,
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": EDIT_TOOL,
                    "arguments": {
                        "path": str(target),
                        "new_content": CORRUPT_CONTENT,
                        "reply_format": "diff",
                    },
                },
            }
        ],
    )

    text = replies[0]["result"]["content"][0]["text"]
    # A unified diff whose `Index:` line carries the absolute path — the substring
    # a later reply-normalization phase must canonicalize away.
    assert f"Index: {target}" in text
    assert text.startswith("Index: ")


def test_edit_abs_rejects_a_path_outside_the_root(tmp_path: Path) -> None:
    """Path-confinement to argv[1] is what makes relocating the argv root load-bearing."""
    root = tmp_path / "root"
    root.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("do not touch", encoding="utf-8")

    replies = _drive(
        root,
        cwd,
        [
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": EDIT_TOOL,
                    "arguments": {"path": str(outside), "new_content": "x"},
                },
            }
        ],
    )

    assert replies[0]["result"]["isError"] is True
    assert outside.read_text(encoding="utf-8") == "do not touch"
