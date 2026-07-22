"""Phase 2: the gate records the resolved scope, and it survives to replay + corpus.

Phase 1 gave the manifest a `source_root` field and a fail-closed round-trip. This phase
wires the gate to write its already-resolved `self._scope` at the persist call site, and
proves three things:

- CAPTURE (darwin-gated): a REAL gated snapshot's manifest carries `source_root` equal to
  the resolved scope. This is the RED->GREEN driver for the one-line gate change.
- VERDICT-NEUTRALITY (darwin-gated real replay): the SAME capture verified with a manifest
  that HAS `source_root` and one that does NOT yields a byte-identical `TurnVerdict`. The
  field is recorded and exposed but never consumed — this is the most important guard in the
  aspect, the whole safety argument for landing the prerequisite on its own.
- CORPUS (cross-platform): `corpus add` copies `manifest.json` verbatim (only rewriting
  `tree_path`), so an ingested case's manifest still carries `source_root` — it rides along
  for free.

The darwin-gated tests re-invoke inside the macOS Seatbelt sandbox / take real APFS clones;
CI runs on macos-latest, so they run there and honestly skip elsewhere. The corpus test is
pure filesystem composition (no Seatbelt), mirroring the synthetic runs in
`test_corpus_add.py`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from belay.corpus.add import add_case
from belay.replay.persist import load_snapshot, persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

darwin_only = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="a real gated capture / replay needs macOS clonefile + Seatbelt",
)

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING = FIXTURES / "conforming_server.py"
CONFORMING_CMD = [sys.executable, str(CONFORMING)]

CAPTURED_AT = "2026-01-01T00:00:00+00:00"


# --- shared rig --------------------------------------------------------------


def _trace(tmp_path: Path, name: str, frames: list[tuple]) -> list[dict]:
    """Build a real trace via `TraceWriter` and read its records back (see test_replay_engine)."""
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


def _echo_call(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"s": text}},
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


# --- CAPTURE: a real gated snapshot records the resolved scope ----------------


@darwin_only
def test_gated_capture_manifest_carries_the_scope(tmp_path: Path) -> None:
    """A REAL gated capture's manifest has `source_root` == the resolved scope.

    RED before the gate passes `source_root=str(self._scope)`: the persisted manifest has no
    such key, so `manifest.source_root` loads `None` and this assertion fails. GREEN after.
    The scope is resolved by the gate (`Path(scope).resolve()`), so the recorded value equals
    the realpath — the consistent prefix a later relocation aspect needs.
    """
    from belay.sandbox.gate import TurnGate

    # A scope reached through a symlink, so "== resolved scope" is a real claim, not a no-op.
    real = tmp_path / "real-work"
    (real / "tests").mkdir(parents=True)
    (real / "tests" / "test_auth.py").write_text("x = 1\n", encoding="utf-8")
    link = tmp_path / "linked-work"
    link.symlink_to(real)

    tools_call = _echo_call(1, "hi")
    gate = TurnGate(scope=link, snapshot_root=tmp_path / "snaps")
    gate.before_frame(tools_call, "c2s")

    assert len(gate.snapshots) == 1, "the tools/call did not snapshot"
    handle = next(iter(gate.snapshots))
    manifest_path = gate.manifest_root / f"{handle}.json"

    loaded = load_snapshot(manifest_path)
    assert loaded.manifest.source_root == str(link.resolve()), loaded.manifest.source_root
    assert Path(loaded.manifest.source_root).is_absolute()


# --- VERDICT-NEUTRALITY: same capture, with vs without the field, same verdict -----


@darwin_only
def test_replay_turn_sees_source_root_but_verdict_is_unchanged(tmp_path: Path) -> None:
    """The recorded-but-unconsumed field never moves the verdict.

    One real capture, verified twice through the REAL `verify_turn` (replay + both A2 checks
    + the A1 invariant): once with a manifest that carries `source_root`, once with the field
    absent. The two `TurnVerdict`s must be byte-identical. If they ever diverge, something
    began consuming the field — the exact overstep this aspect forbids.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("x", encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    handle = present_handle(snap)

    records = _trace(
        tmp_path,
        "neutral",
        [
            ("c2s", _echo_call(2, "hi"), handle),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    # Two manifest dirs naming the SAME snapshot tree: one WITHOUT source_root, one WITH.
    without_dir = tmp_path / "m-without"
    persist_snapshot(snap, without_dir / "m.json")
    with_dir = tmp_path / "m-with"
    persist_snapshot(snap, with_dir / "m.json", source_root=str(work.resolve()))

    # The inputs genuinely differ in the field under test — otherwise the guard is vacuous.
    assert load_snapshot(without_dir / "m.json").manifest.source_root is None
    assert load_snapshot(with_dir / "m.json").manifest.source_root == str(work.resolve())

    invariants = [Invariant(scope=b"keep.txt", rule="read-only")]

    def _verify(manifest_dir: Path) -> TurnVerdict:
        return verify_turn(
            records, 0,
            server_command=CONFORMING_CMD,
            manifest_dir=manifest_dir,
            timeout=15.0,
            invariants=invariants,
        )

    without = _verify(without_dir)
    have = _verify(with_dir)

    assert have == without, (
        "the recorded source_root changed the verdict — it must be exposed, never consumed:\n"
        f"  without={without}\n  with={have}"
    )


# --- CORPUS: the field rides along into an ingested case's manifest -----------


def _fail_verdict() -> TurnVerdict:
    """A minimal FAIL TurnVerdict (one A1 sub-verdict) — enough for `add_case` composition."""
    return TurnVerdict(
        turn_index=0,
        tool_name="edit_file",
        status=Status.FAIL,
        sub_verdicts=[
            Verdict(
                "A1", "invariant", Status.FAIL,
                ["tests/test_auth.py"], {"rule": "read-only", "scope": "tests/", "turn": 0},
                "read-only invariant on 'tests/' FAILED at turn 0",
            ),
        ],
        cause=None,
    )


def test_corpus_case_manifest_preserves_source_root(tmp_path: Path) -> None:
    """`corpus add` copies `manifest.json` verbatim, so `source_root` survives ingestion.

    Cross-platform: `add_case` composes (copytree + JSON rewrite of `tree_path` only), no
    Seatbelt. A synthetic manifest carrying `source_root` is ingested; the case's copied
    manifest must still carry it — it rides along for free, and this pins that it does.
    """
    tree = tmp_path / "snap-tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_auth.py").write_text("x = 1\n", encoding="utf-8")

    source_root = str(tmp_path / "original-work")
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "H1.json").write_text(
        json.dumps(
            {
                "handle": "H1",
                "tree_path": str(tree),
                "backend": "clonefile",
                "capabilities": ["dir-mtimes", "hardlinks"],
                "fidelity_gaps": ["hardlinks", "dir-mtimes"],
                "sidecar": {"link_groups": [], "special_modes": [], "dir_times": []},
                "source_root": source_root,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    records = _trace(
        tmp_path,
        "synth-trace",
        [
            ("c2s", _echo_call(2, "hi"), {"status": "present", "handle": "H1"}),
            ("s2c", _echo_reply(2, "hi"), None),
        ],
    )

    case_dir = add_case(
        tmp_path / "corpus",
        records=records,
        target_turn_index=0,
        verdict=_fail_verdict(),
        manifest_dir=manifest_dir,
        server_command=[sys.executable, "editor.py"],
        invariants=[Invariant(scope=b"tests/", rule="read-only")],
        replays=3,
        timeout=20.0,
        source_trace_id="synth-trace",
        captured_at=CAPTURED_AT,
    )

    copied = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
    assert copied["source_root"] == source_root, copied
    # tree_path was rewritten to the relative prestate; source_root rode along untouched.
    assert copied["tree_path"] == "prestate", copied
    assert load_snapshot(case_dir / "manifest.json").manifest.source_root == source_root
