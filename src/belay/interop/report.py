"""The C9 correlation-rate report: matched/total with the denominator, always.

`correlate_and_attach` (Task 3) resolves each OTLP span to a `CorrelatedSpan` — a
turn index and a verdict, or `None` and a named cause. This module turns a list of
those into the human-readable report and the `--json` payload the CLI (Task 4)
prints. It computes NOTHING beyond counting: the correlation rate is
`matched/total` (matched = a span whose `turn_index` is not `None`), and every
uncorrelated span is bucketed by its OWN `cause` — never folded into the matched
count, and never spun as a clean report by omission.

Honesty invariants this module upholds, on purpose:
- **The denominator is ALWAYS printed alongside the rate** (`M/T`), never a bare
  percentage — a rate with no total beside it invites the exact false confidence
  this project exists to refuse.
- **`UNVERIFIED` renders as the literal word, in its own column**, next to every
  other status. There is no color in this CLI, so the distinction IS the word,
  and it is never grouped under a matched/"OK" summary that would read as PASS.
- **A status never prints without what it excluded.** This one was written into
  the list above *before* `NOT_COVERED` existed, when a dimension Belay could not
  observe dragged the whole turn to `UNVERIFIED` and the boundary was therefore
  visible in the status column itself. `NOT_COVERED` moved it: the sub-verdict is
  dropped before the reduction, so such a turn now correlates as a clean `PASS`
  and this module — which reads only `.status` — would have printed one with no
  hint of what it left out. The bullet above stayed literally true while quietly
  ceasing to be sufficient, which is the most dangerous shape a stale invariant
  can take. Hence `_coverage_lines`, unconditional, on both the human and `--json`
  surfaces.
- **The `--json` shape is stdlib-serializable**: every `Status` becomes its
  `.value` string, and every absent fact stays JSON `null` (never a Python-repr
  string, never a fabricated 0/""). It round-trips through `json.loads` unchanged.

This module computes no verdict of its own, same discipline as `attach.py`: every
`status`/`cause` it prints came from a `CorrelatedSpan` handed to it. Pure and
deterministic: stdlib only, no filesystem, no clock, no randomness, no model. Same
list of `CorrelatedSpan` in -> the same string/dict out, always.
"""

from __future__ import annotations

from typing import Sequence

from belay.interop.attach import CorrelatedSpan
from belay.verify.verdict import Status

#: Width of the span-id column in the human report. OTLP/JSON span ids are 16 hex
#: digits; wide enough to show the whole id without forcing a line wrap.
_SPAN_ID_WIDTH = 16


def correlation_summary(results: Sequence[CorrelatedSpan]) -> dict:
    """`{"matched": M, "total": T, "uncorrelated": {cause: count, ...}}`.

    `matched` counts every span whose `turn_index is not None` — REGARDLESS of its
    attached verdict's status, because "did this span name a turn" and "did that
    turn verify clean" are different questions; the correlation rate answers only
    the first. `uncorrelated` buckets the rest (`turn_index is None`) by their own
    `cause` string, so the uncorrelated total is never one opaque number: every
    span that could not be routed to a turn says exactly why.
    """
    total = len(results)
    matched = sum(1 for r in results if r.turn_index is not None)

    uncorrelated: dict[str, int] = {}
    for r in results:
        if r.turn_index is None:
            cause = r.cause or "unknown"
            uncorrelated[cause] = uncorrelated.get(cause, 0) + 1

    return {"matched": matched, "total": total, "uncorrelated": uncorrelated}


def _span_line(r: CorrelatedSpan) -> str:
    span_id = r.span_id[:_SPAN_ID_WIDTH]
    turn = str(r.turn_index) if r.turn_index is not None else "-"
    line = f"{span_id:<{_SPAN_ID_WIDTH}}  turn {turn:<6}  {r.status.value:<12}"
    if r.cause is not None:
        line += r.cause
    return line


def _coverage_lines(results: Sequence[CorrelatedSpan]) -> list[str]:
    """What the rendered verdicts did NOT cover — printed beside them, never instead.

    A `NOT_COVERED` sub-verdict is dropped before the reduction, so it moves no status
    and a reader scanning the status column alone would never learn it existed. That is
    the false-PASS shape the status was introduced to avoid, so this block is
    unconditional: it prints even when there is nothing to report, in words that do not
    claim full coverage.

    Counted per SPAN per kind and rendered as `n/total`, so the fraction bounds the claim
    — the reason a summary block is honest here rather than needing a per-span repeat.
    The sub-verdict's own message is echoed once per kind, because the message is what
    separates "this tool PROMISED a closed network posture and Belay did not check it"
    from "nothing was promised" — a distinction the reduction no longer makes.
    """
    total = len(results)
    counts: dict[str, int] = {}
    messages: dict[str, str] = {}
    for r in results:
        if r.verdict is None:
            continue
        uncovered = [s for s in r.verdict.sub_verdicts if s.status is Status.NOT_COVERED]
        for sub in uncovered:
            messages.setdefault(sub.kind, sub.message)
        for kind in sorted({sub.kind for sub in uncovered}):
            counts[kind] = counts.get(kind, 0) + 1

    lines = ["coverage (NOT_COVERED -- outside what Belay observes; never a PASS)"]
    if not counts:
        lines.append(
            "  no NOT_COVERED dimension on these spans; this is NOT a claim that "
            "everything was inside coverage"
        )
        return lines
    for kind in sorted(counts):
        lines.append(f"  {kind:<20}NOT observed for {counts[kind]}/{total} span(s)")
        lines.append(f"    {messages[kind]}")
    return lines


def render(results: Sequence[CorrelatedSpan]) -> str:
    """The human report: the rate WITH its denominator, the uncorrelated breakdown
    by named cause, the coverage boundary, then one line per span — never grouping an
    UNVERIFIED span under a matched/"OK" summary, never folding the uncorrelated count
    in, and never printing a status without what it excluded.
    """
    summary = correlation_summary(results)
    lines: list[str] = []

    lines.append(f"correlation rate = {summary['matched']}/{summary['total']}")
    lines.append("")

    lines.append("uncorrelated (by named cause -- never folded into the matched count)")
    if summary["uncorrelated"]:
        for cause in sorted(summary["uncorrelated"]):
            lines.append(f"  {cause:<28}{summary['uncorrelated'][cause]}")
    else:
        lines.append("  none")
    lines.append("")

    lines.extend(_coverage_lines(results))
    lines.append("")

    lines.append("spans")
    if results:
        for r in results:
            lines.append(f"  {_span_line(r)}")
    else:
        lines.append("  (no spans in this document)")

    return "\n".join(lines)


def to_json(results: Sequence[CorrelatedSpan]) -> dict:
    """`{"correlation": {...}, "spans": [...]}` — stdlib-serializable.

    Every `Status` is lowered to its `.value` string and every absent fact stays
    JSON `null`. The caller (the CLI) adds the `"trace"` key: this module only
    knows about the spans it was handed, never the file paths behind them.
    """
    summary = correlation_summary(results)
    return {
        "correlation": summary,
        "spans": [
            {
                "span_id": r.span_id,
                "turn_index": r.turn_index,
                "status": r.status.value,
                "cause": r.cause,
                # The coverage boundary, in structured form. A payload carrying only the
                # status hands a downstream tool the same false PASS the human report
                # was just fixed to refuse. `null` for an uncovered span: it has no
                # verdict at all, which is not the same as a verdict with no sub-verdicts.
                "sub_verdicts": (
                    None
                    if r.verdict is None
                    else [
                        {
                            "axis": s.axis,
                            "kind": s.kind,
                            "status": s.status.value,
                            "message": s.message,
                        }
                        for s in r.verdict.sub_verdicts
                    ]
                ),
            }
            for r in results
        ],
    }


__all__ = ["correlation_summary", "render", "to_json"]
