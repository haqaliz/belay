"""The machine surface of `belay verify`: ONE JSON document, from the SAME objects as the text.

The console seam (live-console L6 / C7, aspect `verify-json`): the console cannot parse
human text, and must never compute verdicts itself. So `belay verify --json` emits a
single JSON document carrying exactly what the human report says — per-turn records
(ordinal, tool, reduced status, every sub-verdict with axis/kind/status/message,
NOT_COVERED included and UNVERIFIED with its named cause), the aggregate, the
ALWAYS-present coverage block, the exposure facts, and the trajectory disposition —
rendered from the SAME structured objects the text renderers in `cli.py` consume.

**One computation, two renderers.** Nothing here recomputes a verdict: every builder
derives its record from a `TurnVerdict` (or the trajectory summary `cli.py` already
evaluated), exactly the objects the text report was rendered from. A divergence between
the two surfaces is caught by `tests/test_verify_json.py` driving both.

**The shape is a pinned machine contract.** `tests/fixtures/verify_json_snapshot.json`
locks the keys; a deliberate change is a contract change and re-pins the snapshot. Stdlib
`json` only — the zero-dependency contract holds trivially.

**Always-valid output.** A failed run emits the SAME document shape with `error`
set and `turns` empty — never a truncated `turns` document — and exits non-zero,
exactly as the text run does.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional, Sequence

from belay.verify.verdict import Status

#: The document's schema version. Bumped only when the CONTRACT changes deliberately —
#: the snapshot fixture (`tests/fixtures/verify_json_snapshot.json`) pins it.
SCHEMA = 1

#: The scored status names, in the aggregate's fixed order (mirrors
#: `cli._SCORED_STATUS_NAMES`; NOT_COVERED is sub-verdict-only and can never reduce a
#: turn, so it has no aggregate line — the coverage block speaks for it).
_SCORED = ("PASS", "WARN", "FAIL", "UNVERIFIED")


@dataclass(frozen=True)
class VerifyReport:
    """One run's machine report: the structured truth both renderers could print.

    `turns`/`aggregate`/`coverage`/`exposure`/`trajectory`/`claim` are plain dicts
    derived from the same verdict objects the text renderers consumed (`turn_record`
    and friends); `error` is `None` on a clean run and `{"cause": ...}` on a failed
    one, in which case `turns` stays empty — the never-truncated contract.

    `claim` follows `trajectory`'s absent-never-zero rule, one step stricter: an
    absent key is OMITTED from the document (never `null`), because a trace without a
    claim verdict — no author configured, the axis disabled, or D3 silence — is the
    common case, and writing `"claim": null` would rewrite the pinned `--json`
    snapshot for every such trace.
    """

    trace: Optional[str]
    turns: list[dict]
    aggregate: dict
    coverage: dict
    exposure: dict
    trajectory: Optional[dict]
    claim: Optional[dict]
    error: Optional[dict]

    def as_dict(self) -> dict:
        """The document, in the contract's key order."""
        payload = {
            "schema": SCHEMA,
            "trace": self.trace,
            "turns": self.turns,
            "aggregate": self.aggregate,
            "coverage": self.coverage,
            "exposure": self.exposure,
            "trajectory": self.trajectory,
        }
        if self.claim is not None:
            payload["claim"] = self.claim
        payload["error"] = self.error
        return payload


def render_json(report: VerifyReport) -> str:
    """Serialize the report as ONE JSON document. Stdlib `json` only."""
    return json.dumps(report.as_dict())


def error_report(trace: Optional[str], cause: str) -> VerifyReport:
    """The failure document: `error` set, `turns` empty, every other block present.

    Emitted on any internal failure with the same non-zero exit the text run exits
    with — the console always gets a parseable document, never a truncated `turns`.
    """
    return VerifyReport(
        trace=trace,
        turns=[],
        aggregate={"turns_verified": 0, **{name: 0 for name in _SCORED}},
        coverage={},
        exposure={"recorded": False, "judged_turns": 0, "comparisons": 0},
        trajectory=None,
        claim=None,
        error={"cause": cause},
    )


def turn_record(verdict) -> dict:
    """One `TurnVerdict` -> its machine record: ordinal, tool, reduced status, cause,
    and every sub-verdict (NOT_COVERED included, never dropped, never a PASS)."""
    return {
        "ordinal": verdict.turn_index,
        "tool": verdict.tool_name,
        "status": verdict.status.value,
        "cause": verdict.cause,
        "sub_verdicts": [_subverdict_record(sub) for sub in verdict.sub_verdicts],
    }


def _subverdict_record(sub) -> dict:
    """One `Verdict` -> its machine record.

    Every sub-verdict carries axis/kind/status/message. An A1 invariant additionally
    carries its declared `rule` and `scope` plus the exposure fact the content rule
    actually recorded (`files_compared`, from `expected.exposure.compared` — `None`
    when the sub-verdict carries no exposure fact, never an invented zero).
    """
    record = {
        "axis": sub.axis,
        "kind": sub.kind,
        "status": sub.status.value,
        "message": sub.message,
    }
    if sub.axis == "A1" and sub.kind == "invariant":
        expected = sub.expected if isinstance(sub.expected, dict) else {}
        exposure = expected.get("exposure")
        record["rule"] = expected.get("rule")
        record["scope"] = expected.get("scope")
        record["files_compared"] = (
            exposure.get("compared") if isinstance(exposure, dict) else None
        )
    return record


def aggregate_record(verdicts: Sequence) -> dict:
    """The run's tally, from the same verdicts the text aggregate printed.

    `turns_verified` counts the turns just verified; the four scored statuses count in
    severity order. A turn's reduced status can never be NOT_COVERED (`verdict.reduce`
    filters it before ranking), so the scored four are exhaustive; the coverage block
    carries what the reduction dropped.
    """
    counts = {name: 0 for name in _SCORED}
    for verdict in verdicts:
        name = verdict.status.name
        if name in counts:
            counts[name] += 1
    return {"turns_verified": len(verdicts), **counts}


def coverage_record(verdicts: Sequence) -> dict:
    """The coverage block, keyed by sub-verdict kind — ALWAYS present, empty when no
    NOT_COVERED dimension appeared on these turns.

    Counting mirrors the text block exactly: per TURN per kind (a kind counts once for a
    turn however many sub-verdicts of that kind it carries), and the message is the
    first one observed for the kind.
    """
    counts: dict[str, int] = {}
    messages: dict[str, str] = {}
    for verdict in verdicts:
        uncovered = [s for s in verdict.sub_verdicts if s.status is Status.NOT_COVERED]
        for sub in uncovered:
            messages.setdefault(sub.kind, sub.message)
        for kind in sorted({sub.kind for sub in uncovered}):
            counts[kind] = counts.get(kind, 0) + 1
    total = len(verdicts)
    return {
        kind: {
            "not_observed_turns": counts[kind],
            "of_turns": total,
            "message": messages[kind],
        }
        for kind in sorted(counts)
    }


def exposure_record(summary) -> dict:
    """The A1 content-rule exposure facts, from `cli._exposure_summary`'s accumulator.

    `recorded: false` means no turn ever recorded an exposure fact (the rule never ran
    or judged nothing) — the same absent-never-zero discipline as the text block.
    """
    if summary is None:
        return {"recorded": False, "judged_turns": 0, "comparisons": 0}
    return {
        "recorded": True,
        "judged_turns": summary["turns_judging"],
        "comparisons": summary["files_compared"],
    }


def trajectory_record(trajectory) -> Optional[dict]:
    """The instance-level trajectory disposition, from the SAME serialized summary
    `cli.py` renders text from; `None` mirrors the text report's suppressed line (the
    `--turn N` partial-facts seam, and a run with no instance-level rule declared)."""
    if trajectory is None:
        return None
    status = trajectory.get("status")
    cause = trajectory.get("cause")
    evidence_count = trajectory.get("evidence_count", 0)
    if status == "FAIL":
        message = (
            f"FAIL — the claim asserts verification success with {evidence_count} "
            "evidence turn(s)"
        )
    elif status == "PASS":
        message = (
            f"PASS — the claim is supported by {evidence_count} replayed command "
            "turn(s)"
        )
    else:
        named = cause if cause is not None else "unrecorded"
        message = f"UNVERIFIED [{named}] — never PASS"
    return {"status": status, "cause": cause, "message": message}


def claim_record(claim, *, check=None) -> Optional[dict]:
    """The instance-level A3 disposition, from the SAME `Verdict` the text renders.

    The record carries the artifacts A3 surfaces — `{"axis", "kind", "status",
    "cause", "check": {"source", "exit_code"}}` — where `source` is the exact check
    the verdict was decided by (the recording author's `last_check`; an UNVERIFIED
    verdict falls back to its own `expected["check_source"]`, and never fabricates a
    source) and `exit_code` is the OBSERVED one (an UNVERIFIED abstention's check did
    not execute, so `null`).

    `None` mirrors the suppressed text line — a trace with no claim verdict (no
    author configured, the axis disabled, or D3 silence: the check exited 0) carries
    NO claim record at all, never a fabricated clean and never `null` — the
    absent-never-zero rule that keeps the pinned `--json` snapshot green for every
    trace without a claim/author.
    """
    if claim is None:
        return None
    expected = claim.expected if isinstance(claim.expected, dict) else {}
    source = (
        check.source
        if check is not None
        else expected.get("check_source", "")
    )
    return {
        "axis": claim.axis,
        "kind": claim.kind,
        "status": claim.status.value,
        "cause": expected.get("cause"),
        "check": {"source": source, "exit_code": claim.observed},
    }


__all__ = [
    "SCHEMA",
    "VerifyReport",
    "aggregate_record",
    "claim_record",
    "coverage_record",
    "error_report",
    "exposure_record",
    "render_json",
    "trajectory_record",
    "turn_record",
]