"""The missing wire: merge the composite's per-session traces into ONE per instance.

The dual-server composite runs TWO proxied sessions per instance — one per pinned
server (`eval/minting_driver/composite.py`) — and each proxy writes its own trace
into the instance's `trace_dir` (`BELAY_TRACE_DIR` is one dir per instance,
`workspace.py:119`). Everything downstream assumes exactly one trace per instance:

* `claims.record_session_claim` appends the trajectory claim and SILENTLY SKIPS when
  the dir holds more than one (`claims.py:59-62`) — the claim would be lost.
* `bridge_capture` raises `MultipleTracesError` (`bridge.py:53-60`) — the capture
  would read as `failed`, and a mint full of composite captures reads as
  `INSTRUMENT SUSPECT`, a fake PIVOT.
* the phase-0 runner resolves one trace = one instance (`runner.py:148`).

This module closes that seam AFTER the session and BEFORE the claim append/bridge:
`merge_session_traces` consolidates the per-session traces into a single
`trace-<stamp>.jsonl`, renumbering `seq` monotonically in capture order.

**Why renumbering is honest.** Each proxy numbers its own trace from 0, so the two
traces' `seq` values collide; correlation pairs requests with replies by JSON-RPC
`id` (`index.py:98-105`) and replay locates frames by `seq` (`verify/turn.py:117-121`),
so a merged file MUST renumber or both break. Content hashes are untouched:
`hash_raw`/`hash_canonical` cover the frame bytes, and TRACE_FORMAT.md:75 puts
timing outside the hashed content — `seq`/`t_in` are metadata, so renumbering does
not invalidate a single hash.

**Determinism.** A pure function of the input files: records interleave by `t_in`
(proxy-observed capture order, the same clock for both proxies), ties broken by
`(filename, seq)`, then `seq` renumbered 0..N. Same inputs → byte-identical output.

**Single-server path is a byte-identical no-op.** One trace → returned unchanged,
not rewritten. Zero traces → `None` (the bridge names the missing capture
`NoTraceError`; this module never invents a capture).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Union

StrPath = Union[str, "Path"]


def _read_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
    return records


def _interleave(*sources: tuple[Path, list[dict]]) -> list[dict]:
    """All records from all sources in capture order: by `t_in`, ties by
    `(filename, seq)`. Pure and deterministic — no clock, no randomness."""
    tagged = []
    for path, records in sources:
        for record in records:
            tagged.append((record.get("t_in", ""), path.name, record.get("seq", 0), record))
    tagged.sort(key=lambda item: (item[0], item[1], item[2]))
    return [record for _, _, _, record in tagged]


def merge_session_traces(trace_dir: StrPath) -> Optional[Path]:
    """Merge every `trace-*.jsonl` under `trace_dir` into one, in capture order.

    Returns the single surviving trace path:

    * zero traces → `None` (nothing captured; the bridge names it `NoTraceError`)
    * exactly one trace → that path, byte-identical (single-server path untouched)
    * two or more → a merged `trace-<stamp>-merged.jsonl`, `seq` renumbered
      monotonically 0..N in `t_in` order, originals consumed (moved, never copied).

    The merged file's name starts with `trace-` so the claim append
    (`claims.py:59`) and the bridge (`bridge.py:109`) find it with the same glob.
    """
    trace_dir = Path(trace_dir)
    traces = sorted(trace_dir.glob("trace-*.jsonl"))
    if not traces:
        return None
    if len(traces) == 1:
        return traces[0]

    sources = [(path, _read_records(path)) for path in traces]
    merged = _interleave(*sources)
    for index, record in enumerate(merged):
        record["seq"] = index

    # A fresh name so a merged trace is never mistaken for one proxy's own file.
    dest = trace_dir / "trace-merged.jsonl"
    with dest.open("w", encoding="utf-8") as handle:
        for record in merged:
            handle.write(json.dumps(record) + "\n")

    # Consumed, never copied: the session's capture is ONE trace from here on.
    for path in traces:
        path.unlink()
    return dest


__all__ = ["merge_session_traces"]
