"""Phase 3: relocation wired into the replay flow — the WIRING units, gated & additive.

Phase 1 pinned the pure primitives (`test_replay_relocate.py`); Phase 4 proves the full
end-to-end fidelity on real Seatbelt replay. This file sits between them: it pins the
*wiring* that consumes `Manifest.source_root` and drives those primitives, with fakes and
direct helper calls so the logic is cross-platform and needs no sandbox.

Four load-bearing wiring facts:

1. A relocated `tools/call` frame keeps its JSON-RPC `id` (and every non-path field) through
   re-serialization, so `converse`'s id-correlation still matches the reply — only the
   whole-value path argument moves.
2. Gating: a cwd-relative turn (no in-root absolute path) takes the UNCHANGED path — the
   relocation decision returns "no relocation", and a non-`tools/call` or path-free frame is
   passed through byte-for-byte.
3. Honest fallback: a turn that carries an absolute-path argument but whose manifest recorded
   NO root is `UNVERIFIED` with the named cause — never a guessed PASS/FAIL, and never a
   server re-invocation.
4. Reply canonicalization stays key-order-independent: two replies equal up to key order AND
   differing only in the relocated root compare EQUAL, via structural comparison (not a text
   dump).
"""

from __future__ import annotations

import json
from pathlib import Path

from belay.replay import engine
from belay.replay.client import _relocate_frame
from belay.replay.engine import ROOTLESS_RELOCATION, UNVERIFIED, _equivalence, _relocation_decision
from belay.snapshot.substrate import ClonefileBackend, FIDELITY_GAPS
from belay.trace import TraceWriter


# --- 1. A relocated frame preserves its JSON-RPC id --------------------------


def test_relocated_frame_preserves_jsonrpc_id() -> None:
    """The whole-value path argument moves; the `id`, method, name and content do not.

    `converse` correlates a reply to its request by ``(direction, type(id), id)``; if
    re-serialization dropped or retyped the id, the replayed reply could never be matched.
    Here the `path` argument (a whole-value in-root absolute path) is remapped to the scratch
    while `id`, `method`, the tool `name`, and the `new_content` field (file content that
    merely mentions the root) survive byte-for-byte in value.
    """
    frame = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "edit_abs",
                "arguments": {
                    "path": "/root/proj/tests/t.py",
                    "new_content": "assert '/root/proj' in banner\n",
                },
            },
        }
    ).encode()

    relocated = _relocate_frame(frame, "/root/proj", "/scratch/proj")
    decoded = json.loads(relocated)

    assert decoded["id"] == 7, "the JSON-RPC id must survive re-serialization"
    assert decoded["method"] == "tools/call"
    assert decoded["params"]["name"] == "edit_abs"
    assert decoded["params"]["arguments"]["path"] == "/scratch/proj/tests/t.py", (
        "the whole-value path argument must be relocated to the scratch root"
    )
    assert decoded["params"]["arguments"]["new_content"] == "assert '/root/proj' in banner\n", (
        "content that merely mentions the root must NOT be rewritten"
    )


# --- 2. Gating: a cwd-relative / path-free frame is passed through untouched --


def test_non_path_frames_pass_through_verbatim() -> None:
    """A non-`tools/call` frame, and a `tools/call` with no in-root path, are byte-identical.

    The additive guarantee at the frame level: an `initialize` handshake frame and a
    `tools/call` whose arguments carry no whole-value in-root absolute path are returned as
    the exact input bytes — nothing is re-serialized, so a cwd-relative replay is unchanged.
    """
    initialize = (
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"x"}}'
    )
    assert _relocate_frame(initialize, "/root", "/scratch") is initialize

    cwd_relative_call = (
        b'{"jsonrpc":"2.0","id":2,"method":"tools/call",'
        b'"params":{"name":"read","arguments":{"path":"src/x.py"}}}'
    )
    assert _relocate_frame(cwd_relative_call, "/root", "/scratch") is cwd_relative_call

    garbage = b"not json at all"
    assert _relocate_frame(garbage, "/root", "/scratch") is garbage


def test_relocation_decision_gates_on_in_root_paths() -> None:
    """The pure gate: relocate iff a root is recorded AND the turn carries an in-root path.

    - Root present, in-root path -> relocate under that root, no fallback.
    - Root present, cwd-relative -> NO relocation (today's byte-for-byte path), no fallback.
    - Root absent, cwd-relative -> NO relocation, no fallback (an old cwd-relative trace is
      untouched — the additive guarantee for every existing rootless capture).
    """
    argv = ["python", "/opt/py/server.py", "/root/proj"]

    reloc_root, fallback = _relocation_decision("/root/proj", {"path": "/root/proj/a.py"}, argv)
    assert reloc_root == "/root/proj" and fallback is None

    reloc_root, fallback = _relocation_decision("/root/proj", {"path": "src/a.py"}, ["python", "s.py"])
    assert reloc_root is None and fallback is None, "a cwd-relative turn is not relocated"

    reloc_root, fallback = _relocation_decision(None, {"s": "hi"}, ["python", "/abs/server.py"])
    assert reloc_root is None and fallback is None, (
        "a rootless cwd-relative turn must be UNCHANGED even though argv holds an absolute "
        "python path"
    )


# --- 3. Honest fallback: rootless manifest + an in-root absolute path ---------


def _rootless_manifest(manifest_dir: Path, handle: str) -> Path:
    """A persisted manifest with NO `source_root` key (an old, pre-field capture).

    Hand-built (not `take_snapshot`) so the fallback path is exercised cross-platform: the
    engine reaches its relocation gate — and returns the honest `UNVERIFIED` — BEFORE any
    clonefile restore, so no macOS Seatbelt machinery is touched.
    """
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "handle": handle,
        "tree_path": str(manifest_dir / "tree"),
        "backend": ClonefileBackend.name,
        "capabilities": sorted(ClonefileBackend.capabilities()),
        "fidelity_gaps": [gap.value for gap in FIDELITY_GAPS],
        "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
    }
    (manifest_dir / "m.json").write_text(json.dumps(payload), encoding="utf-8")
    return manifest_dir


def _records(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Build a real trace via `TraceWriter` and read its records back (cross-platform)."""
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


def test_rootless_manifest_with_abs_path_is_unverified(tmp_path) -> None:
    """A turn with an in-root absolute path but no recorded root -> `UNVERIFIED`, named cause.

    Without the recorded root, replay cannot faithfully relocate the absolute path into the
    scratch, so it must NOT guess a verdict. It returns `UNVERIFIED` with the exact named
    cause and does not re-invoke the server — UNVERIFIED-never-PASS made structural for the
    absolute-path class.
    """
    manifest_dir = _rootless_manifest(tmp_path / "mans", "h1")
    call = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_abs", "arguments": {"path": "/some/abs/workspace/a.py"}},
        }
    ).encode()
    present = {"status": "present", "handle": "h1"}
    records = _records(tmp_path, "rootless", [("c2s", call, present)])

    out = engine.replay_turn(
        records, 0, server_command=["python", "srv.py"], manifest_dir=manifest_dir, timeout=1.0
    )

    assert out.status == UNVERIFIED, out
    assert out.cause == ROOTLESS_RELOCATION
    assert out.reinvoked is False, "the honest fallback must NOT re-invoke the server"
    assert out.replayed_reply is None


def test_rootless_cwd_relative_turn_is_not_flagged(tmp_path) -> None:
    """The anti-vacuity partner: a rootless CWD-relative turn is NOT diverted to fallback.

    If the fallback tripped on any rootless turn it would break every existing cwd-relative
    replay. A relative `path` argument carries no absolute path, so the decision is "no
    relocation" and the engine proceeds down its normal path (here it would go on to restore
    — which is why this only asserts it did NOT short-circuit to the fallback cause).
    """
    _reloc, fallback = _relocation_decision(None, {"path": "src/x.py", "s": "hi"}, ["python", "s.py"])
    assert fallback is None


# --- 4. Reply canonicalization stays key-order-independent --------------------


def test_reply_equivalence_is_key_order_independent_and_root_folding() -> None:
    """`_equivalence` compares parsed structures: key order is irrelevant AND roots fold.

    Two facts in one, because they must hold together:
    - key order independence — the recorded (parsed) and replayed (bytes) messages compare
      EQUAL even with their keys serialized in a different order (structural `==`, never a
      text dump).
    - root folding — a path that appears as the ORIGINAL root in the recorded reply and as
      the SCRATCH root in the replayed reply compares EQUAL once both roots are canonicalized.
    Both together, with the keys deliberately reordered, prove the canonicalization did not
    quietly switch to an order-sensitive text comparison.
    """
    recorded = {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"isError": False, "content": [{"text": "Index: /root/proj/a.py", "type": "text"}]},
    }
    # Same message, scratch root, and keys in a DIFFERENT order.
    replayed = json.dumps(
        {
            "id": 3,
            "result": {"content": [{"type": "text", "text": "Index: /scratch/proj/a.py"}], "isError": False},
            "jsonrpc": "2.0",
        }
    ).encode()

    # Without relocation the roots differ -> DIVERGED (control).
    assert _equivalence(recorded, replayed) == engine.DIVERGED

    # With relocation both roots fold to a placeholder, so it is EQUAL despite key order.
    result = _equivalence(recorded, replayed, from_root="/root/proj", to_root="/scratch/proj")
    assert result == engine.EQUAL, "relocated replies differing only by root must compare EQUAL"
