"""`belay verify --invariants` / `--no-default-invariants` — A1 on the CLI surface.

The launch demo (`test_launch_demo.py`) proves the axes' non-redundancy at the
`verify_turn` API. This proves the SAME divergence is reachable from the command line: a
`belay verify` over the weakening-editor trace applies the A1 `tests/` read-only invariant
(on by default), FAILs the corrupt success, and exits non-zero — and `--no-default-invariants`
drops it, so the exact same trace with no invariant declared is a PASS again.

The editor declares `readOnlyHint: false` and overwrites `tests/test_auth.py`, so A2 is a
clean PASS (result reproduces, declared-false effect conforms) and ONLY the A1 invariant
catches the write. On the CLI that shows up as the A1 sub-verdict line and a non-zero exit.

Darwin-gated: the real replay runs in the macOS Seatbelt sandbox.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION

from belay import cli
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_CMD = [sys.executable, str(FIXTURES / "weakening_editor_server.py")]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"


def _snapshot(tmp_path: Path, body: str, manifest_dir: Path):
    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(body, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list() -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _reply() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": "edited tests/test_auth.py"}],
                "isError": False,
            },
        }
    ).encode()


def _trace(tmp_path: Path, frames: list[tuple]) -> Path:
    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    return sorted(trace_dir.glob("*.jsonl"))[0]


def _demo_trace(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot(tmp_path, STRONG_TEST, manifest_dir)
    trace_path = _trace(
        tmp_path,
        _tools_list() + [("c2s", _call(), handle), ("s2c", _reply(), None)],
    )
    return trace_path, manifest_dir


def test_verify_default_invariant_fails_the_corrupt_success(tmp_path, capsys):
    """`belay verify` with the DEFAULT `tests/` read-only invariant FAILs the write.

    No `--invariants` file: the default invariant is on out of the box, so the CLI catches
    the corrupt success with zero operator authoring. The A1 sub-verdict line is shown and
    the exit is non-zero.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    rc = cli.main(["verify", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *EDITOR_CMD])
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "A1 invariant" in out, out
    assert "tests/test_auth.py" in out, out


def test_no_default_invariants_drops_a1(tmp_path, capsys):
    """`--no-default-invariants` with no `--invariants` file: A1 absent, PASS again.

    The exact same trace, with the default invariant dropped and none supplied, carries no
    A1 sub-verdict — A2 is a clean PASS and the turn is a PASS, exit zero. This is the
    one-flag proof that the A1 FAIL above is the invariant's doing and not A2's.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "A1 invariant" not in out, out


def test_invariants_file_is_applied(tmp_path, capsys):
    """`--invariants <file>` declaring `tests/` read-only FAILs the write.

    Proves the operator-file path reaches `verify_turn`. Combined with
    `--no-default-invariants` so the FAIL can only come from the file, not the default.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)
    inv_file = tmp_path / "policy.json"
    inv_file.write_text(json.dumps([{"scope": "tests/", "rule": "read-only"}]), encoding="utf-8")

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--no-default-invariants", "--invariants", str(inv_file), "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 1, out
    assert "A1 invariant" in out, out


def test_malformed_invariants_file_is_fail_closed(tmp_path, capsys):
    """A malformed `--invariants` file is a clean exit 2, never a silent verify-against-nothing.

    An operator who declared a policy Belay could not parse must not have the run verified
    against NO policy and reported clean. The loader raises `ValueError`; the CLI prints it
    and exits 2 (fail-closed) rather than proceeding with a dropped policy.
    """
    trace_path, manifest_dir = _demo_trace(tmp_path)
    inv_file = tmp_path / "bad.json"
    inv_file.write_text("{ not valid json", encoding="utf-8")

    rc = cli.main(
        ["verify", str(trace_path), "--manifest-dir", str(manifest_dir),
         "--invariants", str(inv_file), "--server", *EDITOR_CMD]
    )
    out = capsys.readouterr().out

    assert rc == 2, out
    assert "belay:" in out, out
