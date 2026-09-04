"""Task A1 — export-engine: verdict attributes + one event on every ingested span.

C9's second aspect is the export direction of the observability interop: slice 1
(`correlate.py`/`attach.py`/`otlp.py`) proved a foreign OTLP span can be correlated to
a recorded MCP turn and get the replayed verdict attached; this module is the pure
function that puts that verdict back INSIDE the OTLP document a collector consumes —
`belay.verdict.*` span attributes plus one `belay.verdict` event, on EVERY ingested
span (matched -> the real `TurnVerdict` verbatim; uncovered -> `UNVERIFIED` with its
named cause, never PASS, never a bare span).

This module is written FIRST, entirely through the `verify=` stub seam (never a real
sandboxed replay), pinning the contract before any `export.py` exists:

- **AC1 round-trip** — the exported document re-parses with `parse_otlp` and the
  span's `belay.verdict.status`/`belay.verdict.axis` equal the source verdict's
  reduced status and worst axis.
- **AC2 UNVERIFIED-never-PASS** — an unmatched/ambiguous ingested span exports
  `UNVERIFIED` with its named cause.
- **AC3 coverage** — a `NOT_COVERED` sub-verdict exports as `belay.verdict.coverage`;
  a verdict without one exports NO coverage key (absent-never-zero).
- **AC4 absent-never-zero** — no cause -> no `belay.verdict.cause` key (never `""`);
  no sub-verdicts -> no `belay.verdict.sub_verdicts` key.
- **AC5 purity + determinism** — inputs deep-equal after the call; two identical runs
  produce byte-identical documents.
- **AC7 no bare span** — every ingested span carries `belay.verdict.status`.
- **AC8 pairing** — same `span_id` across traces gets its own verdict; a `spans`/`
  `results` length mismatch is a loud `ValueError`, never a silent zip.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from conftest import trace_of
from fixtures.connection_frames import TRACE_CONTEXT_META

from belay.interop.attach import (
    AMBIGUOUS_CORRELATION,
    NO_MATCHING_MCP_TURN,
    correlate_and_attach,
)
from belay.interop.export import (
    VERDICT_ATTRIBUTE_PREFIX,
    VERDICT_EVENT_NAME,
    build_enriched_document,
    dumps,
)
from belay.interop.otlp import Span, parse_otlp
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict

FIXTURES = Path(__file__).parent / "fixtures" / "interop"
SPANS_OK = json.loads((FIXTURES / "spans_ok.json").read_text())

# The exact ids TRACE_CONTEXT_META's traceparent carries
# ("00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01") — the canonical
# fixture ids shared by test_interop_attach.py / test_interop_otlp.py.
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
SPAN_ID = "00f067aa0ba902b7"

UNUSED_SERVER = ["unused-server"]
UNUSED_MANIFEST_DIR = "/nonexistent"


def _span(trace_id: str, span_id: str, name: str = "mcp.tools/call") -> Span:
    return Span(
        trace_id=trace_id,
        span_id=span_id,
        name=name,
        start_time_unix_nano=1700000000000000000,
        attributes={},
    )


def _otlp_span(
    trace_id: str, span_id: str, name: str = "mcp.tools/call",
    start: str = "1700000000000000000",
) -> dict:
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": start,
    }


def _doc(spans: list[dict]) -> dict:
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def _never_call(*a, **k):  # pragma: no cover - only reached if the seam is misused
    raise AssertionError("verify_turn must not be called for an uncovered span")


def _exported_spans(document: dict) -> list[dict]:
    """The raw span dicts of an exported document, in document order."""
    out: list[dict] = []
    for resource_span in document["resourceSpans"]:
        for scope_span in resource_span.get("scopeSpans") or []:
            out.extend(scope_span.get("spans") or [])
    return out


#: A known FAIL verdict, built directly (frozen dataclass, keyword args) exactly as
#: test_interop_attach.py builds its stubs — the export must carry it verbatim.
_DIVERGED_VERDICT = TurnVerdict(
    turn_index=0,
    tool_name="echo",
    status=Status.FAIL,
    sub_verdicts=[
        Verdict(
            "A2", "result", Status.FAIL,
            observed=None, expected=None,
            message="the replayed reply diverged from the recorded reply",
        )
    ],
    cause=None,
)


def _stub_verify(*a, **k):
    return _DIVERGED_VERDICT


# --- AC1: the round-trip — status + axis survive into a re-parsed collector doc -----


def test_ac1_round_trip_status_and_axis_intact(tmp_path):
    """The exported document re-parses with `parse_otlp`; the span carries the source
    verdict's reduced status and worst axis (`CAPABILITY_ROADMAP.md:839`)."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )
    exported = build_enriched_document(doc, spans, results)

    [span] = parse_otlp(json.dumps(exported))
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "FAIL"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.axis"] == "A2"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index"] == 0
    assert span.name == "mcp.tools/call"

    [raw] = _exported_spans(exported)
    [event] = raw["events"]
    assert event["name"] == VERDICT_EVENT_NAME
    assert event["timeUnixNano"] == "1700000000000000000"


# --- AC2: a non-replayable ingested span exports UNVERIFIED, never PASS -------------


def test_ac2_unmatched_span_exports_unverified_never_pass(tmp_path):
    """No recorded turn carries this span's ids -> UNVERIFIED, `no-matching-mcp-turn`,
    no fabricated turn_index/axis/sub_verdicts — and never PASS."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span("f" * 32, "f" * 16)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_never_call,
    )
    exported = build_enriched_document(doc, spans, results)

    [span] = parse_otlp(json.dumps(exported))
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "UNVERIFIED"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] != "PASS"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.cause"] == NO_MATCHING_MCP_TURN
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index" not in span.attributes
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.axis" not in span.attributes
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.sub_verdicts" not in span.attributes


def test_ac2_ambiguous_span_exports_unverified_never_pass(tmp_path):
    """A re-used span id across two turns -> UNVERIFIED, `ambiguous-correlation`;
    `verify_turn` is never even reached."""
    records = trace_of(
        tmp_path,
        [("c2s", TRACE_CONTEXT_META), ("c2s", TRACE_CONTEXT_META)],
    )
    spans = [_span(TRACE_ID, SPAN_ID)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_never_call,
    )
    exported = build_enriched_document(doc, spans, results)

    [span] = parse_otlp(json.dumps(exported))
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "UNVERIFIED"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] != "PASS"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.cause"] == AMBIGUOUS_CORRELATION
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index" not in span.attributes


# --- AC3: the coverage line survives the round-trip --------------------------------


def test_ac3_coverage_line_survives(tmp_path):
    """A `NOT_COVERED` sub-verdict (a tool's `openWorldHint: false` network promise)
    exports as `belay.verdict.coverage`; a verdict without one exports NO coverage key
    — a PASS rendered without its coverage line is the failure mode this status exists
    to prevent."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID)])

    covered = TurnVerdict(
        turn_index=0, tool_name="echo", status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "result", Status.PASS, observed="ok", expected="ok",
                    message="the reply reproduced"),
            Verdict("A2", "effect:network", Status.NOT_COVERED, observed=None,
                    expected=None,
                    message="the tool declares openWorldHint: false and Belay has no "
                            "network instrument"),
        ],
        cause=None,
    )
    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=lambda *a, **k: covered,
    )
    exported = build_enriched_document(doc, spans, results)

    [span] = parse_otlp(json.dumps(exported))
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "PASS"
    assert span.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.coverage"] == '["effect:network"]'

    clean = TurnVerdict(
        turn_index=0, tool_name="echo", status=Status.PASS,
        sub_verdicts=[
            Verdict("A2", "result", Status.PASS, observed="ok", expected="ok",
                    message="the reply reproduced"),
        ],
        cause=None,
    )
    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=lambda *a, **k: clean,
    )
    exported = build_enriched_document(doc, spans, results)

    [span] = parse_otlp(json.dumps(exported))
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.coverage" not in span.attributes


# --- AC4: absent-never-zero — no cause key (never ""), no empty sub_verdicts key ----


def test_ac4_absent_never_zero(tmp_path):
    """A matched verdict with no cause exports NO `belay.verdict.cause` key (never
    `""`); an uncovered span exports NO `belay.verdict.sub_verdicts` key."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("f" * 32, "f" * 16)])

    pass_verdict = TurnVerdict(
        turn_index=0, tool_name="echo", status=Status.PASS, sub_verdicts=[], cause=None
    )
    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=lambda *a, **k: pass_verdict,
    )
    exported = build_enriched_document(doc, spans, results)

    [matched, uncovered] = parse_otlp(json.dumps(exported))
    assert matched.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "PASS"
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.cause" not in matched.attributes
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.cause" != ""
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.sub_verdicts" not in uncovered.attributes
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.axis" not in uncovered.attributes


# --- AC5: purity + determinism ------------------------------------------------------


def test_ac5_inputs_unmutated(tmp_path):
    """The export deep-copies the document and never mutates any input: the document,
    the parsed spans and the correlation results all deep-equal after the call."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("f" * 32, "f" * 16)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )
    doc_before = copy.deepcopy(doc)
    spans_before = copy.deepcopy(spans)
    results_before = copy.deepcopy(results)

    build_enriched_document(doc, spans, results)

    assert doc == doc_before
    assert spans == spans_before
    assert results == results_before


def test_ac5_two_runs_byte_identical(tmp_path):
    """Identical inputs -> byte-identical documents (the serializer is
    `sort_keys=True, indent=2` + trailing newline)."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("f" * 32, "f" * 16)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )

    first = build_enriched_document(doc, spans, results)
    second = build_enriched_document(doc, spans, results)

    assert dumps(first) == dumps(second)


# --- AC8: document-order pairing — shared span ids, loud length mismatch ------------


def test_ac8_shared_span_id_across_traces_gets_its_own_verdict(tmp_path):
    """Two spans sharing a `span_id` across different `trace_id`s: the one that names
    a recorded turn gets its verdict, the other gets UNVERIFIED — no cross-talk."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("a" * 32, SPAN_ID)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("a" * 32, SPAN_ID)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )
    exported = build_enriched_document(doc, spans, results)

    [matched, unmatched] = parse_otlp(json.dumps(exported))
    assert matched.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "FAIL"
    assert matched.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index"] == 0
    assert unmatched.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.status"] == "UNVERIFIED"
    assert unmatched.attributes[f"{VERDICT_ATTRIBUTE_PREFIX}.cause"] == NO_MATCHING_MCP_TURN
    assert f"{VERDICT_ATTRIBUTE_PREFIX}.turn_index" not in unmatched.attributes


def test_ac8_length_mismatch_is_loud(tmp_path):
    """`results` truncated by one -> a `ValueError` naming the pairing, never a silent
    partial zip."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("f" * 32, "f" * 16)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )[:1]

    with pytest.raises(ValueError) as exc:
        build_enriched_document(doc, spans, results)
    message = str(exc.value)
    assert "spans" in message and "results" in message


# --- AC7: every ingested span is marked — no span is exported bare ------------------


def test_ac7_no_span_exported_bare(tmp_path):
    """Every span in the exported document carries `belay.verdict.status` — matched
    and uncovered alike."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    spans = [_span(TRACE_ID, SPAN_ID), _span("f" * 32, "f" * 16)]
    doc = _doc([_otlp_span(TRACE_ID, SPAN_ID), _otlp_span("f" * 32, "f" * 16)])

    results = correlate_and_attach(
        records, spans,
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )
    exported = build_enriched_document(doc, spans, results)

    for span in parse_otlp(json.dumps(exported)):
        status = span.attributes.get(f"{VERDICT_ATTRIBUTE_PREFIX}.status")
        assert status in {"PASS", "WARN", "FAIL", "UNVERIFIED"}, status