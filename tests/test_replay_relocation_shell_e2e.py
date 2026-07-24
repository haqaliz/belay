"""Phase 4 — the end-to-end acceptance suite for FAITHFUL SHELL command relocation.

The shell analogue of `test_replay_relocation_e2e.py`. Aspect 1 detected-and-abstained a
`run_process` turn whose `command_line` buried the workspace path; aspect 2 RELOCATES the
tractable case (a whole-token in-root path) so the turn replays against the scratch and earns
a real, grounded verdict. This file proves that on REAL Seatbelt replay, driving the committed
shell fixture (`shell_command_server.py`) through `engine.replay_turn` / `verify.turn.verify_turn`
from a REAL gated capture — a snapshot taken with `take_snapshot`, persisted WITH `source_root`
(exactly as `sandbox.gate` records it), and a trace recorded through the real `TraceWriter`.

## The load-bearing axis for shell is A1, by design

`run_process` mirrors the real `mcp-server-commands`: it declares **NO** MCP annotations. So the
A2 effect axis is honestly UNVERIFIED (an absent contract is never a permissive one), and a shell
turn never reduces to a bare PASS. **A user-declared invariant (A1) is the load-bearing check** —
exactly as `shell_command_server.py`'s docstring and `CLAUDE.md` state. So a corrupt shell WRITE
is caught by A1 (`tests/` read-only), and "no false positive" means the RELOCATION machinery adds
no spurious FAIL and the A2 *result* axis reproduces — not that an un-annotated turn turns green.

The four criteria pinned here (the SAFE, high-value subset):

  1. `test_verdict_is_invariant_to_live_workspace_state` — THE core: pristine / mutated / deleted
     original workspace -> IDENTICAL verdict. The shell contamination fix proven.
  2. `test_corrupt_shell_write_is_flagged` — no false negative: a relocated corrupt WRITE FAILs.
  3. `test_benign_shell_write_does_not_flag` — no false positive: a faithful write adds no FAIL.
  4. `test_stdout_reply_with_abs_path_compares_equal` — the stdout path folds to EQUAL.

Why the darwin gate: real replay re-invokes inside the macOS Seatbelt sandbox, so off-darwin
these are an honest skip, exactly like `test_replay_relocation_e2e.py`. The capture helpers
mirror that file; this one adapts them to a rootless shell server addressed by absolute paths
embedded inside a `command_line` string.

## What OLD (aspect-1) behavior would do — the RED these are red against

Before aspect 2, a `command_line` embedding the workspace path abstained
(`EMBEDDED_PATH_UNRELOCATABLE`) — every shell turn read as UNVERIFIED, catching nothing. These
tests need the relocation to land the write in the scratch so A1 can see the real delta; they
fail against the aspect-1 engine (UNVERIFIED, no delta) and pass against the wired one.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from fixtures.shell_command_server import (
    BENIGN_CONTENT,
    CORRUPT_CONTENT,
    ORIGINAL_CONTENT,
    RUN_TOOL,
    SEED_REL_PATH,
    TOOLS,
)

from belay.replay import engine
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
SHELL_SERVER = FIXTURES / "shell_command_server.py"

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

#: The task-scoped invariant that catches a corrupt success: `tests/` is read-only. The seed
#: lives at `tests/seed.txt` (SEED_REL_PATH), so any write there crosses this scope.
TESTS_READONLY = Invariant(scope=b"tests/", rule="read-only")


# --- frame builders (mirror test_replay_relocation_e2e.py, adapted to the shell server) ---


def _server_cmd() -> list[str]:
    """`python shell_command_server.py` — a ROOTLESS shell (no argv allow-root token).

    The whole point of aspect 2: the server takes its root from the absolute paths INSIDE each
    command, not from an argv allowlist, so no argv token is under the recorded root.
    """
    return [sys.executable, str(SHELL_SERVER)]


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    """`run_process` with NO annotations — matching the real `mcp-server-commands`.

    Absent (not declared-false) is the honest shape: the A2 effect axis is UNVERIFIED and A1
    carries the verdict, exactly as the fixture's docstring intends.
    """
    return json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": TOOLS}}).encode()


def _call(arguments: dict) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": RUN_TOOL, "arguments": arguments},
        }
    ).encode()


def _reply(text: str, *, is_error: bool = False) -> bytes:
    """A recorded `tools/call` response shaped exactly like the fixture's `_text_result`."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
        }
    ).encode()


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Record `frames` via the REAL `TraceWriter`; read the records back (verbatim pattern)."""
    trace_dir = tmp_path / name
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, handle in frames:
            if handle is not None:
                writer.set_state_handle(handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()
    path = sorted(trace_dir.glob("*.jsonl"))[0]
    return [json.loads(line) for line in path.read_bytes().split(b"\n") if line]


def _shell_capture(tmp_path: Path, name: str, seed_content: str, frames_for):
    """A REAL gated capture of one shell turn: (records, manifest_dir, work, root).

    Seeds `work/tests/seed.txt = seed_content`, snapshots it, and persists the manifest WITH
    `source_root` (the resolved workspace root — exactly what `sandbox.gate` records) so the
    engine's relocation gate fires. `frames_for(root)` returns the `(call, reply)` bytes for the
    single `run_process` turn, whose `command_line` embeds an absolute path under `root`.
    """
    work = tmp_path / f"{name}-work"
    (work / "tests").mkdir(parents=True)
    (work / SEED_REL_PATH).write_text(seed_content, encoding="utf-8")
    root = os.path.realpath(str(work))

    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json", source_root=root)
    present = present_handle(snap)

    call, reply = frames_for(root)
    records = _trace(
        tmp_path,
        f"{name}-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", call, present),
            ("s2c", reply, None),
        ],
    )
    return records, manifest_dir, work, root


def _abs_path(root: str) -> str:
    """The absolute path of the seed file under `root` — embedded inside the command string."""
    return os.path.join(root, SEED_REL_PATH)


def _write_frames(content: str):
    """A `frames_for` closure: overwrite the seed via `printf '<content>' > <abs>`.

    The path is a clean whole shell token, so aspect 2 relocates it to the scratch; the write
    lands in the restored copy and the tree diff sees the real content change. `content` is
    single-quote-free (the fixture guarantees it), so it drops into `printf '...'` without
    escaping, and the redirect's stdout is empty — a deterministic reply that reproduces.
    """

    def frames_for(root: str):
        command_line = f"printf '{content}' > {_abs_path(root)}"
        return _call({"command_line": command_line}), _reply("")

    return frames_for


def _shape(verdict) -> tuple:
    """A comparable fingerprint of a TurnVerdict: reduced status + each sub-verdict's identity.

    Excludes free-text messages (which embed the mkdtemp scratch path) — the *verdict* must be
    invariant to the specific scratch path, and this fingerprint is what that is asserted over.
    """
    return (
        verdict.status,
        tuple(sorted((s.axis, s.kind, s.status) for s in verdict.sub_verdicts)),
    )


# --- 1. THE CORE: the verdict is invariant to live workspace state --------------------


@darwin_only
def test_verdict_is_invariant_to_live_workspace_state(tmp_path) -> None:
    """Pristine / mutated / DELETED original workspace -> the SAME verdict. Contamination fixed.

    A corrupt shell write (`printf CORRUPT > <abs>/tests/seed.txt`, gutting the assertion) is
    captured once, with the `tests/` read-only invariant declared. The SAME (records, manifest)
    is verified three times while the ORIGINAL workspace is (a) pristine, (b) mutated, (c)
    deleted. Because replay restores the persisted SNAPSHOT into a fresh scratch and RELOCATES
    the command_line's absolute path there, the verdict reads only the restored pre-state — so
    all three are IDENTICAL (and FAIL, by A1).

    Against the aspect-1 engine the command_line abstained (UNVERIFIED, no delta); against an
    un-relocated replay the write would hit the live workspace and move with (a)/(b)/(c). This
    is the fix.
    """
    records, manifest_dir, work, root = _shell_capture(
        tmp_path, "invariant", ORIGINAL_CONTENT, _write_frames(CORRUPT_CONTENT)
    )
    cmd = _server_cmd()

    def _verify():
        return verify_turn(
            records, 0, server_command=cmd, manifest_dir=manifest_dir,
            invariants=[TESTS_READONLY], timeout=20.0,
        )

    # (a) original workspace pristine
    pristine = _verify()
    assert pristine.status is Status.FAIL, pristine

    # (b) original workspace MUTATED after capture — must not move the verdict
    (work / SEED_REL_PATH).write_text("print('unrelated live edit')\n", encoding="utf-8")
    mutated = _verify()

    # (c) original workspace DELETED after capture — must not move the verdict
    shutil.rmtree(work)
    assert not work.exists()
    deleted = _verify()

    assert _shape(pristine) == _shape(mutated) == _shape(deleted), (
        "the verdict must depend ONLY on the restored snapshot, never on live workspace state",
        _shape(pristine), _shape(mutated), _shape(deleted),
    )
    # And it is a real, meaningful verdict (A1 caught the gutting in the relocated scratch).
    a1 = next(s for s in deleted.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert a1.status is Status.FAIL, a1.message
    assert "tests/seed.txt" in a1.message, a1.message


# --- 2. No false negative: a corrupt shell write IS flagged ---------------------------


@darwin_only
def test_corrupt_shell_write_is_flagged(tmp_path) -> None:
    """A corrupt shell write (`printf CORRUPT > <abs>`) under a `tests/` read-only invariant -> FAIL.

    The relocated command_line lands the write in the scratch, so the tree diff sees a REAL
    content change under the read-only `tests/` subtree and A1 FAILs — the shell analogue of the
    weakening-editor cheat. No false negative: the delta is real precisely because the command's
    absolute path was relocated into the restored copy rather than denied against the original.
    """
    records, manifest_dir, _work, root = _shell_capture(
        tmp_path, "corrupt", ORIGINAL_CONTENT, _write_frames(CORRUPT_CONTENT)
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(), manifest_dir=manifest_dir,
        invariants=[TESTS_READONLY], timeout=20.0,
    )

    assert verdict.status is Status.FAIL, verdict
    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert a1.status is Status.FAIL, a1.message
    assert "tests/seed.txt" in a1.message, a1.message


# --- 3. No false positive: a benign shell write adds no FAIL --------------------------


@darwin_only
def test_benign_shell_write_does_not_flag(tmp_path) -> None:
    """A correct shell write (BENIGN_CONTENT, keeps the assertion) adds NO FAIL sub-verdict.

    With no invariant declared this isolates the RELOCATION + A2 machinery: the relocated write
    lands in the scratch, the empty-stdout reply reproduces (A2 result PASS), and no FAIL is
    produced. The turn's REDUCED status is UNVERIFIED — honestly, because `run_process` declares
    no `readOnlyHint`, so the effect axis has no contract to confirm (an absent contract is never
    a permissive PASS). "No false positive" is the absence of a FAIL, and the result axis
    reproducing — not a green light manufactured from an un-annotated tool.
    """
    records, manifest_dir, _work, root = _shell_capture(
        tmp_path, "benign", ORIGINAL_CONTENT, _write_frames(BENIGN_CONTENT)
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert [s for s in verdict.sub_verdicts if s.status is Status.FAIL] == [], verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


# --- 4. Reply comparison: a stdout reply carrying the abs path folds to EQUAL ----------


@darwin_only
def test_stdout_reply_with_abs_path_compares_equal(tmp_path) -> None:
    """A command whose STDOUT echoes the absolute path compares EQUAL after relocation.

    `echo <abs>` prints the (relocated) path on replay while the recorded reply carries the
    ORIGINAL path; the existing `canonicalize` fold maps both roots to a placeholder for
    comparison only, so result-equivalence is a PASS — no false positive from a path that
    legitimately surfaces in stdout. No new normalization code: this exercises the shipped fold.
    """
    def frames_for(root: str):
        abs_path = _abs_path(root)
        return _call({"command_line": f"echo {abs_path}"}), _reply(f"{abs_path}\n")

    records, manifest_dir, _work, root = _shell_capture(
        tmp_path, "reply", ORIGINAL_CONTENT, frames_for
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message
