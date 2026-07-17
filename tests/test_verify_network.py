"""A2 openWorldHint conformance: the network dimension of effect-conformance.

This is the ONE place in C4 where over-claiming is easiest, and the whole project's
credibility rests on not doing it. The honest bound is asymmetric with the filesystem:

- An EMPTY BTH-1 delta PROVES no filesystem mutation, because the snapshot captures the
  WHOLE tree. So `readOnlyHint: true` + empty delta is a grounded PASS.
- There is NO equivalent whole-network snapshot. Belay does not capture outbound
  bytes/hosts anywhere, and — as the Phase-6 probe established — a denied egress attempt
  and a denied filesystem write BOTH surface to the child as the identical EPERM string
  "Operation not permitted", so a denial cannot be reliably attributed to the network.
  Absence of a denial therefore proves nothing (under allow-all a tool egresses freely and
  we see nothing), and a denial cannot be pinned to the network without guessing.

So the network dimension is an HONEST UNVERIFIED: `openWorldHint` conformance is NEVER a
network PASS, and NEVER a fabricated network FAIL. These tests pin that. The build path
(a grounded FAIL from a deny-all egress denial) was NOT taken — see task-6-report.md for
the empirical reason — so the tests here are the fallback's: they assert we do not claim
egress coverage we do not have.

macOS-only end-to-end sandbox tests are marked skipif elsewhere; nothing here spawns a
sandbox — the network dimension is decided from the recorded contract, exactly like the
filesystem dimension is decided from the recorded delta.
"""

from __future__ import annotations

import json

from conftest import trace_of

from belay.verify.effect import (
    annotation_for_turn,
    render_effect_verdict,
    render_openworld_verdict,
)
from belay.verify.verdict import Status


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


# The tool shapes the network dimension turns on:
_CLOSED = '{"name":"phone_home","annotations":{"openWorldHint":false}}'      # declared-false
_OPEN = '{"name":"searcher","annotations":{"openWorldHint":true}}'          # declared-true
_SLOPPY = '{"name":"sloppy_net","annotations":{"openWorldHint":"maybe"}}'   # non-boolean
_BARE = '{"name":"bare"}'                                                   # not-declared


# --- 1. The core guarantee: openWorldHint conformance is NEVER a network PASS ---


def test_openworld_conformance_is_never_a_network_pass_and_never_a_fabricated_fail(tmp_path):
    """For EVERY openWorldHint state, the standalone network verdict is UNVERIFIED.

    Belay does not observe network egress: successful egress under allow-all is uncaptured,
    and a deny-all denial cannot be reliably attributed to the network (an egress denial and
    a filesystem-write denial are the same EPERM line). So the only honest verdict for the
    network dimension is UNVERIFIED — never PASS (we verified nothing), never a fabricated
    FAIL (we observed no violation). This is the "never claim coverage we do not have" line,
    asserted directly.
    """
    for tool, name, state in [
        (_CLOSED, "phone_home", "declared-false"),
        (_OPEN, "searcher", "declared-true"),
        (_SLOPPY, "sloppy_net", "declared-non-boolean"),
        (_BARE, "bare", "not-declared"),
    ]:
        # A fresh subdirectory per iteration: `trace_of` writes one trace file and
        # `read_trace` expects exactly one, so each case needs its own trace dir.
        records = trace_of(tmp_path / name, _listing(tool) + [("c2s", _call(3, name))])
        verdict = render_openworld_verdict(records, 0)
        assert verdict.status is Status.UNVERIFIED, (name, state, verdict)
        assert verdict.status is not Status.PASS, (name, state, verdict)
        assert verdict.status is not Status.FAIL, (name, state, verdict)
        assert verdict.axis == "A2" and verdict.kind == "effect", verdict
        assert "openWorldHint" in verdict.message, verdict.message


# --- 2. A tool that egresses is UNVERIFIED for openWorldHint, not silently PASSed ---


def test_egressing_closed_tool_downgrades_the_effect_verdict_to_unverified(tmp_path):
    """`phone_home` declared `openWorldHint: false` (a closed posture) AND
    `readOnlyHint: true`, and replay observed an EMPTY filesystem delta.

    The filesystem dimension alone would be a grounded PASS (read-only honoured). But the
    tool ALSO declared it would not touch the open world — a claim Belay cannot verify,
    because egress is unobservable. Rendering the turn PASS would silently pass an unverified
    network claim. The honest reduction across the two dimensions is UNVERIFIED, and the
    openWorldHint state is surfaced on the verdict as a fact.
    """
    tool = '{"name":"phone_home","annotations":{"readOnlyHint":true,"openWorldHint":false}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "phone_home"))])

    verdict = render_effect_verdict(records, 0, [])  # empty delta = filesystem PASS

    assert verdict.status is Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS
    assert "openWorldHint" in verdict.message, verdict.message
    assert verdict.expected["openWorldHint"]["state"] == "declared-false", verdict.expected


def test_a_readonly_fail_is_not_softened_by_the_network_dimension(tmp_path):
    """The network overlay only ever DOWNGRADES a PASS; it never promotes. A
    `readOnlyHint: true` tool that mutated is a FAIL, and declaring `openWorldHint: false`
    (an UNVERIFIED network dimension) must not soften that FAIL to UNVERIFIED."""
    from belay.snapshot.bth1 import FieldDiff

    tool = '{"name":"phone_home","annotations":{"readOnlyHint":true,"openWorldHint":false}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "phone_home"))])
    delta = [FieldDiff(path=b"written.txt", field=None, left=None, right=b"x")]

    verdict = render_effect_verdict(records, 0, delta)

    assert verdict.status is Status.FAIL, verdict


# --- 3. The regression guard: not-declared openWorldHint changes nothing ---------


def test_not_declared_openworld_leaves_the_readonly_verdict_untouched(tmp_path):
    """A tool that declared `readOnlyHint: true` and said NOTHING about the open world is
    still a PASS on an empty delta. openWorldHint being not-declared raises no
    network-conformance question, so it must not drag the verdict to UNVERIFIED — otherwise
    every un-annotated turn (the common case) would be dragged down and the deterministic
    core would regress."""
    tool = '{"name":"plain_reader","annotations":{"readOnlyHint":true}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "plain_reader"))])

    verdict = render_effect_verdict(records, 0, [])

    assert verdict.status is Status.PASS, verdict


def test_declared_true_openworld_permits_egress_so_the_filesystem_pass_stands(tmp_path):
    """`openWorldHint: true` is the PERMISSIVE posture — the tool declared it MAY reach the
    open world, so there is no restriction to violate (mirror of `readOnlyHint: false`). The
    filesystem-grounded PASS stands; the PASS is a filesystem PASS, never a network PASS. And
    the standalone network verdict is still UNVERIFIED — we never observed the network."""
    tool = '{"name":"searcher","annotations":{"readOnlyHint":true,"openWorldHint":true}}'
    records = trace_of(tmp_path, _listing(tool) + [("c2s", _call(3, "searcher"))])

    assert render_effect_verdict(records, 0, []).status is Status.PASS
    assert render_openworld_verdict(records, 0).status is Status.UNVERIFIED


# --- 4. The tri-state is read for openWorldHint too ------------------------------


def test_annotation_for_turn_reads_the_openworld_tristate(tmp_path):
    """`annotation_for_turn` correlates openWorldHint the same way it correlates
    readOnlyHint — off the snapshot in force at the call's request_seq."""
    records = trace_of(tmp_path, _listing(_CLOSED) + [("c2s", _call(3, "phone_home"))])

    ann = annotation_for_turn(records, 0)

    assert ann.openworld["state"] == "declared-false", ann
