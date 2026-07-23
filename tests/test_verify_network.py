"""A2 openWorldHint conformance: the network dimension, as its OWN sub-verdict.

This is the ONE place in C4 where over-claiming is easiest, and the whole project's
credibility rests on not doing it. The honest bound is asymmetric with the filesystem:

- An EMPTY BTH-1 delta PROVES no filesystem mutation, because the snapshot captures the
  WHOLE tree. So `readOnlyHint: true` + empty delta is a grounded PASS.
- There is NO equivalent whole-network snapshot. Belay does not capture outbound
  bytes/hosts anywhere, and — as the Phase-6 probe established — a denied egress attempt
  and a denied filesystem write BOTH surface to the child as the identical EPERM string
  "Operation not permitted", so a denial cannot be reliably attributed to the network.
  Absence of a denial proves nothing either. So the network dimension is NOT_COVERED:
  never a network PASS, never a fabricated network FAIL.

That status used to be UNVERIFIED, and the reversal is deliberate. UNVERIFIED means "we tried
to check this and could not"; Belay has no network instrument at all, so the non-answer is the
same for every trace ever recorded — a coverage BOUNDARY, not a failed attempt. Under the old
rule a server that honestly declared `openWorldHint: false` was strictly worse off than a
silent one (declare nothing -> PASS, declare truthfully -> UNVERIFIED forever). `reduce` now
filters NOT_COVERED out, so the boundary is recorded and rendered without deciding the turn.
The two guarantees this file exists for — never a network PASS, never a fabricated network
FAIL — are unchanged and still asserted directly.

The network dimension is a SEPARATE sub-verdict (`kind="effect:network"`), composed BESIDE
the filesystem `effect` verdict — never folded into it. Folding made a PASS-message verdict
carry an UNVERIFIED status; the separate sub-verdict keeps every message agreeing with its
status and lets a reader see exactly which dimension was and was not verified.

Nothing here spawns a sandbox — the network dimension is decided from the recorded contract,
exactly like the filesystem dimension is decided from the recorded delta.
"""

from __future__ import annotations

import json

from conftest import trace_of

from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.verify import turn as turn_module
from belay.verify.effect import (
    annotation_for_turn,
    network_subverdict,
    render_effect_verdict,
    render_openworld_verdict,
)
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status, reduce

_NETWORK_KIND = "effect:network"


def _listing(*tools_json: str) -> list[tuple]:
    """A `tools/list` request + response declaring `tools_json`, as trace frames."""
    request = b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
    response = (
        '{"jsonrpc":"2.0","id":2,"result":{"tools":[' + ",".join(tools_json) + "]}}"
    ).encode()
    return [("c2s", request), ("s2c", response)]


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


def _reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


# The tool shapes the network dimension turns on:
_CLOSED = '{"name":"phone_home","annotations":{"openWorldHint":false}}'      # declared-false
_OPEN = '{"name":"searcher","annotations":{"openWorldHint":true}}'          # declared-true
_SLOPPY = '{"name":"sloppy_net","annotations":{"openWorldHint":"maybe"}}'   # non-boolean
_BARE = '{"name":"bare"}'                                                   # not-declared


# --- 1. The core guarantee: the network sub-verdict is NEVER a PASS -------------


def test_openworld_conformance_is_never_a_network_pass_and_never_a_fabricated_fail(tmp_path):
    """For EVERY openWorldHint state, the standalone network verdict is NOT_COVERED, and its
    message agrees with its status.

    Belay does not observe network egress, so the network dimension is never a PASS (we
    verified nothing) and never a fabricated FAIL (we observed no violation). That guarantee
    is the point of this test and it is asserted UNCHANGED below. What changed is the name of
    the non-finding: it was UNVERIFIED ("we tried and could not"), it is now NOT_COVERED
    ("this was never inside what Belay claims to check"), which is the truthful description of
    a dimension with no instrument at all. The status is asserted for all four states because
    the non-observation is identical whatever the tool declared.

    The DECLARED-vs-silent distinction did not move into the reduction's business — it lives
    in the message, and that is asserted here too: a reader can still tell "this tool promised
    and we did not check" from "nothing was promised".
    """
    for tool, name, state, promised in [
        (_CLOSED, "phone_home", "declared-false", True),
        (_OPEN, "searcher", "declared-true", False),
        (_SLOPPY, "sloppy_net", "declared-non-boolean", True),
        (_BARE, "bare", "not-declared", False),
    ]:
        # A fresh subdirectory per iteration: `trace_of` writes one trace file and
        # `read_trace` expects exactly one, so each case needs its own trace dir.
        records = trace_of(tmp_path / name, _listing(tool) + [("c2s", _call(3, name))])
        verdict = render_openworld_verdict(records, 0)
        assert verdict.status is Status.NOT_COVERED, (name, state, verdict)
        # The two guarantees this test exists for, unweakened by the reclassification.
        assert verdict.status is not Status.PASS, (name, state, verdict)
        assert verdict.status is not Status.FAIL, (name, state, verdict)
        assert verdict.axis == "A2" and verdict.kind == _NETWORK_KIND, verdict
        # message and status agree — no PASS-worded verdict carrying a NOT_COVERED status.
        assert "NOT_COVERED" in verdict.message, verdict.message
        assert "PASS" not in verdict.message.replace("never PASS", ""), verdict.message
        assert "openWorldHint" in verdict.message, verdict.message
        # The promise distinction survives the status change (spec criterion 4 / plan D4).
        if promised:
            assert "DECLARED openWorldHint" in verdict.message, (name, verdict.message)
        else:
            assert "DECLARED openWorldHint" not in verdict.message, (name, verdict.message)
    # ...and "nothing was promised" is said in as many words, so the two are not merely
    # distinguishable by absence.
    bare = trace_of(tmp_path / "bare2", _listing(_BARE) + [("c2s", _call(3, "bare"))])
    assert "nothing was promised" in render_openworld_verdict(bare, 0).message


# --- 2. The filesystem verdict is PURELY readOnlyHint; message and status agree -


def test_openworld_false_leaves_the_filesystem_verdict_a_clean_pass(tmp_path):
    """`phone_home` declared `readOnlyHint: true` AND `openWorldHint: false`, empty delta.

    The FILESYSTEM verdict is a clean PASS whose message says PASS — no network claim mutates
    it. The network dimension is a SEPARATE NOT_COVERED sub-verdict. This is the fix for the
    self-contradiction the overlay produced (status UNVERIFIED, message "…PASS…").
    """
    tool = '{"name":"phone_home","annotations":{"readOnlyHint":true,"openWorldHint":false}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "phone_home"))])

    fs = render_effect_verdict(records, 0, [])
    assert fs.status is Status.PASS, fs
    assert fs.kind == "effect"
    assert "PASS" in fs.message, fs.message  # message agrees with the status
    assert "openWorldHint" not in fs.expected  # the fs verdict speaks only for readOnlyHint

    net = network_subverdict(records, 0)
    assert net is not None and net.status is Status.NOT_COVERED, net
    assert net.status is not Status.PASS and net.status is not Status.FAIL, net
    assert net.kind == _NETWORK_KIND, net
    # The declared promise is still on the record, even though it no longer moves the status.
    assert "DECLARED openWorldHint: false" in net.message, net.message


def test_turn_composes_three_sub_verdicts_and_reduces_to_pass(tmp_path, monkeypatch):
    """The whole point of the separate sub-verdict: a REPLAYED turn for an `openWorldHint:
    false` tool carries THREE sub-verdicts — result PASS, effect(fs) PASS, network
    NOT_COVERED — and `reduce` leaves the turn a **PASS**. A reader sees exactly what was and
    was not verified, and no sub-verdict's message contradicts its status.

    **This test previously asserted UNVERIFIED, and inverting it is the deliberate act of this
    change** (spec criterion 6). The old expectation encoded the rule that a tool's honestly
    declared `openWorldHint: false` should sink a turn Belay had verified perfectly — which
    made the honest declaration strictly worse than silence and pinned every reference-server
    turn at UNVERIFIED forever. The network dimension is a coverage boundary, not a failed
    attempt; `reduce` drops NOT_COVERED, so the turn passes *on what Belay actually verifies*
    while the boundary stays visible as a sub-verdict. Nothing here weakens
    UNVERIFIED-never-PASS: no UNVERIFIED sub-verdict is present to be promoted, and a genuine
    one would still win (`tests/test_verdict_not_covered.py:165-175`).
    """
    tool = '{"name":"phone_home","annotations":{"readOnlyHint":true,"openWorldHint":false}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "phone_home"))])

    replayed = TurnReplay(
        turn_index=0,
        status=REPLAYED,
        reinvoked=True,
        delta=[],  # empty delta -> filesystem PASS for readOnlyHint:true
        result_equivalence=EQUAL,
        replayed_reply=_reply(3, "ok"),
    )
    monkeypatch.setattr(turn_module, "replay_turn", lambda *a, **k: replayed)

    verdict = verify_turn(records, 0, server_command=["unused"], manifest_dir="/nonexistent")

    kinds = {sub.kind: sub.status for sub in verdict.sub_verdicts}
    assert len(verdict.sub_verdicts) == 3, verdict.sub_verdicts
    assert kinds.get("effect") is Status.PASS, kinds               # filesystem verified
    assert kinds.get(_NETWORK_KIND) is Status.NOT_COVERED, kinds   # network outside coverage
    assert verdict.status is Status.PASS, verdict
    # The turn's own status is never the sub-verdict-only status.
    assert verdict.status is not Status.NOT_COVERED, verdict
    # Never a network PASS, anywhere in the composition.
    assert not any(
        sub.kind == _NETWORK_KIND and sub.status is Status.PASS for sub in verdict.sub_verdicts
    )
    # The PASS is honest only because the boundary is still there to be rendered.
    assert any(sub.kind == _NETWORK_KIND for sub in verdict.sub_verdicts), verdict.sub_verdicts


def test_the_network_dimension_never_softens_a_readonly_fail(tmp_path):
    """The network sub-verdict never promotes: it can only lower a PASS — never lift a FAIL.
    A `readOnlyHint: true` tool that mutated is a FAIL, and the turn stays FAIL even with the
    openWorldHint:false network dimension beside it.

    The guard's assertion is `reduce([fs, net]) is Status.FAIL` and it is UNCHANGED. Only the
    network sub-verdict's status name was retargeted (UNVERIFIED -> NOT_COVERED), because
    `NOT_COVERED` is dropped by `reduce` rather than ranked — which is precisely the case that
    needs guarding: a status that is *filtered out* must not become a status that *excuses*.
    """
    from belay.snapshot.bth1 import FieldDiff

    tool = '{"name":"phone_home","annotations":{"readOnlyHint":true,"openWorldHint":false}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "phone_home"))])

    fs = render_effect_verdict(
        records, 0, [FieldDiff(path=b"x.txt", field=None, left=None, right=b"y")]
    )
    net = network_subverdict(records, 0)
    assert fs.status is Status.FAIL, fs
    assert net is not None and net.status is Status.NOT_COVERED
    assert reduce([fs, net]) is Status.FAIL
    assert reduce([net, fs]) is Status.FAIL  # order-independent


# --- 3. The regression guard: no network sub-verdict where no restriction was declared -


def test_not_declared_openworld_adds_no_network_sub_verdict(tmp_path):
    """A tool that said NOTHING about the open world raises no network-conformance question,
    so `network_subverdict` is None and the filesystem PASS stands. Without this, every
    un-annotated turn (the common case) would be dragged to UNVERIFIED and the deterministic
    core would regress."""
    tool = '{"name":"plain_reader","annotations":{"readOnlyHint":true}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "plain_reader"))])

    assert render_effect_verdict(records, 0, []).status is Status.PASS
    assert network_subverdict(records, 0) is None


def test_declared_true_openworld_adds_no_network_sub_verdict(tmp_path):
    """`openWorldHint: true` is the PERMISSIVE posture (mirror of `readOnlyHint: false`) —
    the tool declared it MAY reach the open world, so there is no restriction to verify.
    `network_subverdict` is None (the turn is not dragged down), yet the standalone
    `render_openworld_verdict` still reports the dimension as outside coverage — never a
    network PASS. That standalone status is NOT_COVERED for this state too: the function
    reports what Belay's network coverage IS, and that is nil regardless of the declaration."""
    tool = '{"name":"searcher","annotations":{"readOnlyHint":true,"openWorldHint":true}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "searcher"))])

    assert render_effect_verdict(records, 0, []).status is Status.PASS
    assert network_subverdict(records, 0) is None
    standalone = render_openworld_verdict(records, 0)
    assert standalone.status is Status.NOT_COVERED
    assert standalone.status is not Status.PASS


# --- 4. The tri-state is read for openWorldHint too ------------------------------


def test_annotation_for_turn_reads_the_openworld_tristate(tmp_path):
    """`annotation_for_turn` correlates openWorldHint the same way it correlates
    readOnlyHint — off the snapshot in force at the call's request_seq."""
    records = trace_of(tmp_path, _listing(_CLOSED) + [("c2s", _call(3, "phone_home"))])

    ann = annotation_for_turn(records, 0)

    assert ann.openworld["state"] == "declared-false", ann
