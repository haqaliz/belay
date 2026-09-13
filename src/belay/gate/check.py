"""The gate check: compare a new capture against its banked baseline, by re-execution.

`belay gate check <trace>` answers "did the new agent version break a
previously-passing trajectory?" in CI. It resolves the run's identity (the
trace's `run_identity` record, or a `--run-id` override), loads the banked
baseline under the run id, and then:

1. **Re-verifies the baseline's OWN stored trace** against the STORED policy
   (the baseline's invariants, server command(s), replays, timeout — never
   re-resolved, never operator-supplied at check time) and the baseline's own
   bundled manifests. That is the SKIP gate: a baseline whose pre-state cannot
   be restored on THIS box abstains with a named cause (`BASELINE_UNRESTORABLE`,
   or the cross-substrate `BASELINE_CAPABILITY_MISMATCH`) and the whole
   comparison is UNVERIFIED — never a false clean, never a false regression. It
   is also the DRIFT report: recomputed != stored is engine-change evidence,
   named, never a failure.
2. **Verifies the new capture** against the SAME stored policy and the capture's
   own manifest dir.
3. **Compares** the two verdict sets with the pure decision table
   (`belay.gate.compare`): a dimension the baseline held PASS/WARN on that now
   FAILs is a grounded REGRESSION (exit 1); named abstentions, shape changes and
   drift are reported and exit 0; a comparison that could not run at all exits 2.

Text and `--json` are ONE computation: `report_dict` builds the machine document
(the gate.json schema-1 contract) and the text renderer walks the SAME document,
so the two surfaces cannot drift. UNVERIFIED is never rendered as PASS: a
preflight or skipped comparison carries `outcome: UNVERIFIED` with its named
cause on every surface.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from belay.gate.bank import load_baseline
from belay.gate.baseline import compose_verdict_set
from belay.gate.compare import (
    PREFLIGHT,
    REGRESSION,
    GateComparison,
    compare,
)
from belay.identity import derive_run_identity, validate_run_id
from belay.replay.reader import TraceCorrupt, read_trace
from belay.verify.claims import CheckAuthor
from belay.verify.invariants import Invariant
from belay.verify.json import coverage_record

#: The gate report document's schema version. Bumped only when the CONTRACT
#: changes deliberately; the JSON contract test pins it.
GATE_SCHEMA = 1

#: The named preflight causes. Each is rendered as `UNVERIFIED [<cause>]` — never
#: a false clean, never a false regression.
BASELINE_NOT_FOUND = "BASELINE_NOT_FOUND"
NO_RUN_IDENTITY = "NO_RUN_IDENTITY"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


class GatePreflight(ValueError):
    """A comparison that cannot run, named. `cause` is the stable token rendered
    as `UNVERIFIED [<cause>]`; `run_id` is the resolved identity (or `None` when
    no identity could be derived)."""

    def __init__(self, cause: str, detail: str, run_id: Optional[str] = None) -> None:
        super().__init__(f"{detail}: {cause}")
        self.cause = cause
        self.run_id = run_id


@dataclass(frozen=True)
class GateCheckResult:
    """One check's outcome: the comparison, the capture verdicts, the coverage.

    `comparison` is the pure decision table's answer; `capture` is the capture
    side's verdict records (the verify builders' shape); `coverage` the coverage
    block over the capture verdicts — both travel with the report so an
    abstention is never rendered as a clean pass.
    """

    run_id: str
    trace: str
    baseline_dir: Path
    comparison: GateComparison
    capture: dict
    coverage: dict


def check_gate(
    trace_path: Path,
    *,
    root_dir: Path,
    manifest_dir: Path,
    server_override: Sequence[str],
    shell_server_override: Optional[Sequence[str]] = None,
    run_id_override: Optional[str] = None,
    claim_author: Optional[CheckAuthor] = None,
) -> GateCheckResult:
    """Run one gate check: identity -> baseline -> both verdict sets -> comparison.

    Every preflight condition raises `GatePreflight` with its named cause: no
    usable run identity (`NO_RUN_IDENTITY`), an unusable id, a missing baseline
    (`BASELINE_NOT_FOUND`), a baseline whose stored run_id disagrees with the
    resolved identity (`IDENTITY_MISMATCH`), a malformed baseline document, an
    unreadable stored trace, or a stored policy that cannot be applied. The
    comparison itself decides the exit: `clean` / `regression` / `preflight`
    (`BASELINE_UNRESTORABLE` / `BASELINE_CAPABILITY_MISMATCH`).
    """
    try:
        read = read_trace(trace_path)
    except TraceCorrupt as exc:
        raise GatePreflight(
            "TRACE_CORRUPT", f"the trace could not be read: {exc}"
        ) from exc
    records = list(read.records)

    run_id: Optional[str] = run_id_override
    if run_id is None:
        run_id = derive_run_identity(records)
    if run_id is None:
        raise GatePreflight(
            NO_RUN_IDENTITY,
            "the trace records no run identity (BELAY_RUN_ID was unset at capture) "
            "and no --run-id was given",
        )
    # Whatever the id's source, it must be usable as a baseline directory key —
    # fail-closed on an unusable value, never a weird path.
    try:
        validate_run_id(run_id)
    except ValueError as exc:
        raise GatePreflight("INVALID_RUN_ID", str(exc), run_id) from exc

    baseline_dir = Path(root_dir) / run_id
    if not baseline_dir.is_dir():
        raise GatePreflight(
            BASELINE_NOT_FOUND,
            f"no baseline for run id {run_id!r} under {root_dir}",
            run_id,
        )
    try:
        baseline = load_baseline(baseline_dir)
    except ValueError as exc:
        raise GatePreflight(
            "BASELINE_MALFORMED", f"the baseline could not be loaded: {exc}", run_id
        ) from exc
    if baseline.run_id != run_id:
        raise GatePreflight(
            IDENTITY_MISMATCH,
            f"the baseline under {baseline_dir} is keyed to run id {baseline.run_id!r}, "
            f"not the resolved {run_id!r}",
            run_id,
        )

    policy = baseline.policy
    invariants = [
        Invariant(scope=os.fsencode(inv["scope"]), rule=inv["rule"])
        for inv in policy["invariants"]
    ]
    replays: int = policy["replays"]
    timeout: float = policy["timeout"]
    baseline_manifests = baseline_dir / policy["manifest_dir"]

    # The boundary: the STORED command by default, the operator's --server /
    # --shell-server as an override. There is no default-server guessing — a
    # baseline that stores nothing and an operator who overrides nothing is a
    # preflight, never a guessed replay.
    server_command = list(server_override) if server_override else list(
        baseline.provenance.get("server_command", [])
    )
    shell_server_command = shell_server_override
    if shell_server_command is None and "shell_server_command" in baseline.provenance:
        shell_server_command = list(baseline.provenance["shell_server_command"])
    if not server_command:
        raise GatePreflight(
            "NO_SERVER",
            "the baseline stores no server command and no --server override was given",
            run_id,
        )

    # The baseline side, re-verified on the CURRENT engine — the SKIP gate and
    # the drift report in one computation.
    baseline_trace = baseline_dir / "trace.jsonl"
    try:
        baseline_read = read_trace(baseline_trace)
    except TraceCorrupt as exc:
        raise GatePreflight(
            "BASELINE_TRACE_CORRUPT",
            f"the baseline's stored trace could not be read: {exc}",
            run_id,
        ) from exc
    baseline_recomputed, _ = compose_verdict_set(
        baseline_read,
        manifest_dir=baseline_manifests,
        server_command=server_command,
        shell_server_command=shell_server_command,
        replays=replays,
        timeout=timeout,
        invariants=invariants,
        claim_author=claim_author,
    )

    # The capture side, under the SAME stored policy.
    recomputed, capture_verdicts = compose_verdict_set(
        read,
        manifest_dir=manifest_dir,
        server_command=server_command,
        shell_server_command=shell_server_command,
        replays=replays,
        timeout=timeout,
        invariants=invariants,
        claim_author=claim_author,
    )

    comparison = compare(
        str(trace_path),
        baseline.expected,
        recomputed,
        baseline_recomputed=baseline_recomputed,
    )
    return GateCheckResult(
        run_id=run_id,
        trace=str(trace_path),
        baseline_dir=baseline_dir,
        comparison=comparison,
        capture=recomputed,
        coverage=coverage_record(capture_verdicts),
    )


def preflight_report(trace: str, run_id: Optional[str], cause: str) -> dict:
    """The never-computed document: `UNVERIFIED` + the named cause, never PASS.

    Emitted when the comparison could not start (no identity, missing baseline,
    malformed baseline, ...) — the same schema-1 shape as a real report, with the
    row families empty and `skip_reason` naming why.
    """
    return {
        "schema": GATE_SCHEMA,
        "run_id": run_id,
        "trace": trace,
        "outcome": "UNVERIFIED",
        "exit_reason": PREFLIGHT,
        "skip_reason": cause,
        "divergences": [],
        "shape": [],
        "drift": [],
        "capture": {"turns": []},
        "coverage": {},
    }


def _outcome(comparison: GateComparison) -> str:
    if comparison.exit_reason == PREFLIGHT:
        return "UNVERIFIED"
    if comparison.exit_reason == REGRESSION:
        return "REGRESSION"
    return "PASS"


def _divergence_row(row) -> dict:
    return {
        "dimension": row.dimension,
        "expected": row.expected,
        "got": row.got,
        "regression": row.regression,
    }


def _shape_row(row) -> dict:
    return {"kind": row.kind, "dimension": row.dimension, "expected": row.expected, "got": row.got}


def _drift_row(row) -> dict:
    return {"dimension": row.dimension, "expected": row.expected, "got": row.got}


def report_dict(result: GateCheckResult) -> dict:
    """The whole report, ONE computation: the schema-1 machine document.

    Every renderer (JSON and text) walks this document, so a change to the report
    is made once, never twice in parallel. UNVERIFIED never renders as PASS: a
    preflight comparison carries `outcome: UNVERIFIED` and the named
    `skip_reason`, and the capture verdicts travel with the report.
    """
    comparison = result.comparison
    return {
        "schema": GATE_SCHEMA,
        "run_id": result.run_id,
        "trace": result.trace,
        "outcome": _outcome(comparison),
        "exit_reason": comparison.exit_reason,
        "skip_reason": comparison.skip_reason,
        "divergences": [_divergence_row(row) for row in comparison.divergences],
        "shape": [_shape_row(row) for row in comparison.shape],
        "drift": [_drift_row(row) for row in comparison.drift],
        "capture": result.capture,
        "coverage": result.coverage,
    }


def render_json(result: GateCheckResult) -> str:
    """Serialize the report as ONE JSON document. Stdlib `json` only."""
    return json.dumps(report_dict(result))


def render_json_preflight(trace: str, run_id: Optional[str], cause: str) -> str:
    return json.dumps(preflight_report(trace, run_id, cause))


def _coverage_line(coverage: dict) -> str:
    if not coverage:
        return "coverage: no dimensions left uncovered"
    parts = []
    for kind in sorted(coverage):
        entry = coverage[kind]
        parts.append(
            f"{kind} NOT_COVERED on {entry['not_observed_turns']}/{entry['of_turns']} "
            f"turn(s)"
        )
    return "coverage: " + "; ".join(parts)


def report_lines(doc: dict) -> list[str]:
    """The human renderer, walking the SAME document `--json` serializes.

    The width is a MINIMUM, and the space after it is unconditional — the same
    alignment rule the corpus report uses, so a long tool name never abuts the
    status column.
    """
    lines = [
        f"belay gate check {doc['trace']}",
        f"  run id        {doc['run_id']}",
        f"  outcome       {doc['outcome']}",
    ]
    if doc["exit_reason"] == PREFLIGHT:
        lines.append(f"  skip reason   {doc['skip_reason']}")
        lines.append("  nothing was compared — the outcome is UNVERIFIED, never PASS.")
        return lines

    if doc["divergences"]:
        lines.append("")
        lines.append("  divergences")
        for row in doc["divergences"]:
            expected = "—" if row["expected"] is None else row["expected"]
            got = "—" if row["got"] is None else row["got"]
            marker = " (REGRESSION)" if row["regression"] else ""
            lines.append(f"    {row['dimension']:<22}{expected} -> {got}{marker}")
    if doc["shape"]:
        lines.append("")
        lines.append("  shape")
        for row in doc["shape"]:
            expected = "—" if row["expected"] is None else row["expected"]
            got = "—" if row["got"] is None else row["got"]
            lines.append(f"    {row['kind']:<14}{row['dimension']:<22}{expected} -> {got}")
    if doc["drift"]:
        lines.append("")
        lines.append("  drift")
        for row in doc["drift"]:
            expected = "—" if row["expected"] is None else row["expected"]
            got = "—" if row["got"] is None else row["got"]
            lines.append(f"    {row['dimension']:<22}{expected} -> {got}")
    if doc["capture"]["turns"]:
        lines.append("")
        lines.append("  turns")
        for turn in doc["capture"]["turns"]:
            tool = turn["tool"] or "?"
            lines.append(f"    turn {turn['ordinal']:<3} {tool:<18}{turn['status']}")
    lines.append("")
    lines.append(f"  {_coverage_line(doc['coverage'])}")
    return lines


__all__ = [
    "BASELINE_NOT_FOUND",
    "GATE_SCHEMA",
    "IDENTITY_MISMATCH",
    "NO_RUN_IDENTITY",
    "GateCheckResult",
    "GatePreflight",
    "check_gate",
    "preflight_report",
    "render_json",
    "render_json_preflight",
    "report_dict",
    "report_lines",
]