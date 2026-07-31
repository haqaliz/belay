"""C6 Phase 2: compose a SELF-CONTAINED, labeled corpus case from a flagged run.

`add_case` is the seam between a caught failure and the corpus that regresses against it.
Given the run's records, the target turn, its recomputed verdict, and where the gate
persisted this run's snapshot manifests, it writes a case DIRECTORY that survives deletion
of the original run:

    <case>/
      case.json          # the recomputed expected verdict, the A1 policy, the HUMAN label
      trace.jsonl        # the FULL records (the handshake too — corpus run re-selects the turn)
      manifest.json      # the TARGET turn's manifest, tree_path rewritten to "prestate"
      prestate/          # a real COPY of that tree, so the case needs no original run
      task_manifest.json # turn 0's manifest, tree_path rewritten to "task_prestate"
      task_prestate/     # a real COPY of turn 0's tree — the A1 content rule's baseline

## Two pre-states, because the rule and the replay need different baselines

Replay needs the TARGET turn's pre-state: that is the state the call was made from.
`no-assertion-weakening` needs the **TASK** pre-state, turn 0's — an agent editing a scratch
test it wrote earlier in the same run has weakened nothing, and a file absent from turn 0's
tree is exactly how that stops reading as cheating. A case bundling only the first left the
rule with no baseline on every non-zero turn, so it abstained; `corpus run` could then not
express "these cases reach PASS" at all.

Both are resolved by the same mechanism and neither needs a change in `run.py`:
`replay.engine._manifest_for` globs `manifest_dir/*.json` and matches on the recorded
**handle**, not the filename, and `run_case` already passes `manifest_dir=case_dir`.
`case.json` is skipped by that glob because it carries no `handle` key.

At `target_turn_index == 0` the two handles are identical, so the `task_*` pair is NOT
written and the declaration points at the existing `manifest.json` / `prestate/` — see
`_bundle_task_prestate`.

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

## Re-adding is a human act

A case id that already exists is a `CaseExistsError` raised before the first write, and that
is not an error to route around. There is deliberately no `--overwrite`: the engine must not
have a supported path to overwrite a human adjudication, so the remedies are both human ones —
delete the case dir, or point `--corpus-dir` at a fresh corpus. Ingesting into a new, empty
directory is the INTENDED re-verification path and is pinned unharmed by
`test_fresh_corpus_dir_ingest_unchanged`; a collision check widened from the case dir to the
corpus dir would refuse it, which is why that test exists.

## Deterministic, zero runtime deps

The case id is derived from `source_trace_id` + the turn index — never a uuid or a clock
read, so re-composing the same flagged turn yields the same case. `captured_at` is passed in
(the CLI boundary reads the clock, not this library code). stdlib only: `json`, `shutil`,
`os`, `sys`, `pathlib`. The turn's pre-state handle is located with the engine's OWN
`_manifest_for`, not a reinvented glob. No model is consulted.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

from belay.corpus.case import Case, write_case
from belay.index import derive_correlation, tool_calls
from belay.replay.engine import _manifest_for
from belay.replay.persist import load_snapshot
from belay.verify.invariants import (
    NO_TASK_PRESTATE_HANDLE,
    NO_TASK_PRESTATE_MANIFEST,
    NO_TASK_PRESTATE_TREE,
    Invariant,
)
from belay.verify.turn import TurnVerdict

class CaseExistsError(ValueError):
    """The target case id already exists in the corpus dir; nothing was written.

    **Subclasses `ValueError` on purpose, and that is load-bearing.** `phase0/runner.py`'s
    per-turn ingest loop catches `ValueError` and records the turn in `flagged_unaddable`,
    leaving the instance's real disposition and turn counts intact. Any other base class —
    `FileExistsError`, which is what the collision used to surface as — escapes to
    `run_batch`'s catch-all, turns the WHOLE instance into `Disposition.ERRORED`, and drops
    it from `violation_denominator()`. Enough of those and `instrument_suspect()` fires: a
    re-run of a measurement could manufacture a fake `INSTRUMENT SUSPECT`, i.e. a fake
    PIVOT. The base class is therefore part of this error's contract, pinned by a test.

    **Any** existing case dir is a collision, including one already half-damaged by the bug
    this error replaces. Conservative deliberately: this code cannot tell an intact case from
    a wreck, and guessing risks overwriting a human adjudication. There is no `--overwrite`;
    re-adding is a human act — delete the case dir, or use a fresh corpus dir.
    """


_PRESTATE_DIRNAME = "prestate"
_MANIFEST_FILENAME = "manifest.json"
_TASK_PRESTATE_DIRNAME = "task_prestate"
_TASK_MANIFEST_FILENAME = "task_manifest.json"


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


def _target_tool_name(records: Sequence[dict], target_turn_index: int) -> Optional[str]:
    """The `params.name` off the target `tools/call`'s request frame, or `None`.

    Selects the turn the same way `_target_state_handle` does — by correlation index —
    and reads the name off THAT frame. `None` when the frame or the name is missing:
    absent-never-guessed, because the strict independence clause reads this field and a
    fabricated tool name would silently change the count the gate is read against.

    Mirrors `verify.turn._tool_name`; kept local so this module owns its own read of the
    trace, matching the convention that module already records.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if not (0 <= target_turn_index < len(calls)):
        return None
    request_seq = calls[target_turn_index].get("request_seq")
    if request_seq is None:
        return None
    for record in records:
        if record.get("kind") != "frame" or record.get("seq") != request_seq:
            continue
        try:
            message = json.loads(base64.b64decode(record["raw"]))
        except Exception:
            return None
        params = message.get("params")
        if isinstance(params, dict) and isinstance(params.get("name"), str):
            return params["name"]
        return None
    return None


def _bundle_task_prestate(
    case_dir: Path,
    records: Sequence[dict],
    manifest_dir: Path,
    target_handle: dict,
) -> dict:
    """Copy turn 0's tree into `<case>/task_prestate/`; return the `task_prestate` declaration.

    `no-assertion-weakening` is judged against the **task** pre-state, so a case that carries
    only the target turn's baseline leaves the rule nothing to compare and it abstains. This
    bundles the second tree exactly the way the target's is bundled — `copytree` plus a
    `tree_path` rewritten to the relative dirname — so the case still restores from itself
    alone on any machine.

    **When turn 0's handle IS the target's, nothing extra is written** and the declaration
    points at the existing pair. That is the `target_turn_index == 0` case, and skipping it is
    a property rather than an optimisation: two manifests carrying the SAME handle in one
    directory would leave which one `_manifest_for`'s `sorted(glob)` returns as an
    *"it should be harmless"* no fixture exercises. Eliminating the situation beats reasoning
    about it, and beats every future reader having to re-do the reasoning.

    **Fail-closed by RECORDING the absence, never by raising.** A case with a target pre-state
    but no task pre-state is still fully replayable — A2 result and A2 effect are unaffected
    and only A1 abstains. Raising would send the turn to `flagged_unaddable`
    (`phase0/runner.py`) and lose the case from the corpus entirely, trading an honest partial
    verdict for no evidence at all, in the one system whose purpose is compounding evidence.
    The contrast is deliberate: an absent TARGET pre-state still raises in `add_case`, because
    then nothing can be replayed at all.
    """
    try:
        handle = _target_state_handle(records, 0)
    except ValueError:
        return {"status": "absent", "cause": NO_TASK_PRESTATE_HANDLE}
    if handle.get("status") != "present":
        return {"status": "absent", "cause": NO_TASK_PRESTATE_HANDLE}

    if handle.get("handle") == target_handle.get("handle"):
        return {
            "handle": handle["handle"],
            "tree": _PRESTATE_DIRNAME,
            "manifest": _MANIFEST_FILENAME,
        }

    manifest_path = _manifest_for(handle.get("handle"), manifest_dir)
    if manifest_path is None:
        return {"status": "absent", "cause": NO_TASK_PRESTATE_MANIFEST}

    tree_dest = case_dir / _TASK_PRESTATE_DIRNAME
    try:
        snap = load_snapshot(manifest_path)
        shutil.copytree(snap.snapshot.path, tree_dest)
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        # A tree that vanished, an unreadable manifest, a copy that failed part-way: all one
        # finding — there is no reconstructable task pre-state. Remove any partial copy so
        # the case's artifact set stays exactly what the declaration says it is; a half-tree
        # on disk would be read by `_manifest_for`'s sibling as a bundled baseline.
        shutil.rmtree(tree_dest, ignore_errors=True)
        return {"status": "absent", "cause": NO_TASK_PRESTATE_TREE}

    payload["tree_path"] = _TASK_PRESTATE_DIRNAME
    (case_dir / _TASK_MANIFEST_FILENAME).write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return {
        "handle": handle["handle"],
        "tree": _TASK_PRESTATE_DIRNAME,
        "manifest": _TASK_MANIFEST_FILENAME,
    }


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
    with no pre-state cannot be a replayable corpus case. And `CaseExistsError` (a
    `ValueError`) when the case id already exists: an existing case may carry a HUMAN label,
    so it is never overwritten, and the check runs before ANY write so a refused re-add
    leaves the stored case byte-identical.
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
    # Collision is decided BEFORE the first write. `trace.jsonl` opens in `"w"` mode below,
    # which used to truncate an existing case's trace on the way to failing in `copytree`.
    # Ordering against the pre-state checks above is deliberate: they stay first, so a turn
    # that both collides AND has no restorable pre-state keeps reporting the pre-state cause,
    # exactly as before. Not atomic, and it does not need to be — this path is sequential by
    # construction (one `tools/call` in flight, R7), so a TOCTOU race is not in the model.
    if case_dir.exists():
        raise CaseExistsError(
            f"corpus case {case_id!r} already exists at {case_dir}; refusing to overwrite "
            f"(a stored case may carry a human label). Delete it or use a fresh corpus dir."
        )
    # No `exist_ok`: after the check above, an existing dir is a real defect and must surface
    # as an error rather than being silently written into.
    case_dir.mkdir(parents=True)

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
    (case_dir / _MANIFEST_FILENAME).write_text(
        json.dumps(manifest_payload, indent=2), encoding="utf-8"
    )

    # 3. task_manifest.json + task_prestate/ — turn 0's pair, resolved by the SAME by-handle
    #    glob, so `run_case`'s `manifest_dir=case_dir` finds both with no change in run.py.
    task_prestate = _bundle_task_prestate(case_dir, records, manifest_dir, handle)

    # 4. case.json — the recomputed expected verdict, the A1 policy, the HUMAN label.
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
        target_tool=_target_tool_name(records, target_turn_index),
        task_prestate=task_prestate,
    )
    write_case(case_dir, case)
    return case_dir


__all__ = ["add_case", "CaseExistsError"]
