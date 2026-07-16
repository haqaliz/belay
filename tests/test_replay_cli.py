"""`belay replay <trace>` — the whole-trace replay and its UNVERIFIED-rate report.

C3's earlier tasks replay ONE turn (`engine`), classify determinism (`determinism`),
and read a trace back (`reader`). This is the surface that runs replay over a whole
trace and reports the one number the Phase-0 gate exists to earn:

    ROADMAP.md:112 — "UNVERIFIED rate measured and EXPLAINED — every UNVERIFIED must
    trace to a named cause."

So the load-bearing assertions here are not about any single turn. They are: (1) the
rate is reported, (2) **every** unverified turn appears under a named cause — a
causeless UNVERIFIED is itself a bug — and (3) the number cannot pass vacuously. A
classifier that called everything unverified would report 100% and look busy; the
positive control (a fully-replayable trace reporting a NON-100% rate, and a
fully-unrestorable one reporting 100%) is what stops that.

**C3 OBSERVES; it does not judge.** The report states replayed / unverified /
not-verifiable + causes + the rate. No PASS/FAIL — that is C4. The UNVERIFIED rate is
an observation about coverage, not a grade.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from belay import cli
from belay.replay.engine import UNVERIFIED
from belay.replay.persist import persist_snapshot
from belay.replay.report import replay_trace
from belay.snapshot.substrate import (
    UnrestorableCause,
    absent_handle,
    present_handle,
    take_snapshot,
)
from belay.trace import TraceWriter

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
CONFORMING_CMD = [sys.executable, str(CONFORMING)]
DIES_MIDWAY = FIXTURES / "dies_midway_server.py"
DIES_MIDWAY_CMD = [sys.executable, str(DIES_MIDWAY)]

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)


# --- rig ---------------------------------------------------------------------


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> tuple[Path, list[dict]]:
    """Build a real trace via `TraceWriter`; return its path AND its records.

    Each frame is `(direction, raw_bytes, state_handle_or_None)`. Going through the
    real writer keeps the records the exact envelope the engine reads in production.
    The path is returned so a test can assert the source is byte-unchanged (A4).
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
    records = [json.loads(line) for line in path.read_bytes().split(b"\n") if line]
    return path, records


def _snapshot(tmp_path: Path, name: str):
    """A one-file workspace, snapshotted. Returns the `GuardedSnapshot` and its handle.

    The caller decides where (or whether) to persist the manifest — which is exactly
    the distinction between a replayable `present` turn and a `manifest-not-found` one.
    """
    work = tmp_path / f"{name}-work"
    work.mkdir()
    (work / "keep.txt").write_text("x")
    snap = take_snapshot(work, tmp_path / f"{name}-snap")
    return snap, present_handle(snap)


def _persist(snap, manifest_dir: Path) -> None:
    """Persist `snap`'s manifest into `manifest_dir` under the gate's `<handle>.json`."""
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")


def _echo_call(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"s": text},
                "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
            },
        }
    ).encode()


def _echo_reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _unrestorable(cause: UnrestorableCause) -> dict:
    return {"status": "unrestorable", "cause": cause.value}


def _initialize(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        }
    ).encode()


def _initialize_reply(version: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": version, "capabilities": {}, "serverInfo": {"name": "x", "version": "1"}},
        }
    ).encode()


_INITIALIZED = b'{"jsonrpc":"2.0","method":"notifications/initialized"}'


# --- 1. The headline: the UNVERIFIED rate, every instance under a named cause -


def test_unverified_rate_traces_every_instance_to_a_named_cause(tmp_path, capsys):
    """A mixed trace reports the rate AND names the cause of every unverified turn.

    Four turns, one of each shape: a `present` turn whose manifest is on disk
    (replays), a `present` turn whose manifest is NOT (manifest not found), an
    `unrestorable` turn (concurrent turn), and an `absent` turn (not-verifiable). The
    report must show the UNVERIFIED rate, and — the load-bearing part — no unverified
    turn may be causeless: the by-cause breakdown must account for every one.
    """
    manifest_dir = tmp_path / "manifests"
    replayable, present_a = _snapshot(tmp_path, "ok")
    _persist(replayable, manifest_dir)
    orphan, present_b = _snapshot(tmp_path, "orphan")  # manifest deliberately NOT persisted

    trace_path, records = _trace(
        tmp_path,
        "mixed",
        [
            ("c2s", _echo_call(1, "replays"), present_a),
            ("s2c", _echo_reply(1, "replays"), None),
            ("c2s", _echo_call(2, "no-manifest"), present_b),
            ("c2s", _echo_call(3, "raced"), _unrestorable(UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN)),
            ("c2s", _echo_call(4, "unsnapshotted"), absent_handle()),
        ],
    )

    report = replay_trace(records, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0)

    assert report.total == 4, report
    assert report.replayed == 1, report
    assert report.unverified == 2, report
    assert report.not_verifiable == 1, report
    assert report.unverified_rate == 0.5, report

    # THE invariant: no unverified turn is causeless, and the by-cause breakdown
    # accounts for every single one.
    unverified_turns = [t for t in report.turns if t.status == UNVERIFIED]
    assert all(t.cause for t in unverified_turns), unverified_turns
    assert sum(report.by_cause.values()) == report.unverified
    assert "manifest not found" in report.by_cause
    assert UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value in report.by_cause

    # And the CLI renders all of it — this is the sample the checkpoint wants to see.
    rc = cli.main(
        ["replay", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *CONFORMING_CMD]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "UNVERIFIED RATE" in out
    assert "2 / 4" in out
    assert "manifest not found" in out
    assert UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN.value in out


# --- 2. The confirmed gap: a present handle with no manifest is honest UNVERIFIED


def test_missing_manifest_is_unverified_not_a_fabricated_result(tmp_path):
    """A `present` turn whose manifest is not in --manifest-dir -> UNVERIFIED, named.

    This is the concrete gap: the trace records the snapshot HANDLE, not where its
    manifest lives, and `belay replay` cannot discover it alone. Pointed at an EMPTY
    manifest dir, the turn must be unverified with a "manifest not found" cause —
    never a fabricated result, never a silent skip, never a crash.
    """
    _snap, present = _snapshot(tmp_path, "orphan")
    empty_manifest_dir = tmp_path / "empty"
    empty_manifest_dir.mkdir()

    _path, records = _trace(tmp_path, "gap", [("c2s", _echo_call(1, "x"), present)])

    report = replay_trace(
        records, server_command=CONFORMING_CMD, manifest_dir=empty_manifest_dir, timeout=15.0
    )

    turn = report.turns[0]
    assert turn.status == UNVERIFIED, turn
    assert turn.cause == "manifest not found", turn
    assert turn.raw_cause is not None and "no persisted snapshot manifest" in turn.raw_cause
    # No fabrication: an unverified turn re-invoked nothing and has no result to show.
    assert turn.reinvoked is False
    assert turn.result_equivalence is None
    assert turn.delta_summary is None
    assert report.unverified_rate == 1.0


# --- 3. A4: replay never mutates the source trace ----------------------------


def test_source_trace_is_byte_unchanged_after_a_full_replay(tmp_path):
    """A4: a full replay run leaves the source trace byte-for-byte what C1 wrote.

    The report goes to stdout; nothing is written back into the append-only trace. A
    mixed trace (one replayed, one unverified) is replayed through the CLI and the
    source file's hash is identical before and after.
    """
    manifest_dir = tmp_path / "manifests"
    replayable, present_a = _snapshot(tmp_path, "ok")
    _persist(replayable, manifest_dir)

    trace_path, _records = _trace(
        tmp_path,
        "a4",
        [
            ("c2s", _echo_call(1, "x"), present_a),
            ("c2s", _echo_call(2, "y"), _unrestorable(UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN)),
        ],
    )

    before = hashlib.sha256(trace_path.read_bytes()).hexdigest()
    rc = cli.main(
        ["replay", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *CONFORMING_CMD]
    )
    after = hashlib.sha256(trace_path.read_bytes()).hexdigest()

    assert rc == 0
    assert after == before, "the source trace was mutated — A4 violated"


# --- 4. Positive control: the rate cannot pass vacuously in either direction --


def test_rate_is_non_vacuous_in_both_directions(tmp_path):
    """A fully-replayable trace reports a NON-100% rate; a fully-unrestorable one 100%.

    Without this, "everything is unverified" would pass every rate assertion vacuously
    — a report that called all turns unverified would look busy and prove nothing. So
    both ends are pinned: turns that CAN replay must lower the rate below 100%, and
    turns that cannot must raise it to 100%.
    """
    # Fully replayable: two present turns, both manifests on disk.
    manifest_dir = tmp_path / "manifests"
    s1, p1 = _snapshot(tmp_path, "r1")
    s2, p2 = _snapshot(tmp_path, "r2")
    _persist(s1, manifest_dir)
    _persist(s2, manifest_dir)
    _path, replayable_records = _trace(
        tmp_path, "allok", [("c2s", _echo_call(1, "a"), p1), ("c2s", _echo_call(2, "b"), p2)]
    )

    good = replay_trace(
        replayable_records, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0
    )
    assert good.total == 2
    assert good.replayed == 2, good
    assert good.unverified == 0
    assert good.unverified_rate == 0.0, good
    assert good.unverified_rate != 1.0

    # Fully unrestorable: two unrestorable turns.
    _path2, unrestorable_records = _trace(
        tmp_path,
        "allbad",
        [
            ("c2s", _echo_call(1, "a"), _unrestorable(UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN)),
            ("c2s", _echo_call(2, "b"), _unrestorable(UnrestorableCause.UNRESTORABLE_WALL_CLOCK)),
        ],
    )

    bad = replay_trace(
        unrestorable_records, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, timeout=15.0
    )
    assert bad.total == 2
    assert bad.unverified == 2, bad
    assert bad.unverified_rate == 1.0, bad
    # Even the fully-unrestorable trace names every turn — none is causeless.
    assert sum(bad.by_cause.values()) == 2
    assert all(t.cause for t in bad.turns)


# --- 4b. --turn narrows the report to a single turn, aggregating over it alone


def test_turn_selector_reports_only_that_turn(tmp_path):
    """`--turn N` replays and aggregates over exactly one turn, keeping its real index.

    A whole-trace total the caller did not ask for would misdescribe a single-turn
    run. With `only=1`, the report holds one turn — the unrestorable one — so the
    rate is 1/1, and the turn keeps its original index (1), not 0.
    """
    manifest_dir = tmp_path / "manifests"
    replayable, present_a = _snapshot(tmp_path, "ok")
    _persist(replayable, manifest_dir)

    _path, records = _trace(
        tmp_path,
        "sel",
        [
            ("c2s", _echo_call(1, "x"), present_a),
            ("c2s", _echo_call(2, "y"), _unrestorable(UnrestorableCause.UNRESTORABLE_CONCURRENT_TURN)),
        ],
    )

    report = replay_trace(
        records, server_command=CONFORMING_CMD, manifest_dir=manifest_dir, only=1, timeout=15.0
    )

    assert report.total == 1
    assert report.turns[0].turn_index == 1
    assert report.turns[0].status == UNVERIFIED
    assert report.unverified_rate == 1.0


# --- 4c. A replay that never answers the target lands in the UNVERIFIED rate --


def test_unanswered_target_turn_is_unverified_under_a_named_cause(tmp_path, capsys):
    """A `present` turn whose re-invoked server dies before the target lands in the
    UNVERIFIED rate under a named cause — not counted as `replayed`.

    `dies_midway_server` answers the `initialize` handshake then exits, so the target
    `tools/call` is never answered on replay. The old engine scored this `replayed`
    with a null reply, understating the honest headline (a turn that answered nothing
    was hidden from the rate). Now it is UNVERIFIED, filed under its own named bucket,
    and visible in the CLI breakdown like every other unverified turn.
    """
    manifest_dir = tmp_path / "manifests"
    replayable, present_a = _snapshot(tmp_path, "ok")
    _persist(replayable, manifest_dir)

    trace_path, records = _trace(
        tmp_path,
        "dies",
        [
            ("c2s", _initialize("2025-11-25"), None),
            ("s2c", _initialize_reply("2025-11-25"), None),
            ("c2s", _INITIALIZED, None),
            ("c2s", _echo_call(2, "hi"), present_a),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    report = replay_trace(
        records, server_command=DIES_MIDWAY_CMD, manifest_dir=manifest_dir, timeout=15.0
    )

    assert report.total == 1, report
    assert report.replayed == 0, "a turn that answered nothing must NOT count as replayed"
    assert report.unverified == 1, report
    assert report.unverified_rate == 1.0, report
    turn = report.turns[0]
    assert turn.status == UNVERIFIED, turn
    assert turn.cause, "the unverified turn must carry a named cause"
    assert sum(report.by_cause.values()) == report.unverified
    label = turn.cause

    rc = cli.main(
        ["replay", str(trace_path), "--manifest-dir", str(manifest_dir), "--server", *DIES_MIDWAY_CMD]
    )
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "UNVERIFIED RATE" in out
    assert "1 / 1" in out
    assert label in out, f"the named cause {label!r} must appear in the CLI breakdown:\n{out}"


# --- 5. --help documents where manifests live -------------------------------


def test_help_documents_where_manifests_live():
    """`belay replay --help` tells a user where to point --manifest-dir.

    The confirmed gap is only closed if the user knows the convention: manifests live
    in the `.manifests` sibling of the snapshot dir. If --help stopped saying so, the
    UNVERIFIED-for-manifest-not-found turns would look like a bug rather than a
    pointing error the user can fix.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "belay.cli", "replay", "--help"],
        capture_output=True,
        timeout=30,
    )
    out = completed.stdout.decode(errors="replace")

    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert "--manifest-dir" in out
    assert ".manifests" in out
