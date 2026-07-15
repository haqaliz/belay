"""Errors: two different failures that must never be conflated.

A **protocol error** (a JSON-RPC `error` member, no `result`) says the call did
not happen. A **tool execution error** (a successful envelope carrying a
`result` whose payload says `isError: true`) says the call happened and the tool
reported failure inside it. Same word, different events, different replay.

The line between them moved once already — SEP-1303 in the 2025-11-25 revision
reclassified input-validation failures from the first to the second — so a
trace that recorded a single collapsed "it errored" would be unreadable across
revisions. Hence: record raw, derive the classification, never conflate.

`isError` absent is **not-declared**, not `false`. The spec assumes false; an
assumption is not a declaration, and this is the same discipline as the tool
annotations for the same reason.
"""

from __future__ import annotations

import json

from conftest import FIXTURE, run_traced, trace_of
from fixtures.error_frames import (
    EXECUTION_ERROR,
    ISERROR_ABSENT,
    ISERROR_NULL,
    MALFORMED,
    PROTOCOL_ERROR,
    REQUESTS,
    RESULT_TYPE_COMPLETE,
    RESULT_TYPE_INPUT_REQUIRED,
    STRUCTURED_DUPLICATED,
    STRUCTURED_NOT_DUPLICATED,
)

from belay.errors import derive_error_classification


def exchange(*responses: bytes) -> list[tuple]:
    """Pair each canned response with the request whose id it answers."""
    frames = []
    for response in responses:
        frames.append(("c2s", REQUESTS[json.loads(response)["id"]]))
        frames.append(("s2c", response))
    return frames


def classified(tmp_path, *responses: bytes) -> list[dict]:
    records = trace_of(tmp_path, exchange(*responses))
    return [
        r for r in derive_error_classification(records) if r["kind"] == "error_classification"
    ]


def test_a_protocol_error_and_an_execution_error_are_distinguishable(tmp_path):
    """The headline for this part: both are 'an error', and they are not the same."""
    protocol, execution = classified(tmp_path, PROTOCOL_ERROR, EXECUTION_ERROR)

    # The call never happened: no result to speak of.
    assert protocol["protocol_error"]["status"] == "present"
    assert protocol["protocol_error"]["code"] == -32602
    assert protocol["result"] == "absent"
    assert protocol["is_error"]["state"] == "not-declared"

    # The call happened and succeeded at the protocol level; the TOOL failed.
    assert execution["protocol_error"]["status"] == "absent"
    assert execution["result"] == "present"
    assert execution["is_error"]["state"] == "declared-true"


def test_is_error_absent_is_not_declared_rather_than_false(tmp_path):
    """The spec assumes false. An assumption is not a declaration."""
    (absent,) = classified(tmp_path, ISERROR_ABSENT)

    assert absent["is_error"]["state"] == "not-declared"
    assert absent["is_error"]["state"] != "declared-false"


def test_is_error_null_is_declared_but_not_as_a_boolean(tmp_path):
    (null,) = classified(tmp_path, ISERROR_NULL)

    assert null["is_error"]["state"] == "declared-non-boolean"
    assert null["is_error"]["declared_value"] is None


def test_structured_content_duplicated_as_text_is_recorded_as_duplication(tmp_path):
    """S3: servers SHOULD send it twice, so downstream must not count it twice."""
    (duplicated,) = classified(tmp_path, STRUCTURED_DUPLICATED)

    structured = duplicated["structured_content"]
    assert structured["status"] == "present"
    assert structured["also_serialised_as_text"] == [0]


def test_a_text_block_that_is_not_the_same_data_is_not_duplication(tmp_path):
    """The counterpart: 'always duplicated' would pass the test above too."""
    (distinct,) = classified(tmp_path, STRUCTURED_NOT_DUPLICATED)

    structured = distinct["structured_content"]
    assert structured["status"] == "present"
    assert structured["also_serialised_as_text"] == []


def test_no_structured_content_is_absent_not_empty(tmp_path):
    (plain,) = classified(tmp_path, ISERROR_ABSENT)
    assert plain["structured_content"]["status"] == "absent"


def test_result_type_is_recorded_when_declared(tmp_path):
    """The RC requires it on every result; Belay records what arrived."""
    complete, input_required = classified(
        tmp_path, RESULT_TYPE_COMPLETE, RESULT_TYPE_INPUT_REQUIRED
    )

    assert complete["result_type"] == {"status": "declared", "value": "complete"}
    assert input_required["result_type"] == {"status": "declared", "value": "input_required"}


def test_an_absent_result_type_is_not_declared_rather_than_complete(tmp_path):
    """Clients MUST *assume* "complete" when it is absent. An assumption is not a declaration.

    Every pre-2026-07-28 server omits this field. Materialising the assumed
    "complete" would record every one of them as having declared something none
    of them said — the same false-PASS mechanism as the annotation defaults, in a
    field that says whether the call even finished.
    """
    (absent,) = classified(tmp_path, ISERROR_ABSENT)

    assert absent["result_type"] == {"status": "not-declared"}
    assert "value" not in absent["result_type"]
    assert "complete" not in json.dumps(absent["result_type"])


def test_a_malformed_frame_is_a_named_cause_never_a_dropped_turn(tmp_path):
    records = trace_of(tmp_path, exchange(EXECUTION_ERROR) + [("s2c", MALFORMED)])
    derived = derive_error_classification(records)

    (gap,) = [r for r in derived if r["kind"] == "classification_gap"]
    assert gap["cause"]

    # The turn either side of it survives: the gap is a fact about one frame, not
    # the derivation giving up.
    assert [r for r in derived if r["kind"] == "error_classification"]


def test_the_real_fixtures_non_conforming_reply_end_to_end(tmp_path):
    """Grounding: `fake_server.py` really does send `"isError":null`."""
    records = run_traced(tmp_path, "t", server=FIXTURE)
    classifications = [
        r for r in derive_error_classification(records) if r["kind"] == "error_classification"
    ]

    call = [c for c in classifications if c["id"] == 3]
    assert call, "the tools/call reply was not classified"
    assert call[0]["is_error"]["state"] == "declared-non-boolean"
    assert call[0]["protocol_error"]["status"] == "absent"
