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


def render(results: Sequence[CorrelatedSpan]) -> str:
    """The human report: the rate WITH its denominator, the uncorrelated breakdown
    by named cause, then one line per span — never grouping an UNVERIFIED span
    under a matched/"OK" summary, never folding the uncorrelated count in.
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
            }
            for r in results
        ],
    }


__all__ = ["correlation_summary", "render", "to_json"]
