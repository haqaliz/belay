"""Tool annotations: what the server DECLARED, never what the spec would assume.

The single correctness property here is that **a default is not a declaration**.
The MCP spec gives every annotation a fail-safe default (`readOnlyHint: false`,
`destructiveHint: true`, `idempotentHint: false`, `openWorldHint: true`), and
those defaults are right for deciding how to *treat* a tool. They are wrong to
write into a trace, because they erase the difference between a server that said
"I am not read-only" and a server that said nothing at all.

That difference is load-bearing downstream: an un-annotated tool recorded as
`readOnlyHint: false` lets a check reason "it mutated, and it never claimed
read-only, therefore fine -> PASS". The tool declared nothing; the only honest
verdict is UNVERIFIED; the PASS was manufactured by a default this layer
materialised. So the trace records `declared-true` / `declared-false` /
`not-declared`, and the defaults appear nowhere in this module.
"""

from __future__ import annotations

import json

from conftest import FIXTURE, run_traced, trace_of
from fixtures.annotation_frames import (
    NOTIFICATION_LIST_CHANGED,
    TOOLS_LIST_REQUEST,
    TOOLS_LIST_REQUEST_AGAIN,
    TOOLS_LIST_RESPONSE,
    TOOLS_LIST_RESPONSE_CHANGED,
)

from belay.annotations import ANNOTATIONS, derive_annotations
from belay.index import derive_correlation

LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]


def snapshots(records: list[dict]) -> list[dict]:
    return [r for r in derive_annotations(records) if r["kind"] == "annotation_snapshot"]


def tool(snapshot: dict, name: str) -> dict:
    (found,) = [t for t in snapshot["tools"] if t["name"] == name]
    return found


def test_not_declared_is_distinguishable_from_declared_false(tmp_path):
    """The headline. `write_file` said false; `mystery` said nothing."""
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))

    declared_false = tool(snapshot, "write_file")["annotations"]["readOnlyHint"]
    not_declared = tool(snapshot, "mystery")["annotations"]["readOnlyHint"]

    assert declared_false["state"] == "declared-false"
    assert not_declared["state"] == "not-declared"
    assert declared_false["state"] != not_declared["state"]

    # And the coarser fact, kept separately: one of these tools carried no
    # `annotations` object at all, which is not the same as carrying an empty one.
    assert tool(snapshot, "write_file")["annotations_object"] == "present"
    assert tool(snapshot, "mystery")["annotations_object"] == "absent"


def test_no_spec_default_is_ever_materialised(tmp_path):
    """Not one of the four defaults may appear against a tool that declared nothing."""
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))

    mystery = tool(snapshot, "mystery")
    assert {a["state"] for a in mystery["annotations"].values()} == {"not-declared"}

    # The defaults are `readOnlyHint:false`, `destructiveHint:true`,
    # `idempotentHint:false`, `openWorldHint:true`. Serialised, an un-annotated
    # tool must contain no declaration of any of them - in either polarity, so
    # this catches materialising the default AND materialising its opposite.
    for annotation in ANNOTATIONS:
        assert mystery["annotations"][annotation]["state"] == "not-declared"
        assert "declared_value" not in mystery["annotations"][annotation]

    # Nothing anywhere in the record narrowed a not-declared annotation to a bool.
    assert "true" not in json.dumps(mystery).replace("declared-true", "")
    assert "false" not in json.dumps(mystery).replace("declared-false", "")


def test_a_declared_annotation_is_recorded_as_declared(tmp_path):
    """The counterpart: not-declared everywhere would pass the test above too."""
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))

    read_file = tool(snapshot, "read_file")
    assert read_file["annotations"]["readOnlyHint"]["state"] == "declared-true"
    # ...and declaring one annotation declares nothing about the others.
    assert read_file["annotations"]["destructiveHint"]["state"] == "not-declared"
    assert read_file["annotations"]["openWorldHint"]["state"] == "not-declared"


def test_incoherent_annotations_are_recorded_as_a_fact_not_resolved(tmp_path):
    """`readOnlyHint:true` + `destructiveHint:true`. Recorded; not adjudicated."""
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))
    contradictory = tool(snapshot, "contradictory")

    (incoherence,) = contradictory["incoherence"]
    assert incoherence["annotation"] == "destructiveHint"

    # Both declarations survive verbatim. Resolving the contradiction - dropping
    # either one, or picking a winner - would be this layer deciding what the
    # server meant, which is the next capability's job and not on this evidence.
    assert contradictory["annotations"]["readOnlyHint"]["state"] == "declared-true"
    assert contradictory["annotations"]["destructiveHint"]["state"] == "declared-true"


def test_a_coherent_tool_records_no_incoherence(tmp_path):
    """M-1: `read_file` is the case that carries this test.

    `write_file` and `mystery` both leave via `_incoherence`'s early return —
    neither declares `readOnlyHint: true`, so neither ever reaches the rule. They
    would stay green if the rule were inverted or deleted. `read_file` declares
    `readOnlyHint: true` and nothing else, which is the only input that reaches
    the comprehension and must still come back empty.
    """
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))
    assert tool(snapshot, "read_file")["incoherence"] == []
    assert tool(snapshot, "write_file")["incoherence"] == []
    assert tool(snapshot, "mystery")["incoherence"] == []


def test_a_non_boolean_declaration_is_neither_true_false_nor_undeclared(tmp_path):
    """`readOnlyHint:"yes"` was declared - just not as a boolean.

    Recording it `not-declared` would lose the declaration; recording it
    `declared-true` would invent a boolean the server never sent.
    """
    (snapshot,) = snapshots(trace_of(tmp_path, LISTING))
    sloppy = tool(snapshot, "sloppy")["annotations"]["readOnlyHint"]

    assert sloppy["state"] == "declared-non-boolean"
    assert sloppy["declared_value"] == "yes"


def test_a_resnapshot_appends_and_the_earlier_snapshot_survives(tmp_path):
    """M8: snapshots are timestamped and appended, never overwritten."""
    records = trace_of(
        tmp_path,
        LISTING
        + [
            ("s2c", NOTIFICATION_LIST_CHANGED),
            ("c2s", TOOLS_LIST_REQUEST_AGAIN),
            ("s2c", TOOLS_LIST_RESPONSE_CHANGED),
        ],
    )
    first, second = snapshots(records)

    # The earlier contract is still there, unmodified: a call made before the
    # change must be readable against the contract that was live at the time.
    assert tool(first, "read_file")["annotations"]["readOnlyHint"]["state"] == "declared-true"
    assert tool(second, "read_file")["annotations"]["readOnlyHint"]["state"] == "declared-false"

    # Each snapshot says when it was taken, so "which contract was live then?"
    # is answerable at all.
    assert first["t_snapshot"] < second["t_snapshot"]
    assert first["source_seq"] < second["source_seq"]


def test_list_changed_with_no_resnapshot_is_recorded_as_a_named_cause(tmp_path):
    """The contract is known stale and the trace says so, rather than implying currency."""
    records = trace_of(tmp_path, LISTING + [("s2c", NOTIFICATION_LIST_CHANGED)])

    (stale,) = [r for r in derive_annotations(records) if r["kind"] == "annotation_staleness"]
    assert stale["cause"]
    assert "list_changed" in stale["cause"]


def test_a_call_with_no_snapshot_at_all_is_a_named_cause_not_a_default(tmp_path):
    """If `tools/list` never arrived, annotations are not-declared WITH a cause."""
    records = trace_of(
        tmp_path,
        [("c2s", b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"rm"}}')],
    )

    (gap,) = [r for r in derive_annotations(records) if r["kind"] == "annotation_gap"]
    assert gap["tool"] == "rm"
    assert "tools/list" in gap["cause"]


def test_a_result_that_is_not_an_object_is_a_named_gap_not_a_crash(tmp_path):
    """C-3: `"result":"oops"` is legal JSON a non-conforming server can send.

    `.get("result", {})` defaults only an ABSENT key, so a present-but-wrong-typed
    one used to raise straight out of the derivation.
    """
    records = trace_of(
        tmp_path,
        [
            ("c2s", TOOLS_LIST_REQUEST),
            ("s2c", b'{"jsonrpc":"2.0","id":2,"result":"oops"}'),
        ],
    )

    (gap,) = [r for r in derive_annotations(records) if r["kind"] == "annotation_gap"]
    assert gap["tool"] is None
    assert "result" in gap["cause"]


def test_positional_params_on_a_tools_call_are_a_named_gap_not_a_crash(tmp_path):
    """C-3: JSON-RPC 2.0 explicitly permits `params` as an array.

    The cause must say we could not READ the request. Falling through to
    `name = None` would emit "the tool is absent from the most recent tools/list
    snapshot" — a fabrication. The tool is not absent; we never learned its name.
    """
    records = trace_of(
        tmp_path,
        LISTING + [("c2s", b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":["echo"]}')],
    )

    (gap,) = [r for r in derive_annotations(records) if r["kind"] == "annotation_gap"]
    assert gap["tool"] is None
    assert "params" in gap["cause"]
    assert "absent from the most recent" not in gap["cause"], (
        "an unreadable request must not be reported as a tool the snapshot lacked"
    )


def test_one_non_conforming_frame_does_not_take_down_the_other_snapshots(tmp_path):
    """The blast radius is the point: a crash lost EVERY tool's annotations.

    A malformed frame yields a recorded, honest error, never a dropped turn —
    and the turns either side of it still derive.
    """
    records = trace_of(
        tmp_path,
        [
            ("c2s", b'{"jsonrpc":"2.0","id":9,"method":"tools/list"}'),
            ("s2c", b'{"jsonrpc":"2.0","id":9,"result":"oops"}'),
        ]
        + LISTING,
    )
    derived = derive_annotations(records)

    (snapshot,) = [r for r in derived if r["kind"] == "annotation_snapshot"]
    assert tool(snapshot, "read_file")["annotations"]["readOnlyHint"]["state"] == "declared-true"
    assert [r for r in derived if r["kind"] == "annotation_gap"], "the bad frame lost its cause"


def test_an_unparseable_tools_list_response_invents_no_snapshot_and_is_named(tmp_path):
    """An unreadable response must not become a snapshot, and must not go quiet.

    This layer does not gap it, and that is deliberate rather than a hole: a
    frame that could not be parsed never correlates, so no `tools/list` response
    reaches this module to gap. The naming happens once, upstream, where the
    decode failed — duplicating it here would report one lost frame as two.
    """
    records = trace_of(
        tmp_path,
        [("c2s", TOOLS_LIST_REQUEST), ("s2c", b'{"jsonrpc":"2.0","id":2,"result":{oops}')],
    )

    assert derive_annotations(records) == []

    # The frame is not lost: the index names the decode failure, and the request
    # it answered stays visibly unanswered rather than silently satisfied.
    index = derive_correlation(records)
    (gap,) = [r for r in index if r["kind"] == "index_gap"]
    assert "unparseable" in gap["cause"]
    (correlation,) = [r for r in index if r["kind"] == "correlation"]
    assert correlation["status"] == "unanswered"


def test_the_real_fixture_declares_nothing_end_to_end(tmp_path):
    """Grounding: the differential fixture's `echo` tool carries no annotations."""
    (snapshot,) = snapshots(run_traced(tmp_path, "t", server=FIXTURE))

    echo = tool(snapshot, "echo")
    assert echo["annotations_object"] == "absent"
    assert echo["annotations"]["readOnlyHint"]["state"] == "not-declared"
