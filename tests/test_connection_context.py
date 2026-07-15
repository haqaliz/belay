"""Connection context, resolved per frame and never guessed.

Called *connection*, not *session*, because the 2026-07-28 revision says a
session is not a thing that exists: *"an open connection, such as a STDIO
process, is not a conversation or session... a server must not treat connection
or process identity as a proxy for conversation or session continuity."*

Belay records the resolved protocol version and client identity **on every
frame**, rather than writing one header and pointing at it. That looks like
redundancy and is not: the same revision deletes the thing a pointer would point
at. It removes the `initialize`/`initialized` handshake (SEP-2575) and the
protocol-level session (SEP-2567), and moves version and client identity into
`_meta` on every request. A trace whose context lived in a header would go blank
the day a client updates; per-frame resolution costs nothing and reads both
worlds.

Order: the handshake if one was captured, else per-request `_meta`, else
**unknown with a named cause**. Never a guess, and never the last value we
happened to see applied to a frame that predates it.
"""

from __future__ import annotations

from conftest import CLIENT_LINES, FIXTURE, run_traced, trace_of
from fixtures.connection_frames import (
    META_REQUEST,
    NO_META_AT_ALL,
    RESPONSE_TO_META_CALL,
    TRACE_CONTEXT_META,
    UNRECOGNISED_META,
)

from belay.connection import derive_connection_context


def context(records: list[dict]) -> dict[int, dict]:
    return {
        r["seq"]: r
        for r in derive_connection_context(records)
        if r["kind"] == "connection_context"
    }


def seq_of_frame(records: list[dict], needle: bytes) -> int:
    import base64

    for record in records:
        if record["kind"] == "frame" and needle in base64.b64decode(record["raw"]):
            return record["seq"]
    raise AssertionError(f"no frame contained {needle!r}")


def test_context_resolves_from_the_handshake_when_there_is_one(tmp_path):
    """The <=2025-11-25 world, end to end through the real proxy and fixture.

    Asserted on the reply to `tools/call`, not the request: the scripted client
    pipelines all four lines without waiting, so in capture order its
    `tools/call` REQUEST really does precede the server's initialize response.
    Nothing was negotiated yet at that point, and the frame that follows the
    negotiation is the one the handshake can honestly speak for.
    """
    records = run_traced(tmp_path, "t", server=FIXTURE)
    by_seq = context(records)

    reply = by_seq[seq_of_frame(records, b'"isError"')]

    assert reply["protocol_version"]["status"] == "resolved"
    assert reply["protocol_version"]["value"] == "2025-11-25"
    assert reply["protocol_version"]["source"] == "handshake"
    assert reply["client"]["value"] == {"name": "t", "version": "1"}


def test_the_negotiated_version_is_not_applied_to_frames_that_predate_it(tmp_path):
    """Before the server has answered, nothing has been negotiated.

    Stamping the eventual version onto the frames that came before it would be
    the cheap kind of lie: locally harmless, and it makes the trace unable to
    say when the contract actually took effect.
    """
    records = run_traced(tmp_path, "t", server=FIXTURE)
    by_seq = context(records)

    initialize_request = by_seq[seq_of_frame(records, b'"initialize"')]

    assert initialize_request["protocol_version"]["status"] == "unknown"
    assert initialize_request["protocol_version"]["cause"]
    # The client's own identity, though, IS declared on that very frame.
    assert initialize_request["client"]["value"] == {"name": "t", "version": "1"}


def test_context_resolves_from_per_request_meta_when_no_handshake_exists(tmp_path):
    """The 2026-07-28 world: no handshake to find, context on the request itself."""
    records = trace_of(tmp_path, [("c2s", META_REQUEST)])
    call = context(records)[seq_of_frame(records, b"io.modelcontextprotocol")]

    assert call["protocol_version"]["status"] == "resolved"
    assert call["protocol_version"]["value"] == "2026-07-28"
    assert call["protocol_version"]["source"] == "request_meta"
    assert call["client"]["value"] == {"name": "future-client", "version": "9"}

    # The key that actually matched is recorded, so a reader never has to
    # reverse-engineer which spelling arrived.
    assert call["protocol_version"]["source_key"] == "io.modelcontextprotocol/protocolVersion"


def test_a_response_inherits_the_context_of_the_request_it_answers(tmp_path):
    """Responses carry no `_meta` and no handshake to fall back on."""
    records = trace_of(tmp_path, [("c2s", META_REQUEST), ("s2c", RESPONSE_TO_META_CALL)])
    response = context(records)[seq_of_frame(records, b'"result"')]

    assert response["protocol_version"]["value"] == "2026-07-28"
    assert response["protocol_version"]["source"] == "request_meta"


def test_unrecognised_meta_names_the_keys_it_actually_carried(tmp_path):
    """The safety net for a wrong guess about `_meta`'s key names.

    If neither spelling Belay knows is the real one, this is what the trace says
    — and it says it loudly, with evidence, instead of resolving to nothing and
    looking like a client that declared nothing.
    """
    records = trace_of(tmp_path, [("c2s", UNRECOGNISED_META)])
    call = context(records)[seq_of_frame(records, b"com.example")]

    assert call["protocol_version"]["status"] == "unknown"
    assert "com.example/some-other-key" in call["protocol_version"]["cause"]


def test_no_handshake_and_no_meta_is_unknown_with_a_cause(tmp_path):
    records = trace_of(tmp_path, [("c2s", NO_META_AT_ALL)])
    call = context(records)[seq_of_frame(records, b'"tools/call"')]

    assert call["protocol_version"]["status"] == "unknown"
    assert call["protocol_version"]["cause"]
    assert call["client"]["status"] == "unknown"
    # Never invented, and never the version Belay happens to have been built for.
    assert "value" not in call["protocol_version"]


def test_w3c_trace_context_is_recorded_as_a_fact(tmp_path):
    """Recorded verbatim, interpreted not at all.

    `traceparent`/`tracestate`/`baggage` are reserved in `_meta` as an explicit
    exception to the prefix rule, for OpenTelemetry propagation. They matter to
    the OTel bridge later; C1's whole job here is to not lose them.
    """
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    (fact,) = [r for r in derive_connection_context(records) if r["kind"] == "trace_context"]

    assert fact["traceparent"] == "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"
    assert fact["tracestate"] == "vendor=opaque"
    assert fact["baggage"] == "key=value"
    assert fact["seq"] == seq_of_frame(records, b"traceparent")


def test_no_trace_context_record_when_there_is_none(tmp_path):
    """The counterpart: an empty record for every frame would be noise, not a fact."""
    records = trace_of(tmp_path, [("c2s", META_REQUEST)])

    assert [r for r in derive_connection_context(records) if r["kind"] == "trace_context"] == []


def test_trace_context_does_not_disturb_connection_context(tmp_path):
    """The reserved keys sit alongside the required ones and neither shadows the other."""
    records = trace_of(tmp_path, [("c2s", TRACE_CONTEXT_META)])
    by_seq = context(records)

    call = by_seq[seq_of_frame(records, b"traceparent")]
    assert call["protocol_version"]["value"] == "2026-07-28"


def test_every_frame_gets_its_own_context_not_a_pointer(tmp_path):
    records = run_traced(tmp_path, "t", server=FIXTURE)
    frames = [r for r in records if r["kind"] == "frame"]

    assert len(context(records)) == len(frames)
    # Four client lines, and the fixture's four s2c frames: three replies plus
    # the unsolicited notification it interleaves before the last one.
    assert len(frames) == len(CLIENT_LINES) + 4
