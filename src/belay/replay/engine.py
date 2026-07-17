"""Single-turn replay: restore a recorded turn's pre-state, re-invoke it, diff.

This is the first real re-execution. C1 recorded every frame; C2 snapshotted each
turn's pre-state; the earlier replay tasks joined the snapshot to disk (`persist`),
read the trace back (`reader`), and built the client half that spawns a server and
awaits a reply (`client`). `replay_turn` here composes all of it: take a trace's
records, pick the Nth `tools/call`, restore the pre-state it ran against, send the
recorded frames to a fresh server, and capture what actually happened — the reply,
and the field-level delta of the workspace.

**C3 OBSERVES; IT DOES NOT JUDGE.** Everything this module emits is raw material for
A2's verdict, which is C4's. There is no PASS/FAIL here, on purpose: a judge's guess
gets cheaper to fool every year, and a re-executed diff does not. The observations
are `replayed` (with a delta and a result-equivalence fact), `unverified` (the
pre-state could not be restored, named cause, and — the load-bearing part — **no
re-invocation happened and no result was fabricated**), and `not-verifiable` (no
snapshot was ever attempted, so there is nothing to restore).

## Read the status FIRST, and key on `tools/call` — never on the handle

Two traps sit at the front door and both manufacture false confidence:

- A `state_handle` of `present` on a frame does **not** mean that frame is a
  replayable turn. A batched `initialize` claims `present` too. So the turn is
  selected from `index.tool_calls(...)` — `method == "tools/call"` — and the handle
  is read off *that* frame, never used to find it.
- The three handle statuses are not interchangeable. `absent` is "no snapshot was
  attempted" — un-snapshotted, not a failure, and it is emitted as `not-verifiable`
  rather than as an `unverified` with a cause it never had. `unrestorable` carries a
  recorded cause string that is emitted verbatim: in particular the gate's own
  `UNRESTORABLE_SNAPSHOT_FAILED` is deliberately **not** an `UnrestorableCause`
  member, so it is never round-tripped through that enum — doing so throws, and the
  cause is carried as the string it already is.

## The handshake is replayed if present, tolerated if absent

Under MCP 2026-07-28 there is no `initialize`/`initialized` handshake (SEP-2575);
the per-request `_meta` carries what a stateless server needs. So the recorded
handshake frames are gathered and sent before the target *if they exist*, and the
target is sent alone if they do not. A fresh server may negotiate a *different*
protocol version than the one recorded — that is a **finding**
(`recorded_version` vs `replayed_version`), never an error to swallow.

## Zero runtime dependencies

stdlib only; the scratch-restore and sandboxed spawn are reused from `client`, the
state diff from `bth1`, the pre-state from `persist` + `substrate`. `mcp` is never
imported (the import guard enforces it).
"""

from __future__ import annotations

import base64
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.connection import derive_connection_context
from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import ANSWERED, DEFAULT_TIMEOUT, FrameOutcome
from belay.replay.client import replay_turn as _client_replay_turn
from belay.replay.persist import load_snapshot
from belay.snapshot.bth1 import FieldDiff, diff_records, scan_tree
from belay.snapshot.substrate import guarded_restore

#: The turn was re-invoked against its restored pre-state. Carries the delta, the
#: result-equivalence observation, and any version-drift finding.
REPLAYED = "replayed"
#: The pre-state could not be restored (`unrestorable` handle). Carries the recorded
#: cause verbatim and NO result — nothing was re-invoked, nothing was fabricated.
UNVERIFIED = "unverified"
#: No snapshot was ever attempted (`absent` handle). There is nothing to restore, so
#: the turn is simply un-snapshotted — distinct from `unverified`, which names a
#: restore that was attempted and failed.
NOT_VERIFIABLE = "not-verifiable"

#: The prefix on the cause of a `present` turn that WAS re-invoked but whose server
#: never answered the target frame (it exited, timed out, or the frame had no usable
#: id). Such a turn produced no result to compare, so it is UNVERIFIED — keyed on the
#: REPLAY outcome's status, never the recorded side — and this is the stable label the
#: report buckets it under, carried verbatim like the gate's SNAPSHOT_FAILED string
#: rather than round-tripped through any enum.
UNANSWERED_TARGET = "the re-invoked server did not answer the target frame"

#: The replayed reply and the recorded reply are the same message.
EQUAL = "equal"
#: They differ. What that MEANS is C4's to decide; C3 only reports that they do.
DIVERGED = "diverged"

_HANDSHAKE_METHODS = ("initialize", "notifications/initialized")


@dataclass(frozen=True)
class TurnReplay:
    """What replaying one recorded turn observed — never a verdict.

    `status` is one of `REPLAYED` / `UNVERIFIED` / `NOT_VERIFIABLE`. The other
    fields are populated as that status allows: `cause` names why an `unverified` or
    `not-verifiable` turn was not re-invoked; `delta`, `result_equivalence`,
    `recorded_reply`, `replayed_reply`, `workspace` and the version fields describe a
    `replayed` turn. `reinvoked` says plainly whether a server was actually spawned —
    the positive control that keeps "no result" from being read as "replay is broken".
    """

    turn_index: int
    status: str
    cause: Optional[str] = None
    reinvoked: bool = False
    delta: Optional[list[FieldDiff]] = None
    result_equivalence: Optional[str] = None
    recorded_reply: Optional[bytes] = None
    replayed_reply: Optional[bytes] = None
    recorded_version: Optional[Any] = None
    replayed_version: Optional[Any] = None
    version_drift: bool = False
    workspace: Optional[str] = None
    outcomes: Optional[list[FrameOutcome]] = None


def _frames_by_seq(records: Sequence[dict]) -> dict[int, dict]:
    return {r["seq"]: r for r in records if r.get("kind") == "frame"}


def _method_of(record: dict) -> Optional[str]:
    message, _cause = message_of(record)
    return message.get("method") if isinstance(message, dict) else None


def _manifest_for(handle: Any, manifest_dir: Path) -> Optional[Path]:
    """The persisted manifest whose recorded handle is `handle`, or `None`.

    The trace records only the handle; `persist_snapshot` wrote a manifest per turn
    naming it. Resolving by scanning the directory keeps the engine independent of
    how the gate names the files on disk.
    """
    for path in sorted(Path(manifest_dir).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if data.get("handle") == handle:
            return path
    return None


def _recorded_version(records: Sequence[dict], target_seq: int) -> Any:
    """The protocol version in force for the target frame, or `None`.

    Resolved by `derive_connection_context`, which reads the handshake or the
    per-request `_meta` in the one order the connection module allows — never a
    guess, never a value smeared back over frames that predate it.
    """
    for ctx in derive_connection_context(list(records)):
        if ctx.get("kind") != "connection_context" or ctx.get("seq") != target_seq:
            continue
        resolution = ctx.get("protocol_version") or {}
        if resolution.get("status") == "resolved":
            return resolution.get("value")
        return None
    return None


def _replayed_version(outcomes: Sequence[FrameOutcome]) -> Any:
    """The version a replayed `initialize` response negotiated, or `None`.

    A stateless (2026-07-28) replay sends no `initialize`, so there is no negotiated
    version to read — `None` then, which is not drift, just nothing to compare.
    """
    for outcome in outcomes:
        if outcome.reply is None:
            continue
        try:
            message = json.loads(outcome.reply)
        except ValueError:
            continue
        result = message.get("result") if isinstance(message, dict) else None
        if isinstance(result, dict) and "protocolVersion" in result:
            return result["protocolVersion"]
    return None


def _equivalence(recorded: Optional[Any], replayed: Optional[bytes]) -> Optional[str]:
    """`EQUAL` / `DIVERGED`, or `None` when there is nothing to compare.

    Compared as parsed messages, not raw bytes: two servers may serialise the same
    result with different key order, and whether *that* matters is C4's call. `None`
    is honest — a turn with no recorded reply, or no replayed one, has no
    equivalence fact, and inventing one would be the fabrication this module refuses.
    """
    if recorded is None or replayed is None:
        return None
    try:
        return EQUAL if recorded == json.loads(replayed) else DIVERGED
    except ValueError:
        return DIVERGED


def replay_turn(
    records: Sequence[dict],
    n: int,
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> TurnReplay:
    """Replay the Nth recorded `tools/call` against its restored pre-state.

    Picks the turn by `method == "tools/call"` (never by the state handle), reads the
    handle off *that* frame, and:

    - `absent` handle -> `NOT_VERIFIABLE`, no re-invocation. Un-snapshotted, not failed.
    - `unrestorable` handle -> `UNVERIFIED` naming the recorded cause verbatim, no
      re-invocation, no result. The cause string is carried as-is (the gate's
      `UNRESTORABLE_SNAPSHOT_FAILED` is not an `UnrestorableCause` member).
    - `present` handle -> restore the pre-state, gather the recorded handshake frames
      if any, send them and the target to a fresh sandboxed server, and capture the
      reply, the field-level workspace delta, the result-equivalence observation, and
      any protocol-version drift.

    Emits observations only. C4 renders the verdict.
    """
    index = derive_correlation(list(records))
    calls = tool_calls(index)
    if n < 0 or n >= len(calls):
        raise ValueError(
            f"no tools/call at index {n}: the trace holds {len(calls)} tool call(s)"
        )

    by_seq = _frames_by_seq(records)
    target_entry = calls[n]
    target_seq = target_entry["request_seq"]
    if target_seq is None or target_seq not in by_seq:
        # A response-without-request correlation: no request frame to replay.
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause="the tools/call has no recorded request frame to re-invoke",
        )
    target_record = by_seq[target_seq]
    handle = target_record.get("state_handle") or {}
    status = handle.get("status")

    if status == "absent":
        return TurnReplay(
            turn_index=n,
            status=NOT_VERIFIABLE,
            cause="no snapshot was attempted for this turn; there is no pre-state to restore",
        )
    if status == "unrestorable":
        # Carry the recorded cause string exactly. NEVER `UnrestorableCause(cause)`:
        # the gate's own SNAPSHOT_FAILED cause is deliberately not a member and the
        # enum would throw. This is the point where "UNVERIFIED is never PASS" is code.
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause=handle.get("cause"),
        )
    if status != "present":
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause=f"unrecognised state_handle status {status!r}; the pre-state cannot be restored",
        )

    target_message, target_cause = message_of(target_record)
    if target_cause is not None:
        # The frame the trace kept is not readable, so it cannot be faithfully
        # re-sent. Honest unverified rather than sending half a frame as if it were
        # whole.
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause=f"the tools/call frame could not be read: {target_cause}",
        )

    manifest_path = _manifest_for(handle.get("handle"), manifest_dir)
    if manifest_path is None:
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause=(
                f"no persisted snapshot manifest for handle {handle.get('handle')!r}; "
                "the pre-state cannot be restored in this process"
            ),
        )

    frames_to_send, target_index = _gather_frames(records, by_seq, target_seq, target_record)

    # Pre-state: a fresh, deterministic restore of the same snapshot. Restore is
    # byte-identical by construction (C2's guarantee), so this equals the state the
    # server's own scratch copy starts from — the honest baseline for the delta.
    snap = load_snapshot(manifest_path)
    pre_dir = Path(tempfile.mkdtemp(prefix="belay-replay-pre-"))
    guarded_restore(snap, pre_dir)
    before = scan_tree(pre_dir)

    result = _client_replay_turn(
        list(server_command),
        snapshot_manifest=manifest_path,
        frames=frames_to_send,
        network=network,
        timeout=timeout,
    )
    # The delta is a real before/after diff ONLY when the replay produced a post-state to
    # scan. A missing workspace means no post-state was ever observed, so there is nothing
    # to diff — `delta` is `None` (-> effect UNVERIFIED), NEVER `[]`. An empty delta must
    # mean "scanned the post-state and saw no mutation"; manufacturing one from
    # `diff_records(before, before)` would let a readOnlyHint:true tool read as effect PASS
    # on a post-state that was never observed — the exact false PASS this project refuses.
    # The delta is a real before/after diff ONLY when the replay produced a post-state to
    # scan. A missing workspace means no post-state was ever observed, so there is nothing
    # to diff — `delta` is `None` (-> effect UNVERIFIED), NEVER `[]`. An empty delta must
    # mean "scanned the post-state and saw no mutation"; manufacturing one from
    # `diff_records(before, before)` would let a readOnlyHint:true tool read as effect PASS
    # on a post-state that was never observed — the exact false PASS this project refuses.
    if result.workspace is not None:
        delta = diff_records(before, scan_tree(result.workspace))
    else:
        delta = None
    # The internal baseline restore is ours alone (the client's scratch is the
    # post-state the caller owns; this pre_dir is not). Drop it now that `before` is
    # captured — otherwise a whole-trace, N-replay run leaks a temp dir per replay.
    shutil.rmtree(pre_dir, ignore_errors=True)

    # Key the status on the REPLAY outcome, never the recorded side. A `present` turn
    # whose re-invoked server never ANSWERED the target — it exited, timed out, or the
    # frame had no usable id — produced no result to compare and must not read as a
    # clean `replayed` with a null reply (that is the false-clean shape C3 exists to
    # catch). It is UNVERIFIED with a named cause, and stays honest that a server WAS
    # spawned. The benign converse — the RECORDING had no reply but the replay DID
    # answer — keeps `ANSWERED` here and stays `replayed`.
    target_outcome = (
        result.outcomes[target_index]
        if 0 <= target_index < len(result.outcomes)
        else None
    )
    if target_outcome is None or target_outcome.status != ANSWERED:
        reason = target_outcome.status if target_outcome is not None else "target frame not reached"
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            reinvoked=True,
            cause=f"{UNANSWERED_TARGET}: {reason}",
            delta=delta,
            workspace=result.workspace,
            outcomes=result.outcomes,
        )

    replayed_reply = target_outcome.reply
    response_seq = target_entry.get("response_seq")
    recorded_record = by_seq.get(response_seq) if response_seq is not None else None
    recorded_reply = (
        base64.b64decode(recorded_record["raw"]) if recorded_record is not None else None
    )
    recorded_parsed = message_of(recorded_record)[0] if recorded_record is not None else None

    recorded_version = _recorded_version(records, target_seq)
    replayed_version = _replayed_version(result.outcomes)
    version_drift = (
        recorded_version is not None
        and replayed_version is not None
        and recorded_version != replayed_version
    )

    return TurnReplay(
        turn_index=n,
        status=REPLAYED,
        reinvoked=True,
        delta=delta,
        result_equivalence=_equivalence(recorded_parsed, replayed_reply),
        recorded_reply=recorded_reply,
        replayed_reply=replayed_reply,
        recorded_version=recorded_version,
        replayed_version=replayed_version,
        version_drift=version_drift,
        workspace=result.workspace,
        outcomes=result.outcomes,
    )


def _gather_frames(
    records: Sequence[dict],
    by_seq: dict[int, dict],
    target_seq: int,
    target_record: dict,
) -> tuple[list[bytes], int]:
    """The client->server frames to replay: the recorded handshake, then the target.

    The handshake frames (`initialize`, `notifications/initialized`) are sent before
    the target *only if the trace captured them* — a 2026-07-28 trace has none, and
    the target's `_meta` carries what a stateless server needs. Sent as the exact
    bytes that crossed the wire; a truncated handshake frame is dropped rather than
    sent incomplete.
    """
    frames: list[bytes] = []
    for seq in sorted(by_seq):
        if seq > target_seq:
            break
        record = by_seq[seq]
        if record.get("dir") != "c2s" or seq == target_seq:
            continue
        if record.get("truncated"):
            continue
        if _method_of(record) in _HANDSHAKE_METHODS:
            frames.append(base64.b64decode(record["raw"]))
    frames.append(base64.b64decode(target_record["raw"]))
    return frames, len(frames) - 1


__all__ = [
    "DIVERGED",
    "EQUAL",
    "NOT_VERIFIABLE",
    "REPLAYED",
    "UNANSWERED_TARGET",
    "UNVERIFIED",
    "TurnReplay",
    "replay_turn",
]
