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
import os
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
from belay.replay.relocate import (
    canonicalize_obj,
    command_embeds_in_root_path,
    is_under,
    relocate_command_line,
    turn_needs_relocation,
)
from belay.snapshot.bth1 import FieldDiff, diff_records, scan_tree
from belay.snapshot.substrate import Unrestorable, guarded_restore

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

#: The honest fallback for the absolute-path class: a turn that carries an in-root
#: absolute path but whose manifest recorded NO `source_root` cannot be faithfully
#: relocated into the scratch, so no verdict is guessed. Carried verbatim like the
#: gate's SNAPSHOT_FAILED string — this is where UNVERIFIED-never-PASS is code for the
#: relocation axis.
ROOTLESS_RELOCATION = (
    "original workspace root not recorded; cannot relocate absolute paths"
)

#: The honesty floor for a mis-rooted replay: the manifest DID record a root, but the
#: server command handed to the replay is not rooted anywhere under it, so relocating the
#: turn's paths into the scratch would point the server outside what it can reach. A
#: rooting problem is an evaluation failure, not a violation — so the turn abstains here,
#: before any restore or spawn, rather than diverging into a fabricated FAIL (or a
#: causeless "nondeterministic tool"). Distinct from `ROOTLESS_RELOCATION`, which names the
#: opposite gap: there the root was never recorded at all.
UNROOTABLE_SERVER_COMMAND = (
    "server command is not rooted at the recorded workspace; cannot relocate"
)

#: The honesty floor for an EMBEDDED in-root path: the manifest recorded a root, but the
#: turn buries an in-root absolute path *inside* a string argument (a shell `command_line`,
#: a nested argv element) rather than as a whole-value `path`. The whole-value relocation
#: rule cannot safely rewrite it — a substring remap of an argument would corrupt content
#: written to the scratch and manufacture a false delta — so the turn abstains here, before
#: any restore or spawn, rather than replaying un-relocated against the original workspace
#: (a contaminated verdict). Distinct from `UNROOTABLE_SERVER_COMMAND` (a mis-rooted server
#: command) and `ROOTLESS_RELOCATION` (no root recorded at all): here the root is known and
#: the path is present, but embedded, so relocation of the command string is the follow-up
#: aspect's job; until it lands, every embedded-path turn is honestly UNVERIFIED.
EMBEDDED_PATH_UNRELOCATABLE = (
    "an in-root path is embedded in an argument value; cannot safely relocate"
)

#: The literal argv token an operator writes where the server's workspace allow-root
#: goes, so ONE server command can verify a batch of traces captured from DIFFERENT
#: workspaces. Before the relocation gate runs, a token EQUAL to this placeholder is
#: replaced by that turn's OWN recorded `source_root`; the existing relocation path then
#: rewrites it to the scratch exactly as it does a hand-written root, so there is one code
#: path and no second mechanism. Whole-token only — the same whole-value rule
#: `relocate.remap_argv` applies, so an embedded `--root={workspace}` is NOT substituted
#: and reads as `UNROOTABLE_SERVER_COMMAND` rather than being silently half-handled. A
#: placeholder with no recorded root is `ROOTLESS_RELOCATION`: the root genuinely was not
#: recorded, and no root is ever guessed. Cannot collide with a real argv value: the
#: substitution is exact-equality against this whole token, and a path is only ever
#: compared to it literally — nothing is expanded, formatted, or pattern-matched.
WORKSPACE_PLACEHOLDER = "{workspace}"

#: A sentinel both roots fold to when canonicalizing replies for comparison. NUL-wrapped
#: so it cannot occur in a filesystem path and thus cannot collide with real reply text.
_ROOT_PLACEHOLDER = "\x00belay-workspace-root\x00"

_HANDSHAKE_METHODS = ("initialize", "notifications/initialized")


@dataclass(frozen=True)
class ReplayBoundary:
    """The boundary a replay actually spawned — the argv, the snapshot, the root.

    A replay is an observation, and *which server produced it* is part of what was
    observed. Until now that fact was computed inside `replay_turn` and thrown away: the
    caller held only the operator-typed template, in which `{workspace}` is still a
    placeholder. So a caller that later wants to ask the same boundary a question — "do you
    even offer this tool?" — could not, without resolving `{workspace}` a second time, and
    a second copy of a rooting rule silently drifts from the first (both produce *a*
    verdict, just not the same one). This carries the resolved fact instead.

    - `argv` is the command as SPAWNED, already through `resolve_server_argv` — the one
      substitution site — before the client's relocation of in-root tokens.
    - `manifest_path` is the snapshot that was restored for this turn.
    - `source_root` is the root the manifest recorded (`None` when it recorded none).
    - `relocation_root` is what was handed to the client as `source_root`, i.e. the root
      relocation actually keyed on — `None` for a cwd-relative replay that relocates
      nothing. It is NOT the same as `source_root`: the relocation gate decides per turn.

    Reported ONLY on a `REPLAYED` status, which is the only status that got as far as
    spawning a boundary. Absent means "this observation names no boundary", never "the
    boundary was empty".
    """

    argv: tuple[str, ...]
    manifest_path: str
    source_root: Optional[str] = None
    relocation_root: Optional[str] = None


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
    #: The boundary this replay spawned, on a REPLAYED status only. See `ReplayBoundary`.
    boundary: Optional[ReplayBoundary] = None


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


def _equivalence(
    recorded: Optional[Any],
    replayed: Optional[bytes],
    *,
    from_root: Optional[str] = None,
    to_root: Optional[str] = None,
) -> Optional[str]:
    """`EQUAL` / `DIVERGED`, or `None` when there is nothing to compare.

    Compared as parsed messages, not raw bytes: two servers may serialise the same
    result with different key order, and whether *that* matters is C4's call. `None`
    is honest — a turn with no recorded reply, or no replayed one, has no
    equivalence fact, and inventing one would be the fabrication this module refuses.

    When `from_root`/`to_root` are both given (a relocated turn), both parsed messages
    are canonicalized — the recorded reply carries the ORIGINAL root, the replayed one the
    SCRATCH root, in the same string positions — so a path buried in a reply (a diff header,
    a `file://` URL) folds to one form and compares equal. The fold is applied per string
    VALUE inside the parsed structure (`canonicalize_obj`), so the comparison stays the
    key-order-independent structural `==` and never a text dump. It is **comparison-only**:
    the raw `recorded_reply`/`replayed_reply` bytes are stored unchanged; nothing is
    persisted or written to the scratch.
    """
    if recorded is None or replayed is None:
        return None
    try:
        replayed_parsed = json.loads(replayed)
    except ValueError:
        return DIVERGED
    if from_root is not None and to_root is not None:
        recorded = canonicalize_obj(recorded, from_root, to_root, _ROOT_PLACEHOLDER)
        replayed_parsed = canonicalize_obj(replayed_parsed, from_root, to_root, _ROOT_PLACEHOLDER)
    return EQUAL if recorded == replayed_parsed else DIVERGED


def _arguments_of(message: Optional[Any]) -> object:
    """The `tools/call` frame's `arguments` object, or `None` if it has none."""
    if not isinstance(message, dict):
        return None
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    return params.get("arguments")


def _arguments_hold_absolute_path(obj: object) -> bool:
    """Does `obj` hold any whole-value string that is an absolute path? (root-independent).

    The rootless companion to `turn_needs_relocation`: with no recorded root, in-root
    membership cannot be tested, so the honest signal that a turn WOULD need relocation is a
    whole-value argument string that is itself an absolute path (`os.path.isabs`). Used only
    to trip the honest-`UNVERIFIED` fallback, never to remap — without a root there is no
    prefix to swap. Conservative by construction: a content string that merely begins with a
    separator reads as absolute here and yields UNVERIFIED, never a false verdict.
    """
    if isinstance(obj, dict):
        return any(_arguments_hold_absolute_path(value) for value in obj.values())
    if isinstance(obj, list):
        return any(_arguments_hold_absolute_path(item) for item in obj)
    if isinstance(obj, str):
        return os.path.isabs(obj)
    return False


#: A sentinel destination root for the DECISION-time dry run of `relocate_command_line`
#: (`_command_relocatable`). The RELOCATED/ABSTAIN outcome is a pure function of the command
#: and the SOURCE root — the destination only supplies the rewritten bytes, which the decision
#: discards — so any value works; a fixed sentinel keeps the probe pure and self-documenting.
_RELOCATION_PROBE_ROOT = "/belay-relocation-probe"


def _command_relocatable(arguments: object, root: str) -> bool:
    """True iff every embedded in-root COMMAND path is a clean whole token (relocatable).

    The follow-on question aspect 2 adds to `command_embeds_in_root_path`. **Precondition:**
    `command_embeds_in_root_path(arguments, root)` is True — the turn buries an in-root path
    inside a `command_line` string or an `argv` element. This asks whether that embedding can be
    faithfully relocated, so the gate can LIFT aspect 1's unconditional abstain for exactly the
    tractable case and keep abstaining on the rest.

    Keyed on the SAME executed-command fields as `command_embeds_in_root_path`, so the abstain
    detector and this relocatability question can never disagree:

    - An `argv` element that contains the root but is NOT itself a whole-value path
      (`--file=/root/x`) is substring-fused residue — `relocate_command_line` cannot touch an
      argv token, so it is never relocatable → False.
    - A `command_line` string is relocatable iff `relocate_command_line` returns RELOCATED (a dry
      run against `_RELOCATION_PROBE_ROOT`; the outcome is independent of the destination root).

    Pure, no I/O. Only a top-level `dict` is inspected; any other shape is False.
    """
    if not isinstance(arguments, dict):
        return False
    root_n = os.path.normpath(root)
    argv = arguments.get("argv")
    if isinstance(argv, list):
        for element in argv:
            if isinstance(element, str) and root_n in element and not is_under(element, root):
                return False
    command_line = arguments.get("command_line")
    if isinstance(command_line, str) and root_n in command_line:
        _new, outcome = relocate_command_line(command_line, root, _RELOCATION_PROBE_ROOT)
        if outcome != "RELOCATED":
            return False
    return True


def resolve_server_argv(
    server_command: Sequence[str], source_root: Optional[str]
) -> tuple[Optional[list[str]], Optional[str]]:
    """Resolve `{workspace}` against a turn's OWN recorded root. `(argv, cause)`.

    ONE substitution site, exported, so every caller that needs the argv the replay
    actually spawns — the replay itself, and anything that later asks the same boundary a
    question — reads the same rule from the same place. A second copy of a rooting rule
    drifts silently: both copies still produce *a* verdict, just not the same one.

    - `(resolved_argv, None)` — a NEW list, with every token EQUAL to
      `WORKSPACE_PLACEHOLDER` replaced by `source_root` and every other token untouched.
      A command with no placeholder token is returned unchanged, root recorded or not.
      Whole-token only, exactly as `WORKSPACE_PLACEHOLDER` documents: an embedded
      `--root={workspace}` is NOT substituted here and reads downstream as
      `UNROOTABLE_SERVER_COMMAND` rather than being silently half-handled.
    - `(None, ROOTLESS_RELOCATION)` — a placeholder token with NO recorded root. No root
      is ever guessed, and no half-resolved argv is handed back. The cause is *returned*,
      never rendered: this function emits no verdict, so `replay_turn`'s honest
      UNVERIFIED abstention stays `replay_turn`'s to make.

    Mirrors `_relocation_decision`'s `(value, cause)` shape deliberately — the two gates
    sit next to each other in `replay_turn` and read the same way.
    """
    if WORKSPACE_PLACEHOLDER not in server_command:
        return list(server_command), None
    if source_root is None:
        return None, ROOTLESS_RELOCATION
    return [
        source_root if token == WORKSPACE_PLACEHOLDER else token
        for token in server_command
    ], None


def _relocation_decision(
    source_root: Optional[str], arguments: object, argv: Sequence[str]
) -> tuple[Optional[str], Optional[str]]:
    """Gate relocation. Return `(relocation_root, fallback_cause)`.

    - `relocation_root` is the root to hand the client, or `None` to keep today's
      byte-for-byte cwd-relative replay.
    - `fallback_cause` is set (with `relocation_root` `None`) for the honest fallbacks:
      `ROOTLESS_RELOCATION` — a turn that carries an absolute-path argument but whose
      manifest recorded no root; `UNROOTABLE_SERVER_COMMAND` — a turn that needs
      relocation, whose root WAS recorded, but whose server command holds no token under
      that root, so the command cannot be relocated with it; and
      `EMBEDDED_PATH_UNRELOCATABLE` — a recorded root IS present but the turn buries an
      in-root path *inside* a string argument (a shell `command_line`, a fused argv token)
      that cannot be safely rewritten as a clean whole token. The embedded check runs FIRST,
      before the whole-value relocation, so an embedded turn never reaches (nor misfires) the
      argv rooting check.

    **Aspect 2 lifts aspect 1's unconditional embedded abstain for the tractable case.** When
    a turn embeds an in-root command path, `_command_relocatable` asks whether that embedding
    is a clean whole shell token: if so, the turn RELOCATES (`(source_root, None)`) — and the
    argv-rooting `UNROOTABLE` guard is deliberately bypassed for it, because a relocatable
    `command_line` implies a shell server that serves ANY absolute path (it has no argv root to
    be mis-rooted). Only a genuinely un-relocatable embedding (a `--file=/root/x` residue, an
    un-lexable command) still abstains `EMBEDDED_PATH_UNRELOCATABLE`. A turn carrying a
    relocatable whole-value path AND an un-relocatable residue abstains for the WHOLE turn —
    never a partial rewrite.

    With a recorded root, the whole-value/in-root rule (`turn_needs_relocation`) decides
    exactly, so an out-of-root abs path (`/etc/hosts`) and a cwd-relative turn are both
    UNCHANGED. Without a recorded root, argv is NOT consulted — it always holds an absolute
    interpreter/server path — so the signal is an absolute-path *argument*, which a
    cwd-relative turn never carries.

    When relocation IS needed, argv is consulted for one thing only: whether any token is
    `is_under` the recorded root. If none is, the server is rooted somewhere else (or
    rootless by design) and relocating the turn's paths would hand it paths it cannot
    serve; the resulting divergence would say nothing about the recorded run. Abstaining is
    conservative on purpose — a rootless-by-design absolute-path server is marked UNVERIFIED
    too, which is a false abstention, never a false verdict.
    """
    if source_root is not None:
        if command_embeds_in_root_path(arguments, source_root):
            if not _command_relocatable(arguments, source_root):
                return None, EMBEDDED_PATH_UNRELOCATABLE
            # A relocatable embedded command path -> relocate. The argv-rooting UNROOTABLE
            # guard below assumes an argv-rooted server; a shell that serves any absolute
            # path has no such root, so it does not apply here.
            return source_root, None
        if turn_needs_relocation(arguments, list(argv), source_root):
            if not any(is_under(token, source_root) for token in argv):
                return None, UNROOTABLE_SERVER_COMMAND
            return source_root, None
        return None, None
    if _arguments_hold_absolute_path(arguments):
        return None, ROOTLESS_RELOCATION
    return None, None


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

    # Gate absolute-path relocation on the RECORDED root and the target's own arguments,
    # BEFORE any restore or spawn. A turn that needs relocation but has no recorded root is
    # the honest fallback: UNVERIFIED, named cause, no re-invocation — never a guessed
    # verdict for the absolute-path class. A cwd-relative turn decides "no relocation" and
    # keeps today's byte-for-byte path.
    snap = load_snapshot(manifest_path)
    source_root = snap.manifest.source_root
    # Resolve the server's root per TRACE, not per batch: a `{workspace}` token becomes
    # this turn's own recorded root, and everything downstream (the gate, the relocation,
    # the spawn) then sees an ordinary rooted command. Without a recorded root there is
    # nothing to substitute, and guessing one is exactly what UNVERIFIED-never-PASS forbids.
    resolved_command, rootless_cause = resolve_server_argv(server_command, source_root)
    if resolved_command is None:
        return TurnReplay(turn_index=n, status=UNVERIFIED, cause=rootless_cause)
    server_command = resolved_command
    relocation_root, fallback_cause = _relocation_decision(
        source_root, _arguments_of(target_message), server_command
    )
    if fallback_cause is not None:
        return TurnReplay(turn_index=n, status=UNVERIFIED, cause=fallback_cause)

    # Pre-state: a fresh, deterministic restore of the same snapshot. Restore is
    # byte-identical by construction (C2's guarantee), so this equals the state the
    # server's own scratch copy starts from — the honest baseline for the delta.
    #
    # The restore can refuse: a snapshot whose capability set this box's substrate
    # does not have (the cross-substrate case — banked on clonefile/APFS, replayed
    # on a copy-fidelity box, and the mirror) raises `Unrestorable` with
    # `UNRESTORABLE_CAPABILITY_MISMATCH`. That refusal is the pre-state never
    # arriving, exactly like the recorded `unrestorable` handle above: UNVERIFIED
    # with the named cause, never a crash and never a guessed restore.
    pre_dir = Path(tempfile.mkdtemp(prefix="belay-replay-pre-"))
    try:
        guarded_restore(snap, pre_dir)
    except Unrestorable as exc:
        shutil.rmtree(pre_dir, ignore_errors=True)
        return TurnReplay(
            turn_index=n,
            status=UNVERIFIED,
            cause=exc.cause.value,
        )
    before = scan_tree(pre_dir)

    result = _client_replay_turn(
        list(server_command),
        snapshot_manifest=manifest_path,
        frames=frames_to_send,
        network=network,
        timeout=timeout,
        source_root=relocation_root,
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
        result_equivalence=_equivalence(
            recorded_parsed,
            replayed_reply,
            from_root=relocation_root,
            to_root=result.workspace if relocation_root is not None else None,
        ),
        recorded_reply=recorded_reply,
        replayed_reply=replayed_reply,
        recorded_version=recorded_version,
        replayed_version=replayed_version,
        version_drift=version_drift,
        workspace=result.workspace,
        outcomes=result.outcomes,
        # Report the boundary this turn was actually replayed against, so a caller can ask
        # that same boundary a question without re-resolving `{workspace}` itself.
        boundary=ReplayBoundary(
            argv=tuple(server_command),
            manifest_path=str(manifest_path),
            source_root=source_root,
            relocation_root=relocation_root,
        ),
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
    "EMBEDDED_PATH_UNRELOCATABLE",
    "EQUAL",
    "NOT_VERIFIABLE",
    "REPLAYED",
    "ROOTLESS_RELOCATION",
    "UNANSWERED_TARGET",
    "UNROOTABLE_SERVER_COMMAND",
    "UNVERIFIED",
    "WORKSPACE_PLACEHOLDER",
    "ReplayBoundary",
    "TurnReplay",
    "replay_turn",
    "resolve_server_argv",
]
