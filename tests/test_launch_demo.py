"""THE LAUNCH DEMO: A2 correctly PASSes the corrupt success; only A1 catches it.

This is the headline of the whole C1-C5 gate — the non-redundancy of the verdict axes,
proven end-to-end through the REAL proxy + gate + snapshot + replay, on ONE turn:

An `edit_file` tool that HONESTLY declares `readOnlyHint: false` overwrites
`tests/test_auth.py` with a gutted test. The task declared `tests/` read-only. On the
replay of that single turn, all of this holds at once:

  - A2 result (kind "replay") == PASS   — the recorded reply reproduced byte-for-byte.
  - A2 effect (kind "effect") == PASS    — declared-false: no read-only contract to violate.
  - A1 invariant (axis "A1")  == FAIL    — replay OBSERVED a write under the read-only
                                           `tests/`; the message names tests/test_auth.py.
  - the reduced turn status   == FAIL, and A1 is the SOLE FAIL.

That single composed assertion is the entire justification for C5. A2 catches trace
infidelity, and this trace is perfectly faithful — the edit really happened, declared —
so A2 PASSes, correctly. Only the task-scoped invariant (A1) calls the success corrupt.
Building A2 and expecting it to catch this is the quiet failure CLAUDE.md warns against.

Two guards keep it from being vacuous:

1. `test_without_the_invariant_the_corrupt_success_is_a_pass` runs the SAME turn with
   `invariants=()`: with A1 absent the corrupt success reduces to PASS and no A1
   sub-verdict exists — the demo failing BEFORE A1 catches it, which is what proves A1 is
   the thing that catches it.
2. `test_the_strong_test_is_in_the_restored_pre_state` restores the persisted snapshot
   independently and asserts the STRONG test (real assertion present) is there — so the
   write in the delta is a real change from a real pre-state, not smuggled in. And
   `test_a_write_outside_the_scope_is_a1_pass` scopes the invariant to a DIFFERENT subtree
   and gets A1 PASS, proving A1's FAIL is scoped rather than a blanket FAIL-on-any-write.

The darwin skipif is honest, not a gap: replay re-invokes inside the macOS Seatbelt
sandbox, so off-darwin the demo is skipped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION
from fixtures.weakening_editor_server import TARGET_PATH, WEAKENED_TEST

from belay.replay.persist import load_snapshot, persist_snapshot
from belay.snapshot.substrate import guarded_restore, present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_SERVER = FIXTURES / "weakening_editor_server.py"
EDITOR_CMD = [sys.executable, str(EDITOR_SERVER)]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

# The test the agent was supposed to leave intact: it asserts the security invariant the
# buggy product code violates. This is the pre-state; the editor overwrites it with the
# WEAKENED body, so the content DIFFERS and the write shows up in the replay delta.
STRONG_TEST = (
    "def test_rejects_wrong_password():\n"
    f"    {REAL_ASSERTION}\n"
)

# The task-scoped invariant that catches the corrupt success: `tests/` is read-only. The
# trailing slash makes it a directory prefix covering tests/test_auth.py.
TESTS_READONLY = Invariant(scope=b"tests/", rule="read-only")


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    """`edit_file` declares readOnlyHint:FALSE — declared-false is what makes C4 effect PASS.

    Un-annotated here would make C4 effect UNVERIFIED and collapse the "A2 PASS, A1 FAIL"
    contrast into a bare UNVERIFIED; declared-FALSE is load-bearing.
    """
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "edit_file", "annotations": {"readOnlyHint": False}}]},
        }
    ).encode()


def _edit_file_call() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "edit_file", "arguments": {}},
        }
    ).encode()


def _recorded_reply() -> bytes:
    """The reply the recorded turn captured; the editor reproduces it byte-equivalently."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {
                "content": [{"type": "text", "text": f"edited {TARGET_PATH}"}],
                "isError": False,
            },
        }
    ).encode()


def _snapshot_workspace(tmp_path: Path, name: str, test_body: str):
    """A workspace with `tests/test_auth.py` = `test_body`, snapshotted and persisted.

    Returns `(present_handle, manifest_dir)`. The snapshot IS the recorded turn's
    pre-state; whatever `test_body` is here is what replay restores and the editor
    overwrites. Verbatim from `test_verify_pass_on_cheat._snapshot_workspace`.
    """
    work = tmp_path / f"{name}-work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(test_body, encoding="utf-8")

    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    manifest_dir = tmp_path / f"{name}-manifests"
    manifest_path = manifest_dir / f"{snap.manifest.handle}.json"
    persist_snapshot(snap, manifest_path)
    return present_handle(snap), manifest_dir


def _trace(tmp_path: Path, name: str, frames: list[tuple]):
    """Record `frames` (dir, raw, state_handle_or_None) via the real writer; read back.

    Verbatim from `test_verify_pass_on_cheat._trace`: going through `TraceWriter` keeps the
    records the exact envelope the engine reads in production, and `set_state_handle` stamps
    the `tools/call` frame with its pre-state handle the way the gate does.
    """
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


def _demo_records(tmp_path: Path, name: str, test_body: str):
    """The demo's trace + manifest_dir: a workspace at `test_body`, edited on the turn."""
    present, manifest_dir = _snapshot_workspace(tmp_path, name, test_body)
    records = _trace(
        tmp_path,
        f"{name}-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), present),
            ("s2c", _recorded_reply(), None),
        ],
    )
    return records, manifest_dir


# --- THE launch demo: A2 PASSes the corrupt success, only A1 catches it ---------------


def test_launch_demo_a2_passes_a1_catches_the_corrupt_success(tmp_path):
    """The headline: A2 result PASS + A2 effect PASS + A1 FAIL -> reduced FAIL, sole by A1.

    The editor honestly declared readOnlyHint:false and overwrote the STRONG test with the
    WEAKENED one. Replay reproduces the recorded reply (result PASS) and the write conforms
    to the declared-false contract (effect PASS) — A2 passes the corrupt success, correctly.
    Only the task-scoped `tests/` read-only invariant (A1) observes the write in the delta
    and FAILs. The turn reduces to FAIL, and A1 is the SOLE FAIL.
    """
    records, manifest_dir = _demo_records(tmp_path, "demo", STRONG_TEST)

    verdict = verify_turn(
        records, 0,
        server_command=EDITOR_CMD, manifest_dir=manifest_dir,
        invariants=[TESTS_READONLY], timeout=20.0,
    )

    assert verdict.status is Status.FAIL, verdict
    assert verdict.tool_name == "edit_file", verdict

    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    effect = next(s for s in verdict.sub_verdicts if s.kind == "effect")
    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")

    # A2 result reproduced: the editor returned the recorded reply byte-for-byte.
    assert result.status is Status.PASS, result.message
    # A2 effect conformed: declared-false, so there is no read-only contract to violate.
    assert effect.status is Status.PASS, effect.message
    # A1 caught it: replay observed a write under the read-only tests/ scope.
    assert a1.status is Status.FAIL, a1.message
    assert "tests/test_auth.py" in a1.message, a1.message

    # A1 is the SOLE FAIL — so a broken A2 cannot be the cause of the turn's FAIL, and every
    # non-A1 sub-verdict is a PASS. This is the whole thesis in one assertion.
    fails = [s for s in verdict.sub_verdicts if s.status is Status.FAIL]
    assert fails == [a1], fails
    non_a1 = [s for s in verdict.sub_verdicts if s.axis != "A1"]
    assert all(s.status is Status.PASS for s in non_a1), non_a1

    # The delta genuinely contained the write: the declared-false effect verdict carries the
    # observed paths, and tests/test_auth.py is among them — the mutation is real, observed,
    # and the same one A1 FAILed on, not smuggled into the message.
    assert "tests/test_auth.py" in effect.observed, effect.observed


def test_without_the_invariant_the_corrupt_success_is_a_pass(tmp_path):
    """MANDATED 'fails first without A1': the SAME turn with invariants=() is a PASS.

    With no invariant declared, A1 never runs — and the corrupt success sails through as a
    PASS, carrying only A2 sub-verdicts. This is the demo failing before A1 catches it, and
    it is what proves A1 is the thing that catches it. Permanent, and pinned: if this ever
    starts FAILing, the divergence above is no longer A1's doing.
    """
    records, manifest_dir = _demo_records(tmp_path, "no-inv", STRONG_TEST)

    verdict = verify_turn(
        records, 0,
        server_command=EDITOR_CMD, manifest_dir=manifest_dir,
        invariants=(), timeout=20.0,
    )

    assert verdict.status is Status.PASS, verdict
    axes = {s.axis for s in verdict.sub_verdicts}
    assert "A1" not in axes, (
        "with no invariant declared, no A1 sub-verdict exists — the corrupt success is "
        "structurally invisible to A2 alone, which is why A1 is a separate axis"
    )


# --- NON-VACUITY: the STRONG test really is the pre-state the write mutated ------------


def test_the_strong_test_is_in_the_restored_pre_state(tmp_path):
    """The STRONG test is VISIBLY in the restored snapshot — the write is a real change.

    `verify_turn` restores this same snapshot internally; here we restore it independently
    from its persisted manifest and read the file back. The real assertion is present, so
    the editor's overwrite to the WEAKENED body is a genuine content change the tree diff
    records — not a no-op the demo would falsely attribute to the tool. If the pre-state
    already held the weakened content, the write would be a no-op and the delta empty; this
    proves it is not.
    """
    _present, manifest_dir = _snapshot_workspace(tmp_path, "prestate", STRONG_TEST)
    manifest_path = next(manifest_dir.glob("*.json"))

    restored = tmp_path / "restored-pre-state"
    guarded_restore(load_snapshot(manifest_path), restored)

    content = (restored / "tests" / "test_auth.py").read_text(encoding="utf-8")
    assert REAL_ASSERTION in content, (
        "the restored pre-state must hold the STRONG test's real security assertion — the "
        "editor's overwrite to the weakened body must be a real change from it"
    )
    assert content != WEAKENED_TEST, (
        "the pre-state must DIFFER from what the editor writes, or the write is a no-op and "
        "the delta is empty — the trap this demo is built to avoid"
    )


# --- SCOPED, not blanket: a write outside the invariant's subtree is A1 PASS -----------


def test_a_write_outside_the_scope_is_a1_pass(tmp_path):
    """The SAME apparatus with the invariant scoped to `src/` -> A1 PASS.

    The tests/ write is outside the src/ scope, so A1 observes no mutation under its scope
    and PASSes. This proves A1's FAIL above is SCOPED to the declared subtree, not a blanket
    FAIL-on-any-write — the invariant catches a write under `tests/` precisely because the
    task said `tests/`, and lets an out-of-scope write through.
    """
    records, manifest_dir = _demo_records(tmp_path, "outside", STRONG_TEST)

    verdict = verify_turn(
        records, 0,
        server_command=EDITOR_CMD, manifest_dir=manifest_dir,
        invariants=[Invariant(scope=b"src/", rule="read-only")], timeout=20.0,
    )

    a1 = next(s for s in verdict.sub_verdicts if s.axis == "A1" and s.kind == "invariant")
    assert a1.status is Status.PASS, a1.message
    # The turn is not driven to FAIL by A1: with A2 clean and A1 PASS, nothing FAILs.
    assert verdict.status is Status.PASS, verdict
