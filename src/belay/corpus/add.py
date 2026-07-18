"""C6 Phase 2: compose a SELF-CONTAINED, labeled corpus case from a flagged run.

`add_case` is the seam between a caught failure and the corpus that regresses against it.
Given the run's records, the target turn, its recomputed verdict, and where the gate
persisted this run's snapshot manifests, it writes a case DIRECTORY that survives deletion
of the original run:

    <case>/
      case.json      # the recomputed expected verdict, the A1 policy, the HUMAN label
      trace.jsonl    # the FULL records (the handshake too — corpus run re-selects the turn)
      manifest.json  # the snapshot manifest, tree_path rewritten to the relative "prestate"
      prestate/      # a real COPY of the pre-state tree, so the case needs no original run

## The one rule that cannot bend: the engine never labels (D3)

`human_label` is a PASS-THROUGH input, defaulting to `pending`. `add_case` has NO code path
from `verdict` to `human_label`. Labeling a case "true-positive" because the engine FAILed
it would manufacture 100% precision by construction and destroy the corpus's whole purpose:
the corpus measures how well the engine's verdicts match HUMAN ground truth, and a label the
engine wrote is not ground truth. A human relabels `pending` later; the engine only records
what it computed (the `expected` verdict) and what a human told it (the label), never
conflating the two.

## Self-contained by COPY, not reference (moat #2 durability)

The pre-state tree is `shutil.copytree`-d into `<case>/prestate/` and the manifest's
`tree_path` rewritten to the relative string `"prestate"` (which `load_snapshot` resolves
against the manifest's own directory). So the case restores from itself alone — delete the
original run's manifest dir and snapshot tree and the case still reconstructs the pre-state.
That is what makes a case portable between machines and durable past a run's cleanup.

## Deterministic, zero runtime deps

The case id is derived from `source_trace_id` + the turn index — never a uuid or a clock
read, so re-composing the same flagged turn yields the same case. `captured_at` is passed in
(the CLI boundary reads the clock, not this library code). stdlib only: `json`, `shutil`,
`os`, `sys`, `pathlib`. The turn's pre-state handle is located with the engine's OWN
`_manifest_for`, not a reinvented glob. No model is consulted.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

from belay.corpus.case import Case, write_case
from belay.index import derive_correlation, tool_calls
from belay.replay.engine import _manifest_for
from belay.replay.persist import load_snapshot
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict

_PRESTATE_DIRNAME = "prestate"


def _safe_case_id(source_trace_id: str, target_turn_index: int) -> str:
    """A deterministic, filesystem-safe case dir name from the trace id and turn index.

    Derived, never random: the same flagged turn always yields the same case id, so a
    re-compose is idempotent rather than a fresh uuid every time. Any character that is not
    alphanumeric / `-` / `_` / `.` is replaced with `_`, so an awkward trace stem cannot
    escape the corpus dir or name an unwriteable path.
    """
    base = f"{source_trace_id}-turn{target_turn_index}"
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in base)


def _target_state_handle(records: Sequence[dict], target_turn_index: int) -> dict:
    """The `state_handle` off the target `tools/call`'s request frame.

    Selects the turn the way the replay engine does — by the correlation index
    (`method == tools/call`), never by the handle — and reads the handle off THAT frame.
    Raises a named `ValueError` when the index is out of range or the request frame is
    missing, so a case is never composed against a turn that does not exist.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if not (0 <= target_turn_index < len(calls)):
        raise ValueError(
            f"no tools/call at index {target_turn_index}: the trace holds {len(calls)} "
            f"tool call(s)"
        )
    request_seq = calls[target_turn_index].get("request_seq")
    by_seq = {r["seq"]: r for r in records if r.get("kind") == "frame"}
    record = by_seq.get(request_seq) if request_seq is not None else None
    if record is None:
        raise ValueError(
            f"tools/call at index {target_turn_index} has no recorded request frame; "
            f"there is no pre-state handle to bundle"
        )
    return record.get("state_handle") or {}


def add_case(
    corpus_dir: Path,
    *,
    records: list[dict],
    target_turn_index: int,
    verdict: TurnVerdict,
    manifest_dir: Path,
    server_command: list[str],
    invariants: list[Invariant],
    human_label: str = "pending",
    replays: int,
    timeout: float,
    source_trace_id: str,
    captured_at: str,
) -> Path:
    """Compose `corpus_dir/<case-id>/` from a flagged run; return the created case dir.

    `human_label` is a PASS-THROUGH input (default `pending`) — this function NEVER derives
    it from `verdict`. See the module docstring: a label the engine wrote is not human
    ground truth, and inferring "true-positive" from a FAIL would fake the metric.

    Raises a named `ValueError` when the target turn has no restorable pre-state (an
    `absent`/non-`present` handle) or no persisted manifest is found for its handle — a case
    with no pre-state cannot be a replayable corpus case.
    """
    handle = _target_state_handle(records, target_turn_index)
    if handle.get("status") != "present":
        raise ValueError(
            f"turn {target_turn_index} has no restorable pre-state (state_handle status "
            f"{handle.get('status')!r}); a case with no pre-state cannot be a corpus case"
        )
    manifest_path = _manifest_for(handle.get("handle"), manifest_dir)
    if manifest_path is None:
        raise ValueError(
            f"no persisted snapshot manifest for handle {handle.get('handle')!r} in "
            f"{manifest_dir}; the pre-state cannot be bundled into a self-contained case"
        )

    case_id = _safe_case_id(source_trace_id, target_turn_index)
    case_dir = Path(corpus_dir) / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    # 1. trace.jsonl — the FULL records, so the case carries the tools/list handshake a
    #    later `corpus run`'s verify_turn needs, not just the target frame.
    with (case_dir / "trace.jsonl").open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")

    # 2. manifest.json + prestate/ — copy the tree in (a real copy, so the case survives
    #    deletion of the original run), then rewrite tree_path to the relative "prestate".
    snap = load_snapshot(manifest_path)
    shutil.copytree(snap.snapshot.path, case_dir / _PRESTATE_DIRNAME)
    manifest_payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    manifest_payload["tree_path"] = _PRESTATE_DIRNAME
    (case_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )

    # 3. case.json — the recomputed expected verdict, the A1 policy, the HUMAN label.
    expected = {
        "reduced_status": verdict.status.value,
        "sub_verdicts": [
            {"axis": v.axis, "kind": v.kind, "status": v.status.value}
            for v in verdict.sub_verdicts
        ],
    }
    case = Case(
        id=case_id,
        target_turn_index=target_turn_index,
        expected=expected,
        # PASS-THROUGH, verbatim. There is deliberately NO path from `verdict` to this
        # field — see the module docstring (D3). A label the engine wrote is not human
        # ground truth, and a FAIL with no human label is `pending`, never `true-positive`.
        human_label=human_label,
        invariants=[{"scope": os.fsdecode(inv.scope), "rule": inv.rule} for inv in invariants],
        server_command=list(server_command),
        replays=replays,
        timeout=timeout,
        provenance={"source_trace_id": source_trace_id, "captured_at": captured_at},
        capture_platform=sys.platform,
        capture_capabilities=sorted(snap.manifest.capabilities),
    )
    write_case(case_dir, case)
    return case_dir


__all__ = ["add_case"]
