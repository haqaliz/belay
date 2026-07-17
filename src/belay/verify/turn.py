"""The per-turn verdict: C3's replay status folded together with the two A2 checks.

C3's `engine.replay_turn` OBSERVES one turn (did the reply reproduce, what did the
filesystem do), and Tasks 2 and 3 each turn one observation into a grounded A2
sub-verdict — result-equivalence (*"did the result reproduce?"*) and effect-conformance
(*"did the observed effect match the declared contract?"*). Neither is the turn's answer
on its own. This module composes them into ONE `TurnVerdict` that carries BOTH
sub-verdicts and the single reduced status, so the report can still say *which* check
drove a FAIL.

## The composition, and the one place it must not cut a corner

`verify_turn` replays the turn ONCE, then branches on the replay `status`:

- **REPLAYED** — the turn was re-invoked against its restored pre-state. Both A2 checks
  run and reduce worst-status-wins. The single replay is threaded through both:
  `render_result_verdict` scores the reply (with the determinism gate consulted ONLY on a
  DIVERGED reply, never on a match — a match is a reproduction at one replay, and
  classifying it would triple the replay cost for nothing), and `render_effect_verdict`
  weighs the same replay's `delta` against the declared `readOnlyHint`. One replay, two
  grounded verdicts.
- **UNVERIFIED / NOT_VERIFIABLE** — nothing was re-invoked, so there is NOTHING for A2 to
  have a PASS/FAIL about. The turn is UNVERIFIED, full stop, carrying the engine's cause.

**That last branch is the whole point, and the easiest thing here to get wrong.** A naive
composition writes `status = FAIL if any FAIL else PASS`; on a turn whose pre-state could
not be restored — or that was never snapshotted at all — no check ran, nothing is FAIL,
and it reports **PASS**. That is the exact false pass this project exists to prevent: a
turn we could not verify, rendered clean. So a non-REPLAYED turn is UNVERIFIED **directly**,
not by defaulting. `NOT_VERIFIABLE` (an absent snapshot handle — no snapshot was ever
attempted) and `UNVERIFIED` (a restore that was attempted and failed) both collapse to a
turn-level UNVERIFIED, but their causes are kept DISTINCT, so a later failure corpus never
conflates "nobody snapshotted this" with "the restore broke".

## Causes are carried verbatim, never coerced

The engine's cause string is carried as-is and bucketed with `report.canonical_cause` —
total and never-empty — so the failure corpus stays consistent. In particular the gate's
`UNRESTORABLE_SNAPSHOT_FAILED` is deliberately NOT an `UnrestorableCause` enum member;
this module never round-trips a cause through that enum (doing so throws), and never
imports it. `canonical_cause` maps that string to itself, so it survives verbatim.

Zero runtime dependencies: stdlib only; the re-execution is C3's, the two sub-verdicts are
Tasks 2/3's, the reduction is Task 1's. No model is imported — the verdict is grounded in
re-execution and the declared contract, never a judge. `mcp` is never imported (the import
guard enforces it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.determinism import DeterminismResult, classify_determinism
from belay.replay.engine import DIVERGED, REPLAYED, TurnReplay, replay_turn
from belay.replay.report import canonical_cause
from belay.verify.effect import render_effect_verdict
from belay.verify.result import render_result_verdict
from belay.verify.verdict import Status, Verdict, reduce

#: The axis and kind stamped on the single sub-verdict of a turn that could not be
#: replayed at all. It speaks for the replay axis (A2) — nothing was re-executed, so the
#: honest claim is "the replay could not speak to this turn", never a result or effect.
_AXIS = "A2"
_KIND = "replay"


@dataclass(frozen=True)
class TurnVerdict:
    """One turn's composed verdict — the reduced status AND the sub-verdicts behind it.

    `status` is the reduced Status (worst-status-wins across the sub-verdicts, with
    UNVERIFIED outranking PASS/WARN). `sub_verdicts` are the grounded Verdict(s) that
    drove it: both A2 checks for a REPLAYED turn, one UNVERIFIED verdict otherwise —
    carried so the report can answer "why did this turn FAIL?" rather than assert a bare
    status. `cause` names why a non-REPLAYED turn could not be verified (the canonical
    bucket, never empty); it is `None` for a REPLAYED turn, whose sub-verdicts already
    explain it.
    """

    turn_index: int
    tool_name: Optional[str]
    status: Status
    sub_verdicts: list[Verdict] = field(default_factory=list)
    cause: Optional[str] = None


def _tool_name(records: Sequence[dict], n: int) -> Optional[str]:
    """The Nth `tools/call`'s declared tool name, or `None` if it was never observed.

    Selects the turn by the correlation index (`method == tools/call`), then reads the
    `params.name` off that exact request frame — never used to FIND the turn. Mirrors
    `report._tool_name`; kept local so this module owns its own read of the trace.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if not (0 <= n < len(calls)):
        return None
    request_seq = calls[n].get("request_seq")
    if request_seq is None:
        return None
    for record in records:
        if record.get("kind") != "frame" or record.get("seq") != request_seq:
            continue
        message, _cause = message_of(record)
        if isinstance(message, dict):
            params = message.get("params")
            if isinstance(params, dict) and isinstance(params.get("name"), str):
                return params["name"]
    return None


def _unverifiable_verdict(reply: TurnReplay) -> tuple[Verdict, str]:
    """The single UNVERIFIED sub-verdict (and canonical cause) for a non-REPLAYED turn.

    No check ran because nothing was re-invoked. The engine's cause is carried VERBATIM
    into the message and bucketed by `canonical_cause` for the `cause` field — never
    coerced through `UnrestorableCause` (the gate's `UNRESTORABLE_SNAPSHOT_FAILED` is not
    a member and would throw). `canonical_cause` is total, so the bucket is never empty.
    """
    raw = reply.cause
    bucket = canonical_cause(raw)
    detail = raw if raw is not None else bucket
    verdict = Verdict(
        _AXIS, _KIND, Status.UNVERIFIED,
        observed=None, expected=None,
        message=(
            f"turn UNVERIFIED: the pre-state could not be restored and re-invoked, so "
            f"A2 has no result or effect to verify ({detail}); a turn that was not "
            f"replayed is never a pass"
        ),
    )
    return verdict, bucket


def verify_turn(
    records: Sequence[dict],
    n: int,
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    replays: int = 3,
) -> TurnVerdict:
    """Compose the Nth `tools/call`'s per-turn verdict — replay once, both A2 checks, reduce.

    Replays the turn a SINGLE time. On a REPLAYED turn both A2 checks run against that one
    replay (the determinism gate consulting the classifier only on a DIVERGED reply) and
    reduce worst-status-wins. On any non-REPLAYED status the turn is UNVERIFIED directly —
    nothing was re-invoked, so A2 verified nothing, and an un-restored or un-snapshotted
    turn must never fall through to PASS. Emits a grounded verdict; no model anywhere.
    """
    tool_name = _tool_name(records, n)
    reply = replay_turn(
        records, n,
        server_command=server_command, manifest_dir=manifest_dir,
        network=network, timeout=timeout,
    )

    if reply.status != REPLAYED:
        verdict, bucket = _unverifiable_verdict(reply)
        return TurnVerdict(
            turn_index=n,
            tool_name=tool_name,
            status=Status.UNVERIFIED,
            sub_verdicts=[verdict],
            cause=bucket,
        )

    # REPLAYED: both A2 checks share the one replay. The classifier is consulted ONLY on a
    # DIVERGED reply — a match is a reproduction at one replay, and classifying it would
    # triple the replay cost for nothing (Task 2's cost discipline, threaded through here).
    determinism: Optional[DeterminismResult] = None
    if reply.result_equivalence == DIVERGED:
        determinism = classify_determinism(
            records, n,
            server_command=server_command, manifest_dir=manifest_dir,
            replays=replays, network=network, timeout=timeout,
        )
    result_verdict = render_result_verdict(reply, determinism)
    effect_verdict = render_effect_verdict(records, n, reply.delta)
    sub_verdicts = [result_verdict, effect_verdict]

    return TurnVerdict(
        turn_index=n,
        tool_name=tool_name,
        status=reduce(sub_verdicts),
        sub_verdicts=sub_verdicts,
        cause=None,
    )


__all__ = ["TurnVerdict", "verify_turn"]
