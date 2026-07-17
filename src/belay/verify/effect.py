"""A2 effect-conformance: the observed filesystem effect vs the declared annotation.

Result-equivalence (Task 2) asks *"did the reply reproduce?"*. This asks a different,
independent question: *"did the tool's OBSERVED effect match what it DECLARED?"*. A tool
that said `readOnlyHint: true` and then mutated the filesystem on replay is a grounded
FAIL, with no model anywhere. This is the verdict axis that exists ONLY because Belay
proxies MCP, where annotations are declared contracts — the wedge's payoff, named in
CLAUDE.md as "the readOnlyHint that mutates -> FAIL with zero LLM".

**The whole discipline, in one line: an absent contract is NOT a permissive one.** A tool
that declared no `readOnlyHint` cannot be verified for conformance — UNVERIFIED, never
PASS. Defaulting an un-annotated tool to "it never claimed read-only, so a mutation is
fine -> PASS" is the exact false pass the tri-state (C1) was built to prevent. The
tri-state (declared-true / declared-false / not-declared / declared-non-boolean) already
lives in the trace; this module READS it per-turn and applies the rule. It never
re-introduces a default — the spec defaults appear nowhere here, deliberately.

The rule, over the turn's `readOnlyHint` state and the replay's `delta`:

    declared-true    + a NON-EMPTY delta   -> FAIL   (declared read-only, observed a write)
    declared-true    + an EMPTY delta       -> PASS   (declared read-only, honoured it)
    declared-true    + NO delta observed    -> UNVERIFIED (cannot confirm; never PASS)
    declared-false   (any delta)            -> PASS   (declared it may mutate; nothing to violate)
    not-declared                            -> UNVERIFIED (no contract to check against)
    declared-non-boolean                    -> UNVERIFIED (no readable contract)

`declared-false` is always PASS because there is no read-only contract to violate — the
tool announced it mutates, so any observed effect (or none) conforms.

## The part C4 must build: per-turn annotation correlation

There is no helper that returns "the annotation state for turn N", so `annotation_for_turn`
builds it, mirroring `annotations._uncovered_calls`:

1. The turn's tool name is the request-frame's `params.name` (the `tools/call` at the
   turn's `request_seq`).
2. The applicable snapshot is the MOST RECENT `annotation_snapshot` with
   `source_seq < request_seq` — the contract in force WHEN the call happened, not a later
   re-snapshot (annotations can change mid-session via `tools/list_changed`). Using the
   latest snapshot instead is the subtle bug the correlation test guards against.
3. If there is no such snapshot, or the tool is absent from it, or the request frame is
   unreadable, the annotation is NOT-DECLARED for this turn -> UNVERIFIED, with a named
   cause (never "absent" reported as a bare default).

Incoherence (a tool declaring `destructiveHint`/`idempotentHint` alongside
`readOnlyHint: true`) is carried onto the verdict as a FACT — surfaced, not resolved. It
never changes the status; the status is decided by `readOnlyHint` vs the delta.

## Independence

Effect-conformance produces its OWN Verdict. It does NOT reduce with result-equivalence
here — the per-turn composition (a later task) reduces them. So an un-annotated tool is
UNVERIFIED for effect while result-equivalence independently yields its own PASS/FAIL.

Zero runtime dependencies: stdlib only; `mcp` is never imported (the import guard enforces
it). No model is imported — the verdict is grounded in the declared contract and the
re-executed diff, never a judge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.annotations import derive_annotations
from belay.declared import (
    DECLARED_FALSE,
    DECLARED_NON_BOOLEAN,
    DECLARED_TRUE,
    NOT_DECLARED,
    declared_state,
)
from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.engine import replay_turn
from belay.snapshot.bth1 import FieldDiff
from belay.verify.verdict import Status, Verdict

#: This module speaks only for the replay axis. A1 (invariants) and A3 (claim
#: re-derivation) are other capabilities; the reduction folds them in by status alone.
_AXIS = "A2"
_KIND = "effect"

#: The one annotation this check grounds on. `readOnlyHint` is the declared contract a
#: filesystem delta can confirm or refute; the other three are recorded but not checked
#: against the delta here.
_HINT = "readOnlyHint"


@dataclass(frozen=True)
class TurnAnnotation:
    """The `readOnlyHint` contract in force for one turn, plus the facts around it.

    `readonly` is the tri-state dict `declared.declared_state` produces — `{"state": ...}`
    (and `"declared_value"` for a non-boolean). `snapshot_seq` is the `source_seq` of the
    snapshot that was in force (or `None` when none was), which is what the correlation
    test asserts on. `incoherence` rides along to be surfaced on the verdict. `cause`
    names why the contract is not-declared, when it is, so a downstream UNVERIFIED can
    say WHY rather than assert a bare absence.
    """

    tool: Optional[str]
    readonly: dict
    incoherence: list = field(default_factory=list)
    snapshot_seq: Optional[int] = None
    cause: Optional[str] = None


def _tool_name(record: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """`(name, cause)` — the `params.name` off a `tools/call` request frame.

    Mirrors `annotations._uncovered_calls`: an unreadable frame or non-object `params`
    (JSON-RPC 2.0 permits positional params) yields `(None, cause)`, never a fabricated
    name. The cause is carried so an UNVERIFIED can say we never learned the name rather
    than assert the snapshot lacked the tool.
    """
    if record is None:
        return None, "the tools/call has no recorded request frame to read a tool name from"
    message, cause = message_of(record)
    if cause is not None:
        return None, f"the tools/call request frame could not be read: {cause}"
    params = message.get("params") if isinstance(message, dict) else None
    if not isinstance(params, dict):
        return None, (
            "the tools/call request's params could not be read as an object "
            "(JSON-RPC 2.0 permits positional params), so the tool name was never observed"
        )
    name = params.get("name")
    if not isinstance(name, str):
        return None, "the tools/call request declared no string tool name"
    return name, None


def annotation_for_turn(records: Sequence[dict], n: int) -> TurnAnnotation:
    """The `readOnlyHint` contract in force for the Nth `tools/call`.

    Picks the turn by `method == "tools/call"` (index `n`), reads its tool name, and
    correlates it against the MOST RECENT snapshot whose `source_seq` precedes the call's
    `request_seq`. A missing snapshot, an absent tool, or an unreadable request all yield
    a not-declared contract WITH a named cause — never a manufactured default.
    """
    records = list(records)
    index = derive_correlation(records)
    calls = tool_calls(index)
    if n < 0 or n >= len(calls):
        raise ValueError(
            f"no tools/call at index {n}: the trace holds {len(calls)} tool call(s)"
        )

    entry = calls[n]
    request_seq = entry["request_seq"]
    if request_seq is None:
        return TurnAnnotation(
            tool=None,
            readonly=declared_state(None, False),
            cause="the tools/call has no recorded request frame to correlate an annotation to",
        )

    by_seq = {r["seq"]: r for r in records if r.get("kind") == "frame"}
    name, name_cause = _tool_name(by_seq.get(request_seq))
    if name_cause is not None:
        return TurnAnnotation(
            tool=name, readonly=declared_state(None, False), cause=name_cause
        )

    snapshots = sorted(
        (d for d in derive_annotations(records) if d["kind"] == "annotation_snapshot"),
        key=lambda d: d["source_seq"],
    )
    # The contract in force WHEN the call happened: the latest snapshot that PRECEDES it.
    # `>= request_seq` snapshots are a later re-snapshot and must not be read back over
    # a call that predates them — that is the correlation bug the test guards.
    live = [s for s in snapshots if s["source_seq"] < request_seq]
    if not live:
        return TurnAnnotation(
            tool=name,
            readonly=declared_state(None, False),
            cause=(
                "no tools/list response was captured before this call, so this tool's "
                "readOnlyHint is not-declared for want of observation rather than by the "
                "server's choice"
            ),
        )

    snapshot = live[-1]
    facts = next((t for t in snapshot["tools"] if t["name"] == name), None)
    if facts is None:
        return TurnAnnotation(
            tool=name,
            readonly=declared_state(None, False),
            snapshot_seq=snapshot["source_seq"],
            cause=(
                "the tool is absent from the most recent tools/list snapshot "
                f"(seq {snapshot['source_seq']}), so its readOnlyHint is not-declared"
            ),
        )

    return TurnAnnotation(
        tool=name,
        readonly=facts["annotations"][_HINT],
        incoherence=facts["incoherence"],
        snapshot_seq=snapshot["source_seq"],
    )


def _paths(delta: Sequence[FieldDiff]) -> list[str]:
    """The distinct paths a delta touched, decoded for a human-readable message.

    `surrogateescape` so a non-UTF-8 path bytes round-trips into the string rather than
    raising — the same discipline BTH-1 uses to keep path bytes honest.
    """
    return [
        p.decode("utf-8", "surrogateescape")
        for p in sorted({fd.path for fd in delta})
    ]


def _incoherence_note(incoherence: Sequence[dict]) -> str:
    """A trailing clause naming incoherent annotations — surfaced, never resolved."""
    if not incoherence:
        return ""
    named = ", ".join(sorted({i["annotation"] for i in incoherence}))
    return (
        f" (note: incoherent annotations declared alongside readOnlyHint:true, "
        f"surfaced not resolved: {named})"
    )


def render_effect_verdict(
    records: Sequence[dict], n: int, delta: Optional[list[FieldDiff]]
) -> Verdict:
    """Turn the Nth turn's declared `readOnlyHint` and observed `delta` into an A2 verdict.

    Pure: it re-runs nothing and consults no model. `delta` is the BTH-1 tree diff from
    replay — a non-empty list means the tool touched the filesystem, an empty list means
    it did not, and `None` means no effect was observed at all (nothing to ground a PASS
    on). The verdict's `expected` carries the declared contract (the readOnlyHint state
    and any incoherence); `observed` carries the effect that was seen.
    """
    ann = annotation_for_turn(records, n)
    state = ann.readonly["state"]
    tool = ann.tool
    incoherence = ann.incoherence
    contract = {"readOnlyHint": ann.readonly, "incoherence": incoherence}
    note = _incoherence_note(incoherence)

    if state == DECLARED_TRUE:
        if delta is None:
            return Verdict(
                _AXIS, _KIND, Status.UNVERIFIED,
                observed=None, expected=contract,
                message=(
                    f"effect-conformance UNVERIFIED: tool {tool!r} declared "
                    f"readOnlyHint: true, but replay observed no filesystem delta to "
                    f"confirm it against; a PASS requires observing no mutation" + note
                ),
            )
        if delta:
            paths = _paths(delta)
            return Verdict(
                _AXIS, _KIND, Status.FAIL,
                observed=paths, expected=contract,
                message=(
                    f"effect-conformance FAIL: tool {tool!r} declared readOnlyHint: true "
                    f"but replay observed a filesystem mutation at {paths}" + note
                ),
            )
        return Verdict(
            _AXIS, _KIND, Status.PASS,
            observed=[], expected=contract,
            message=(
                f"effect-conformance PASS: tool {tool!r} declared readOnlyHint: true and "
                f"replay observed no filesystem mutation" + note
            ),
        )

    if state == DECLARED_FALSE:
        return Verdict(
            _AXIS, _KIND, Status.PASS,
            observed=_paths(delta) if delta else [], expected=contract,
            message=(
                f"effect-conformance PASS: tool {tool!r} declared readOnlyHint: false "
                f"(it may mutate); the observed effect conforms — there is no read-only "
                f"contract to violate"
            ),
        )

    if state == DECLARED_NON_BOOLEAN:
        return Verdict(
            _AXIS, _KIND, Status.UNVERIFIED,
            observed=_paths(delta) if delta else None, expected=contract,
            message=(
                f"effect-conformance UNVERIFIED: tool {tool!r} declared readOnlyHint as a "
                f"non-boolean ({ann.readonly.get('declared_value')!r}); a contract cannot "
                f"be read off it, so conformance cannot be verified — never PASS"
            ),
        )

    # NOT_DECLARED: an absent contract is not a permissive one. This is the false PASS the
    # whole capability exists to refuse.
    return Verdict(
        _AXIS, _KIND, Status.UNVERIFIED,
        observed=_paths(delta) if delta else None, expected=contract,
        message=(
            f"effect-conformance UNVERIFIED: tool {tool!r} did not declare readOnlyHint "
            f"({ann.cause}); an absent contract cannot be verified for conformance — "
            f"never PASS"
        ),
    )


def verify_effect(
    records: Sequence[dict],
    n: int,
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Verdict:
    """Replay the Nth `tools/call` for its delta, then render the effect-conformance verdict.

    The orchestrator: one replay produces the observed filesystem delta, which
    `render_effect_verdict` weighs against the tool's declared `readOnlyHint`. The
    annotation correlation reads the trace, not the replay, so the two are composed here
    rather than coupled.
    """
    reply = replay_turn(
        records, n,
        server_command=server_command, manifest_dir=manifest_dir,
        network=network, timeout=timeout,
    )
    return render_effect_verdict(records, n, reply.delta)


__all__ = [
    "TurnAnnotation",
    "annotation_for_turn",
    "render_effect_verdict",
    "verify_effect",
]
