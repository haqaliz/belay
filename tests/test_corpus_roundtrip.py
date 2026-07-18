"""C6 Phase 3 acceptance: a flagged run -> `corpus add` -> `corpus run` reproduces the verdict.

This is roadmap acceptance bullet 1 for `corpus run`, end-to-end through the REAL apparatus:
take a real snapshot, record the weakening-editor turn, recompute its verdict (an A1 FAIL —
the launch-demo corrupt success), bundle it with `add_case`, then re-verify the stored case
with `run_case` and assert it still reaches the same per-sub-verdict set (MATCH). The A1 FAIL
reproduces from the case ALONE.

Darwin-gated: `run_case` re-invokes the server inside the macOS Seatbelt sandbox, so off
darwin there is no replay to run — which is exactly the SKIP the pure tests exercise. The
one non-darwin test here asserts that up-front platform SKIP directly.

Also here: a case whose stored `server_command` points at a nonexistent binary re-verifies
to UNVERIFIED (the server never answers) and is classified SKIP — server-unavailable is an
environment gap, never a regression. This is the honesty property proven against the real
engine, not just a hand-built verdict.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.corpus.case import Case, load_case, write_case
from belay.corpus.run import MATCH, SKIP, run_case
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.verdict import Status

CAPTURED_AT = "2026-07-18T00:00:00+00:00"

FIXTURES = Path(__file__).parent / "fixtures"
EDITOR_SERVER = FIXTURES / "weakening_editor_server.py"

STRONG_BODY = (
    "def test_rejects_wrong_password():\n"
    "    assert authenticate('user', 'wrong') is False\n"
)


# --- frame builders (mirroring the add / launch-demo apparatus) -----------------------


def _tools_list_request() -> bytes:
    return json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()


def _tools_list_response() -> bytes:
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


def _trace(tmp_path: Path, name: str, frames: list[tuple]):
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


# --- off-darwin: the up-front platform SKIP -------------------------------------------


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="on darwin run_case runs the REAL replay; this asserts the off-substrate SKIP",
)
def test_run_case_off_darwin_is_a_platform_skip(tmp_path):
    """Off the macOS substrate, `run_case` cannot replay at all -> a SKIP, decided up front.

    load_case still validates the case (fail-closed), then the platform gate returns SKIP
    before any replay is attempted. A SKIP is never a pass and never a regression, so a
    non-darwin CI box does not fail the build over a case it structurally cannot evaluate.
    """
    case_dir = tmp_path / "corpus" / "some-case"
    case_dir.mkdir(parents=True)
    write_case(
        case_dir,
        Case(
            id="some-case",
            target_turn_index=0,
            expected={"reduced_status": "FAIL", "sub_verdicts": []},
            human_label="pending",
            invariants=[{"scope": "tests/", "rule": "read-only"}],
            server_command=[sys.executable, "editor.py"],
            replays=3,
            timeout=10.0,
            provenance={"source_trace_id": "t", "captured_at": CAPTURED_AT},
            capture_platform="darwin",
            capture_capabilities=["clonefile"],
        ),
    )
    result = run_case(case_dir)
    assert result.outcome == SKIP, result
    assert result.skip_reason is not None and "darwin" in result.skip_reason


# --- darwin: the real roundtrip -------------------------------------------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="run_case re-invokes the server inside the macOS Seatbelt sandbox",
)


def _real_flagged_run(tmp_path: Path):
    """A real snapshot + persisted manifest + the weakening-editor turn's records."""
    from belay.replay.persist import persist_snapshot
    from belay.snapshot.substrate import present_handle, take_snapshot

    work = tmp_path / "work"
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_auth.py").write_text(STRONG_BODY, encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    manifest_dir = tmp_path / "run-manifests"
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    present = present_handle(snap)

    records = _trace(
        tmp_path,
        "flagged-trace",
        [
            ("c2s", _tools_list_request(), None),
            ("s2c", _tools_list_response(), None),
            ("c2s", _edit_file_call(), present),
            ("s2c", _recorded_reply(), None),
        ],
    )
    return records, manifest_dir


@pytestmark_darwin
def test_roundtrip_flagged_run_add_then_run_is_match(tmp_path):
    """A real A1 FAIL: recompute -> add_case -> run_case reproduces the exact verdict (MATCH).

    verify_turn re-invokes the weakening editor (declares readOnlyHint:false, overwrites the
    strong test under the read-only `tests/`): A2 result+effect PASS, A1 invariant FAIL,
    reduced FAIL. `add_case` bundles that. `run_case` reads the case, re-invokes from the
    bundled pre-state alone, recomputes, and the per-sub-verdict set matches -> MATCH.
    """
    from belay.verify.turn import verify_turn

    records, manifest_dir = _real_flagged_run(tmp_path)
    invariants = [Invariant(scope=b"tests/", rule="read-only")]

    verdict = verify_turn(
        records,
        0,
        server_command=[sys.executable, str(EDITOR_SERVER)],
        manifest_dir=manifest_dir,
        invariants=invariants,
        replays=3,
    )
    assert verdict.status is Status.FAIL, verdict  # precondition: the run is a caught A1 FAIL

    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=0,
        verdict=verdict,
        manifest_dir=manifest_dir,
        server_command=[sys.executable, str(EDITOR_SERVER)],
        invariants=invariants,
        replays=3,
        timeout=20.0,
        source_trace_id="flagged-trace",
        captured_at=CAPTURED_AT,
    )

    result = run_case(case_dir)
    assert result.outcome == MATCH, (result.outcome, result.divergences)


@pytestmark_darwin
def test_roundtrip_nonexistent_server_is_a_skip(tmp_path):
    """A case whose stored server_command is a nonexistent binary re-verifies to a SKIP.

    The bundled pre-state restores fine, but the server never answers, so verify_turn is
    UNVERIFIED with a server-unavailable cause. That is an environment gap on THIS box, not a
    detector change — classified SKIP, never a regression. Proven against the real engine.
    """
    from belay.verify.turn import TurnVerdict

    records, manifest_dir = _real_flagged_run(tmp_path)
    nonexistent = [str(tmp_path / "no-such-belay-server")]

    # The stored `expected` verdict is immaterial here — add_case never re-runs, so any
    # verdict is bundled; run_case recomputes against the nonexistent server and SKIPs
    # regardless of what was expected.
    placeholder = TurnVerdict(
        turn_index=0, tool_name="edit_file", status=Status.FAIL, sub_verdicts=[], cause=None
    )
    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=0,
        verdict=placeholder,
        manifest_dir=manifest_dir,
        server_command=nonexistent,
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        replays=3,
        timeout=10.0,
        source_trace_id="flagged-trace",
        captured_at=CAPTURED_AT,
    )
    # sanity: the case really does record the nonexistent server command.
    assert load_case(case_dir).server_command == nonexistent

    result = run_case(case_dir)
    assert result.outcome == SKIP, (result.outcome, result.divergences)
    assert result.skip_reason is not None
