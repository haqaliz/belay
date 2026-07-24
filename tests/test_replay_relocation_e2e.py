"""Phase 4 — the end-to-end acceptance suite that PROVES the absolute-path relocation fix.

This is the falsifiable core of `replay-relocation`. Phase 1 pinned the pure primitives
(`test_replay_relocate.py`) and Phase 3 pinned the wiring units with fakes
(`test_replay_relocation_wiring.py`). This file proves the whole spec on REAL Seatbelt
replay, driving the committed absolute-path fixture (`abs_path_editor_server.py`) through
`engine.replay_turn` / `verify.turn.verify_turn` from a REAL gated capture — a snapshot
taken with `take_snapshot`, persisted WITH `source_root` (exactly as `sandbox.gate` records
it), and a trace recorded through the real `TraceWriter`.

The nine criteria map to the aspect spec's nine acceptance criteria, in order:

  1. `test_verdict_is_invariant_to_live_workspace_state` — THE core: pristine / mutated /
     deleted original workspace -> IDENTICAL verdict. The contamination fix proven.
  2. `test_benign_abs_path_edit_does_not_flag` — no false positive.
  3. `test_corrupt_abs_path_edit_is_flagged` — no false negative (write lands in scratch).
  4. `test_diff_reply_with_abs_path_compares_equal` — reply normalization (diff header path).
  5. `test_out_of_root_abs_path_is_not_remapped` — out-of-root path untouched.
  6. `test_rootless_manifest_with_abs_path_is_unverified` — honest fallback (cross-platform).
  7. `test_content_containing_the_root_is_not_corrupted` — content boundary is content-safe.
  8. `test_cwd_relative_fixtures_unchanged` — additive guarantee (no regression).
  9. `test_relocated_replay_is_deterministic` — same (trace, snapshot) -> same verdict.

Why the darwin gate: real replay re-invokes inside the macOS Seatbelt sandbox, so off-darwin
those tests are an honest skip, exactly like `test_phase0_e2e.py` / `test_launch_demo.py`.
Criterion 6 (the rootless fallback) short-circuits to UNVERIFIED BEFORE any restore/spawn, so
it is pure and stays cross-platform — it is not gated.

The gated-capture helpers (`_snapshot_workspace`, `_trace`) mirror `test_launch_demo.py`; see
that file for why each piece is shaped the way it is. This file does not re-derive it.

## What OLD (unwired) behavior would do — the RED these tests are red against

Before Phase 3, `client.replay_turn` sent the argv root and the frame paths VERBATIM: the
abs-path server pointed at the ORIGINAL workspace. Under Seatbelt, reads are globally
unscoped but writes are confined to the scratch, so an in-root absolute WRITE to the original
workspace is DENIED (the server raises and dies -> target unanswered -> UNVERIFIED), while an
in-root READ leaks to whatever the LIVE workspace holds at replay time. So criterion 1's
verdict would have DEPENDED on live state (pristine vs mutated vs deleted), and a benign edit
would have read as UNVERIFIED rather than clean. Relocation is what makes the verdict a pure
function of (trace, snapshot). These tests fail against that old engine and pass against the
wired one.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from fixtures.abs_path_editor_server import (
    BENIGN_CONTENT,
    CORRUPT_CONTENT,
    EDIT_REPLY,
    EDIT_TOOL,
    ORIGINAL_CONTENT,
    READ_TOOL,
    SEED_REL_PATH,
    _diff_reply,
)
from fixtures.cheat_test_runner_server import REAL_ASSERTION
from fixtures.weakening_editor_server import TARGET_PATH

from belay.replay import engine
from belay.replay.persist import persist_snapshot
from belay.replay.report import canonical_cause
from belay.snapshot.substrate import ClonefileBackend, FIDELITY_GAPS, present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
ABS_SERVER = FIXTURES / "abs_path_editor_server.py"
WEAKENING_SERVER = FIXTURES / "weakening_editor_server.py"

#: The STRONG pre-state test carrying the real security assertion — verbatim from the launch
#: demo. Its overwrite with a gutted body is the cwd-relative regression case (criterion 8).
STRONG_TEST = "def test_rejects_wrong_password():\n" f"    {REAL_ASSERTION}\n"

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

#: The task-scoped invariant that catches a corrupt success: `tests/` is read-only. The
#: seed lives at `tests/test_auth.py` (SEED_REL_PATH), so a write there crosses this scope.
TESTS_READONLY = Invariant(scope=b"tests/", rule="read-only")


# --- frame builders (mirror test_launch_demo.py, adapted to the abs-path server) -------


def _server_cmd(root: str) -> list[str]:
    """`python abs_path_editor_server.py <ROOT>` — ROOT is the argv allow-root token."""
    return [sys.executable, str(ABS_SERVER), root]


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    """Both tools with HONEST annotations: read_abs readOnly:true, edit_abs readOnly:false.

    edit_abs declared readOnly:FALSE is what makes the A2 effect verdict PASS a real write
    (declared-false: no read-only contract to violate) — the same load-bearing shape the
    launch demo relies on.
    """
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {"name": READ_TOOL, "annotations": {"readOnlyHint": True}},
                    {"name": EDIT_TOOL, "annotations": {"readOnlyHint": False}},
                ]
            },
        }
    ).encode()


def _call(tool: str, arguments: dict) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
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


def _abs_capture(tmp_path: Path, name: str, seed_content: str, frames_for, *, with_root: bool = True):
    """A REAL gated capture of one abs-path turn: (records, manifest_dir, work, root).

    Seeds `work/tests/test_auth.py = seed_content`, snapshots it, and persists the manifest
    WITH `source_root` (the resolved workspace root — exactly what `sandbox.gate` records) so
    the engine's relocation gate fires. `frames_for(root)` returns the `(call, reply)` bytes
    for the single `tools/call` turn, addressed by absolute path under `root`.

    With `with_root=False` the manifest omits `source_root` (an old, pre-field capture) so the
    honest-UNVERIFIED fallback can be exercised.
    """
    work = tmp_path / f"{name}-work"
    (work / "tests").mkdir(parents=True)
    (work / SEED_REL_PATH).write_text(seed_content, encoding="utf-8")
    root = os.path.realpath(str(work))

    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    persist_snapshot(
        snap,
        manifest_dir / f"{snap.manifest.handle}.json",
        source_root=root if with_root else None,
    )
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
    """The absolute path of the seed file under `root` — what the server addresses."""
    return os.path.join(root, SEED_REL_PATH)


def _edit_frames(new_content: str, reply_format: str = "plain"):
    """A `frames_for` closure: edit the seed by absolute path with `new_content`.

    For `reply_format="diff"` the recorded reply is the fixture's own deterministic diff over
    (ORIGINAL_CONTENT -> new_content) with the ORIGINAL absolute path in its headers — what the
    server produced at capture. On replay the server produces the SAME diff with the SCRATCH
    path; the two differ only in that prefix, which `canonicalize` folds away.
    """

    def frames_for(root: str):
        abs_path = _abs_path(root)
        call = _call(EDIT_TOOL, {"path": abs_path, "new_content": new_content, "reply_format": reply_format})
        if reply_format == "diff":
            reply = _reply(_diff_reply(abs_path, ORIGINAL_CONTENT, new_content))
        else:
            reply = _reply(EDIT_REPLY)
        return call, reply

    return frames_for


def _shape(verdict) -> tuple:
    """A comparable fingerprint of a TurnVerdict: reduced status + each sub-verdict's identity.

    Deliberately EXCLUDES free-text messages (which legitimately embed the mkdtemp scratch path
    for some sub-verdicts) — the *verdict* must be invariant to the specific scratch path, and
    this fingerprint is what that invariance is asserted over.
    """
    return (
        verdict.status,
        tuple(sorted((s.axis, s.kind, s.status) for s in verdict.sub_verdicts)),
    )


# --- 1. THE CORE: the verdict is invariant to live workspace state --------------------


@darwin_only
def test_verdict_is_invariant_to_live_workspace_state(tmp_path) -> None:
    """Pristine / mutated / DELETED original workspace -> the SAME verdict. Contamination fixed.

    A corrupt abs-path edit (CORRUPT_CONTENT gutting the assertion) is captured once, with the
    `tests/` read-only invariant declared. The SAME (records, manifest) is then verified three
    times while the ORIGINAL workspace is (a) left pristine, (b) mutated to unrelated content,
    (c) deleted outright. Because replay restores the persisted SNAPSHOT into a fresh scratch
    and relocates the absolute paths there, the verdict reads only the restored pre-state — the
    original workspace is never touched — so all three verdicts are IDENTICAL (and FAIL, by A1).

    Against the OLD unwired engine the absolute paths pointed at the live workspace, so the
    read/write outcome — and thus the verdict — moved with (a)/(b)/(c). This is the fix.
    """
    records, manifest_dir, work, root = _abs_capture(
        tmp_path, "invariant", ORIGINAL_CONTENT, _edit_frames(CORRUPT_CONTENT)
    )
    cmd = _server_cmd(root)

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
    assert "tests/test_auth.py" in a1.message, a1.message


# --- 2. No false positive: a benign edit does not flag --------------------------------


@darwin_only
def test_benign_abs_path_edit_does_not_flag(tmp_path) -> None:
    """A correct edit (BENIGN_CONTENT, keeps the assertion) via the abs-path server -> PASS.

    With no invariant declared this isolates the A2 axis: the relocated write lands in the
    scratch (effect PASS, declared-false) and the recorded reply reproduces (result PASS), so
    the turn is a clean PASS with NO FAIL sub-verdict. Against the old engine the write to the
    original workspace was DENIED and the server died, reading as UNVERIFIED — the false alarm
    relocation removes.
    """
    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "benign", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT)
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert verdict.status is Status.PASS, verdict
    assert [s for s in verdict.sub_verdicts if s.status is Status.FAIL] == [], verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


# --- 3. No false negative: a corrupt edit IS flagged ----------------------------------


@darwin_only
def test_corrupt_abs_path_edit_is_flagged(tmp_path) -> None:
    """A genuinely corrupt edit (CORRUPT_CONTENT) under a `tests/` read-only invariant -> FAIL.

    The relocated write lands in the scratch, so the tree diff sees a REAL content change under
    the read-only `tests/` subtree and A1 FAILs — the same shape the launch demo asserts, but
    driven through the absolute-path server. No false negative: the delta is real precisely
    because the write was relocated into the restored copy rather than denied.
    """
    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "corrupt", ORIGINAL_CONTENT, _edit_frames(CORRUPT_CONTENT)
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir,
        invariants=[TESTS_READONLY], timeout=20.0,
    )

    assert verdict.status is Status.FAIL, verdict
    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert a1.status is Status.FAIL, a1.message
    assert "tests/test_auth.py" in a1.message, a1.message
    # The write was OBSERVED in the delta (a real change), so A2 effect saw the mutation too.
    effect = next(s for s in verdict.sub_verdicts if s.kind == "effect")
    assert "tests/test_auth.py" in effect.observed, effect.observed


# --- 4. Reply normalization: a diff reply carrying the abs path compares EQUAL --------


@darwin_only
def test_diff_reply_with_abs_path_compares_equal(tmp_path) -> None:
    """A recorded reply that is a unified DIFF with the abs path in its headers -> result PASS.

    The recorded diff carries the ORIGINAL root in `Index:`/`---`/`+++`; the replayed diff
    carries the SCRATCH root in the same positions. `canonicalize` folds both roots to a
    placeholder for comparison only, so the replies compare EQUAL and result-equivalence is a
    PASS — no false positive from a path buried in a diff line.
    """
    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "diff", ORIGINAL_CONTENT, _edit_frames(BENIGN_CONTENT, reply_format="diff")
    )

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message
    assert verdict.status is Status.PASS, verdict


# --- 5. Out-of-root: an absolute path outside the recorded root is not remapped -------


@darwin_only
def test_out_of_root_abs_path_is_not_remapped(tmp_path) -> None:
    """A turn reading an out-of-root absolute path behaves as today (path left unmapped).

    `read_abs` is called with an absolute path OUTSIDE the recorded root (a sibling of the
    workspace). The fixture's confinement check refuses it deterministically with a message
    naming that exact path. Because the path is out-of-root it is NOT remapped, so the replayed
    refusal names the SAME path as the recorded one and result-equivalence is EQUAL -> PASS.
    Had the out-of-root path been wrongly remapped, the messages would diverge; they don't.
    """
    outside = os.path.join(str(tmp_path), "outside-the-root.txt")  # sibling, not under work

    def frames_for(_root: str):
        call = _call(READ_TOOL, {"path": outside})
        reply = _reply(f"path is not under the allowed root: {outside}", is_error=True)
        return call, reply

    records, manifest_dir, _work, root = _abs_capture(tmp_path, "outofroot", ORIGINAL_CONTENT, frames_for)

    verdict = verify_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert verdict.status is Status.PASS, verdict
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


# --- 6. Honest fallback: a rootless manifest + an in-root abs path -> UNVERIFIED -------


def _rootless_capture(tmp_path: Path, name: str, abs_path: str):
    """A hand-built (cross-platform) capture: manifest with NO source_root + an abs-path turn.

    Mirrors `test_replay_relocation_wiring.py`'s rootless manifest so this stays off-Seatbelt:
    the engine reaches its relocation gate and returns the honest UNVERIFIED BEFORE any restore
    or spawn, so no clonefile / macOS machinery is touched.
    """
    manifest_dir = tmp_path / f"{name}-manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "handle": "h1",
        "tree_path": str(tmp_path / f"{name}-tree"),
        "backend": ClonefileBackend.name,
        "capabilities": sorted(ClonefileBackend.capabilities()),
        "fidelity_gaps": [gap.value for gap in FIDELITY_GAPS],
        "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
    }
    (manifest_dir / "m.json").write_text(json.dumps(payload), encoding="utf-8")

    call = _call(READ_TOOL, {"path": abs_path})
    present = {"status": "present", "handle": "h1"}
    records = _trace(tmp_path, f"{name}-trace", [("c2s", call, present)])
    return records, manifest_dir


def test_rootless_manifest_with_abs_path_is_unverified(tmp_path) -> None:
    """A rootless manifest + an in-root absolute path -> UNVERIFIED with the named cause.

    Cross-platform on purpose: the fallback short-circuits before restore/spawn. Without the
    recorded root replay cannot faithfully relocate the absolute path, so it emits UNVERIFIED
    naming `ROOTLESS_RELOCATION` and never guesses a PASS/FAIL — UNVERIFIED-never-PASS made
    structural for the absolute-path class, asserted here at acceptance level (the wiring test
    pins the engine-level detail).
    """
    records, manifest_dir = _rootless_capture(tmp_path, "rootless", "/some/abs/workspace/tests/x.py")

    verdict = verify_turn(
        records, 0, server_command=[sys.executable, str(ABS_SERVER), "/some/abs/workspace"],
        manifest_dir=manifest_dir, invariants=(), timeout=5.0,
    )

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.cause == canonical_cause(engine.ROOTLESS_RELOCATION), verdict.cause
    sub = verdict.sub_verdicts[0]
    assert engine.ROOTLESS_RELOCATION in sub.message, sub.message


# --- 7. Content safety: content that legitimately contains the root is not corrupted --


@darwin_only
def test_content_containing_the_root_is_not_corrupted(tmp_path) -> None:
    """An edit whose NEW CONTENT contains the workspace path string replays without rewrite.

    The relocation rule remaps only a whole-value path ARGUMENT (`path`), never a `new_content`
    field. So an edit whose body legitimately embeds the workspace root string is written to
    the relocated scratch BYTE-FOR-BYTE, root string intact — the delta reflects the true
    content. If content were substring-remapped, the original root would be gone and the scratch
    root injected; this asserts neither happens.
    """
    holder = {}

    def frames_for(root: str):
        new_content = (
            f"BANNER = '{root}/config'  # the workspace path lives INSIDE file content\n"
            "assert authenticate('user', 'wrong') is False\n"
        )
        holder["new_content"] = new_content
        holder["root"] = root
        call = _call(EDIT_TOOL, {"path": _abs_path(root), "new_content": new_content, "reply_format": "plain"})
        return call, _reply(EDIT_REPLY)

    records, manifest_dir, _work, root = _abs_capture(tmp_path, "content", ORIGINAL_CONTENT, frames_for)

    reply = engine.replay_turn(
        records, 0, server_command=_server_cmd(root), manifest_dir=manifest_dir, timeout=20.0,
    )
    assert reply.status == engine.REPLAYED, reply
    written = (Path(reply.workspace) / SEED_REL_PATH).read_text(encoding="utf-8")

    assert written == holder["new_content"], "the edit body must be written byte-for-byte"
    assert holder["root"] in written, "the original workspace root string must survive in content"
    assert reply.workspace not in written, "the scratch root must NOT be injected into content"


# --- 8. No regression: cwd-relative fixtures replay exactly as before ------------------


def _weakening_capture(tmp_path: Path):
    """The launch demo's cwd-relative cheat capture, rebuilt here: (records, manifest_dir).

    Seeds `tests/test_auth.py = STRONG_TEST`, persists the manifest WITHOUT `source_root` (a
    cwd-relative capture records none), and records an `edit_file` turn whose `arguments` are
    EMPTY — the server writes the WEAKENED body to its cwd-relative `TARGET_PATH`, which under
    replay is the restored scratch. Uses the `edit_file` tools/list so C4 effect grounds on the
    declared-false hint, exactly as the launch demo does.
    """
    work = tmp_path / "cwdrel-work"
    (work / "tests").mkdir(parents=True)
    (work / SEED_REL_PATH).write_text(STRONG_TEST, encoding="utf-8")

    snap = take_snapshot(work, tmp_path / "cwdrel-snap")
    manifest_dir = tmp_path / "cwdrel-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")  # NO source_root
    present = present_handle(snap)

    tools_list_resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()
    call = json.dumps(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "edit_file", "arguments": {}}}
    ).encode()
    reply = _reply(f"edited {TARGET_PATH}")
    records = _trace(
        tmp_path,
        "cwdrel-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", tools_list_resp, None),
            ("c2s", call, present),
            ("s2c", reply, None),
        ],
    )
    return records, manifest_dir


@darwin_only
def test_cwd_relative_fixtures_unchanged(tmp_path) -> None:
    """The existing cwd-relative `weakening_editor_server` replay verdict is UNCHANGED.

    The additive guarantee at acceptance level, driven through the REAL launch-demo fixture: a
    cwd-relative capture (no source_root) of the weakening editor overwriting the STRONG test
    still reduces to FAIL driven SOLELY by A1 (A2 result + effect both PASS the corrupt success),
    byte-for-byte as it did before relocation existed. If the relocation gate had leaked onto
    cwd-relative turns — or the honest-UNVERIFIED fallback had tripped on a rootless capture —
    this would change; it doesn't.
    """
    records, manifest_dir = _weakening_capture(tmp_path)

    verdict = verify_turn(
        records, 0, server_command=[sys.executable, str(WEAKENING_SERVER)],
        manifest_dir=manifest_dir, invariants=[TESTS_READONLY], timeout=20.0,
    )

    assert verdict.status is Status.FAIL, verdict
    # The relocation fallback never fired on this rootless-but-cwd-relative capture.
    for sub in verdict.sub_verdicts:
        assert engine.ROOTLESS_RELOCATION not in (sub.message or ""), sub.message
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    effect = next(s for s in verdict.sub_verdicts if s.kind == "effect")
    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert result.status is Status.PASS, result.message
    assert effect.status is Status.PASS, effect.message
    assert a1.status is Status.FAIL, a1.message
    assert [s for s in verdict.sub_verdicts if s.status is Status.FAIL] == [a1], verdict


# --- 9. Determinism: same (trace, snapshot) -> same verdict; no scratch-path leak ------


@darwin_only
def test_relocated_replay_is_deterministic(tmp_path) -> None:
    """Repeated verification of the SAME (trace, snapshot) yields the SAME verdict.

    Each replay restores into a FRESH mkdtemp scratch, so the specific relocation target differs
    run to run. The verdict must not: relocation is a pure function of (trace, snapshot), with
    the scratch path canonicalized away in every comparison. Two runs of the corrupt case
    produce identical fingerprints AND an identical A1 message (which names the RELATIVE
    `tests/test_auth.py`, never the mkdtemp path), proving the scratch path does not leak in.
    """
    records, manifest_dir, _work, root = _abs_capture(
        tmp_path, "determinism", ORIGINAL_CONTENT, _edit_frames(CORRUPT_CONTENT)
    )
    cmd = _server_cmd(root)

    first = verify_turn(records, 0, server_command=cmd, manifest_dir=manifest_dir, invariants=[TESTS_READONLY], timeout=20.0)
    second = verify_turn(records, 0, server_command=cmd, manifest_dir=manifest_dir, invariants=[TESTS_READONLY], timeout=20.0)

    assert _shape(first) == _shape(second), (_shape(first), _shape(second))
    a1_first = next(s for s in first.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    a1_second = next(s for s in second.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert a1_first.message == a1_second.message, "the verdict message must not carry the mkdtemp path"
