"""Is a tool replayable to the same result at all? — classify, never judge.

C3's engine (`replay.engine`) replays ONE recorded turn against its restored
pre-state. This module answers the prior question it depends on: **does the tool
produce the same result every time, or does it diverge across identical replays?**
That distinction is load-bearing, and it is where C2's sharpest warning lands:

    "Never let a timestamp diff render as FAIL — that's how you train users to
    ignore the verifier."

A clock-dependent or random tool diverges on re-execution **legitimately**. That is
*nondeterminism, not a fabricated trace.* If C3 reported it as a divergence/FAIL,
C4's verdict would fill with noise and users would learn to ignore the verifier. So
the whole point of replaying N times is this: divergence *across identical replays*
means the tool is **nondeterministic**, never that the trace was tampered with.

**Nondeterminism is a classification, never a verdict. C3 emits no PASS/FAIL** — C4
decides what the classification means. This module produces the honest raw material
and nothing more.

## Why N, and why 3

Each replay is a fresh scratch restore of the *same* pre-state (`engine.replay_turn`
guarantees it), so all N runs start byte-identical — which is exactly what makes a
divergence between them meaningful rather than an artifact of drifting inputs. N is
configurable, default **3**: N=2 cannot tell a one-off flake from a genuinely random
tool (with two samples they are indistinguishable), so 3 is the floor that separates
them.

## Naming the axis — a fact, never a guess

When a turn is nondeterministic and the divergence is legible, the axis is named as
one of C3's three inherited `UnrestorableCause` values — the causes `substrate`
declares C3 owns because a running process, an entropy source and the wall clock are
all invisible to a filesystem snapshot:

- monotone, timestamp-shaped divergence -> `UNRESTORABLE_WALL_CLOCK`
- hex/entropy-shaped divergence          -> `UNRESTORABLE_RANDOMNESS`
- small-integer (pid-shaped) divergence  -> `UNRESTORABLE_RUNNING_PROCESS`

The axis is a *fact about why the tool cannot be re-derived*, exactly as a substrate
cause is a fact about what could not be restored — never a verdict. **"Nondeterministic,
axis unknown" is a valid, honest outcome**; an axis is named only when it can be
shown, never guessed (`detect_axis` returns `None` when the divergence is illegible).

## The mark is appended to a SIBLING, never the source trace

The trace is append-only and A4 is absolute: *replay never mutates the original
trace.* So the `nondeterminism` record (the kind C1 reserved at `trace.py:52`) is
written to a **sibling** artifact through the writer's own envelope, never back into
the source. An older reader skips the unknown kind and records the skip
(`test_trace_reader.py`); a C4-aware reader understands it. Forward-compat holds.

## Zero runtime dependencies

stdlib only; `engine.replay_turn` does the re-execution, `TraceWriter.record` writes
the sibling mark. `mcp` is never imported (the import guard enforces it).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.engine import REPLAYED, TurnReplay, replay_turn
from belay.snapshot.substrate import UnrestorableCause
from belay.trace import TraceWriter

#: Every replay produced the same result. The tool is a pure function of its
#: restored pre-state and arguments — replayable, and A2 can speak to it.
DETERMINISTIC = "deterministic"
#: The result differed across identical replays. Legitimate divergence, NOT
#: infidelity — the axis (when legible) says why. A classification, never a FAIL.
NONDETERMINISTIC = "nondeterministic"
#: The turn could not be replayed at all (the engine returned something other than
#: REPLAYED — an unrestorable pre-state, or no snapshot). Determinism is undefined,
#: so it is not claimed; the engine's status and cause are carried through.
NOT_REPLAYABLE = "not-replayable"

#: A run of hex long enough to be entropy rather than a coincidence, requiring at
#: least one hex letter so a pure-decimal value (a clock or a pid) is not mistaken
#: for randomness.
_HEX = re.compile(rb"^[0-9a-fA-F]{8,}$")
_HAS_HEX_LETTER = re.compile(rb"[a-fA-F]")
_DECIMAL = re.compile(rb"^[0-9]+$")
#: Maximal alphanumeric runs — the "tokens" whose per-column variation across runs
#: is what names an axis. Structural JSON (braces, keys) is constant across runs and
#: falls away; only the value token moves.
_TOKEN = re.compile(rb"[A-Za-z0-9]+")

#: A timestamp value is long (epoch seconds are 10 digits; nanoseconds 19) — short
#: decimals are pids, not clocks.
_CLOCK_MIN_DIGITS = 10


@dataclass(frozen=True)
class DeterminismResult:
    """What replaying a turn N times observed about its determinism — never a verdict.

    `classification` is `DETERMINISTIC` / `NONDETERMINISTIC` / `NOT_REPLAYABLE`.
    `replays` is how many times the turn was actually re-invoked. `axis` names the
    source of a nondeterministic divergence when it is legible, and is `None`
    otherwise — including for a deterministic tool, which has no axis. `tool` is the
    tool name from the recorded call. When the turn was not replayable,
    `replay_status` and `cause` carry the engine's reason through unchanged.
    `record` is the `nondeterminism` mark appended to the sibling artifact (its
    fields, as written), and `artifact_path` is where it landed — both `None` when
    no artifact path was given.
    """

    turn_index: int
    classification: str
    replays: int
    tool: Optional[str] = None
    axis: Optional[UnrestorableCause] = None
    replies: Optional[list[Optional[bytes]]] = None
    replay_status: Optional[str] = None
    cause: Optional[str] = None
    record: Optional[dict] = None
    artifact_path: Optional[str] = None


def _tool_name(records: Sequence[dict], n_turn: int) -> Optional[str]:
    """The `params.name` of the Nth recorded `tools/call`, or `None`.

    Resolved the same way the engine picks the turn — by `method == "tools/call"`,
    never by the state handle — so the name names the exact frame that gets replayed.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if n_turn < 0 or n_turn >= len(calls):
        return None
    request_seq = calls[n_turn].get("request_seq")
    if request_seq is None:
        return None
    for record in records:
        if record.get("kind") != "frame" or record.get("seq") != request_seq:
            continue
        message, _cause = message_of(record)
        if isinstance(message, dict):
            params = message.get("params")
            if isinstance(params, dict):
                name = params.get("name")
                return name if isinstance(name, str) else None
    return None


def _signature(outcome: TurnReplay) -> tuple:
    """A comparable fingerprint of one replay: its reply AND its state delta.

    Two runs are "the same result" only if both the reply and the field-level
    workspace delta match — a tool that diverges *only* in the files it writes (a
    timestamped log, say) is nondeterministic too. The reply is compared parsed, not
    as raw bytes, matching the engine's own equivalence: two serialisations of one
    message must not read as a divergence. An unparseable reply falls back to its raw
    bytes rather than being coerced.
    """
    reply = outcome.replayed_reply
    if reply is not None:
        try:
            parsed: Any = json.loads(reply)
        except ValueError:
            parsed = reply
    else:
        parsed = None
    return (parsed, outcome.delta)


def _classify_column(column: list[bytes]) -> Optional[UnrestorableCause]:
    """The axis a single varying token column points at, or `None` if illegible.

    Conservative by design — an axis is named only when the shape *shows* it:

    - all values are long hex WITH a hex letter -> entropy (`RANDOMNESS`)
    - all values are long decimals that strictly increase -> a clock (`WALL_CLOCK`)
    - all values are short decimals -> process identity, pid-shaped (`RUNNING_PROCESS`)

    Anything else is `None`: a guessed axis would be the false confidence this
    project refuses.
    """
    if all(_HEX.match(v) for v in column) and any(_HAS_HEX_LETTER.search(v) for v in column):
        return UnrestorableCause.UNRESTORABLE_RANDOMNESS
    if all(_DECIMAL.match(v) for v in column):
        if all(len(v) >= _CLOCK_MIN_DIGITS for v in column):
            values = [int(v) for v in column]
            if all(b > a for a, b in zip(values, values[1:])):
                return UnrestorableCause.UNRESTORABLE_WALL_CLOCK
            # Long decimals that do not increase are not demonstrably a clock; do
            # not guess. (A pid is short, so this is not the pid case either.)
            return None
        return UnrestorableCause.UNRESTORABLE_RUNNING_PROCESS
    return None


def detect_axis(replies: Sequence[Optional[bytes]]) -> Optional[UnrestorableCause]:
    """Best-effort: the axis a set of divergent replies points at, or `None`.

    The replies are tokenised into maximal alphanumeric runs and aligned column by
    column; structural JSON and constant values (the request id, key names) do not
    vary and fall away, leaving the value token(s) that moved. Each varying column is
    classified, and an axis is named only when every legible column agrees — a reply
    that diverges in two unrelated ways (a clock *and* a pid) is honestly "axis
    unknown" rather than arbitrarily one of them.

    `None` is a valid, honest outcome: the tool is nondeterministic, and we cannot
    show why. Never a guess.
    """
    present = [r for r in replies if r is not None]
    if len(present) < 2:
        return None
    token_lists = [_TOKEN.findall(r) for r in present]
    lengths = {len(t) for t in token_lists}
    if len(lengths) != 1:
        # Structurally different replies cannot be aligned token-for-token; the
        # divergence is real but its axis is not legible this way.
        return None

    axes: set[UnrestorableCause] = set()
    for column in zip(*token_lists):
        values = list(column)
        if len(set(values)) == 1:
            continue  # constant across runs — not a source of divergence
        axis = _classify_column(values)
        if axis is not None:
            axes.add(axis)
    return axes.pop() if len(axes) == 1 else None


def _write_mark(
    artifact_path: Path,
    *,
    turn: int,
    tool: Optional[str],
    classification: str,
    replays: int,
    axis: Optional[UnrestorableCause],
    replies: Sequence[Optional[bytes]],
) -> dict:
    """Append one `nondeterminism` record to the sibling artifact; return its fields.

    Written through `TraceWriter.record` so the mark carries the writer's envelope
    (`v`, `seq`, `t_in`) rather than a hand-rolled shape that could drift from the
    format. The differing results are base64'd — lossless, and never decoded as text,
    the same discipline the trace applies to `raw`. The source trace is untouched:
    this is a *different* file, which is how A4 ("replay never mutates the original
    trace") is kept by construction rather than by care.
    """
    fields = {
        "turn": turn,
        "tool": tool,
        "classification": classification,
        "replays": replays,
        "axis": axis.value if axis is not None else None,
        "results": [
            base64.b64encode(r).decode("ascii") if r is not None else None
            for r in replies
        ],
    }
    writer = TraceWriter(Path(artifact_path))
    try:
        writer.record("nondeterminism", **fields)
    finally:
        writer.close()
    return fields


def classify_determinism(
    records: Sequence[dict],
    n_turn: int,
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    replays: int = 3,
    artifact_path: Path | str | None = None,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> DeterminismResult:
    """Replay the Nth recorded `tools/call` `replays` times and classify its determinism.

    Each replay is delegated to `engine.replay_turn`, which restores the same
    pre-state into a fresh scratch copy — so every run starts byte-identical and a
    divergence between them is the tool's, not the input's. Then:

    - the underlying turn is not replayable (the engine returns anything but
      `REPLAYED`) -> `NOT_REPLAYABLE`, carrying the engine's status and cause. There
      is nothing to classify and nothing is claimed; further replays are skipped
      because a pre-state that could not be restored will not restore on the retry.
    - every replay yields the same reply-and-delta -> `DETERMINISTIC`.
    - the results differ across runs -> `NONDETERMINISTIC`, with the axis named when
      the divergence is legible (clock/random/pid) and `None` when it is not.

    When `artifact_path` is given, a `nondeterminism` mark is appended there (never to
    the source trace) for a classified turn. Emits a classification only — **no
    verdict**. C4 decides what it means.
    """
    if replays < 2:
        raise ValueError(
            f"replays must be at least 2 to distinguish divergence from a single "
            f"sample (got {replays}); the default is 3"
        )

    tool = _tool_name(records, n_turn)

    outcomes: list[TurnReplay] = []
    for _ in range(replays):
        outcome = replay_turn(
            records,
            n_turn,
            server_command=server_command,
            manifest_dir=manifest_dir,
            network=network,
            timeout=timeout,
        )
        outcomes.append(outcome)
        if outcome.status != REPLAYED:
            # The pre-state could not be restored (or was never snapshotted). Every
            # further replay would return the same non-result; determinism is
            # undefined, so it is not claimed.
            return DeterminismResult(
                turn_index=n_turn,
                classification=NOT_REPLAYABLE,
                replays=len(outcomes),
                tool=tool,
                replay_status=outcome.status,
                cause=outcome.cause,
            )

    replies = [o.replayed_reply for o in outcomes]
    signatures = [_signature(o) for o in outcomes]
    all_equal = all(sig == signatures[0] for sig in signatures[1:])

    if all_equal:
        classification: str = DETERMINISTIC
        axis: Optional[UnrestorableCause] = None
    else:
        classification = NONDETERMINISTIC
        axis = detect_axis(replies)

    record: Optional[dict] = None
    resolved_path: Optional[str] = None
    if artifact_path is not None:
        record = _write_mark(
            Path(artifact_path),
            turn=n_turn,
            tool=tool,
            classification=classification,
            replays=replays,
            axis=axis,
            replies=replies,
        )
        resolved_path = str(artifact_path)

    return DeterminismResult(
        turn_index=n_turn,
        classification=classification,
        replays=replays,
        tool=tool,
        axis=axis,
        replies=replies,
        record=record,
        artifact_path=resolved_path,
    )


__all__ = [
    "DETERMINISTIC",
    "NONDETERMINISTIC",
    "NOT_REPLAYABLE",
    "DeterminismResult",
    "classify_determinism",
    "detect_axis",
]
