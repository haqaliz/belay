"""Task 3 — attach the replayed verdict; uncovered/ambiguous -> UNVERIFIED, never PASS.

This is where correlation (Task 2) meets the verdict engine (`belay.verify.turn`). C9
computes NO verdict of its own: a `Matched` span's turn is handed, unchanged, to
`verify_turn`, and whatever it returns is attached verbatim (AC5 — the proof this
capability changes no verdict). An `Unmatched`/`Ambiguous` span never reaches
`verify_turn` at all — it is UNVERIFIED with a named cause, structurally, not by
some code path that happens to compute the same thing.

Most tests here inject `verify=` with a stub/spy so the correlation/attach LOGIC is
exercised without a real sandboxed replay. Exactly one test (`test_ac5_...`) calls
the REAL `verify_turn` end-to-end, over a real snapshot + a real conforming server,
and asserts the attached verdict is byte-identical (dataclass-equal) to what a direct
`verify_turn` call on the same fixture returns — the actual proof of AC5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from conftest import trace_of
from fixtures.connection_frames import TRACE_CONTEXT_META

from belay.interop.attach import (
    AMBIGUOUS_CORRELATION,
    NO_MATCHING_MCP_TURN,
    UNRESTORABLE_PRE_STATE,
    CorrelatedSpan,
    correlate_and_attach,
)
from belay.interop.otlp import Span
from belay.replay.persist import persist_snapshot
from belay.snapshot.substrate import present_handle, take_snapshot
from belay.trace import TraceWriter
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

FIXTURES = Path(__file__).parent / "fixtures"
CONFORMING_SERVER = [sys.executable, str(FIXTURES / "conforming_server.py")]

# The exact ids TRACE_CONTEXT_META's traceparent carries
# ("00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01") — Task 1/2's own
# canonical fixture ids.
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


def _never_call(*a, **k):  # pragma: no cover - only reached if the seam is misused
    raise AssertionError("verify_turn must not be called for an uncovered span")


# --- AC2: unmatched span -> UNVERIFIED, cause no-matching-mcp-turn, never PASS -------


def test_ac2_unmatched_span_is_unverified_with_named_cause(tmp_path):
    """No recorded turn carries this span's ids -> UNVERIFIED, `no-matching-mcp-turn`.

    `verify_turn` must never even be invoked for an unmatched span — the seam is a
    spy that raises if called.
    """
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    span = _span("f" * 32, "f" * 16)  # matches nothing in the trace

    [result] = correlate_and_attach(
        records, [span],
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_never_call,
    )

    assert isinstance(result, CorrelatedSpan)
    assert result.turn_index is None
    assert result.verdict is None
    assert result.cause == NO_MATCHING_MCP_TURN
    assert result.status is Status.UNVERIFIED
    assert result.status != Status.PASS


# --- AC4-attach: ambiguous span -> UNVERIFIED, cause ambiguous-correlation, no call --


def test_ac4_ambiguous_span_is_unverified_and_verify_turn_is_never_called(tmp_path):
    """A re-used span id across two turns -> UNVERIFIED, `ambiguous-correlation`.

    Picking either turn would be an attach-by-guess — the exact failure this
    capability exists to prevent. The spy asserts `verify_turn` is never reached.
    """
    records = trace_of(
        tmp_path,
        [("c2s", TRACE_CONTEXT_META), ("c2s", TRACE_CONTEXT_META)],
    )
    span = _span(TRACE_ID, SPAN_ID)

    [result] = correlate_and_attach(
        records, [span],
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_never_call,
    )

    assert result.turn_index is None
    assert result.verdict is None
    assert result.cause == AMBIGUOUS_CORRELATION
    assert result.status is Status.UNVERIFIED
    assert result.status != Status.PASS


# --- AC3: matched turn, pre-state unrestorable -> UNVERIFIED, unrestorable-pre-state -


def test_ac3_matched_turn_with_unrestorable_pre_state(tmp_path):
    """A matched span whose turn's `verify_turn` came back UNVERIFIED (non-replayed,
    e.g. the pre-state could not be restored) -> the CorrelatedSpan's cause is the
    named `unrestorable-pre-state`, derived from the TurnVerdict's own cause — never
    a hand-built PASS.
    """
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    span = _span(TRACE_ID, SPAN_ID)

    stub_verdict = TurnVerdict(
        turn_index=0,
        tool_name="echo",
        status=Status.UNVERIFIED,
        sub_verdicts=[
            Verdict(
                "A2", "replay", Status.UNVERIFIED,
                observed=None, expected=None,
                message="turn UNVERIFIED: the pre-state could not be restored",
            )
        ],
        cause="UNRESTORABLE_FIFO",
    )

    def _stub_verify(records_arg, n, **kwargs):
        assert n == 0
        return stub_verdict

    [result] = correlate_and_attach(
        records, [span],
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )

    assert result.turn_index == 0
    assert result.verdict is stub_verdict
    assert result.cause == UNRESTORABLE_PRE_STATE
    assert result.status is Status.UNVERIFIED
    assert result.status != Status.PASS


# --- A matched, REPLAYED, clean turn attaches its verdict with no bespoke cause ------


def test_matched_replayed_pass_turn_has_no_bespoke_cause(tmp_path):
    """A matched span whose turn actually replayed cleanly (PASS) attaches the
    TurnVerdict as-is, with `cause=None` on the CorrelatedSpan — the TurnVerdict's own
    sub_verdicts already explain a REPLAYED turn; Task 3 invents no cause for it.
    """
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    span = _span(TRACE_ID, SPAN_ID)

    stub_verdict = TurnVerdict(
        turn_index=0, tool_name="echo", status=Status.PASS, sub_verdicts=[], cause=None
    )

    def _stub_verify(records_arg, n, **kwargs):
        return stub_verdict

    [result] = correlate_and_attach(
        records, [span],
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_stub_verify,
    )

    assert result.verdict is stub_verdict
    assert result.cause is None
    assert result.status is Status.PASS


# --- No-false-PASS property: every uncovered case is never Status.PASS --------------


def test_no_false_pass_property_over_every_uncovered_case(tmp_path):
    """Mirrors the spirit of tests/test_verdict.py: for every span this module could
    not confidently attach a real verdict to (Unmatched or Ambiguous), the resulting
    status must never be Status.PASS.
    """
    records = trace_of(
        tmp_path,
        [("c2s", TRACE_CONTEXT_META), ("c2s", TRACE_CONTEXT_META)],  # -> ambiguous
    )
    unmatched_span = _span("a" * 32, "b" * 16)
    ambiguous_span = _span(TRACE_ID, SPAN_ID)

    results = correlate_and_attach(
        records, [unmatched_span, ambiguous_span],
        server_command=UNUSED_SERVER, manifest_dir=UNUSED_MANIFEST_DIR,
        verify=_never_call,
    )

    assert len(results) == 2
    for result in results:
        assert result.turn_index is None
        assert result.status is not Status.PASS
        assert result.status is Status.UNVERIFIED


# --- Structural guard: attach.py never spells Status.PASS -----------------------------


def test_attach_module_never_hand_constructs_a_pass_status():
    """No code path in attach.py may assign `Status.PASS` to a span that was not
    matched-and-replayed; the only PASS a CorrelatedSpan can ever carry comes from a
    real `TurnVerdict` returned by `verify_turn` (or its injected stand-in).
    """
    import belay.interop.attach as attach_module

    source = Path(attach_module.__file__).read_text(encoding="utf-8")
    assert "Status.PASS" not in source, (
        "attach.py must never hand-construct Status.PASS; it only forwards a "
        "TurnVerdict's own status"
    )


# --- AC5: the real, end-to-end proof — byte-identical to a direct verify_turn call ---
#
# Only THIS test needs the real sandbox — it is marked individually rather than via a
# module-level `pytestmark`, which would (wrongly) skip every stub-based test above too.

_REQUIRES_SEATBELT = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="replay re-invokes inside the macOS Seatbelt sandbox",
)


def _tools_list_frames() -> list[tuple]:
    """`echo` declared readOnlyHint:true — the contract effect-conformance grounds on.

    Annotations are read from the RECORDED tools/list reply, never re-queried from the
    live server, so this can declare a contract independent of what conforming_server.py
    itself would say if asked.
    """
    req = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).encode()
    resp = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "echo", "annotations": {"readOnlyHint": True}}]},
        }
    ).encode()
    return [("c2s", req, None), ("s2c", resp, None)]


def _echo_call_with_traceparent() -> bytes:
    """A real `tools/call` for `echo`, carrying TRACE_CONTEXT_META's exact traceparent
    in `_meta`, so the span built from those same ids correlates to this turn.
    """
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "echo",
                "arguments": {"s": "hi"},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "traceparent": f"00-{TRACE_ID}-{SPAN_ID}-01",
                },
            },
        }
    ).encode()


def _echo_reply() -> bytes:
    """What `conforming_server.py`'s `echo` tool actually replies with `arguments.s`."""
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "result": {"content": [{"type": "text", "text": "hi"}], "isError": False},
        }
    ).encode()


def _snapshot_handle(tmp_path: Path, manifest_dir: Path):
    """A real, restorable snapshot of an empty workspace — the turn's pre-state."""
    work = tmp_path / "work"
    work.mkdir()
    (work / "keep.txt").write_text("untouched\n", encoding="utf-8")
    snap = take_snapshot(work, tmp_path / "snap")
    persist_snapshot(snap, manifest_dir / f"{snap.manifest.handle}.json")
    return present_handle(snap)


def _real_trace_and_manifest(tmp_path: Path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    handle = _snapshot_handle(tmp_path, manifest_dir)

    trace_dir = tmp_path / "trace"
    writer = TraceWriter.in_directory(trace_dir)
    try:
        for direction, raw, state_handle in _tools_list_frames() + [
            ("c2s", _echo_call_with_traceparent(), handle),
            ("s2c", _echo_reply(), None),
        ]:
            if state_handle is not None:
                writer.set_state_handle(state_handle, frame=raw)
            writer.observer(direction)(raw, False)
    finally:
        writer.close()

    trace_path = sorted(trace_dir.glob("*.jsonl"))[0]
    records = [json.loads(line) for line in trace_path.read_bytes().split(b"\n") if line]
    return records, manifest_dir


@_REQUIRES_SEATBELT
def test_ac5_matched_replayable_turn_attaches_the_byte_identical_turnverdict(tmp_path):
    """The load-bearing proof: over a REAL trace + REAL snapshot + REAL server, the
    CorrelatedSpan's verdict for the matched span equals — field for field — what a
    direct `verify_turn(records, 0, ...)` call returns on the exact same fixture. C9
    changes no verdict; it only routes one to the right span.
    """
    records, manifest_dir = _real_trace_and_manifest(tmp_path)
    span = _span(TRACE_ID, SPAN_ID)

    direct = verify_turn(records, 0, server_command=CONFORMING_SERVER, manifest_dir=manifest_dir)

    [result] = correlate_and_attach(
        records, [span],
        server_command=CONFORMING_SERVER, manifest_dir=manifest_dir,
    )

    assert result.turn_index == 0
    assert result.verdict == direct
    assert result.status == direct.status
    # Non-vacuity: this really replayed and really produced a verdict, not a stub.
    assert direct.status is Status.PASS, direct
    assert direct.tool_name == "echo", direct
