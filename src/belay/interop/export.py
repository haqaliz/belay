"""The export half of C9: verdicts travel back into the OTLP document a collector reads.

`correlate_and_attach` (Task 3) resolves each ingested OTLP span to a `CorrelatedSpan`
— a real replayed `TurnVerdict`, or `UNVERIFIED` with a named cause. Nothing in
`interop/` could put that verdict back INSIDE the OTLP document the team already
exports to their collector, which is the whole point of the export direction: a FAIL
must be visible next to the span it belongs to, in the dashboard they already watch.

This module is the one pure function: `build_enriched_document` deep-copies the
parsed OTLP document, pairs `results[i]` with `spans[i]` positionally (one
`CorrelatedSpan` per input span, in input order — the `correlate_and_attach`
invariant, guarded here by a loud length assertion rather than a silent partial
zip), and enriches every ingested span with `belay.verdict.*` attributes plus ONE
`belay.verdict` event. Inputs are never mutated (asserted by test).

**The attribute contract** (pinned byte-for-byte by
`tests/fixtures/interop/exported_ok.json`; drift shows as a fixture diff):

- `belay.verdict.status` — the reduced status (`CorrelatedSpan.status`, `.value`).
- `belay.verdict.axis` — the axis of the highest-ranked sub-verdict per the rank
  table in `verdict.py` (FAIL > UNVERIFIED > WARN > PASS; `NOT_COVERED` never ranks —
  it is filtered first), first among ties; ABSENT when the verdict has no sub-verdicts.
- `belay.verdict.cause` — the span's named cause; ABSENT when `None`, never `""`.
- `belay.verdict.turn_index` — int; matched spans only.
- `belay.verdict.coverage` — a JSON string array of the `kind`s of `NOT_COVERED`
  sub-verdicts (e.g. `["effect:network"]`); ABSENT when none. The coverage line
  travels with the status on every surface — a PASS exported without it is the named
  failure mode of this surface.
- `belay.verdict.sub_verdicts` — a JSON string array of `{"axis","kind","status",
  "message"}` (a plain dict per sub-verdict, `.value` for status); ABSENT when empty.
- Span event `belay.verdict` — `timeUnixNano` is the span's OWN
  `start_time_unix_nano` (deterministic, from the input; the only timestamp in the
  output); attributes: `message` (the worst sub-verdict's message, `""` if none) and
  `observed`/`expected` of that same sub-verdict where present (JSON-stringified via
  `json.dumps` if not already a string).

**Honesty invariants, inherited from the rest of the engine.** An uncovered span
(unmatched/ambiguous) exports `UNVERIFIED` with its named cause — never PASS, never a
bare span. Nothing is re-computed: a matched span's `TurnVerdict` is carried
verbatim, and the status comes from `CorrelatedSpan.status`, which is the same
"nothing was verified -> UNVERIFIED" reduction every other surface uses.

Zero runtime dependencies: stdlib only (`json`, `copy`). No OTel SDK import, no
network, no clock — determinism is asserted two ways (byte-identical re-runs and the
committed fixture). The `dumps` serializer (`sort_keys=True, indent=2` + trailing
newline) is shared so the CLI aspect writes byte-identical output.
"""

from __future__ import annotations

import copy
import json
from typing import Sequence

from belay.interop.attach import CorrelatedSpan
from belay.interop.otlp import Span
from belay.verify.verdict import Status, Verdict

#: Every attribute this module adds to a span is namespaced under this prefix.
VERDICT_ATTRIBUTE_PREFIX = "belay.verdict"

#: The single span event carrying the verdict message/diff.
VERDICT_EVENT_NAME = "belay.verdict"

#: The worst-status-wins ordering, mirrored from `verdict.py`'s private `_RANK`
#: (FAIL > UNVERIFIED > WARN > PASS). `NOT_COVERED` is filtered out BEFORE ranking —
#: it states a coverage boundary, never a finding, exactly as `verdict.reduce` drops
#: it — so it never appears in this table and can never win the axis.
_RANK = {
    Status.PASS: 0,
    Status.WARN: 1,
    Status.UNVERIFIED: 2,
    Status.FAIL: 3,
}


def dumps(document: dict) -> str:
    """Serialize an exported document byte-stably: sorted keys, 2-space indent,
    trailing newline. Shared so the CLI aspect writes byte-identical output."""
    return json.dumps(document, sort_keys=True, indent=2) + "\n"


def _attribute(key: str, value: object) -> dict:
    """One OTLP attribute entry, in the exact shape the parser reads (spans_ok.json):
    `{"key": ..., "value": {"stringValue": ...}}` for strings, `{"intValue": str(n)}`
    for ints. Anything else is a bug in this module — fail closed rather than emit a
    shape the ingest half cannot read back.
    """
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    raise TypeError(f"cannot encode attribute {key!r} with value {value!r}")


def _sub_verdict_record(verdict: Verdict) -> dict:
    """One sub-verdict as the plain `{"axis","kind","status","message"}` record the
    JSON-string attribute carries — `.value` for the status, per the contract."""
    return {
        "axis": verdict.axis,
        "kind": verdict.kind,
        "status": verdict.status.value,
        "message": verdict.message,
    }


def _coverage_dimensions(sub_verdicts: Sequence[Verdict]) -> list[str]:
    """The `kind`s of the `NOT_COVERED` sub-verdicts, in list order — the coverage
    line that must travel with every exported status."""
    return [s.kind for s in sub_verdicts if s.status is Status.NOT_COVERED]


def _worst_sub_verdict(sub_verdicts: Sequence[Verdict]) -> Verdict | None:
    """The highest-ranked sub-verdict per the `verdict.py` rank table — `NOT_COVERED`
    filtered FIRST (it never ranks), first among ties, `None` when nothing scored."""
    scored = [s for s in sub_verdicts if s.status is not Status.NOT_COVERED]
    if not scored:
        return None
    return max(scored, key=lambda s: _RANK[s.status])


def _event(span: dict, worst: Verdict | None) -> dict:
    """The one `belay.verdict` event: `timeUnixNano` is the span's OWN start time
    (deterministic — the only timestamp in the output), attributes carry the worst
    sub-verdict's `message` (`""` if none) and its `observed`/`expected` where
    present, JSON-stringified when not already a string."""
    attributes = [{"key": "message", "value": {"stringValue": worst.message if worst else ""}}]
    if worst is not None:
        for name in ("observed", "expected"):
            value = getattr(worst, name)
            if value is not None:
                if not isinstance(value, str):
                    value = json.dumps(value)
                attributes.append({"key": name, "value": {"stringValue": value}})
    return {
        "timeUnixNano": str(span["startTimeUnixNano"]),
        "name": VERDICT_EVENT_NAME,
        "attributes": attributes,
    }


def _enrich(span: dict, result: CorrelatedSpan) -> None:
    """Append the verdict attributes and one event to ONE raw span dict, in place.

    The status comes from `CorrelatedSpan.status` — the same "nothing was verified
    -> UNVERIFIED" reduction every other surface uses, so an uncovered span can never
    read as PASS and the export never spells `Status.PASS` itself. Matched spans
    carry their `TurnVerdict` verbatim; absent facts stay absent (absent-never-zero:
    no `cause` key for `None`, no `axis`/`turn_index`/`sub_verdicts` for an uncovered
    span, no `coverage` key without a `NOT_COVERED` dimension).
    """
    prefix = VERDICT_ATTRIBUTE_PREFIX
    verdict = result.verdict

    attributes = span.setdefault("attributes", [])
    attributes.append(_attribute(f"{prefix}.status", result.status.value))

    worst = None
    if verdict is not None:
        worst = _worst_sub_verdict(verdict.sub_verdicts)
        if worst is not None:
            attributes.append(_attribute(f"{prefix}.axis", worst.axis))
        if result.cause is not None:
            attributes.append(_attribute(f"{prefix}.cause", result.cause))
        if result.turn_index is not None:
            attributes.append(_attribute(f"{prefix}.turn_index", result.turn_index))
        uncovered_kinds = _coverage_dimensions(verdict.sub_verdicts)
        if uncovered_kinds:
            attributes.append(
                _attribute(f"{prefix}.coverage", json.dumps(uncovered_kinds))
            )
        if verdict.sub_verdicts:
            attributes.append(
                _attribute(
                    f"{prefix}.sub_verdicts",
                    json.dumps([_sub_verdict_record(s) for s in verdict.sub_verdicts]),
                )
            )
    else:
        attributes.append(_attribute(f"{prefix}.cause", result.cause))

    span.setdefault("events", []).append(_event(span, worst))


def build_enriched_document(
    document: dict,
    spans: Sequence[Span],
    results: Sequence[CorrelatedSpan],
) -> dict:
    """A deep copy of `document` in which every ingested span carries its verdict.

    Pairs `results[i]` with `spans[i]` POSITIONALLY — `correlate_and_attach` returns
    exactly one `CorrelatedSpan` per input span, in input order, and `parse_otlp`
    preserves document order, so the walk below enriches the k-th raw span with the
    k-th result. A length mismatch between `spans` and `results` — or between the
    document's span count and `spans` — is a loud `ValueError`, never a silent partial
    zip. The input document, spans and results are never mutated.
    """
    spans = list(spans)
    results = list(results)
    if len(spans) != len(results):
        raise ValueError(
            f"spans/results length mismatch: {len(spans)} span(s) but "
            f"{len(results)} CorrelatedSpan(s) — the export pairs results[i] with "
            f"spans[i] positionally, so correlation must yield exactly one result "
            f"per ingested span"
        )

    enriched = copy.deepcopy(document)

    walked = 0
    for resource_span in enriched["resourceSpans"]:
        for scope_span in resource_span.get("scopeSpans") or []:
            for raw_span in scope_span.get("spans") or []:
                if walked >= len(spans):
                    raise ValueError(
                        f"document/spans mismatch: the document carries more spans "
                        f"than the {len(spans)} parsed span(s) — pairing would be "
                        f"partial, and a partial export is a silent mis-export"
                    )
                if "startTimeUnixNano" not in raw_span:
                    raise ValueError(
                        f"span {raw_span.get('spanId', '<no spanId>')!r} in the "
                        f"document has no startTimeUnixNano; only a parsed OTLP "
                        f"document is an acceptable input"
                    )
                _enrich(raw_span, results[walked])
                walked += 1
    if walked != len(spans):
        raise ValueError(
            f"document/spans mismatch: the document carries {walked} span(s) but "
            f"{len(spans)} were parsed — pairing would be partial, and a partial "
            f"export is a silent mis-export"
        )

    return enriched


__all__ = [
    "VERDICT_ATTRIBUTE_PREFIX",
    "VERDICT_EVENT_NAME",
    "build_enriched_document",
    "dumps",
]