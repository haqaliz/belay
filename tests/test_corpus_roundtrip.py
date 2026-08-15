"""C6 Phase 3 acceptance: a flagged run -> `corpus add` -> `corpus run` reproduces the verdict.

This is roadmap acceptance bullet 1 for `corpus run`, end-to-end through the REAL apparatus:
take a real snapshot, record the weakening-editor turn, recompute its verdict (an A1 FAIL —
the launch-demo corrupt success), bundle it with `add_case`, then re-verify the stored case
with `run_case` and assert it still reaches the same per-sub-verdict set (MATCH). The A1 FAIL
reproduces from the case ALONE.

The two substrate roundtrips are darwin-gated with a named cause
(`replay-reinvokes-seatbelt`): they re-invoke the server inside the macOS Seatbelt sandbox.
The CROSS-SUBSTRATE test here is the reverse gate — it runs on BOTH darwin and linux and
asserts that a case banked on the OTHER substrate reaches the restore machinery, refuses
with `UNRESTORABLE_CAPABILITY_MISMATCH`, and classifies SKIP with that named cause (the new
reality since the Linux replay backends landed; it used to be an up-front platform skip).
A box with no sandbox backend at all still skips up front, pinned by the win32 simulation.

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


# --- cross-substrate: the reverse gate -------------------------------------------------
# Before the Linux snapshot/replay backends existed, off darwin `run_case` could
# not replay at all and SKIPped up front, and this test asserted that old skip.
# Linux replay works now: `run_case`'s platform gate admits darwin AND linux,
# so on either substrate a case banked on the OTHER one reaches the restore
# machinery and refuses there with UNRESTORABLE_CAPABILITY_MISMATCH — the
# cross-substrate consequence, stated in README. That refusal is what this test
# asserts: SKIP, decided by the capability mismatch, never by the platform gate.
# Only a box with NO sandbox backend (neither darwin nor linux) still SKIPs
# before any replay, and the gate in `run_case` covers it.


def test_a_case_banked_on_the_other_substrate_is_a_capability_mismatch_skip(
    tmp_path: Path,
):
    """The reverse gate, rewritten for the new reality (spec criterion 3).

    On darwin, a linux-banked case; on linux, a darwin-banked case: `run_case`
    admits the substrate, the restore refuses by capability mismatch, and the
    case classifies SKIP with the named cause — NOT the old up-front platform
    skip. The foreign capability set is the other backend's REAL set (probed),
    so the vocabulary is production, not a sentinel. The case is built through
    the REAL machinery (`_real_flagged_run` -> `add_case`); only the persisted
    manifest's backend/capabilities are rewritten to the foreign substrate's,
    exactly as a case that really was banked there would carry.
    """
    from belay.snapshot.linux import LinuxSnapshotBackend
    from belay.snapshot.substrate import ClonefileBackend

    if sys.platform == "darwin":
        foreign_name, foreign_caps = (
            LinuxSnapshotBackend.name,
            LinuxSnapshotBackend.capabilities(tmp_path),
        )
    else:
        foreign_name, foreign_caps = (
            ClonefileBackend.name,
            ClonefileBackend.capabilities(),
        )

    from belay.corpus.add import add_case
    from belay.verify.invariants import Invariant
    from belay.verify.turn import TurnVerdict

    records, manifest_dir = _real_flagged_run(tmp_path)

    manifest_path = sorted(manifest_dir.glob("*.json"))[0]
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["backend"] = foreign_name
    manifest_payload["capabilities"] = sorted(foreign_caps)
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    # `add_case` bundles the tampered manifest verbatim; the stored verdict is
    # immaterial here (run_case recomputes), so a placeholder is fine.
    placeholder = TurnVerdict(
        turn_index=0, tool_name="edit_file", status=Status.FAIL, sub_verdicts=[], cause=None
    )
    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=0,
        verdict=placeholder,
        manifest_dir=manifest_dir,
        server_command=[sys.executable, str(EDITOR_SERVER)],
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        replays=3,
        timeout=10.0,
        source_trace_id="flagged-trace",
        captured_at=CAPTURED_AT,
    )

    stored = load_case(case_dir)
    # The case really did bundle the foreign substrate's capabilities (the
    # tampered manifest's), so the stored case reads as if banked there.
    assert stored.capture_capabilities == sorted(foreign_caps)

    result = run_case(case_dir)
    assert result.outcome == SKIP, (result.outcome, result.divergences)
    # The cause is the capability mismatch, named — never "platform ... is not
    # darwin" (that gate no longer fires on either substrate).
    assert "CAPABILITY" in result.skip_reason.upper(), result.skip_reason


def test_run_case_on_a_platform_with_no_backend_skips_up_front(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A box with NO sandbox backend (neither darwin nor linux) still SKIPs
    before any replay — the honest remainder of the old gate, now expressed
    per-platform with the named cause."""
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
    # A platform with no implementation (win32), simulated the way the seam
    # tests do it: run_case's gate reads sys.platform at call time.
    monkeypatch.setattr("sys.platform", "win32")
    result = run_case(case_dir)
    assert result.outcome == SKIP, result
    assert "no sandbox backend" in result.skip_reason
    assert "win32" in result.skip_reason


# --- darwin: the real roundtrip -------------------------------------------------------

pytestmark_darwin = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay-reinvokes-seatbelt: run_case re-invokes the server inside the macOS Seatbelt sandbox",
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
