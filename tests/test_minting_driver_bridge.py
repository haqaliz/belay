"""Offline tests for the rename bridge (`eval/minting_driver/bridge.py`).

The bridge is the fake-PIVOT guard: it turns one instance's gated capture (a
`trace-<ts>-<hex>.jsonl` beside a `<snapshots>.manifests/` sibling) into the exact layout
`belay phase0 run` resolves (`trace-<id>.jsonl` beside `trace-<id>.manifests/`). If it
mis-wires the manifests, every turn reads as UNVERIFIED and the whole mint reads as
`INSTRUMENT SUSPECT` — a fake pivot, the worst possible wrong answer. So the key test
asserts the *real* resolver (`belay.phase0.runner.default_manifest_dir_for`) lands on the
moved manifests dir and that dir actually holds the handle json — never a reimplementation.

Every test builds the FROM layout by hand in `tmp_path`: no proxy, no sandbox, no model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from belay.phase0.runner import default_manifest_dir_for
from eval.minting_driver.bridge import (
    BridgeCollisionError,
    MultipleTracesError,
    NoTraceError,
    bridge_capture,
)


def _build_from_layout(
    inst: Path,
    *,
    trace_name: str = "trace-20260722T120000Z-deadbeef.jsonl",
    handle: str = "abc123",
    tree_turns: int = 1,
) -> tuple[Path, Path, Path]:
    """Materialize the gated-proxy FROM layout under `inst`; return the three roots.

    Returns `(trace_dir, snapshot_dir, manifests_dir)`. `snapshot_dir` holds the turn
    trees; `manifests_dir` is its `.manifests` sibling with one `<handle>.json`.
    """
    trace_dir = inst / "traces"
    snapshot_dir = inst / "snapshots"
    manifests_dir = inst / "snapshots.manifests"
    trace_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    manifests_dir.mkdir(parents=True)

    (trace_dir / trace_name).write_text('{"turn": 0}\n', encoding="utf-8")
    (manifests_dir / f"{handle}.json").write_text(
        '{"handle": "' + handle + '"}\n', encoding="utf-8"
    )
    for turn in range(tree_turns):
        tree = snapshot_dir / f"turn-{turn:04d}"
        tree.mkdir()
        (tree / "file.txt").write_text("snapshot tree content\n", encoding="utf-8")

    return trace_dir, snapshot_dir, manifests_dir


def test_bridge_produces_the_layout_phase0_run_resolves(tmp_path: Path) -> None:
    """THE key test: the stock resolver lands on the moved manifests, which hold the handle.

    Uses `belay.phase0.runner.default_manifest_dir_for` (imported from src, not
    reimplemented) to prove the bridged trace resolves to real manifests — the exact
    property whose absence is a silent fake-PIVOT.
    """
    trace_dir, snapshot_dir, _manifests = _build_from_layout(tmp_path / "inst")
    batch_dir = tmp_path / "batch"

    renamed = bridge_capture(
        instance_id="django__django-12345",
        trace_dir=trace_dir,
        snapshot_dir=snapshot_dir,
        batch_dir=batch_dir,
    )

    assert renamed == batch_dir / "trace-django__django-12345.jsonl"
    assert renamed.is_file()

    resolved_manifests = default_manifest_dir_for(renamed)
    assert resolved_manifests == batch_dir / "trace-django__django-12345.manifests"
    assert resolved_manifests.is_dir()
    # The load-bearing assertion: the handle json the gate wrote is now under the dir the
    # stock CLI resolves. If the bridge mis-wired it, this dir would be empty/absent.
    assert (resolved_manifests / "abc123.json").is_file()


def test_bridge_creates_empty_manifests_dir_when_source_is_absent(tmp_path: Path) -> None:
    """A trace with NO snapshots.manifests sibling bridges to an EMPTY dest manifests dir.

    The gate creates the manifests dir lazily (`gate.py:429`) only when it persists a
    snapshot, so a session that issued tool calls but snapshotted nothing has a trace but no
    `<snapshots>.manifests/`. A present trace is never a bridge failure — only a missing
    trace is. Bridging it to an empty dest dir lets `run_batch` see the instance, find no
    manifests, and classify it `NO_VERIFIABLE_TURNS` honestly, rather than raising and
    letting the instance vanish from the ledger (which would read cleaner than the truth —
    the exact false-zero the INSTRUMENT SUSPECT guard exists to prevent).
    """
    inst = tmp_path / "inst"
    trace_dir = inst / "traces"
    snapshot_dir = inst / "snapshots"
    trace_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (trace_dir / "trace-20260722T120000Z-deadbeef.jsonl").write_text(
        '{"turn": 0}\n', encoding="utf-8"
    )
    # Deliberately do NOT create inst/snapshots.manifests: the honesty case under test.
    batch_dir = tmp_path / "batch"

    renamed = bridge_capture(
        instance_id="inst-1",
        trace_dir=trace_dir,
        snapshot_dir=snapshot_dir,
        batch_dir=batch_dir,
    )

    # The trace is still moved (a present trace is never a bridge failure).
    assert renamed == batch_dir / "trace-inst-1.jsonl"
    assert renamed.is_file()

    # The stock resolver lands on a dest manifests dir that exists and is EMPTY.
    resolved_manifests = default_manifest_dir_for(renamed)
    assert resolved_manifests == batch_dir / "trace-inst-1.manifests"
    assert resolved_manifests.is_dir()
    assert list(resolved_manifests.iterdir()) == []


def test_bridge_raises_when_no_trace_is_present(tmp_path: Path) -> None:
    """An instance that produced no trace is a named error, never a silent skip."""
    trace_dir = tmp_path / "inst" / "traces"
    snapshot_dir = tmp_path / "inst" / "snapshots"
    trace_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir.parent / "snapshots.manifests").mkdir()

    with pytest.raises(NoTraceError):
        bridge_capture(
            instance_id="inst-1",
            trace_dir=trace_dir,
            snapshot_dir=snapshot_dir,
            batch_dir=tmp_path / "batch",
        )


def test_bridge_raises_when_multiple_traces_are_present(tmp_path: Path) -> None:
    """Two traces in one instance dir is a violated mint invariant — surface it, never pick-first."""
    trace_dir, snapshot_dir, _manifests = _build_from_layout(tmp_path / "inst")
    (trace_dir / "trace-20260722T130000Z-cafef00d.jsonl").write_text(
        '{"turn": 0}\n', encoding="utf-8"
    )

    with pytest.raises(MultipleTracesError):
        bridge_capture(
            instance_id="inst-1",
            trace_dir=trace_dir,
            snapshot_dir=snapshot_dir,
            batch_dir=tmp_path / "batch",
        )


def test_bridge_refuses_to_overwrite_an_existing_destination(tmp_path: Path) -> None:
    """An id collision in the batch dir is a bug to surface, never a silent overwrite."""
    trace_dir, snapshot_dir, _manifests = _build_from_layout(tmp_path / "inst")
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    # A destination trace already claimed by an earlier instance with the same id.
    (batch_dir / "trace-inst-1.jsonl").write_text("preexisting\n", encoding="utf-8")

    with pytest.raises(BridgeCollisionError):
        bridge_capture(
            instance_id="inst-1",
            trace_dir=trace_dir,
            snapshot_dir=snapshot_dir,
            batch_dir=batch_dir,
        )


def test_bridge_leaves_snapshot_trees_in_place(tmp_path: Path) -> None:
    """Manifest tree paths are absolute, so trees stay where the gate wrote them."""
    trace_dir, snapshot_dir, _manifests = _build_from_layout(
        tmp_path / "inst", tree_turns=2
    )
    batch_dir = tmp_path / "batch"

    bridge_capture(
        instance_id="inst-1",
        trace_dir=trace_dir,
        snapshot_dir=snapshot_dir,
        batch_dir=batch_dir,
    )

    # The snapshot trees are untouched at their original absolute location.
    assert (snapshot_dir / "turn-0000" / "file.txt").is_file()
    assert (snapshot_dir / "turn-0001" / "file.txt").is_file()
    # And they were NOT copied into the batch dir.
    assert not (batch_dir / "turn-0000").exists()
