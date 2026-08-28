"""Ask a replay boundary what tools it offers, by spawning it the way a replay does.

## The question, and why it needs its own spawn

A2's result-equivalence compares a recorded reply against a replayed one. When the
replay boundary does not offer the recorded tool at all, the replayed reply is a
`Tool ... not found` error, the comparison DIVERGEs, and — with nothing else to go on
— that reads as a confident FAIL of the agent's tool call. It is not one: nothing was
re-executed, so nothing was refuted. Answering that honestly needs a fact only the
boundary has, so this module goes and gets it.

It goes and gets it by **spawning the boundary**, not by reading the trace. The trace's
own recorded `tools/list` says what the CAPTURE boundary offered; the question here is
what the REPLAY boundary offers, and those are different servers whenever the operator
typed a different `--server`. That difference is the entire defect.

## The three-way answer, which is the whole point

    set of names   the boundary answered, and this is what it offers
    set()          the boundary answered, and it offers NOTHING
    None           the probe could not run, or its answer could not be read

`set()` and `None` are different facts and must never be interchanged. An unreadable
answer rendered as `set()` would assert "this boundary offers nothing" on no evidence
— absence of evidence sold as evidence of absence — and the caller would abstain with
the wrong cause. So every unreadable shape below is `None`, fail-closed.

## Nothing about sandboxing, restore or relocation is reimplemented here

`client.replay_turn` already restores the snapshot into a fresh scratch, spawns the
server contained with its cwd there, relocates argv against `source_root`, and bounds
the conversation by a timeout. The probe calls it with the SAME resolved argv and the
SAME manifest, and only the frames differ. A second copy of that machinery would drift
from the replay it is supposed to be asking about, which would make the answer worse
than no answer.

## It never enters the replayed conversation

The frames are an `initialize`, the `notifications/initialized` a conforming client
owes the server, and a `tools/list`. This is a SEPARATE call with its own restore and
its own spawn: the recorded frames the replay sends are untouched, which is what keeps
a fully-offered trace byte-identical to today.

Zero runtime dependencies: stdlib only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.replay.client import ANSWERED, DEFAULT_TIMEOUT, FrameOutcome, replay_turn

#: The JSON-RPC ids the probe's two requests carry. They are `belay-probe-`-prefixed
#: strings rather than small integers so that nothing in a reply stream can be
#: confused for an answer to a recorded frame: the probe's conversation is its own.
_INITIALIZE_ID = "belay-probe-initialize"
_TOOLS_LIST_ID = "belay-probe-tools-list"

#: The protocol version the handshake offers. Matched to the fixtures and to the
#: version the rest of the repo speaks; a server that wants another one negotiates
#: down in its reply, which the probe does not read — it only needs `tools/list`.
_PROTOCOL_VERSION = "2025-11-25"


def probe_frames() -> list[bytes]:
    """The three frames the probe sends, in order — and nothing else, ever.

    An `initialize`, the `notifications/initialized` a conforming client owes the
    server before it may call anything, and a `tools/list`. No recorded frame and no
    `tools/call`: the probe asks a question of the boundary, it does not take part in
    the conversation being replayed.
    """
    return [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": _INITIALIZE_ID,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "belay-probe", "version": "1"},
                },
            }
        ).encode("utf-8"),
        json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        ).encode("utf-8"),
        json.dumps(
            {"jsonrpc": "2.0", "id": _TOOLS_LIST_ID, "method": "tools/list"}
        ).encode("utf-8"),
    ]


def _tool_names(reply: bytes) -> Optional[set[str]]:
    """The tool names in a `tools/list` reply, or `None` when it cannot be read.

    Fail-closed at every step. A reply that is not JSON, is not an object, carries an
    `error` instead of a `result`, whose `result` is not an object, whose `result` has
    no `tools`, whose `tools` is not a list, or any of whose entries is not an object
    with a string `name` — every one of those is `None`. The only path to a set is a
    reply that was read all the way through, so `set()` can only ever mean the
    boundary said it offers nothing.
    """
    try:
        message = json.loads(reply)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict):
        return None
    result = message.get("result")
    if not isinstance(result, dict):
        return None
    tools = result.get("tools")
    if not isinstance(tools, list):
        return None
    names: set[str] = set()
    for entry in tools:
        if not isinstance(entry, dict):
            return None
        name = entry.get("name")
        if not isinstance(name, str):
            return None
        names.add(name)
    return names


def _offered_from_outcomes(outcomes: Sequence[FrameOutcome]) -> Optional[set[str]]:
    """Read the probe's answer off a replayed conversation's outcomes.

    The answer is the reply to the `tools/list` frame — identified by the frame the
    probe sent, not by position, so a conversation that ended early (the server died
    after the handshake) has no `tools/list` outcome to find and is `None` rather than
    an off-by-one read of the initialize reply.
    """
    wanted = probe_frames()[2]
    for outcome in outcomes:
        if outcome.frame != wanted:
            continue
        if outcome.status != ANSWERED or outcome.reply is None:
            return None
        return _tool_names(outcome.reply)
    return None


def offered_tools(
    argv: Sequence[str],
    *,
    snapshot_manifest: Path | str,
    source_root: Optional[str] = None,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[set[str]]:
    """What this boundary offers: a set of tool names, `set()`, or `None`.

    `argv` must be the argv the replay itself spawns — ALREADY resolved through
    `engine.resolve_server_argv`, so the probe and the replay ask the same boundary.
    Resolving it here would be a second substitution site, and two copies of a rooting
    rule both produce *a* verdict, just not the same one.

    `snapshot_manifest`, `source_root`, `network` and `timeout` are handed to
    `client.replay_turn` untouched: the probe gets its OWN restore into its OWN scratch
    and its OWN spawn, and sends only `probe_frames()`. It never touches the recorded
    conversation.

    Returns:
        - a set of names — the boundary answered and this is what it offers;
        - `set()` — the boundary answered, and it offers nothing;
        - `None` — the probe could not run (spawn failure, unsupported platform,
          unrestorable snapshot) or its answer could not be read (no reply, timeout,
          the server died, unparseable bytes, a reply with no `result.tools`).

    It never raises. The caller is `verify_turn`, and an exception escaping into the
    verdict path would turn a verdict into a crash — worse than the false FAIL this
    exists to fix. Every failure is the same honest `None`, and `None` is never
    `set()`: "we could not read the boundary" is not "the boundary offers nothing".
    """
    try:
        result = replay_turn(
            list(argv),
            snapshot_manifest=snapshot_manifest,
            frames=probe_frames(),
            network=network,
            timeout=timeout,
            source_root=source_root,
        )
    except BaseException:  # noqa: BLE001 - see the docstring: never raise into a verdict
        return None
    try:
        return _offered_from_outcomes(result.outcomes)
    except BaseException:  # noqa: BLE001
        return None


__all__ = ["offered_tools", "probe_frames"]
