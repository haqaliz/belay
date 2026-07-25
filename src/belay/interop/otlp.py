"""Parse OTLP/JSON spans into Belay's internal `Span`, using stdlib `json` only.

This is C9's ingest half: turning the wire shape an OpenTelemetry JSON exporter
emits — `{"resourceSpans":[{"scopeSpans":[{"spans":[...]}]}]}` — into a flat,
ordered list of `Span`. It does no correlation against Belay's own recorded MCP
turns and emits no verdict; that is later work. Zero third-party dependency: no
`opentelemetry` SDK, `json` from the standard library only (the same constraint
`tests/test_import_guard.py` enforces on every module under `src/belay/`).

**Ids are hex strings, not bytes.** The *protobuf* wire form of OTLP encodes
`trace_id`/`span_id` as raw bytes, base64-wrapped when carried over JSON — but the
OTLP **JSON exporter** (the thing this module actually reads) encodes them as
plain lowercase hex strings instead. This parser trusts that encoding and never
base64-decodes; doing so would silently corrupt every id it touches.

**Malformed input raises; it is never treated as empty.** An OTLP document with
no spans in it (`{"resourceSpans":[]}`) is valid and returns `[]`. A document that
is not valid OTLP/JSON at all — broken JSON, a missing `resourceSpans`, a span
missing `spanId` — raises `OtlpParseError`. Collapsing those two cases would make
"nothing to ingest" indistinguishable from "the ingest is broken", which is
exactly the false-empty failure mode `belay.phase0` already guards against for
Belay's own trace format (the R6 false-zero defense) — an interop ingest path
that quietly returned `[]` for garbage input would reintroduce it at the seam
with somebody else's exporter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


class OtlpParseError(ValueError):
    """The input is not valid OTLP/JSON — broken JSON, or a structure this parser
    does not recognise as OTLP (missing `resourceSpans`, a span missing an id, ...).

    Deliberately its own type rather than letting a bare `KeyError`/`TypeError`/
    `json.JSONDecodeError` escape: a caller catching "this input was bad" should
    not have to enumerate every stdlib exception `json.loads` and dict-indexing
    might raise on the way to that conclusion.
    """


@dataclass(frozen=True)
class Span:
    """One OTLP span, reduced to the fields Belay's ingest needs.

    `trace_id` and `span_id` are the exact lowercase hex strings the OTLP/JSON
    exporter wrote — never decoded, never re-encoded — so a later correlation
    pass can match them against a `traceparent` header by plain string equality.
    `start_time_unix_nano` is normalised to `int`: OTLP/JSON encodes it as a
    string (JSON numbers cannot losslessly hold an int64), and re-exposing that
    as a string would push the same conversion onto every caller.
    """

    trace_id: str
    span_id: str
    name: str
    start_time_unix_nano: int
    attributes: dict[str, object]


def _fail(message: str) -> "OtlpParseError":
    return OtlpParseError(f"malformed OTLP/JSON: {message}")


def _flatten_attributes(raw: object, *, where: str) -> dict[str, object]:
    """OTLP's `[{"key":..., "value":{"stringValue"/"intValue"/...}}]` -> a plain dict.

    Supports `stringValue`, `intValue`, `boolValue`, `doubleValue`. A value kind
    this parser does not recognise is kept as the raw `value` dict rather than
    dropped — an unrecognised kind is new information the exporter sent, and
    silently discarding it would be a worse failure than passing it through
    un-flattened for a caller to deal with.
    """
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise _fail(f"{where}.attributes must be a list, got {type(raw).__name__}")

    attributes: dict[str, object] = {}
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise _fail(f"{where}.attributes[{i}] must be an object")
        if "key" not in entry:
            raise _fail(f"{where}.attributes[{i}] missing 'key'")
        key = entry["key"]
        value = entry.get("value")
        if not isinstance(value, dict):
            raise _fail(f"{where}.attributes[{i}] ('{key}') missing an object 'value'")

        if "stringValue" in value:
            attributes[key] = str(value["stringValue"])
        elif "intValue" in value:
            # OTLP/JSON encodes int64 fields as strings (a JSON number cannot
            # losslessly hold one); accept either form rather than assume.
            attributes[key] = int(value["intValue"])
        elif "boolValue" in value:
            attributes[key] = bool(value["boolValue"])
        elif "doubleValue" in value:
            attributes[key] = float(value["doubleValue"])
        else:
            # Unknown kind: keep the raw value dict rather than drop the attribute.
            attributes[key] = value
    return attributes


def _parse_span(raw: object, *, where: str) -> Span:
    if not isinstance(raw, dict):
        raise _fail(f"{where} must be an object, got {type(raw).__name__}")

    if "traceId" not in raw:
        raise _fail(f"{where} missing 'traceId'")
    if "spanId" not in raw:
        raise _fail(f"{where} missing 'spanId'")
    if "name" not in raw:
        raise _fail(f"{where} missing 'name'")
    if "startTimeUnixNano" not in raw:
        raise _fail(f"{where} missing 'startTimeUnixNano'")

    trace_id, span_id, name = raw["traceId"], raw["spanId"], raw["name"]
    if not isinstance(trace_id, str):
        raise _fail(f"{where}.traceId must be a string, got {type(trace_id).__name__}")
    if not isinstance(span_id, str):
        raise _fail(f"{where}.spanId must be a string, got {type(span_id).__name__}")
    if not isinstance(name, str):
        raise _fail(f"{where}.name must be a string, got {type(name).__name__}")

    try:
        start_time_unix_nano = int(raw["startTimeUnixNano"])
    except (TypeError, ValueError) as exc:
        raise _fail(
            f"{where}.startTimeUnixNano must be an int or a numeric string, "
            f"got {raw['startTimeUnixNano']!r}"
        ) from exc

    attributes = _flatten_attributes(raw.get("attributes"), where=where)

    return Span(
        trace_id=trace_id,
        span_id=span_id,
        name=name,
        start_time_unix_nano=start_time_unix_nano,
        attributes=attributes,
    )


def parse_otlp(json_text: str) -> list[Span]:
    """Parse an OTLP/JSON document into a flat, document-ordered list of `Span`.

    Reads `{"resourceSpans":[{"scopeSpans":[{"spans":[...]}]}]}`. `resource` and
    `scope` siblings, if present, are accepted and ignored — only `spans` matter
    to this parser. Raises `OtlpParseError` for anything that is not valid
    OTLP/JSON; a document with no spans at all (`{"resourceSpans":[]}`) is valid
    and returns `[]`. Because OTLP/JSON is proto3-JSON, empty repeated fields are
    omitted by default: `scopeSpans` missing from a `resourceSpans` entry, and
    `spans` missing from a `scopeSpans` entry, are each treated as `[]` rather
    than raising — a spec-valid sparse export must not be rejected as malformed.
    A *present* value that is not a list is still malformed and still raises.
    """
    try:
        doc = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise _fail(f"invalid JSON ({exc})") from exc

    if not isinstance(doc, dict):
        raise _fail(f"top level must be an object, got {type(doc).__name__}")
    if "resourceSpans" not in doc:
        raise _fail("missing 'resourceSpans'")
    resource_spans = doc["resourceSpans"]
    if not isinstance(resource_spans, list):
        raise _fail(f"'resourceSpans' must be a list, got {type(resource_spans).__name__}")

    spans: list[Span] = []
    for ri, resource_span in enumerate(resource_spans):
        if not isinstance(resource_span, dict):
            raise _fail(f"resourceSpans[{ri}] must be an object")
        # proto3-JSON omits empty repeated fields by default, so an absent
        # `scopeSpans` is a spec-valid sparse export (no scopes for this resource),
        # not malformed input — symmetric with how `attributes` already defaults to
        # `{}` below. A *present* non-list value is still malformed and still raises.
        scope_spans = resource_span.get("scopeSpans") or []
        if not isinstance(scope_spans, list):
            raise _fail(f"resourceSpans[{ri}].scopeSpans must be a list")

        for si, scope_span in enumerate(scope_spans):
            if not isinstance(scope_span, dict):
                raise _fail(f"resourceSpans[{ri}].scopeSpans[{si}] must be an object")
            # Same proto3-JSON omission one level down: `spans` all sampled out (or
            # never populated) is spec-valid and legitimately absent from the wire.
            raw_spans = scope_span.get("spans") or []
            if not isinstance(raw_spans, list):
                raise _fail(f"resourceSpans[{ri}].scopeSpans[{si}].spans must be a list")

            for spi, raw_span in enumerate(raw_spans):
                where = f"resourceSpans[{ri}].scopeSpans[{si}].spans[{spi}]"
                spans.append(_parse_span(raw_span, where=where))

    return spans
