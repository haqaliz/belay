"""The deterministic join: OTLP spans against Belay's own recorded MCP turns.

C1 already resolves, per frame carrying W3C context, a `trace_context` fact
(`belay.connection.derive_connection_context`) with the raw `traceparent`
string verbatim — nothing here captures anything new. This module reads that
fact plus the correlation index (`belay.index.derive_correlation`,
`tool_calls`) and answers, for a parsed OTLP `Span` (`belay.interop.otlp`),
which `tools/call` turn ordinal `n` it corresponds to. It emits no verdict —
that is a later capability's job. See `CLAUDE.md`'s "the wedge": this is the
ingest-and-correlate half of C9, not verification.

**The join predicate.** A W3C `traceparent` is `version-traceId-id-flags`
(e.g. `00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01`). A `Span`
matches a turn iff `span.trace_id == traceparent.traceId AND
span.span_id == traceparent.id` — plain string equality, both already
lowercase hex on both sides (OTLP/JSON's encoding, W3C's own spec).

**Turn identity.** The positional ordinal `n` over
`tool_calls(derive_correlation(records))` — 0-based, matching every other
consumer of that index (`belay.verify.turn`, `belay.phase0.runner`, ...). A
`trace_context` record's `seq` names a frame; that frame must be the REQUEST
frame of `tools/call` ordinal `n` for the match to name turn `n`. A
`trace_context` on any other frame (a different method, or a response) is not
added to the index at all — it names no turn, so it can name no match.

**Ambiguity is a first-class outcome, never a silent pick.** If the same
`(traceId, id)` pair is carried by more than one `tools/call` turn's request
frame — a re-used span id, non-conforming but observed on the wire before —
`build_turn_index` records the `AMBIGUOUS` sentinel for that key rather than
either turn's ordinal. Picking one would attach a verdict (Task 3) to the
wrong turn with no way for a reader to tell; recording nothing at all would
look identical to "no match" and hide that the trace really did carry two
candidates. Both are the same shape of false-empty this project already
guards against elsewhere (`belay.phase0`'s R6), so ambiguity gets a status of
its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from belay.connection import derive_connection_context
from belay.index import derive_correlation, tool_calls
from belay.interop.otlp import Span


class _Ambiguous:
    """The sentinel `build_turn_index` stores for a re-used `(traceId, id)` key.

    A distinct singleton rather than `None` or `-1`: a reader must not be able
    to mistake "this key maps to more than one turn" for "this key is absent"
    or "this key maps to turn -1". Compare with `is`, never `==`, though `==`
    also works since there is only ever one instance.
    """

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return "AMBIGUOUS"


AMBIGUOUS = _Ambiguous()

# The value `build_turn_index` stores per key: a resolved turn ordinal, or the
# AMBIGUOUS sentinel for a re-used (traceId, id) pair.
TurnIndex = dict[tuple[str, str], Union[int, _Ambiguous]]


@dataclass(frozen=True)
class Matched:
    """The span corresponds to exactly one recorded `tools/call` turn."""

    n: int


@dataclass(frozen=True)
class Unmatched:
    """No recorded turn carried this span's `(trace_id, span_id)`."""


@dataclass(frozen=True)
class Ambiguous:
    """More than one recorded turn carried this span's `(trace_id, span_id)`.

    Distinct from `Unmatched`: the trace positively contains a conflict, not
    an absence, and a caller must not treat the two the same way.
    """


MatchResult = Union[Matched, Unmatched, Ambiguous]


def _split_traceparent(traceparent: object) -> tuple[str, str] | None:
    """`version-traceId-id-flags` -> `(traceId, id)`, or `None` if malformed.

    Defensive by design: a malformed/short traceparent must never crash the
    join, it must simply contribute nothing to the index. Belay recorded the
    string verbatim in C1 without validating it (that was never C1's job), so
    a garbled value crossing the wire is an expected input here, not a bug.
    """
    if not isinstance(traceparent, str):
        return None
    parts = traceparent.split("-")
    if len(parts) != 4:
        return None
    _version, trace_id, span_id, _flags = parts
    if not trace_id or not span_id:
        return None
    return (trace_id, span_id)


def build_turn_index(records: list[dict]) -> TurnIndex:
    """Map `(traceId, id)` -> the `tools/call` ordinal `n` naming that turn.

    Reads only what C1/C1's derivations already produced
    (`derive_connection_context` for `trace_context` facts,
    `derive_correlation` + `tool_calls` for turn ordinals); it derives no new
    facts about the trace. Deterministic: a pure function of `records`, so
    calling it twice over the same records yields equal results.
    """
    calls = tool_calls(derive_correlation(records))
    turn_of_request_seq: dict[int, int] = {
        entry["request_seq"]: n
        for n, entry in enumerate(calls)
        if entry["request_seq"] is not None
    }

    index: TurnIndex = {}
    for record in derive_connection_context(records):
        if record["kind"] != "trace_context":
            continue
        key = _split_traceparent(record.get("traceparent"))
        if key is None:
            continue
        n = turn_of_request_seq.get(record["seq"])
        if n is None:
            # This frame carried a traceparent but is not a tools/call
            # request frame (a different method, or a response) — it names
            # no turn, so it is not added to the index at all.
            continue
        if key in index:
            existing = index[key]
            if existing is not AMBIGUOUS and existing != n:
                index[key] = AMBIGUOUS
            # Same (key, n) seen twice (e.g. duplicate frames) is not a
            # conflict — leave the existing resolved entry as-is.
        else:
            index[key] = n
    return index


def match_span(span: Span, index: TurnIndex) -> MatchResult:
    """Resolve one `Span` against a `build_turn_index` result.

    `Matched(n)` for exactly one turn, `Ambiguous()` for a re-used span id
    across turns, `Unmatched()` for no turn at all. Reads `index` only —
    callers wanting a fresh index re-derive it from `records` themselves.
    """
    value = index.get((span.trace_id, span.span_id))
    if value is None:
        return Unmatched()
    if value is AMBIGUOUS:
        return Ambiguous()
    return Matched(value)
