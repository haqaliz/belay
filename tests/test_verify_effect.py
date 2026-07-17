"""A2 effect-conformance: the tool's OBSERVED filesystem effect vs its DECLARED annotation.

This is the verdict axis that exists ONLY because Belay proxies MCP, where a tool's
`readOnlyHint` is a *declared contract*. A tool that says `readOnlyHint: true` and then
mutates the filesystem on replay is a grounded FAIL, with zero LLM. Result-equivalence
(Task 2) asks "did the reply reproduce?"; this asks a different, independent question:
"did the effect match what the tool promised?".

The one discipline that governs the whole check: **an absent contract is NOT a permissive
one.** A tool that declared no `readOnlyHint` cannot be verified for conformance — that is
UNVERIFIED, never PASS. Defaulting an un-annotated tool to "probably fine" is the exact
false pass the tri-state (C1) was built to prevent. The tri-state
(declared-true / declared-false / not-declared / declared-non-boolean) already exists in
the trace; this check reads it per-turn and applies the rule, never re-introducing a default.

Two tests are the load-bearing controls, each watched RED first:

- **A4 (the headline / positive control):** a `readOnlyHint: true` tool whose replay wrote a
  file -> FAIL naming the annotation AND the observed path. Watched failing against a stub
  that PASSes, proving FAIL is reachable.
- **Correlation correctness:** a trace whose annotation snapshot CHANGES mid-session — the
  turn must pick the snapshot in force at ITS request_seq, not a later one. Watched failing
  against a naive "use the latest snapshot" implementation.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import (
    NOTIFICATION_LIST_CHANGED,
    TOOLS_LIST_REQUEST,
    TOOLS_LIST_REQUEST_AGAIN,
    TOOLS_LIST_RESPONSE,
    TOOLS_LIST_RESPONSE_CHANGED,
)

from belay.snapshot.bth1 import FieldDiff
from belay.verify import effect as effect_module
from belay.verify.effect import (
    annotation_for_turn,
    render_effect_verdict,
    verify_effect,
)
from belay.verify.verdict import Status

# The canned tools/list from the fixture declares, in one snapshot:
#   read_file     -> readOnlyHint: true   (declared-true)
#   write_file    -> readOnlyHint: false  (declared-false)
#   mystery       -> no annotations object (not-declared)
#   contradictory -> readOnlyHint: true + destructiveHint: true (incoherent)
#   sloppy        -> readOnlyHint: "yes"  (declared-non-boolean)
LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]


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
    """A non-empty BTH-1 delta: the tool touched each of `paths`."""
    return [
        FieldDiff(path=p.encode(), field=None, left=None, right=b"content")
        for p in paths
    ]


# --- 1. A4 the headline: readOnlyHint:true + mutation -> FAIL ------------------


def test_a4_readonly_tool_that_mutates_is_a_grounded_fail(tmp_path):
    """`read_file` declared `readOnlyHint: true`; replay observed a write -> FAIL.

    The message NAMES the annotation (`readOnlyHint`) and the observed FieldDiff path,
    because a grounded verdict must point at the evidence, not merely assert a status.

    This is the positive control: watched failing against a stub whose
    `render_effect_verdict` returns PASS for everything, proving FAIL is reachable and
    not vacuously unreachable.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])

    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))

    assert verdict.status is Status.FAIL, verdict
    assert verdict.axis == "A2"
    assert verdict.kind == "effect"
    assert "readOnlyHint" in verdict.message, verdict.message
    assert "written.txt" in verdict.message, verdict.message


# --- 2. A5: un-annotated -> UNVERIFIED; declared-true + no mutation -> PASS -----


def test_a5_unannotated_tool_is_unverified_for_effect(tmp_path):
    """`mystery` declared no `readOnlyHint` at all -> UNVERIFIED, even though it mutated.

    An absent contract cannot be verified for conformance. Defaulting it to PASS ("it
    never claimed read-only, so a mutation is fine") is the exact false pass the tri-state
    was built to prevent — so this is UNVERIFIED, never PASS.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])

    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    assert verdict.axis == "A2" and verdict.kind == "effect"


def test_a_call_with_no_preceding_snapshot_is_unverified(tmp_path):
    """No `tools/list` was captured before the call -> not-declared for want of
    observation -> UNVERIFIED. A missing snapshot is not a permissive one."""
    records = trace_of(tmp_path, [("c2s", _call(3, "read_file"))])

    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))

    assert verdict.status is Status.UNVERIFIED, verdict


def test_declared_true_with_no_mutation_is_pass(tmp_path):
    """The positive control in the same area: `read_file` declared `readOnlyHint: true`
    and replay observed an EMPTY delta -> PASS. This proves UNVERIFIED is not simply what
    the check returns whenever there was no mutation — a *declared* read-only tool that
    honoured its contract genuinely PASSes."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])

    verdict = render_effect_verdict(records, 0, [])

    assert verdict.status is Status.PASS, verdict
    assert verdict.axis == "A2" and verdict.kind == "effect"


# --- 3. declared-false + mutation -> PASS -------------------------------------


def test_declared_false_plus_mutation_is_pass(tmp_path):
    """`write_file` declared `readOnlyHint: false` — it said it mutates. It did -> PASS.

    There is no read-only contract to violate, so a mutation conforms.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "write_file"))])

    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))

    assert verdict.status is Status.PASS, verdict
    assert verdict.axis == "A2" and verdict.kind == "effect"


# --- 4. declared-non-boolean -> UNVERIFIED ------------------------------------


def test_declared_non_boolean_is_unverified(tmp_path):
    """`sloppy` declared `readOnlyHint: "yes"` — present, but not a boolean. We cannot
    read a contract off a non-boolean, so conformance is UNVERIFIED, never PASS."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "sloppy"))])

    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS


# --- 5. Correlation correctness: the snapshot in force at request_seq ---------


def test_correlation_picks_the_snapshot_in_force_not_a_later_one(tmp_path):
    """The subtle one. The annotation snapshot CHANGES mid-session, and the call happened
    BETWEEN the two snapshots. `read_file` is `readOnlyHint: true` in the first snapshot
    and `readOnlyHint: false` in the second. The turn must be verified against the FIRST
    (the contract live when it ran), not the later re-snapshot.

    A naive "use the latest snapshot" implementation reads the second (declared-false) and
    returns PASS on a mutation; the correct implementation reads the first (declared-true)
    and returns FAIL. Watched failing against that naive implementation.
    """
    records = trace_of(
        tmp_path,
        [
            ("c2s", TOOLS_LIST_REQUEST),
            ("s2c", TOOLS_LIST_RESPONSE),          # snapshot 1: read_file declared-true
            ("c2s", _call(3, "read_file")),        # the turn — in force: snapshot 1
            ("s2c", NOTIFICATION_LIST_CHANGED),
            ("c2s", TOOLS_LIST_REQUEST_AGAIN),
            ("s2c", TOOLS_LIST_RESPONSE_CHANGED),  # snapshot 2: read_file declared-false
        ],
    )

    ann = annotation_for_turn(records, 0)

    # The correlation itself: the FIRST snapshot is in force, not the later one.
    from belay.annotations import derive_annotations

    first, second = [
        d for d in derive_annotations(records) if d["kind"] == "annotation_snapshot"
    ]
    assert ann.snapshot_seq == first["source_seq"], ann
    assert ann.snapshot_seq != second["source_seq"], ann
    assert ann.readonly["state"] == "declared-true", ann

    # And the verdict that rides on it: declared-true + mutation -> FAIL. The naive
    # latest-snapshot reading would see declared-false here and PASS.
    verdict = render_effect_verdict(records, 0, _mutation("written.txt"))
    assert verdict.status is Status.FAIL, verdict


# --- 6. Incoherence surfaced, not resolved (S3) -------------------------------


def test_incoherence_is_surfaced_on_the_verdict_not_resolved(tmp_path):
    """`contradictory` declares `readOnlyHint: true` AND `destructiveHint: true`, which
    the spec makes incoherent (destructive is meaningful only when readOnlyHint == false).

    The verdict must carry that incoherence as a FACT — surfaced, not adjudicated. The
    status is still decided by readOnlyHint vs the delta (here an empty delta -> PASS); the
    incoherence rides along without changing it, which is what "surface, do not resolve"
    means.
    """
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "contradictory"))])

    verdict = render_effect_verdict(records, 0, [])

    assert verdict.status is Status.PASS, verdict
    # The incoherence survives verbatim on the verdict's declared-contract grounding...
    assert verdict.expected["incoherence"], verdict
    assert any(
        i["annotation"] == "destructiveHint" for i in verdict.expected["incoherence"]
    ), verdict.expected
    # ...and is named in the human-readable message.
    assert "destructiveHint" in verdict.message, verdict.message


# --- 7. Independence: effect and result decide SEPARATELY ---------------------


def test_effect_is_independent_of_result_equivalence(tmp_path):
    """An un-annotated tool is UNVERIFIED for effect-conformance regardless of whether its
    result reproduced. This check produces its OWN Verdict and does not reduce with
    result-equivalence here — the per-turn composition (a later task) reduces them."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "mystery"))])

    # Same tool, both an empty and a non-empty delta: effect-conformance is UNVERIFIED
    # either way, because the tool declared no contract to check the effect against.
    assert render_effect_verdict(records, 0, []).status is Status.UNVERIFIED
    assert render_effect_verdict(records, 0, _mutation("x")).status is Status.UNVERIFIED


def test_delta_none_cannot_confirm_a_readonly_tool(tmp_path):
    """No delta was observed at all (replay produced none) -> UNVERIFIED even for a
    declared read-only tool: PASS requires OBSERVING no mutation, and there is no
    observation here to ground it on."""
    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])

    verdict = render_effect_verdict(records, 0, None)

    assert verdict.status is Status.UNVERIFIED, verdict


# --- 8. verify_effect orchestrator: replay once, then render ------------------


def test_verify_effect_replays_then_renders(tmp_path, monkeypatch):
    """The orchestrator composes a single replay (for the delta) with the annotation
    correlation. `replay_turn` is stubbed to report a mutation; the recorded annotation
    (`read_file`, declared-true) makes that a FAIL. No sandbox, no network."""
    from belay.replay.engine import REPLAYED, TurnReplay

    records = trace_of(tmp_path, LISTING + [("c2s", _call(3, "read_file"))])

    def fake_replay_turn(*args, **kwargs):
        return TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            delta=_mutation("written.txt"),
        )

    monkeypatch.setattr(effect_module, "replay_turn", fake_replay_turn)

    verdict = verify_effect(
        records, 0, server_command=["unused"], manifest_dir=tmp_path
    )

    assert verdict.status is Status.FAIL, verdict
    assert "readOnlyHint" in verdict.message and "written.txt" in verdict.message
