"""The baseline bank: verify a capture and store its expected verdicts by run id.

`bank_baseline` is the seam between a captured run and the gate that will later
re-verify it: it resolves the run's identity (the trace's `run_identity` record, or
a `--run-id` override), composes the verdict set the SAME way `belay verify` does —
`read_trace` -> `verify_turn` per turn -> `evaluate_trajectory_rules` ->
`evaluate_claim` (the CLI's own imports at `cli.py:658-683` are the seam) — and
stores a SELF-CONTAINED baseline directory that survives deletion of the original
run.

## One computation, one serializer

The stored `expected` set is built with the SAME builders `belay verify --json`
uses (`belay.verify.json`: `turn_record`, `trajectory_record`, `claim_record`), so
a banked baseline's expected set is exactly what a verify of the same trace
renders, modulo the gate envelope. There is deliberately no second verdict
computation and no second serializer for the bank to drift from.

## Stored policy, never re-resolved

baseline.json stores the RESOLVED A1 invariant list (the parsed operator file /
library entries), the resolved server command(s), `replays`, `timeout`, and the
manifest convention used. A later gate check re-verifies against THIS stored
policy, which is what makes the comparison drift-free.

## Fail-closed, nothing half-written

An absent identity raises `NO_RUN_IDENTITY`; a re-bank without `--force` raises;
a missing snapshot tree fails the copy — and in every case NOTHING is left on
disk, because the identity and collision checks run before the first write and a
failed artifact copy removes its partial directory. A baseline of a FAILing
capture is allowed: the mechanism does not require all-PASS, and the gate
compares whatever the bank stored.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

from belay import __version__
from belay.gate.bank import Baseline, copy_trace_artifacts, save_baseline
from belay.identity import derive_run_identity, validate_run_id
from belay.index import derive_correlation, tool_calls
from belay.replay.reader import TraceCorrupt, read_trace
from belay.verify.claims import CheckAuthor, RecordingAuthor, evaluate_claim
from belay.verify.invariants import Invariant
from belay.verify.json import claim_record, trajectory_record, turn_record
from belay.verify.trajectory import evaluate_trajectory_rules
from belay.verify.turn import verify_turn

#: The manifest convention the baseline bundles under: the relative dirname inside
#: the baseline directory. Stored in the policy so a later gate check knows where
#: the run's manifests live without re-deriving the convention.
_MANIFEST_CONVENTION = "manifests"


def bank_baseline(
    trace_path: Path,
    *,
    root_dir: Path,
    manifest_dir: Path,
    server_command: Sequence[str],
    shell_server_command: Optional[Sequence[str]] = None,
    run_id_override: Optional[str] = None,
    force: bool = False,
    replays: int = 3,
    timeout: float = 10.0,
    invariants: Sequence[Invariant],
    claim_author: Optional[CheckAuthor] = None,
) -> Path:
    """Verify `trace_path` and store its baseline under `root_dir/<run-id>/`.

    Returns the created baseline directory. Raises a named `ValueError` (the CLI
    maps it to exit 2) when the trace records no identity and no `--run-id`
    override is given (`NO_RUN_IDENTITY`), when the override is not a usable run
    id, when a baseline already exists for the run id and `force` is false, when
    the trace is corrupt, or when the manifest copy hits a missing tree — in every
    case before any (or any surviving) write.
    """
    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        raise ValueError(f"the trace could not be read: {exc}") from exc

    records = list(read.records)
    if run_id_override is not None:
        validate_run_id(run_id_override)
        run_id = run_id_override
    else:
        run_id = derive_run_identity(records)
    if run_id is None:
        raise ValueError(
            "the trace records no run identity (BELAY_RUN_ID was unset at capture) and "
            "no --run-id was given: NO_RUN_IDENTITY"
        )

    baseline_dir = Path(root_dir) / run_id
    # Collision is decided BEFORE the first write, so a refused re-bank leaves the
    # stored baseline byte-untouched. `force` removes the old baseline first —
    # the copy below refuses an existing destination, and a replace must never
    # half-overwrite a stored record.
    if baseline_dir.exists():
        if not force:
            raise ValueError(
                f"baseline for run id {run_id!r} already exists at {baseline_dir}; "
                f"re-bank with --force to replace it"
            )
        shutil.rmtree(baseline_dir)

    # The verdict set, composed exactly as `belay verify` composes it: every
    # tools/call turn replayed, then the instance-level trajectory and claim
    # dispositions at trace close.
    calls = tool_calls(derive_correlation(records))
    verdicts = []
    for n in range(len(calls)):
        verdicts.append(
            verify_turn(
                records,
                n,
                server_command=server_command,
                shell_server_command=shell_server_command,
                manifest_dir=manifest_dir,
                replays=replays,
                timeout=timeout,
                invariants=invariants,
            )
        )
    verdict_map = {v.turn_index: v for v in verdicts}
    trajectory = evaluate_trajectory_rules(
        invariants,
        skips=read.skips,
        records=records,
        verdicts=verdict_map,
    )
    claim = None
    claim_check = None
    if claim_author is not None:
        recorder = RecordingAuthor(claim_author)
        claim = evaluate_claim(
            records=records,
            skips=read.skips,
            verdicts=verdict_map,
            author=recorder,
            manifest_dir=manifest_dir,
            server_command=server_command,
            shell_server_command=shell_server_command,
            timeout=timeout,
            replays=replays,
        )
        claim_check = recorder.last_check

    # The expected set, rendered by the SAME builders verify --json uses.
    expected: dict = {
        "turns": [turn_record(verdict) for verdict in verdicts],
        "trajectory": trajectory_record(trajectory),
    }
    claim_rec = claim_record(claim, check=claim_check)
    if claim_rec is not None:
        expected["claim"] = claim_rec

    # The copy first: the artifacts are the part that can fail, and a failure here
    # removes its partial directory, so baseline.json is only ever written beside a
    # complete, self-contained artifact set.
    capabilities = copy_trace_artifacts(trace_path, manifest_dir, baseline_dir)

    provenance: dict = {
        "engine_version": __version__,
        "platform": sys.platform,
        "server_command": list(server_command),
    }
    if shell_server_command is not None:
        provenance["shell_server_command"] = list(shell_server_command)
    if capabilities is not None:
        provenance["capabilities"] = capabilities

    baseline = Baseline(
        run_id=run_id,
        provenance=provenance,
        expected=expected,
        policy={
            "invariants": [
                {"scope": os.fsdecode(inv.scope), "rule": inv.rule} for inv in invariants
            ],
            "replays": replays,
            "timeout": timeout,
            "manifest_dir": _MANIFEST_CONVENTION,
        },
    )
    save_baseline(baseline_dir, baseline)
    return baseline_dir


__all__ = ["bank_baseline"]