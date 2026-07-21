"""The rename bridge: one instance's gated capture → the layout `belay phase0 run` resolves.

The gated proxy writes a capture whose names carry no instance id — a
`trace-<UTC-stamp>-<8hex>.jsonl` (`src/belay/trace.py:145-149`) beside a
`<snapshots>.manifests/` sibling the gate persists per turn (`src/belay/sandbox/gate.py:330`).
The stock corpus runner, meanwhile, resolves a batch of captures purely by name:
`default_manifest_dir_for(trace) = trace.parent / (trace.stem + ".manifests")`
(`src/belay/phase0/runner.py:74-83`), with **no `--manifest-dir` flag**. The gap between
those two conventions is exactly one rename per instance, and it lives in its own module so
its test is unmissable.

**Why this is the highest-value code in the aspect.** If the bridge mis-wires the manifests,
`run_batch` finds none, every turn resolves to UNVERIFIED, and the whole mint reads as
`INSTRUMENT SUSPECT` — a fake pivot, the worst possible wrong answer for this project. Every
guard here (exactly-one-trace, no-silent-overwrite) is the difference between a real bridge
and a silent fake-PIVOT.

Snapshot *trees* are never moved: manifest tree paths are absolute
(`src/belay/replay/persist.py:109`), so the trees stay where the gate wrote them and only the
trace file and its `.manifests` dir are renamed into the batch dir. Uses `shutil.move`, not
copy — the capture is consumed into the batch, not duplicated.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class BridgeError(RuntimeError):
    """Base for every named failure the rename bridge surfaces rather than papering over."""


class NoTraceError(BridgeError):
    """No `trace-*.jsonl` in the instance's trace dir — the mint produced no capture.

    Raised, never treated as a real short instance: a mint that captured nothing is a
    failure to record and record as `failed`, not a clean zero-turn result.
    """


class MultipleTracesError(BridgeError):
    """More than one `trace-*.jsonl` in the instance's trace dir — a violated mint invariant.

    One gated session writes exactly one trace; two means the trace dir was reused across
    instances. Surfaced as a named error rather than a pick-the-first, which would silently
    bridge the wrong capture.
    """


class BridgeCollisionError(BridgeError):
    """A destination in the batch dir already exists — two instances collided on an id.

    Never a silent overwrite: an id collision is a bug in instance selection to surface, not
    a capture to clobber.
    """


def _source_manifest_dir(snapshot_dir: Path) -> Path:
    """The gate's `.manifests` sibling for `snapshot_dir`, computed exactly as the gate does.

    Replicates `src/belay/sandbox/gate.py:330` —
    `self._snapshot_root.parent / f"{self._snapshot_root.name}.manifests"`, where the gate
    stores `_snapshot_root = Path(snapshot_root).resolve()`. There is no exposed shared
    helper to import (gate computes it inline, `phase0/runner.py` derives its own from the
    *trace* stem), so the coupling is replicated here with this citation kept visible.
    """
    resolved = snapshot_dir.resolve()
    return resolved.parent / f"{resolved.name}.manifests"


def bridge_capture(
    *,
    instance_id: str,
    trace_dir: Path,
    snapshot_dir: Path,
    batch_dir: Path,
) -> Path:
    """Rename one gated capture into the batch layout `belay phase0 run` resolves.

    Finds the single `trace-*.jsonl` under `trace_dir` and moves it to
    `batch_dir/trace-<instance_id>.jsonl`; moves the gate's `<snapshots>.manifests/` sibling
    to `batch_dir/trace-<instance_id>.manifests/`. Snapshot trees under `snapshot_dir` are
    left in place (their manifest paths are absolute). Returns the path of the renamed trace.

    Raises `NoTraceError`/`MultipleTracesError` unless exactly one trace is present, and
    `BridgeCollisionError` if either destination already exists.
    """
    trace_dir = Path(trace_dir)
    snapshot_dir = Path(snapshot_dir)
    batch_dir = Path(batch_dir)

    traces = sorted(trace_dir.glob("trace-*.jsonl"))
    if not traces:
        raise NoTraceError(
            f"no trace-*.jsonl in {trace_dir} for instance {instance_id!r}: the gated "
            f"session produced no capture — record this instance failed, never as a clean "
            f"zero-turn result"
        )
    if len(traces) > 1:
        raise MultipleTracesError(
            f"{len(traces)} trace-*.jsonl in {trace_dir} for instance {instance_id!r} "
            f"({[t.name for t in traces]}): one gated session writes exactly one trace, so "
            f"the trace dir was reused — refusing to pick-the-first and bridge the wrong one"
        )
    source_trace = traces[0]
    source_manifests = _source_manifest_dir(snapshot_dir)

    dest_trace = batch_dir / f"trace-{instance_id}.jsonl"
    dest_manifests = batch_dir / f"trace-{instance_id}.manifests"

    if dest_trace.exists():
        raise BridgeCollisionError(
            f"destination trace {dest_trace} already exists: instance {instance_id!r} "
            f"collides with an already-bridged capture — refusing to overwrite"
        )
    if dest_manifests.exists():
        raise BridgeCollisionError(
            f"destination manifests {dest_manifests} already exists: instance "
            f"{instance_id!r} collides with an already-bridged capture — refusing to "
            f"overwrite"
        )

    batch_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_trace), str(dest_trace))
    shutil.move(str(source_manifests), str(dest_manifests))
    return dest_trace


__all__ = [
    "BridgeError",
    "NoTraceError",
    "MultipleTracesError",
    "BridgeCollisionError",
    "bridge_capture",
]
