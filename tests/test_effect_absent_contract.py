"""An ABSENT contract is a coverage boundary, not an abstention — A2 effect-conformance.

`src/belay/verify/effect.py:556-566` is a fall-through with no `if`: four structurally
different facts arrive there and leave as one `Status.UNVERIFIED`. Three of them genuinely
are abstentions — *we tried to learn this tool's contract and could not*. The fourth is not
an attempt at all:

    i.   no `tools/list` response was captured before the call      (`effect.py:202-210`)
    ii.  the tool is absent from the snapshot that WAS observed     (`effect.py:215-223`)
    iii. the `tools/call` request frame could not be read           (`effect.py:180-191`)
    iv.  the snapshot WAS observed, the tool IS in it, and the
         server declared no `readOnlyHint`                          (`effect.py:225-231`)

Producer iv is Belay looking at a complete observation and finding the server promised
nothing. There is no contract to check, and there never was — a **coverage boundary**, the
same kind of non-finding `openWorldHint` already carries as `Status.NOT_COVERED`. Calling it
UNVERIFIED asserts a failed attempt that never happened, and because worst-status-wins then
drags the turn down, it is why every turn against the pinned annotation-less npm filesystem
server is UNVERIFIED and `VERIFIED_CLEAN` is unreachable
(`docs/planning/effect-conformance-coverage/absent-contract-coverage/spec.md`).

These tests pin AC-1, AC-5 and AC-6 of that spec. They are written RED, before any
production change.

**Nothing here hand-builds a `Verdict`.** The real `render_effect_verdict` and the real
`verify_turn` produce every object asserted on; only C3's re-execution is stubbed, exactly
as `tests/test_verify_turn.py` stubs it. The reason is recorded at
`tests/test_interop_attach.py:366-372`: a test built through a stub seam was once green
against a live bug, so a green suite was not evidence. Deterministic, offline — no MCP
server is ever spawned.
"""

from __future__ import annotations

import json

from conftest import trace_of
from fixtures.annotation_frames import TOOLS_LIST_REQUEST, TOOLS_LIST_RESPONSE

from belay.replay.engine import EQUAL, REPLAYED, TurnReplay
from belay.verify import turn as turn_module
from belay.verify.effect import render_effect_verdict
from belay.verify.turn import verify_turn
from belay.verify.verdict import Status

# The canned `tools/list` the effect tests already ground on. `mystery` is the tool with
# **no `annotations` object at all** — the producer-iv case, and the shape the reference
# filesystem server emits for every one of its tools.
LISTING = [("c2s", TOOLS_LIST_REQUEST), ("s2c", TOOLS_LIST_RESPONSE)]

#: Never reached: every test that calls `verify_turn` stubs `replay_turn`.
UNUSED = ["unused-server"]


def _call(msg_id: int, name: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    ).encode()


#: A `tools/call` whose `params` is an ARRAY. JSON-RPC 2.0 permits positional params, so
#: this is a legal frame off which no tool name can be read — producer iii, reached without
#: corrupting the trace.
_POSITIONAL_CALL = (
    b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":["read_file",{}]}'
)


def _reply(msg_id: int, text: str) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }
    ).encode()


def _producer_records(tmp_path) -> dict[str, list[dict]]:
    """One recorded trace per producer of the not-declared fall-through.

    Each reaches `effect.py:556-566` by a DIFFERENT route, which is the whole point: the
    fall-through cannot be reasoned about from one example, because it is the collapse of
    four that these four re-separate.
    """
    return {
        "i-no-snapshot": trace_of(
            tmp_path / "i", [("c2s", _call(3, "read_file"))]
        ),
        "ii-tool-absent": trace_of(
            tmp_path / "ii", LISTING + [("c2s", _call(3, "ghost"))]
        ),
        "iii-unreadable-request": trace_of(
            tmp_path / "iii", LISTING + [("c2s", _POSITIONAL_CALL)]
        ),
        "iv-server-declared-nothing": trace_of(
            tmp_path / "iv", LISTING + [("c2s", _call(3, "mystery"))]
        ),
    }


# --- AC-1: the boundary case is NOT_COVERED, and its turn is a PASS ------------------


def test_an_observed_server_that_declared_no_readonly_hint_is_not_covered(tmp_path):
    """Producer iv — the snapshot was observed, `mystery` is IN it, and the server declared
    no `readOnlyHint` -> `Status.NOT_COVERED` on axis `A2`, kind `effect`.

    THE RULE THIS PINS: `UNVERIFIED` means *"we tried to check this and could not"*;
    `NOT_COVERED` means *"this was never inside what Belay claims to check"*. Nothing was
    attempted here and nothing failed — the server simply promised nothing, so there is no
    contract for a filesystem delta to confirm or refute. Reporting that as an abstention
    asserts a failed attempt Belay never made, and (via worst-status-wins) reads to an
    operator as *"the tool is broken"*.

    WHY IT MATTERS: this is the single fact that makes `VERIFIED_CLEAN` unreachable against
    an annotation-less server, so a corpus-filling mint can never bank a per-turn case
    against one.

    The kind stays the bare `effect` and the axis stays `A2` deliberately: this is the SAME
    filesystem dimension, reporting its coverage honestly — not a new dimension and not a
    boundary abstention (which narrows the kind, `effect.py:92-101`).
    """
    records = _producer_records(tmp_path)["iv-server-declared-nothing"]

    verdict = render_effect_verdict(records, 0, [])

    assert verdict.status is Status.NOT_COVERED, verdict
    assert verdict.status is not Status.UNVERIFIED, verdict
    assert verdict.status is not Status.PASS, verdict
    assert verdict.axis == "A2", verdict
    assert verdict.kind == "effect", verdict


def test_a_replayed_turn_against_a_contractless_server_reduces_to_pass(
    tmp_path, monkeypatch
):
    """The turn-level half of AC-1, and the user-visible outcome the whole aspect exists for.

    A turn whose tool the server declared nothing about, which replayed cleanly and whose
    reply reproduced, reduces to **PASS** — carrying the `effect` `NOT_COVERED` sub-verdict
    that says what was not checked. `reduce` drops `NOT_COVERED` before ranking
    (`verdict.py:104-112`), so the PASS falls out of the reclassification alone: this asserts
    NOTHING about `reduce`, `_RANK` or `phase0`'s `replayed_any` predicate, all three of
    which are deliberately untouched by this aspect (plan D3). If making this green requires
    editing any of them, the split is mis-built.

    Today both sub-verdicts are scored — result PASS, effect UNVERIFIED — and UNVERIFIED
    outranks PASS, so the turn is UNVERIFIED.

    NOT weakened here: `UNVERIFIED` is still never rendered as PASS. No UNVERIFIED
    sub-verdict is present to be promoted, and a genuine one would still win — exactly the
    argument `tests/test_verify_network.py:166` records for the same move on the network
    dimension.

    `replay_turn` is stubbed (no sandbox, no server, no network); the composition under test
    is the real `verify_turn`.
    """
    records = _producer_records(tmp_path)["iv-server-declared-nothing"]
    reply = _reply(3, "ok")
    monkeypatch.setattr(
        turn_module,
        "replay_turn",
        lambda *a, **k: TurnReplay(
            turn_index=0,
            status=REPLAYED,
            reinvoked=True,
            result_equivalence=EQUAL,
            recorded_reply=reply,
            replayed_reply=reply,
            delta=[],
        ),
    )

    verdict = verify_turn(records, 0, server_command=UNUSED, manifest_dir="/nonexistent")

    kinds = {sub.kind: sub.status for sub in verdict.sub_verdicts}
    assert kinds.get("replay") is Status.PASS, verdict.sub_verdicts
    assert kinds.get("effect") is Status.NOT_COVERED, verdict.sub_verdicts
    assert verdict.status is Status.PASS, verdict
    # The boundary is still visible on the turn — reclassified, never suppressed.
    assert any(
        sub.status is Status.NOT_COVERED for sub in verdict.sub_verdicts
    ), verdict.sub_verdicts


# --- AC-5: no message renders a Python `None` ---------------------------------------


def test_no_producer_renders_a_python_none_in_its_message(tmp_path):
    """No message `render_effect_verdict` produces may contain the substring `"(None)"`, on
    ANY of the four producers of the not-declared fall-through.

    THE RULE THIS PINS: a verdict message is the operator's only account of what Belay did.
    `effect.py:562-565` interpolates `{ann.cause}` unconditionally, and producer iv is the
    one return site that sets no cause (`effect.py:225-231` — the field defaults to `None`),
    so the common case against an annotation-less server renders literally
    *"did not declare readOnlyHint (None)"*. That is a Python repr leaking into a user-facing
    sentence, and it says nothing true about the turn.

    WHY ALL FOUR, not just iv: the split about to be built changes which producer reaches
    which message, so pinning the whole set stops the defect being moved rather than fixed.

    Every producer is named in the assertion so a failure says WHICH message leaked.
    """
    for producer, records in _producer_records(tmp_path).items():
        verdict = render_effect_verdict(records, 0, [])
        assert "(None)" not in verdict.message, (producer, verdict.message)


# --- AC-6: the distinction is legible in the message --------------------------------

#: Phrasings that attribute the silence to the SERVER — "nothing was promised". Any one of
#: them satisfies the criterion; the set is open so the message can be improved later
#: without this test becoming a transcription of it.
_SERVER_DECLARED_NOTHING = (
    "the server declared no",
    "the server declared nothing",
    "the server declared none",
    "declared no contract",
    "no contract was declared",
)

#: Phrasings that attribute the silence to a failed OBSERVATION — "we could not see what was
#: promised". Same open-set discipline.
_CONTRACT_NOT_OBSERVED = (
    "could not be observed",
    "for want of observation",
    "was never observed",
    "no tools/list response was captured",
)


def test_the_not_covered_message_says_the_server_declared_no_contract(tmp_path):
    """Producer iv's message must say the SERVER DECLARED NO CONTRACT.

    THE RULE THIS PINS (spec AC-6): a reader must be able to tell *"nothing was promised"*
    from *"we could not see what was promised."* Reclassifying the status without saying why
    would hand an operator a `NOT_COVERED` with no account of whose silence produced it —
    and the distinction is the entire justification for splitting this population off from
    the three abstentions.

    Today the message reads *"tool 'mystery' did not declare readOnlyHint (None)"*: it names
    the TOOL, not the server's choice, and its parenthetical — the only slot that could
    explain — is a leaked `None` (see the AC-5 test above).

    The second assertion is the sharper one: producer iv's message must not borrow producer
    i's *failed-observation* language, or the two collapse back into one claim wearing two
    statuses. Asserted on distinguishing substrings, never on a full string — the wording
    should be free to improve.
    """
    records = _producer_records(tmp_path)["iv-server-declared-nothing"]

    message = render_effect_verdict(records, 0, []).message.lower()

    assert any(phrase in message for phrase in _SERVER_DECLARED_NOTHING), message
    assert not any(phrase in message for phrase in _CONTRACT_NOT_OBSERVED), message


def test_the_unobserved_producer_still_says_the_contract_was_never_observed(tmp_path):
    """The other half of AC-6, and the half that must SURVIVE the split unchanged.

    THE RULE THIS PINS: producer i — no `tools/list` was captured before the call — is a
    genuine abstention, and its message must keep saying the contract could not be OBSERVED
    rather than that none was declared. Belay does not know what this server declares; it
    never looked. Letting producer i drift toward *"the server declared no contract"* would
    manufacture a claim about the server out of Belay's own blind spot, and would make it
    indistinguishable from the boundary case — the failure mode in the opposite direction
    from the one the split repairs.

    It also stays `UNVERIFIED`: the three abstentions are untouched by this aspect
    (spec AC-2), and only producer iv moves.
    """
    records = _producer_records(tmp_path)["i-no-snapshot"]

    verdict = render_effect_verdict(records, 0, [])
    message = verdict.message.lower()

    assert verdict.status is Status.UNVERIFIED, verdict
    assert any(phrase in message for phrase in _CONTRACT_NOT_OBSERVED), message
    assert not any(phrase in message for phrase in _SERVER_DECLARED_NOTHING), message
