"""Tool annotations, snapshotted from `tools/list` as DECLARED — never as defaulted.

MCP tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) are the one thing on this wire that is a *declared contract*: a
tool that says `readOnlyHint: true` and then mutates state is a grounded finding
with no model in the loop. That makes them worth recording exactly, and it makes
one particular shortcut expensive.

**A default is not a declaration.** The spec gives each annotation a fail-safe
default — `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint:
false`, `openWorldHint: true`. Those defaults are correct for deciding how to
*treat* an unknown tool, and they are wrong to write into a trace, because they
erase the difference between "the server said it is not read-only" and "the
server said nothing". Downstream, an un-annotated tool recorded as
`readOnlyHint: false` licenses the reasoning *"it mutated, and it never claimed
read-only, therefore fine -> PASS"* — a PASS manufactured by a default, about a
tool whose only honest verdict is UNVERIFIED. So this module records
`declared-true` / `declared-false` / `not-declared`, and **the spec defaults
appear nowhere in this file** — not even as a constant, which is deliberate:
there is nothing here for a future edit to reach for.

Snapshots are **appended and timestamped, never overwritten**. A server may
change its tools mid-session and announce it with
`notifications/tools/list_changed`, so "which contract was live when that call
happened?" only stays answerable if every snapshot survives with its time on it.

**This module does not judge.** Incoherent annotations are recorded as a fact and
left unresolved; no tool is called safe, dangerous, or allowed here.
"""

from __future__ import annotations

from typing import Any, Optional

from belay.declared import DECLARED_TRUE, NOT_DECLARED, declared_state
from belay.frames import message_of
from belay.index import classify, derive_correlation

KINDS = ("annotation_snapshot", "annotation_staleness", "annotation_gap")

ANNOTATIONS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# `destructiveHint` and `idempotentHint` are, per the spec, "meaningful only when
# readOnlyHint == false". Declaring them alongside `readOnlyHint: true` is
# therefore incoherent — a fact worth recording and NOT worth resolving here.
_MEANINGFUL_ONLY_WHEN_MUTABLE = ("destructiveHint", "idempotentHint")
_INCOHERENCE_RULE = "meaningful only when readOnlyHint == false"


def _incoherence(states: dict[str, dict]) -> list[dict]:
    if states["readOnlyHint"]["state"] != DECLARED_TRUE:
        return []
    return [
        {"annotation": annotation, "rule": _INCOHERENCE_RULE, "readOnlyHint": DECLARED_TRUE}
        for annotation in _MEANINGFUL_ONLY_WHEN_MUTABLE
        if states[annotation]["state"] != NOT_DECLARED
    ]


def _tool_facts(tool: Any) -> Optional[dict]:
    if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
        return None
    declared = tool.get("annotations")
    has_object = isinstance(declared, dict)
    states = {
        annotation: (
            declared_state(declared.get(annotation), annotation in declared)
            if isinstance(declared, dict)
            else declared_state(None, False)
        )
        for annotation in ANNOTATIONS
    }
    return {
        "name": tool["name"],
        # Kept separately from the per-annotation states: "carried no annotations
        # object" and "carried an empty one" are different things a server did,
        # and both produce four `not-declared`s.
        "annotations_object": "present" if has_object else "absent",
        "annotations": states,
        "incoherence": _incoherence(states),
    }


_UNREADABLE_TOOLS = (
    "tools/list response carried no readable `result.tools` array"
)

# Distinct from the cause below it on purpose. "We could not read the request" and
# "the snapshot does not describe this tool" are different findings, and reporting
# the first as the second would assert the server omitted a tool it may well have
# declared. A fabricated cause is worse than a blunt one.
_UNREADABLE_PARAMS = (
    "the tools/call request's `params` could not be read as an object (JSON-RPC 2.0 "
    "permits positional params), so the tool name was never observed and no snapshot "
    "can be matched to this call"
)


def _frames_by_seq(records: list[dict]) -> dict[int, dict]:
    return {r["seq"]: r for r in records if r.get("kind") == "frame"}


def derive_annotations(records: list[dict]) -> list[dict]:
    """Snapshot every `tools/list` response; name every gap.

    `tools/list` responses are found through correlation rather than by looking
    for a method on them, because responses carry no method. That is the whole
    reason correlation is derived first.
    """
    frames = _frames_by_seq(records)
    index = derive_correlation(records)
    out: list[dict] = []

    for entry in index:
        if entry["kind"] != "correlation" or entry.get("method") != "tools/list":
            continue
        if entry["response_seq"] is None:
            continue
        record = frames[entry["response_seq"]]
        message, cause = message_of(record)
        # Each `.get` is guarded on its own: the `{}` default covers an ABSENT
        # key, never a present-but-wrong-typed one. `"result":"oops"` is legal
        # JSON, and chaining through it used to raise out of this function
        # entirely — taking every other tool's snapshot with it.
        result = message.get("result") if isinstance(message, dict) else None
        tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(tools, list):
            out.append(
                {
                    "kind": "annotation_gap",
                    "seq": record["seq"],
                    "tool": None,
                    # `cause` is None on every path that reaches here today: a
                    # frame only correlates if it already parsed once. Preferring
                    # it anyway costs nothing and means that if that coupling ever
                    # changes, this reports the decode failure rather than the
                    # misleading "carried no readable array".
                    "cause": cause if cause is not None else _UNREADABLE_TOOLS,
                }
            )
            continue
        out.append(
            {
                "kind": "annotation_snapshot",
                "source_seq": record["seq"],
                # When we OBSERVED the contract, which is all we can honestly
                # claim about when it was live.
                "t_snapshot": record["t_in"],
                "tools": [f for f in (_tool_facts(t) for t in tools) if f is not None],
            }
        )

    out.extend(_staleness(records, out))
    out.extend(_uncovered_calls(records, index, frames, out))
    return out


def _staleness(records: list[dict], derived: list[dict]) -> list[dict]:
    """`list_changed` with no re-snapshot after it: the contract is known stale.

    Recorded rather than implied. A reader that saw only the earlier snapshot
    would otherwise verify later calls against a contract the server has already
    announced it no longer honours.
    """
    snapshots = [d["source_seq"] for d in derived if d["kind"] == "annotation_snapshot"]
    out = []
    for record in records:
        if record.get("kind") != "frame":
            continue
        # The cause is deliberately not carried here, and this is the one place
        # in the module where that is right. A staleness record is a claim that a
        # `list_changed` WAS observed; a frame we could not read gives us no such
        # observation, and inventing a staleness from one would be a fabrication.
        # The unreadable frame is not lost either way: `derive_correlation` names
        # every one of them with an `index_gap`.
        message, _unreadable = message_of(record)
        if not isinstance(message, dict) or classify(message) != "notification":
            continue
        if message.get("method") != "notifications/tools/list_changed":
            continue
        if not any(seq > record["seq"] for seq in snapshots):
            out.append(
                {
                    "kind": "annotation_staleness",
                    "seq": record["seq"],
                    "cause": (
                        "notifications/tools/list_changed observed; no later tools/list "
                        "response was captured, so no snapshot describes the tools as "
                        "they are after this point"
                    ),
                }
            )
    return out


def _uncovered_calls(
    records: list[dict], index: list[dict], frames: dict[int, dict], derived: list[dict]
) -> list[dict]:
    """A `tools/call` for a tool no snapshot describes: not-declared WITH a cause.

    The named cause is the point. Without it this call is indistinguishable from
    one whose tool genuinely declared nothing, and downstream cannot tell "the
    server declined to say" from "we never asked".
    """
    snapshots = sorted(
        (d for d in derived if d["kind"] == "annotation_snapshot"),
        key=lambda d: d["source_seq"],
    )
    out = []
    for entry in index:
        if entry["kind"] != "correlation" or entry.get("method") != "tools/call":
            continue
        if entry["request_seq"] is None:
            continue
        message, cause = message_of(frames[entry["request_seq"]])
        params = message.get("params") if isinstance(message, dict) else None
        if not isinstance(params, dict):
            # We failed to read the request. Falling through to `name = None`
            # would reach the "absent from the most recent snapshot" cause below
            # and assert something about the server that we did not observe.
            # As above, `cause` is None on every path that reaches here today.
            out.append(
                {
                    "kind": "annotation_gap",
                    "seq": entry["request_seq"],
                    "tool": None,
                    "cause": cause if cause is not None else _UNREADABLE_PARAMS,
                }
            )
            continue
        name = params.get("name")
        live = [s for s in snapshots if s["source_seq"] < entry["request_seq"]]
        if not live:
            out.append(
                {
                    "kind": "annotation_gap",
                    "seq": entry["request_seq"],
                    "tool": name,
                    "cause": (
                        "no tools/list response was captured before this call, so this "
                        "tool's annotations are not-declared for want of observation "
                        "rather than by the server's choice"
                    ),
                }
            )
        elif not any(t["name"] == name for t in live[-1]["tools"]):
            out.append(
                {
                    "kind": "annotation_gap",
                    "seq": entry["request_seq"],
                    "tool": name,
                    "cause": (
                        "the tool is absent from the most recent tools/list snapshot "
                        f"(seq {live[-1]['source_seq']})"
                    ),
                }
            )
    return out
