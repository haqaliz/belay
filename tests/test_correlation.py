"""Correlation: which response answered which request, and what could not be indexed.

A derived index over frames the trace already holds. It never mutates a frame
record and never decides whether anything was good, bad or allowed — it records
which bytes answered which other bytes, and names what it could not tell.

Two properties carry the weight here. **The id spaces are separate**: client- and
server-originated ids are different namespaces that both legitimately start at 1,
so the key is `(direction, id)` and never the bare id. **A gap is named**: a
frame that could not be indexed is recorded with a cause, because "no entry" and
"we could not read it" are different facts, and a reader that cannot tell them
apart will eventually report the second as the first.
"""

from __future__ import annotations

from pathlib import Path

from conftest import run_traced, trace_of

from belay.index import classify, derive_correlation, tool_calls

DUPLEX_FIXTURE = Path(__file__).parent / "fixtures" / "duplex_server.py"


def entry(records: list[dict], origin: str, id_: object) -> dict:
    matches = [r for r in records if r["origin"] == origin and r["id"] == id_]
    assert len(matches) == 1, f"expected exactly one entry for ({origin}, {id_}): {matches!r}"
    return matches[0]


def seq_of_frame(records: list[dict], predicate) -> int:
    import base64

    for record in records:
        if record["kind"] == "frame" and predicate(base64.b64decode(record["raw"])):
            return record["seq"]
    raise AssertionError("no frame matched")


def test_client_id_1_and_server_id_1_do_not_cross_wire(tmp_path):
    """The headline: two `id:1`s in one session mean two different things."""
    records = run_traced(tmp_path, "t", server=DUPLEX_FIXTURE)
    index = derive_correlation(records)

    initialize_result = seq_of_frame(records, lambda raw: b'"serverInfo"' in raw)
    sampling = seq_of_frame(records, lambda raw: b"sampling/createMessage" in raw)

    # The client's initialize (c2s id 1) was answered by the initialize result.
    client_entry = entry(index, "c2s", 1)
    assert client_entry["method"] == "initialize"
    assert client_entry["status"] == "answered"
    assert client_entry["response_seq"] == initialize_result

    # The server's sampling request (s2c id 1) is a DIFFERENT entry, and the
    # initialize result did not answer it.
    server_entry = entry(index, "s2c", 1)
    assert server_entry["method"] == "sampling/createMessage"
    assert server_entry["request_seq"] == sampling
    assert server_entry["response_seq"] != initialize_result


def test_a_request_that_never_gets_a_response_is_recorded_as_unanswered(tmp_path):
    """Legal, not an error: cancellation is racy by design."""
    records = run_traced(tmp_path, "t", server=DUPLEX_FIXTURE)
    index = derive_correlation(records)

    unanswered = entry(index, "s2c", 1)
    assert unanswered["status"] == "unanswered"
    assert unanswered["response_seq"] is None

    # Nothing leaked: the entry exists rather than being dropped for lacking a
    # partner, and the derivation returned rather than waiting for one.
    assert unanswered["method"] == "sampling/createMessage"


def test_a_response_carrying_method_is_still_classified_as_a_response(tmp_path):
    """The fixture's non-conforming frame: a response that carries `method`.

    JSON-RPC forbids it, third parties emit it anyway. Classifying on the
    presence of `method` would file this as a request and lose the reply to
    `tools/call` — so classification is structural: `result`/`error` decides.
    """
    records = run_traced(tmp_path, "t")
    index = derive_correlation(records)

    assert classify({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "result": {}}) == "response"

    call = entry(index, "c2s", 3)
    assert call["method"] == "tools/call"
    assert call["status"] == "answered"
    assert call["response_seq"] == seq_of_frame(records, lambda raw: b'"belayFuture"' in raw and b'"result"' in raw)


def test_classification_is_structural():
    assert classify({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) == "request"
    assert classify({"jsonrpc": "2.0", "method": "notifications/initialized"}) == "notification"
    assert classify({"jsonrpc": "2.0", "id": 1, "result": {}}) == "response"
    assert classify({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "x"}}) == "response"
    # Neither shape: a batch array, or junk. Not guessed at.
    assert classify({"jsonrpc": "2.0"}) == "unknown"


def test_tools_call_is_a_filter_over_correlation_not_its_own_capture(tmp_path):
    records = run_traced(tmp_path, "t")
    calls = tool_calls(derive_correlation(records))

    assert [c["id"] for c in calls] == [3]
    assert calls[0]["method"] == "tools/call"


def test_a_truncated_frame_is_an_index_gap_with_a_named_cause(tmp_path):
    """Forwarded whole, observed short: it may index incompletely, and says so.

    Not indexed as absent, which is the tempting shortcut: a request we could
    not read is not a request that was not made.
    """
    records = trace_of(tmp_path, [("c2s", b'{"jsonrpc":"2.0","id":1,"method":"tools/li', True)])
    index = derive_correlation(records)

    (gap,) = [r for r in index if r["kind"] == "index_gap"]
    assert gap["seq"] == seq_of_frame(records, lambda raw: b"tools/li" in raw)
    assert gap["dir"] == "c2s"
    assert "truncated" in gap["cause"]


def test_an_unparseable_frame_is_an_index_gap_with_a_named_cause(tmp_path):
    records = trace_of(tmp_path, [("s2c", b"not json at all")])
    index = derive_correlation(records)

    (gap,) = [r for r in index if r["kind"] == "index_gap"]
    assert gap["seq"] == seq_of_frame(records, lambda raw: raw == b"not json at all")
    assert gap["cause"]


def test_a_response_with_no_request_is_recorded_as_such(tmp_path):
    """The proxy can attach mid-session; the reply's request predates capture."""
    records = trace_of(tmp_path, [("s2c", b'{"jsonrpc":"2.0","id":7,"result":{}}')])
    index = derive_correlation(records)

    (orphan,) = [r for r in index if r["kind"] == "correlation"]
    assert orphan["status"] == "response-without-request"
    assert orphan["request_seq"] is None


def test_a_second_response_to_one_id_does_not_overwrite_the_first(tmp_path):
    """One request, two replies: non-conforming, and both really arrived.

    The tempting shape is a table where the response overwrites a slot, which
    quietly discards whichever reply came second and leaves a trace asserting
    something that did not happen. Belay does not model a request as owning
    exactly one response — see the MRTR note in `belay.index`.
    """
    records = trace_of(
        tmp_path,
        [
            ("c2s", b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"a"}}'),
            ("s2c", b'{"jsonrpc":"2.0","id":1,"result":{"first":true}}'),
            ("s2c", b'{"jsonrpc":"2.0","id":1,"result":{"second":true}}'),
        ],
    )
    index = derive_correlation(records)

    # Two entries for one (direction, id) here, deliberately - so this is the
    # one place `entry`'s uniqueness assertion does not apply.
    (first,) = [r for r in index if r["status"] == "answered"]
    assert first["request_seq"] is not None
    assert first["response_seq"] == seq_of_frame(records, lambda raw: b'"first"' in raw)

    # The second reply is its own recorded fact, not an edit to the first.
    (extra,) = [r for r in index if r.get("status") == "duplicate-response"]
    assert extra["response_seq"] == seq_of_frame(records, lambda raw: b'"second"' in raw)
    assert extra["id"] == 1


def test_ids_of_different_types_are_different_ids(tmp_path):
    """`1` and `"1"` are distinct JSON-RPC ids, and `true` is not `1`."""
    records = trace_of(
        tmp_path,
        [
            ("c2s", b'{"jsonrpc":"2.0","id":1,"method":"a"}'),
            ("c2s", b'{"jsonrpc":"2.0","id":"1","method":"b"}'),
            ("s2c", b'{"jsonrpc":"2.0","id":"1","result":{}}'),
        ],
    )
    index = derive_correlation(records)

    assert entry(index, "c2s", 1)["status"] == "unanswered"
    assert entry(index, "c2s", "1")["status"] == "answered"
