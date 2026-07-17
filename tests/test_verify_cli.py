"""`belay verify <trace>` — the whole-trace verdict, and the honest coverage words.

C4's engine renders one turn's verdict (`verify_turn`); this is the surface that runs
it over a whole trace and prints, per turn, the reduced PASS/FAIL/UNVERIFIED plus BOTH
A2 sub-verdicts (result-equivalence and effect-conformance) with their grounding, and
an aggregate with the FAIL list. A reduced status with no visible sub-verdicts would be
useless — "why did this turn FAIL?" has to be answerable from the output.

The load-bearing assertions here are two. First, the mixed trace really produces one of
each status — a PASS turn (a faithful reproduction), a FAIL turn (a deterministic
divergence), and an UNVERIFIED turn (an unrestorable pre-state) — so the report is not
vacuously all-one-status. Second, M8: the output states IN THE USER'S WORDS what A2's
PASS means ("the trace reproduces", never "the agent was right"), that it does not catch
a cheating agent, and that no model is consulted. Overclaiming there would betray the
whole capability, so it is pinned by a test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from fixtures.cheat_test_runner_server import REAL_ASSERTION
from fixtures.readonly_liar_server import SIDE_EFFECT_PATH

from belay import cli
from belay.replay.reader import read_trace
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import UnrestorableCause, present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

FIXTURES = Path(__file__).parent / "fixtures"
CHEAT_CMD = [sys.executable, str(FIXTURES / "cheat_test_runner_server.py")]
LIAR_CMD = [sys.executable, str(FIXTURES / "readonly_liar_server.py")]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)

WEAKENED_TEST = "def test_rejects_wrong_password():\n    assert True\n"
STRONG_TEST = f"def test_rejects_wrong_password():\n    {REAL_ASSERTION}\n"


def _snapshot(tmp_path: Path, name: str, body: str, manifest_dir: Path):
    work = tmp_path / f"{name}-work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(body, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _tools_list() -> list[tuple]:
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "run_tests", "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _call(msg_id: int) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": "run_tests", "arguments": {}},
        }
    ).encode()


def _reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
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


def test_verify_reports_pass_fail_unverified_with_both_subverdicts(tmp_path, capsys):
    """A mixed trace: PASS (faithful), FAIL (deterministic divergence), UNVERIFIED.

    Turn 0 ran the tests against a gutted pre-state and recorded "1 passed"; replay
    reproduces it -> PASS. Turn 1 ran against the STRONG test but the trace claims "1
    passed"; replay reads the real test, reports "1 failed", diverges deterministically
    -> FAIL. Turn 2's pre-state is unrestorable -> UNVERIFIED. The output must name each
    turn's status, show BOTH sub-verdicts, and aggregate with the FAIL list.
    """
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    pass_handle = _snapshot(tmp_path, "weak", WEAKENED_TEST, manifest_dir)
    fail_handle = _snapshot(tmp_path, "strong", STRONG_TEST, manifest_dir)
    unrestorable = {"status": "unrestorable", "cause": UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value}

    trace_path = _trace(
        tmp_path,
        _tools_list()
        + [
            ("c2s", _call(3), pass_handle),
            ("s2c", _reply(3, "1 passed"), None),
            ("c2s", _call(5), fail_handle),
            ("s2c", _reply(5, "1 passed"), None),
            ("c2s", _call(7), unrestorable),
        ],
    )

    rc = cli.main(["verify", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *CHEAT_CMD])
    out = capsys.readouterr().out

    assert rc == 1, out  # a trace with a FAIL exits non-zero
    # Per-turn: turn 0 is PINNED to PASS by name — the specific reproduction. A regression
    # flipping it (e.g. an effect-check break rendering it UNVERIFIED) breaks THIS line, not
    # a vacuous "PASS" substring that the always-printed labels and banner satisfy anyway.
    assert "turn 0   run_tests         PASS" in out, out
    # Both A2 sub-verdicts are visible so the reduction is explainable.
    assert "result" in out and "effect" in out, out
    # The FAIL's grounding is shown — the observed value the replay produced.
    assert "1 failed" in out, out
    # The UNVERIFIED turn carries its named cause, never spun as PASS.
    assert UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value in out, out
    # Aggregate COUNTS — the one-of-each the docstring claims, asserted on the exact lines
    # `_emit_aggregate` prints. Without these the test passes for the wrong reason: the four
    # labels and the coverage banner print "PASS"/"UNVERIFIED" on every run regardless of any
    # turn's status, so a `"PASS" in out` assertion never fails. The counts have teeth.
    assert "PASS                  1" in out, out
    assert "WARN                  0" in out, out
    assert "FAIL                  1" in out, out
    assert "UNVERIFIED            1" in out, out


def test_verify_drives_a_real_mutation_into_an_effect_fail(tmp_path):
    """A readOnlyHint:true server that ACTUALLY writes -> a real delta -> effect FAIL.

    The real-mutation mirror of the PASS-on-cheat test. That test proves empty-delta ->
    effect PASS end-to-end against a real sandboxed server; this proves the inverse against
    a real server too, so effect-conformance is not leaning on a synthetic delta or a
    monkeypatched replay for its FAIL. The trace declares run_tests readOnlyHint:true; the
    live server declares the same and breaks it by writing a file on the call. The replay
    must produce a NON-EMPTY BTH-1 delta and the effect sub-verdict must FAIL, naming the
    written path — never PASS on a mutation the tool declared it would not make. (If a C3
    regression silently dropped the delta, this is the C4 test that catches it.)
    """
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot(tmp_path, "work", WEAKENED_TEST, manifest_dir)
    trace_path = _trace(
        tmp_path,
        _tools_list() + [("c2s", _call(3), handle), ("s2c", _reply(3, "1 passed"), None)],
    )
    verdict = verify_turn(
        list(read_trace(trace_path).records), 0,
        server_command=LIAR_CMD, manifest_dir=manifest_dir,
    )

    assert verdict.status is Status.FAIL, verdict
    effect = next(s for s in verdict.sub_verdicts if s.kind == "effect")
    assert effect.status is Status.FAIL, effect.message
    # The delta was real and non-empty: the FAIL names the exact path the server wrote.
    assert SIDE_EFFECT_PATH in effect.message, effect.message
    assert "readOnlyHint" in effect.message
    # Result-equivalence is independently clean (the reply reproduced), so the FAIL is the
    # filesystem effect alone — a mutation the declared contract forbade. (The result axis's
    # kind is "replay".)
    result = next(s for s in verdict.sub_verdicts if s.kind == "replay")
    assert result.status is Status.PASS, result.message


def test_verify_states_its_honest_coverage(tmp_path, capsys):
    """M8: the output says what A2 PASS means, what it does NOT catch, and no-LLM.

    A single faithful PASS turn, so the run is clean — and the coverage words are
    present regardless of the verdicts. Overclaiming here (rendering the PASS as "the
    agent did right", or hiding that a cheat PASSes, or implying a model was consulted)
    is the one thing that would betray the capability.
    """
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    pass_handle = _snapshot(tmp_path, "weak", WEAKENED_TEST, manifest_dir)
    trace_path = _trace(
        tmp_path,
        _tools_list() + [("c2s", _call(3), pass_handle), ("s2c", _reply(3, "1 passed"), None)],
    )

    rc = cli.main(["verify", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *CHEAT_CMD])
    out = capsys.readouterr().out.lower()

    assert rc == 0, out
    assert "reproduc" in out, "must say a PASS means the trace reproduces"
    assert "did the right thing" in out or "was correct" in out or "was right" in out, out
    assert "cheat" in out, "must say a cheating agent is NOT caught here"
    assert "no model" in out or "no llm" in out, "must say the verdict consults no model"
    # The network dimension is honestly UNVERIFIED — the coverage must not let a reader
    # believe openWorldHint / egress was checked.
    assert "openworldhint" in out and "egress" in out, "must name the unverified network dimension"


def test_help_states_the_coverage_and_zero_llm():
    """`belay verify --help` carries the same honest coverage the run does.

    A user reading --help before pointing this at a trace must learn the same limits:
    a PASS is a reproduction, not a correctness certificate; cheating is out of scope
    (A1/C5's job); and no model is consulted.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "verify", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace").lower()

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert "--manifest-dir" in out
    assert "reproduc" in out
    assert "cheat" in out
    assert "no model" in out or "no llm" in out
    assert "openworldhint" in out and "egress" in out
