"""The contract in force under a COMPOSITE transport — two servers, one pipe.

Run 2 of the corpus-filling mint (`docs/planning/phase0-corpus-mint/mint-run/
STAGE1_FINDINGS_RUN2.md`) measured the defect this pins. The composite transport
broadcasts ONE `tools/list` (one JSON-RPC id) to the filesystem and the shell server,
so the trace holds two request frames with the SAME id in flight together, then two
responses — one per server. `annotation_for_turn` read the latest snapshot alone, so a
filesystem tool was correlated against the SHELL server's list, read `tool-absent`, and
abstained; which tool lost depended only on which server answered last.

The rule these tests pin: the contract in force is the latest snapshot **together with
its broadcast twins** — `tools/list` responses whose requests carry the same id, came
the same way, and were in flight at the same time. A single pipe can never hold two
in-flight requests with one id, so the grouping is exact, never a time window. A
single-server re-snapshot is untouched: a tool the latest list drops is still absent.
A tool that two twins describe DIFFERENTLY is never resolved by picking one — it
abstains with a named producer.

Nothing here hand-builds a `Verdict`; the real `annotation_for_turn`,
`render_effect_verdict` and `derive_annotations` produce every object asserted on.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import (
    TOOLS_LIST_REQUEST,
    TOOLS_LIST_REQUEST_AGAIN,
    TOOLS_LIST_RESPONSE,
    TOOLS_LIST_RESPONSE_CHANGED,
)

from belay.annotations import derive_annotations
from belay.snapshot.bth1 import FieldDiff
from belay.verify.effect import (
    PRODUCER_SERVER_DECLARED_NOTHING,
    PRODUCER_TOOL_ABSENT,
    PRODUCER_TOOL_AMBIGUOUS,
    annotation_for_turn,
    render_effect_verdict,
)
from belay.verify.verdict import Status

#: The shell server's answer to the SAME broadcast `tools/list` (id 2): one tool, no
#: annotations — the shape `mcp-server-commands` emits.
SHELL_LIST_RESPONSE = (
    b'{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"run_process"}]}}'
)

#: A filesystem server that declares nothing — the pinned npm server's shape.
BARE_FS_LIST_RESPONSE = (
    b'{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"read_text_file"}]}}'
)

#: A second twin that describes `read_file` differently from `TOOLS_LIST_RESPONSE`.
CONFLICTING_LIST_RESPONSE = (
    b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
    b'{"name":"read_file","annotations":{"readOnlyHint":false}}]}}'
)


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _mutation(*paths: str) -> list[FieldDiff]:
    return [
        FieldDiff(path=p.encode(), field=None, left=None, right=b"content")
        for p in paths
    ]


def _composite(first: bytes, second: bytes, call: bytes) -> list[tuple]:
    """The run-2 shape: the broadcast request twice, both responses, then the call."""
    return [
        ("c2s", TOOLS_LIST_REQUEST),
        ("c2s", TOOLS_LIST_REQUEST),
        ("s2c", first),
        ("s2c", second),
        ("c2s", call),
    ]


def test_a_filesystem_tool_is_found_when_the_shell_server_answered_last(tmp_path):
    """The measured run-2 order: fs answers first, shell last — never `tool-absent`."""
    records = trace_of(
        tmp_path, _composite(TOOLS_LIST_RESPONSE, SHELL_LIST_RESPONSE, _call(3, "read_file"))
    )
    ann = annotation_for_turn(records, 0)
    assert ann.producer != PRODUCER_TOOL_ABSENT, ann
    assert ann.readonly["state"] == "declared-true", ann


def test_the_outcome_does_not_depend_on_which_server_answered_last(tmp_path):
    """The run-2 finding named the order-dependence; both orders must read the same."""
    fs_last = trace_of(
        tmp_path / "a",
        _composite(SHELL_LIST_RESPONSE, TOOLS_LIST_RESPONSE, _call(3, "read_file")),
    )
    shell_last = trace_of(
        tmp_path / "b",
        _composite(TOOLS_LIST_RESPONSE, SHELL_LIST_RESPONSE, _call(3, "read_file")),
    )
    a, b = annotation_for_turn(fs_last, 0), annotation_for_turn(shell_last, 0)
    assert (a.producer, a.readonly) == (b.producer, b.readonly)


def test_a_shell_tool_is_found_when_the_filesystem_server_answered_last(tmp_path):
    records = trace_of(
        tmp_path, _composite(SHELL_LIST_RESPONSE, TOOLS_LIST_RESPONSE, _call(3, "run_process"))
    )
    ann = annotation_for_turn(records, 0)
    assert ann.producer == PRODUCER_SERVER_DECLARED_NOTHING, ann


def test_an_annotation_less_composite_reaches_the_coverage_boundary(tmp_path):
    """End to end on the run-2 shape: the npm fs server declares nothing, so a
    `read_text_file` turn is NOT_COVERED on effect — never UNVERIFIED `tool-absent`,
    and never PASS on the sub-verdict itself."""
    records = trace_of(
        tmp_path,
        _composite(BARE_FS_LIST_RESPONSE, SHELL_LIST_RESPONSE, _call(3, "read_text_file")),
    )
    verdict = render_effect_verdict(records, 0, [])
    assert verdict.status is Status.NOT_COVERED, verdict


def test_twins_that_disagree_about_a_tool_abstain_never_pick_one(tmp_path):
    """Two servers both describing `read_file`, differently: the trace cannot say which
    one the call reached (a trace carries no server provenance), so it abstains."""
    records = trace_of(
        tmp_path,
        _composite(TOOLS_LIST_RESPONSE, CONFLICTING_LIST_RESPONSE, _call(3, "read_file")),
    )
    ann = annotation_for_turn(records, 0)
    assert ann.producer == PRODUCER_TOOL_AMBIGUOUS, ann
    assert ann.cause, ann
    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))
    assert verdict.status is Status.UNVERIFIED, verdict


def test_twins_that_agree_about_a_tool_are_not_ambiguous(tmp_path):
    records = trace_of(
        tmp_path,
        _composite(TOOLS_LIST_RESPONSE, TOOLS_LIST_RESPONSE, _call(3, "read_file")),
    )
    ann = annotation_for_turn(records, 0)
    assert ann.readonly["state"] == "declared-true", ann


def test_a_single_server_re_snapshot_that_drops_a_tool_still_reads_absent(tmp_path):
    """The guard against the loose fix ("latest snapshot CONTAINING the tool"): a
    sequential re-snapshot is a NEW contract, not a twin, and a dropped tool is absent."""
    records = trace_of(
        tmp_path,
        [
            ("c2s", TOOLS_LIST_REQUEST),
            ("s2c", TOOLS_LIST_RESPONSE),  # id 2 — lists `mystery`
            ("c2s", TOOLS_LIST_REQUEST_AGAIN),
            ("s2c", TOOLS_LIST_RESPONSE_CHANGED),  # id 4
            ("c2s", _call(5, "mystery")),
        ],
    )
    changed = json.loads(TOOLS_LIST_RESPONSE_CHANGED)["result"]["tools"]
    assert all(t["name"] != "mystery" for t in changed)  # the premise
    ann = annotation_for_turn(records, 0)
    assert ann.producer == PRODUCER_TOOL_ABSENT, ann


def test_the_same_id_reused_after_completion_is_not_a_twin(tmp_path):
    """JSON-RPC allows an id to be reused once its request is answered; sequential reuse
    is a re-snapshot, never a broadcast, so the earlier list does not stay in force."""
    records = trace_of(
        tmp_path,
        [
            ("c2s", TOOLS_LIST_REQUEST),
            ("s2c", TOOLS_LIST_RESPONSE),  # id 2 — lists `read_file`
            ("c2s", TOOLS_LIST_REQUEST),
            ("s2c", SHELL_LIST_RESPONSE),  # id 2 again, AFTER the first was answered
            ("c2s", _call(3, "read_file")),
        ],
    )
    ann = annotation_for_turn(records, 0)
    assert ann.producer == PRODUCER_TOOL_ABSENT, ann


def test_the_derivation_names_no_gap_for_a_tool_a_twin_describes(tmp_path):
    """`derive_annotations` carries the same rule: no `annotation_gap` claiming the tool
    is absent from the most recent snapshot, when its twin lists it."""
    records = trace_of(
        tmp_path, _composite(TOOLS_LIST_RESPONSE, SHELL_LIST_RESPONSE, _call(3, "read_file"))
    )
    gaps = [d for d in derive_annotations(records) if d["kind"] == "annotation_gap"]
    assert gaps == [], gaps
