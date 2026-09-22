"""C10 aspect `surfaces` — the verify-loop integration of the triage seam, kept pure.

Everything the `belay verify` per-turn loop needs that is not argparse and not
I/O lives here, so the loop stays a thin composition and the honesty rules have
one home:

- `build_turn_features` derives one turn's `TriageFeatures` from the trace's own
  records — **whitelisted derived fields only** (tool name, tri-state annotation
  declarations, offered toolset, reply size and hashes, indices/ids, ordering,
  truncated flag, state-handle status, protocol version, `run_process`
  command_line). Raw state or trace bytes are structurally unrepresentable, and
  `TriageFeatures.to_payload` asserts the emitted key set against
  `WHITELISTED_KEYS` — a turn whose only useful signal would require raw egress
  is not triaged (it goes to full replay).
- `skipped_verdict` builds the skipped turn's `TurnVerdict` — UNVERIFIED with the
  verbatim budget cause, never PASS, never WARN — the ONLY verdict this module
  constructs, and it is the budget module's own named stamp.
- `triage_section` builds the additive `triage` document section the JSON report
  and the text line both render from (one computation, two renderers); `None`
  when triage never ran — absent-never-zero, the `approval` precedent.

This module has no verdict authority: it never decides what to replay
(`belay.verify.triage_budget.decide_replays` does) and never scores a turn
(`belay.verify.triage` does). Stdlib plus the seams it consumes; no subprocess.
"""

from __future__ import annotations

import base64
from typing import Any, Mapping, Optional, Sequence

from belay.annotations import derive_annotations
from belay.connection import derive_connection_context
from belay.declared import DECLARED_FALSE, DECLARED_TRUE
from belay.frames import message_of
from belay.verify.triage import TriageFeatures
from belay.verify.triage_budget import SKIPPED_BY_BUDGET_CAUSE
from belay.verify.turn import TurnVerdict
from belay.verify.verdict import Status, Verdict


def _annotation_state(state: str) -> Optional[bool]:
    """Tri-state: declared-true -> True, declared-false -> False, everything else
    (not-declared, declared-non-boolean) -> None. A default is never a declaration."""
    if state == DECLARED_TRUE:
        return True
    if state == DECLARED_FALSE:
        return False
    return None


def _frames_by_seq(records: Sequence[dict]) -> dict[int, dict]:
    return {r["seq"]: r for r in records if r.get("kind") == "frame"}


def _snapshot_tool_facts(
    annotations: Sequence[dict], request_seq: int
) -> tuple[dict[str, dict], tuple[str, ...]]:
    """The tool facts from the LATEST tools/list snapshot before the call, and the
    toolset that snapshot offered. Neither exists -> empty facts, empty toolset:
    not-declared for want of observation, which is the honest tri-state input."""
    snapshots = [
        d for d in annotations
        if d.get("kind") == "annotation_snapshot" and d.get("source_seq", -1) < request_seq
    ]
    if not snapshots:
        return {}, ()
    latest = max(snapshots, key=lambda d: d["source_seq"])
    by_name = {f["name"]: f for f in latest["tools"]}
    offered = tuple(t["name"] for t in latest["tools"])
    return by_name, offered


def _trace_ids(connection: Sequence[dict], request_seq: int) -> tuple[str, str]:
    """The W3C traceparent ids on the request frame, split out, or ("", "")."""
    for ctx in connection:
        if ctx.get("kind") == "trace_context" and ctx.get("seq") == request_seq:
            tp = ctx.get("traceparent")
            if isinstance(tp, str):
                parts = tp.split("-")
                if len(parts) == 4:
                    return parts[1], parts[2]
            return "", ""
    return "", ""


def _protocol_version(connection: Sequence[dict], request_seq: int) -> str:
    """The negotiated protocol version in force at the request frame, or ""."""
    for ctx in connection:
        if ctx.get("kind") == "connection_context" and ctx.get("seq") == request_seq:
            resolved = ctx.get("protocol_version")
            if isinstance(resolved, dict) and resolved.get("status") == "resolved":
                value = resolved.get("value")
                return value if isinstance(value, str) else ""
            return ""
    return ""


def build_turn_features(
    records: Sequence[dict],
    calls: Sequence[dict],
    n: int,
    *,
    annotations: Optional[Sequence[dict]] = None,
    connection: Optional[Sequence[dict]] = None,
) -> TriageFeatures:
    """One turn's whitelisted derived features, from the trace's own records.

    `calls` is the `tool_calls(derive_correlation(records))` index the caller
    already holds; `annotations`/`connection` are the shared derivations
    (`derive_annotations` / `derive_connection_context`), precomputed once by
    the caller so per-turn feature building does not re-derive the whole trace.
    Every field is a derived scalar; raw state or trace bytes never appear.
    """
    entry = calls[n]
    request_seq = entry.get("request_seq")
    response_seq = entry.get("response_seq")
    frames = _frames_by_seq(records)
    annotations = derive_annotations(list(records)) if annotations is None else annotations
    connection = (
        derive_connection_context(list(records)) if connection is None else connection
    )

    tool_name = ""
    command_line: Optional[str] = None
    if request_seq is not None and request_seq in frames:
        message, _unreadable = message_of(frames[request_seq])
        params = message.get("params") if isinstance(message, dict) else None
        if isinstance(params, dict):
            name = params.get("name")
            tool_name = name if isinstance(name, str) else ""
            arguments = params.get("arguments")
            if isinstance(arguments, dict):
                cl = arguments.get("command_line")
                command_line = cl if isinstance(cl, str) else None

    by_name, offered = _snapshot_tool_facts(annotations, request_seq)
    fact = by_name.get(tool_name) if tool_name else None
    read_only: Optional[bool] = None
    destructive: Optional[bool] = None
    idempotent: Optional[bool] = None
    open_world: Optional[bool] = None
    annotations_present = False
    if fact is not None:
        states = fact["annotations"]
        read_only = _annotation_state(states["readOnlyHint"]["state"])
        destructive = _annotation_state(states["destructiveHint"]["state"])
        idempotent = _annotation_state(states["idempotentHint"]["state"])
        open_world = _annotation_state(states["openWorldHint"]["state"])
        annotations_present = fact["annotations_object"] == "present"

    reply_size = 0
    hash_raw = ""
    hash_canonical = ""
    truncated = False
    if response_seq is not None and response_seq in frames:
        response = frames[response_seq]
        reply_size = len(base64.b64decode(response["raw"]))
        hash_raw = response.get("hash_raw") or ""
        hash_canonical = response.get("hash_canonical") or ""
        truncated = bool(response.get("truncated"))

    state_handle_status = ""
    if request_seq is not None and request_seq in frames:
        handle = frames[request_seq].get("state_handle")
        if isinstance(handle, dict):
            status = handle.get("status")
            state_handle_status = status if isinstance(status, str) else ""

    trace_id, span_id = _trace_ids(connection, request_seq)

    return TriageFeatures(
        tool_name=tool_name,
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
        annotations_present=annotations_present,
        offered_toolset=offered,
        reply_size=reply_size,
        hash_raw=hash_raw,
        hash_canonical=hash_canonical,
        turn_index=n,
        request_seq=request_seq if request_seq is not None else 0,
        ordering=n,
        truncated=truncated,
        state_handle_status=state_handle_status,
        trace_id=trace_id,
        span_id=span_id,
        protocol_version=_protocol_version(connection, request_seq),
        command_line=command_line,
    )


def skipped_verdict(n: int, tool_name: Optional[str]) -> TurnVerdict:
    """A skipped turn's verdict: UNVERIFIED with the verbatim budget cause.

    Nothing was re-executed, so A2 has nothing to verify — the honest claim is
    UNVERIFIED-by-budget with the exact cause string the budget module names
    (`"skipped by the triage budget"`), never PASS, never WARN, and never a
    fabricated replay. The single sub-verdict mirrors the non-replayed shape
    (`belay.verify.turn._unverifiable_verdict`): one A2/replay UNVERIFIED
    verdict, with the cause carried verbatim on the `TurnVerdict`.
    """
    return TurnVerdict(
        turn_index=n,
        tool_name=tool_name,
        status=Status.UNVERIFIED,
        sub_verdicts=[
            Verdict(
                "A2",
                "replay",
                Status.UNVERIFIED,
                observed=None,
                expected=None,
                message=(
                    "turn UNVERIFIED: the replay budget skipped this turn "
                    f"({SKIPPED_BY_BUDGET_CAUSE}); a turn that was not replayed is "
                    "never a pass"
                ),
            )
        ],
        cause=SKIPPED_BY_BUDGET_CAUSE,
        replayed_is_error=None,
    )


def triage_section(
    score_by_turn: Mapping[int, Optional[Any]],
    *,
    scope: Sequence[int],
    threshold: Optional[float],
    top_n: Optional[int],
    replay_indices: Optional[frozenset[int]],
) -> Optional[dict]:
    """The additive `triage` section, or None when triage never ran.

    Present iff a triage command was configured for the run — absent-never-zero,
    the `approval` precedent. `mode` is `budgeted` when either knob was set and
    `shadow` otherwise; `skipped` counts the scope turns the budget skipped;
    `scores` records the score of every SCORED turn in scope — replayed rows
    unchanged, skipped rows marked `"skipped": true` (so the future calibration
    ledger can audit what the budget skipped) — and an abstention (None) is NOT
    a score of 0 and stays absent. Shadow mode has no skipped turns, so no row
    gains a marker: the shadow section is byte-identical to v0.36.0's.
    `threshold`/`top_n` appear only when set.
    """
    if replay_indices is None:
        return None
    mode = "budgeted" if (threshold is not None or top_n is not None) else "shadow"
    skipped = sum(1 for n in scope if n not in replay_indices)
    section: dict[str, Any] = {
        "mode": mode,
        "skipped": skipped,
        "scores": [
            {
                "ordinal": n,
                "score": score.score,
                "confidence": score.confidence,
                **({"skipped": True} if n not in replay_indices else {}),
            }
            for n in scope
            if (score := score_by_turn.get(n)) is not None
        ],
    }
    if threshold is not None:
        section["threshold"] = threshold
    if top_n is not None:
        section["top_n"] = top_n
    return section


__all__ = [
    "build_turn_features",
    "skipped_verdict",
    "triage_section",
]