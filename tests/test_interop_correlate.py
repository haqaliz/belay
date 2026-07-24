"""The deterministic span↔turn join: OTLP spans against Belay's own recorded MCP turns.

Belay already records, per frame carrying W3C context, a `trace_context` fact
(`belay.connection.derive_connection_context`) with the raw `traceparent` string
verbatim. This module reads that fact — it adds no capture — and answers, for a
parsed OTLP `Span` (Task 1's `belay.interop.otlp.Span`), which `tools/call` turn
ordinal `n` it corresponds to, matching 0, 1, or >1 turns. No verdict is emitted
here; that is Task 3's job.

The join predicate, pinned by these tests rather than re-derived: a W3C
`traceparent` is `version-traceId-id-flags`; a span matches a turn iff
`span.trace_id == traceparent.traceId AND span.span_id == traceparent.id`, and
the `trace_context` record's `seq` must land on the REQUEST frame of a
`tools/call` turn (a traceparent on any other frame names no turn).
"""

from __future__ import annotations

from conftest import trace_of
from fixtures.connection_frames import TRACE_CONTEXT_META

from belay.interop.correlate import (
    AMBIGUOUS,
    Ambiguous,
    Matched,
    Unmatched,
    build_turn_index,
    match_span,
)
from belay.interop.otlp import Span

# The exact ids embedded in TRACE_CONTEXT_META's traceparent
# ("00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01") — Task 1's own
# canonical fixture ids, so a span built from them is known to correspond to a
# real, previously-tested trace_context fact rather than an invented pair.
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "00f067aa0ba902b7"


def _span(trace_id: str, span_id: str, name: str = "mcp.tools/call") -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        name=name,
        start_time_unix_nano=1700000000000000000,
        attributes={},
    )


def test_a_span_matching_the_tools_call_turns_traceparent_is_matched(tmp_path):
    """TRACE_CONTEXT_META is itself a `tools/call` request — the canonical join."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    index = build_turn_index(records)

    span = _span(TRACE_ID, SPAN_ID)
    result = match_span(span, index)

    assert result == Matched(0)


def test_a_span_whose_ids_match_nothing_is_unmatched(tmp_path):
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    index = build_turn_index(records)

    span = _span("f" * 32, "f" * 16)
    result = match_span(span, index)

    assert result == Unmatched()


def test_the_same_traceparent_on_two_tools_call_turns_is_ambiguous(tmp_path):
    """A re-used span-id across two turns must not silently pick one."""
    records = trace_of(
        tmp_path,
        [("c2s", TRACE_CONTEXT_META), ("c2s", TRACE_CONTEXT_META)],
    )
    index = build_turn_index(records)

    assert index[(TRACE_ID, SPAN_ID)] is AMBIGUOUS

    span = _span(TRACE_ID, SPAN_ID)
    result = match_span(span, index)

    assert result == Ambiguous()


# A traceparent carried by a `tools/list` request, not a `tools/call` — same
# valid W3C shape and the same canonical ids as TRACE_CONTEXT_META, but on a
# frame `derive_correlation` classifies under a different method. It must NOT
# be indexed: a trace_context record naming no `tools/call` turn names nothing.
TRACEPARENT_ON_NON_TOOLS_CALL = (
    b'{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{'
    b'"_meta":{"traceparent":"00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"}}}'
)


def test_a_traceparent_on_a_non_tools_call_frame_is_not_indexed(tmp_path):
    """A trace_context record whose frame isn't a tools/call request names no turn."""
    records = trace_of(tmp_path, [("c2s", TRACEPARENT_ON_NON_TOOLS_CALL)])
    index = build_turn_index(records)

    assert index == {}

    span = _span(TRACE_ID, SPAN_ID)
    assert match_span(span, index) == Unmatched()


def test_building_the_index_twice_over_the_same_records_is_deterministic(tmp_path):
    records = trace_of(
        tmp_path,
        [("c2s", TRACE_CONTEXT_META), ("c2s", TRACE_CONTEXT_META)],
    )

    first = build_turn_index(records)
    second = build_turn_index(records)

    assert first == second


def test_a_duplicate_response_to_one_tools_call_does_not_silently_pick_the_wrong_ordinal(
    tmp_path,
):
    """A non-conforming server replying TWICE to the same id (`index.py`'s own
    `duplicate-response` fact) produces two `tool_calls` entries sharing ONE
    `request_seq` — the original answered call, and the duplicate-response entry that
    inherits its method — but different ordinals `n`. A naive `{request_seq: n}` dict
    comprehension is last-write-wins and would silently point this traceparent's turn
    at the WRONG ordinal: the exact "attach a verdict to the wrong span" failure this
    capability must never produce. The honest outcome mirrors the existing
    `(traceId, id)` key-collision handling: AMBIGUOUS, never a guessed pick.
    """
    duplicate_reply = b'{"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"ok"}]}}'
    records = trace_of(
        tmp_path,
        [
            ("c2s", TRACE_CONTEXT_META),
            ("s2c", duplicate_reply),
            ("s2c", duplicate_reply),
        ],
    )

    index = build_turn_index(records)

    assert index[(TRACE_ID, SPAN_ID)] is AMBIGUOUS

    span = _span(TRACE_ID, SPAN_ID)
    assert match_span(span, index) == Ambiguous()


def test_malformed_traceparent_is_skipped_without_crashing(tmp_path):
    """A short/garbled traceparent string is defensively parsed: no crash, no entry."""
    bad = (
        b'{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"echo",'
        b'"_meta":{"traceparent":"totally-malformed"}}}'
    )
    records = trace_of(tmp_path, [("c2s", bad)])

    index = build_turn_index(records)

    assert index == {}
