"""A9: A2 PASSes the cheating agent — CORRECTLY — and only A1 (C5) could catch it.

This is the subtlest, most load-bearing claim in the whole project, and CLAUDE.md
names getting it wrong "the single most likely way this project fails quietly":

    A2 catches TRACE INFIDELITY, never CHEATING. A cheating agent's trace is
    perfectly FAITHFUL — it really did weaken the test. Replay restores the recorded
    pre-state (which ALREADY CONTAINS the weakened test), re-invokes, sees the same
    "tests pass", and returns PASS — correctly. Only a declared invariant (A1) catches
    corrupt success.

So this test builds the cheat for real and proves A2 does exactly that. A workspace
whose `tests/test_auth.py` has been GUTTED (its real security assertion replaced by a
trivial one) is snapshotted as the turn's pre-state; the recorded turn ran the test
runner against it and recorded "1 passed". `verify_turn` replays end-to-end — restore
the snapshot, re-spawn the runner in the sandbox with its cwd on the restored copy,
diff — and the runner re-reads the gutted file and reproduces "1 passed". A2 returns
**PASS**, and this test asserts that is RIGHT: A2's question is "does the recorded turn
reproduce?", and it does.

The two things that keep this from being a vacuous "a clean turn passes":

1. `test_the_weakened_test_is_in_the_restored_pre_state` restores the persisted
   snapshot independently and asserts the gutting is VISIBLY there — the real
   assertion gone, the trivial one present. The cheat is in the ground truth A2 was
   handed, not smuggled in by the test.
2. `test_swapping_the_tampering_out_changes_the_verdict` is the negative control: the
   SAME apparatus, with the STRONG test in the pre-state instead, makes the runner
   report "1 failed", which diverges from the recorded "1 passed" and drives the
   verdict off PASS. The PASS is caused by the tampering being in the snapshot — swap
   it out and the verdict moves. A test that passed any pre-state would prove nothing;
   this one is pinned to the cheat specifically.

And `test_no_a1_invariant_axis_exists_to_catch_it` documents the non-redundancy in
code, before C5 exists: the PASS carries only A2 sub-verdicts, no A1 invariant, so the
corruption is structurally invisible to what is built today — which is precisely why
A1 is a separate, not-yet-built axis and not a redundant re-run of A2.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION

from belay.replay.persist import load_snapshot, persist_snapshot
from belay.snapshot.substrate import guarded_restore, present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
CHEAT_SERVER = FIXTURES / "cheat_test_runner_server.py"
CHEAT_CMD = [sys.executable, str(CHEAT_SERVER)]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

# The gutted test the cheating agent left behind: the real assertion is gone, replaced
# by a trivial one that passes no matter how broken the product code is.
WEAKENED_TEST = (
    "def test_rejects_wrong_password():\n"
    "    # gutted by the agent so the suite goes green on broken auth\n"
    "    assert True\n"
)

# The real test the agent was supposed to leave intact: it asserts the security
# invariant the buggy product code violates, so a faithful run reports a failure.
STRONG_TEST = (
    "def test_rejects_wrong_password():\n"
    f"    {REAL_ASSERTION}\n"
)


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
    """`run_tests` declares readOnlyHint:true — the contract effect-conformance grounds on."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "run_tests", "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()


def _run_tests_call() -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "run_tests", "arguments": {}},
        }
    ).encode()


def _recorded_reply(text: str) -> bytes:
    """The reply the recorded turn captured. The runner reproduces it byte-equivalently."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _snapshot_workspace(tmp_path: Path, name: str, test_body: str):
    """A workspace with `tests/test_auth.py` = `test_body`, snapshotted and persisted.

    Returns `(present_handle, manifest_path)`. The snapshot IS the recorded turn's
    pre-state; whatever `test_body` is here is what replay restores and the runner
    re-reads. That is the point — the cheat lives in this file's content.
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

    Mirrors `test_replay_cli._trace`: going through `TraceWriter` keeps the records the
    exact envelope the engine reads in production, and `set_state_handle` stamps the
    `tools/call` frame with its pre-state handle the way the gate does.
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


def _verdict_for(tmp_path: Path, name: str, test_body: str):
    """verify_turn over a trace whose run_tests turn ran against `test_body` as pre-state."""
    present, manifest_dir = _snapshot_workspace(tmp_path, name, test_body)
    records = _trace(
        tmp_path,
        f"{name}-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _run_tests_call(), present),
            ("s2c", _recorded_reply("1 passed"), None),
        ],
    )
    return verify_turn(
        records, 0, server_command=CHEAT_CMD, manifest_dir=manifest_dir, timeout=20.0
    )


# --- 1. THE claim: A2 PASSes the cheat, and that is correct --------------------------


def test_a2_passes_the_cheating_agent_and_this_is_correct(tmp_path):
    """The recorded turn ran the tests against a GUTTED test file and recorded "1
    passed". Replay restores that gutted pre-state, re-runs, reproduces "1 passed" —
    so A2 returns PASS. This is CORRECT: A2 asks "does the recorded turn reproduce?",
    and it faithfully does. The cheat is real, the trace is faithful, and faithful is
    all A2 claims to check.
    """
    verdict = _verdict_for(tmp_path, "cheat", WEAKENED_TEST)

    assert verdict.status is Status.PASS, verdict
    assert verdict.tool_name == "run_tests", verdict

    kinds = {v.kind: v for v in verdict.sub_verdicts}
    # Result reproduced: the runner re-read the gutted test and reported "1 passed".
    assert kinds["replay"].status is Status.PASS, kinds["replay"].message
    # Effect conformed: run_tests declared readOnlyHint:true and wrote nothing.
    assert kinds["effect"].status is Status.PASS, kinds["effect"].message


# --- 2. NON-VACUITY: the cheat is really in the pre-state A2 was handed ---------------


def test_the_weakened_test_is_in_the_restored_pre_state(tmp_path):
    """The gutting is VISIBLY in the restored snapshot — not smuggled in by the test.

    This is what makes A9 mean something. `verify_turn` restores this same snapshot
    internally; here we restore it independently from its persisted manifest and read
    the file back. The real assertion is gone and the trivial one is present: the
    corruption is in the ground truth, so A2's PASS is a PASS *on the cheat*, not on
    some incidental clean state.
    """
    present, manifest_dir = _snapshot_workspace(tmp_path, "encodes", WEAKENED_TEST)
    manifest_path = next(manifest_dir.glob("*.json"))

    restored = tmp_path / "restored-pre-state"
    guarded_restore(load_snapshot(manifest_path), restored)

    content = (restored / "tests" / "test_auth.py").read_text(encoding="utf-8")
    assert REAL_ASSERTION not in content, (
        "the restored pre-state must NOT contain the real security assertion — "
        "the whole point is that the agent gutted it before the turn"
    )
    assert "assert True" in content, (
        "the restored pre-state must contain the trivial replacement — the tampering "
        "the runner will re-read and pass on"
    )


# --- 3. NEGATIVE CONTROL: swap the tampering out and the verdict moves ----------------


def test_swapping_the_tampering_out_changes_the_verdict(tmp_path):
    """The SAME apparatus with the STRONG test in the pre-state does NOT PASS.

    The negative control that pins the PASS to the cheat specifically. With the real
    assertion restored, the runner reads it, reports "1 failed", which diverges from
    the recorded "1 passed" — and since the runner is deterministic, that divergence is
    trace infidelity A2 catches. A test that PASSed here would be passing any clean
    turn and proving nothing; this one proves the PASS above is *caused* by the
    tampering being in the snapshot.
    """
    verdict = _verdict_for(tmp_path, "honest", STRONG_TEST)

    assert verdict.status is not Status.PASS, (
        "with the real test in the pre-state the runner reports '1 failed', which "
        "must NOT reproduce the recorded '1 passed'"
    )
    assert verdict.status is Status.FAIL, verdict
    result = {v.kind: v for v in verdict.sub_verdicts}["replay"]
    assert result.status is Status.FAIL and "1 failed" in result.message, result.message


# --- 4. NON-REDUNDANCY, in code, before C5: only A1 could catch this ------------------


def test_no_a1_invariant_axis_exists_to_catch_it(tmp_path):
    """The PASS carries only A2 sub-verdicts — no A1 invariant — so the corruption is
    structurally invisible to what is built today.

    This is the axes' non-redundancy, proven before C5 exists. A2 (replay) and its
    effect check both PASS because the trace is faithful; there is no A1 (invariant)
    sub-verdict, because A1 is a SEPARATE, not-yet-built axis — the only one that could
    declare "the auth test must keep asserting rejection" and FAIL when replay observes
    it does not. Building A2 and expecting it to catch this cheat is the quiet failure
    CLAUDE.md warns against; this asserts A2 does not pretend to.
    """
    verdict = _verdict_for(tmp_path, "axes", WEAKENED_TEST)

    assert verdict.status is Status.PASS, verdict
    axes = {v.axis for v in verdict.sub_verdicts}
    assert axes == {"A2"}, f"only the replay axis is present today: {axes}"
    assert "A1" not in axes, (
        "no A1 invariant axis exists yet — corrupt success is A1's (C5's) to catch, "
        "and A2 structurally cannot, which is why the axes are not redundant"
    )
