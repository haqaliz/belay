"""Parsing OTLP/JSON into Belay's internal `Span`, and nothing past that.

This is the ingest half of C9 (observability interop): later work correlates these
spans against Belay's own recorded MCP turns and attaches a verdict. This module does
neither — it only turns the OTLP/JSON wire shape
(`{"resourceSpans":[{"scopeSpans":[{"spans":[...]}]}]}`) into a flat, ordered list of
`Span`, using stdlib `json` only (the zero-runtime-dependency guard in
`test_import_guard.py` would fail on `import opentelemetry`).

Two properties matter enough to test explicitly. **Ids are hex strings, not
base64.** The OTLP *JSON* exporter (unlike the protobuf wire form) encodes
`traceId`/`spanId` as plain lowercase hex, and this parser must not "helpfully"
decode them as bytes — `spans_ok.json`'s first span carries the exact
`traceId`/`spanId` from Belay's canonical `traceparent` fixture
(`tests/fixtures/connection_frames.py::TRACE_CONTEXT_META`,
`00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01`) so a later correlation
task can match on the string as-is. **Malformed input raises, never returns `[]`.**
An OTLP doc that is empty-but-well-formed (`{"resourceSpans":[]}`) is valid and
returns `[]`; a doc that is not well-formed (invalid JSON, missing `resourceSpans`,
a span missing `spanId`) must raise `OtlpParseError` rather than silently returning
an empty list — an ingest path that treats "broken" and "nothing happened" the same
way manufactures a false-empty exactly like the false-zero this project already
guards against in `belay.phase0`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from belay.interop.otlp import OtlpParseError, Span, parse_otlp

FIXTURES = Path(__file__).parent / "fixtures" / "interop"
SPANS_OK = (FIXTURES / "spans_ok.json").read_text()
SPANS_MALFORMED = (FIXTURES / "spans_malformed.json").read_text()
SPANS_SPARSE = (FIXTURES / "spans_sparse.json").read_text()

# The exact ids from Belay's canonical traceparent fixture
# (tests/fixtures/connection_frames.py::TRACE_CONTEXT_META), so a later correlation
# task can match a parsed Span back to a recorded MCP turn by string equality.
CANONICAL_TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
CANONICAL_SPAN_ID = "00f067aa0ba902b7"


def test_parses_spans_in_document_order() -> None:
    spans = parse_otlp(SPANS_OK)
    assert [s.name for s in spans] == ["mcp.tools/call", "mcp.tools/list"]


def test_first_span_matches_the_canonical_trace_context_fixture_exactly() -> None:
    first = parse_otlp(SPANS_OK)[0]
    assert first.trace_id == CANONICAL_TRACE_ID
    assert first.span_id == CANONICAL_SPAN_ID
    assert first.name == "mcp.tools/call"
    assert first.start_time_unix_nano == 1700000000000000000
    assert isinstance(first.start_time_unix_nano, int)
    assert first.attributes == {"mcp.tool.name": "echo", "mcp.request.id": 5}


def test_ids_stay_hex_strings_not_base64_decoded() -> None:
    """The JSON exporter encodes ids as hex; base64-decoding them would corrupt them."""
    first = parse_otlp(SPANS_OK)[0]
    assert isinstance(first.trace_id, str)
    assert first.trace_id == CANONICAL_TRACE_ID
    # A base64-decode of this hex string would not round-trip to the same value —
    # guard against "helpfully" treating the id as anything but an opaque hex string.
    assert len(first.trace_id) == 32
    assert all(c in "0123456789abcdef" for c in first.trace_id)


def test_start_time_unix_nano_given_as_json_string_is_parsed_to_int() -> None:
    second = parse_otlp(SPANS_OK)[1]
    assert second.start_time_unix_nano == 1700000001000000000
    assert isinstance(second.start_time_unix_nano, int)


def test_attribute_flattening_handles_string_int_and_bool_values() -> None:
    second = parse_otlp(SPANS_OK)[1]
    assert second.attributes == {"mcp.request.id": 6, "belay.sandboxed": True}


def test_unknown_attribute_value_kind_is_kept_raw_not_dropped() -> None:
    doc = json.loads(SPANS_OK)
    span = doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    span["attributes"].append({"key": "belay.weird", "value": {"arrayValue": {"values": []}}})
    spans = parse_otlp(json.dumps(doc))
    assert spans[0].attributes["belay.weird"] == {"arrayValue": {"values": []}}


def test_span_is_a_frozen_dataclass() -> None:
    span = parse_otlp(SPANS_OK)[0]
    assert isinstance(span, Span)
    with pytest.raises(Exception):
        span.name = "mutated"  # type: ignore[misc]


def test_empty_but_well_formed_document_returns_empty_list_not_an_error() -> None:
    """An OTLP doc with no resource spans at all is valid — distinct from malformed."""
    assert parse_otlp('{"resourceSpans":[]}') == []


def test_resource_span_with_omitted_scope_spans_is_valid_empty_not_an_error() -> None:
    """proto3-JSON omits empty repeated fields by default: a `ResourceSpans` with no
    `ScopeSpans` at all is a spec-valid sparse export, not malformed input."""
    assert parse_otlp('{"resourceSpans":[{}]}') == []


def test_scope_span_with_omitted_spans_is_valid_empty_not_an_error() -> None:
    """Same proto3-JSON omission one level down: a `ScopeSpans` whose `spans` were
    all sampled out is spec-valid and omits the (empty) `spans` key entirely."""
    assert parse_otlp('{"resourceSpans":[{"scopeSpans":[{}]}]}') == []


def test_sparse_fixture_with_omitted_scope_spans_and_spans_returns_empty_list() -> None:
    """A real-shaped sparse export: one resourceSpans entry omits `scopeSpans`
    entirely, another's scopeSpans entry omits `spans` entirely. Both are
    proto3-JSON-valid empties, not malformed input, so this must return `[]`."""
    assert parse_otlp(SPANS_SPARSE) == []


def test_non_list_scope_spans_still_raises_otlp_parse_error() -> None:
    """Absence is empty; a present-but-wrong-typed value is still malformed."""
    with pytest.raises(OtlpParseError):
        parse_otlp('{"resourceSpans":[{"scopeSpans":"not-a-list"}]}')


def test_non_list_spans_still_raises_otlp_parse_error() -> None:
    """Absence is empty; a present-but-wrong-typed value is still malformed."""
    with pytest.raises(OtlpParseError):
        parse_otlp('{"resourceSpans":[{"scopeSpans":[{"spans":"not-a-list"}]}]}')


def test_invalid_json_raises_otlp_parse_error() -> None:
    with pytest.raises(OtlpParseError):
        parse_otlp("not json at all {")


def test_missing_resource_spans_key_raises_otlp_parse_error() -> None:
    with pytest.raises(OtlpParseError):
        parse_otlp("{}")


def test_malformed_fixture_raises_otlp_parse_error_not_empty_list() -> None:
    """A span missing `spanId` is malformed, not merely empty — must raise, never `[]`."""
    with pytest.raises(OtlpParseError):
        parse_otlp(SPANS_MALFORMED)


def test_malformed_fixture_does_not_raise_a_bare_keyerror_or_valueerror() -> None:
    """The contract is a domain-specific exception, not whatever stdlib happened to raise."""
    try:
        parse_otlp(SPANS_MALFORMED)
        raise AssertionError("expected OtlpParseError")
    except OtlpParseError:
        pass
    except (KeyError, ValueError) as exc:
        raise AssertionError(
            f"parse_otlp leaked a bare {type(exc).__name__} instead of OtlpParseError"
        ) from exc
