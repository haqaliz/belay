"""Replay a whole trace and report the UNVERIFIED rate — every instance named.

`engine.replay_turn` replays ONE turn; this runs it across every recorded
`tools/call` and aggregates the result into the number the whole Phase-0 gate exists
to earn:

    ROADMAP.md:112 — "UNVERIFIED rate measured and EXPLAINED — every UNVERIFIED must
    trace to a named cause."

That sentence is the entire contract of this module, and it has two halves that are
easy to satisfy separately and hard to satisfy together:

- **Measured.** The rate is `unverified / total`, computed from real replays, not
  guessed. If it is high, that is a GATE SIGNAL — R7, the risk that UNVERIFIED
  dominates and the product shrugs. This module makes the number impossible to miss;
  it does not soften it.
- **Explained.** Every unverified turn is filed under a *named* cause. A turn that is
  unverified for no stated reason is itself a bug, so `canonical_cause` is total: it
  maps `None` and every unrecognised string to a non-empty label rather than dropping
  it. `sum(by_cause.values()) == unverified` is therefore an invariant, not a hope.

**C3 OBSERVES; it does not judge.** `replayed` / `unverified` / `not-verifiable` and
the rate are observations about *coverage*, never a PASS/FAIL — that is C4. The
UNVERIFIED rate is emphatically not a grade: a 60% unverified trace is not "60% bad",
it is "60% of turns this replay could not speak to, and here is why each one".

## not-verifiable is NOT unverified, and the rate keeps them apart

An `absent` handle means *no snapshot was ever attempted* — un-snapshotted, not
failed. It is `not-verifiable`, counted on its own line, and deliberately kept OUT of
the unverified numerator: folding it in would inflate the rate with turns that never
had a pre-state to restore, and the honest headline is about restores that were
attempted and could not be trusted, not about turns nobody tried to snapshot.

## Zero runtime dependencies, and the source trace is never touched (A4)

stdlib only; the re-execution is `engine.replay_turn`'s, the determinism
classification `determinism.classify_determinism`'s. Nothing here writes to the source
trace — the report goes to stdout — so A4 (replay never mutates the original trace)
holds by construction. `mcp` is never imported (the import guard enforces it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.determinism import classify_determinism
from belay.replay.engine import (
    NOT_VERIFIABLE,
    REPLAYED,
    UNANSWERED_TARGET,
    UNVERIFIED,
    TurnReplay,
    replay_turn,
)
from belay.replay.probe import (
    BOUNDARY_AMBIGUOUS,
    BOUNDARY_UNDECIDED,
    TOOL_NOT_OFFERED,
)
from belay.snapshot.bth1 import FieldDiff
from belay.snapshot.substrate import UnrestorableCause

#: The set of `UnrestorableCause` values, so a recorded cause that IS one is filed
#: under its own name rather than a paraphrase.
_UNRESTORABLE_VALUES = frozenset(cause.value for cause in UnrestorableCause)

#: The gate's snapshot-failure cause is deliberately NOT an `UnrestorableCause`
#: member (see `engine`/`gate`), but it is still a stable named cause — carried
#: verbatim, never round-tripped through the enum.
_SNAPSHOT_FAILED = "UNRESTORABLE_SNAPSHOT_FAILED"

#: The named cause every "the manifest for this present handle is not on disk" turn
#: is filed under — the confirmed gap this task closes. The engine's verbatim string
#: is longer and per-handle; this is the label the rate breaks down by.
MANIFEST_NOT_FOUND = "manifest not found"

#: The named cause a `present` turn that WAS re-invoked but whose server never answered
#: the target frame is filed under. The engine's verbatim string carries the raw reason
#: (server-exited / timed-out / …); this is the stable bucket the rate breaks down by.
REPLAY_DID_NOT_ANSWER = "replay did not answer target"

#: A last-resort label so a causeless unverified turn is impossible: an `unrestorable`
#: handle that somehow carried no cause string is still filed under a NAME, never
#: dropped from the breakdown. "Unverified for no stated reason" is the one thing the
#: report must never do — so it does not.
_NO_RECORDED_CAUSE = "unrestorable (no recorded cause)"

#: The prefix `belay.verify.turn` stamps on the cause of a turn that REPLAYED cleanly and
#: only then reduced to UNVERIFIED (an un-annotated tool, an invariant that could not be
#: evaluated, …). The rest of that string is `<axis>/<kind>: <verbatim sub-verdict
#: message>`, which is per-turn detail — so the labels below collapse it to one bucket per
#: DIMENSION. Without them `canonical_cause` would fall through and return the whole
#: sentence, giving one bucket per turn: noisier than `unknown` and no more explanatory.
REPLAYED_SUB_VERDICT = "replayed but unverified"

#: The bucket a replayed-but-unverified turn is filed under, named by the dimension that
#: DROVE the reduction. Not one label for all of them: "the reply could not be compared"
#: and "the declared filesystem contract could not be checked" are different findings and
#: an operator acts on them differently.
REPLAYED_RESULT_UNVERIFIED = "replayed but result unverified"
REPLAYED_EFFECT_UNVERIFIED = "replayed but effect unverified"
REPLAYED_INVARIANT_UNVERIFIED = "replayed but invariant unverified"
REPLAYED_UNVERIFIED = "replayed but sub-verdict unverified"

#: The BOUNDARY buckets. A turn can replay perfectly and still verify nothing, because the
#: server the operator named never offered the recorded tool — the reply the comparison
#: diverged against is the boundary's answer, not the tool's. That abstention used to bucket
#: under `REPLAYED_RESULT_UNVERIFIED` beside unparseable replies and nondeterministic tools,
#: which is why the 2026-08-12 gate mint could not answer the one question it needed to:
#: *"how many turns could not be verified because the boundary lacked the tool"*. It has a
#: name now, and it is counted on its own line wherever the rate breaks down.
#:
#: THREE names, not one, because they call for three different actions: `NOT_OFFERED` is a
#: decided fact about `--server` (name the right server); `AMBIGUOUS` means two configured
#: servers both claim the tool, so routing would be a guess (name one); `UNDECIDED` means the
#: probe could not be run or read at all (the boundary is unreachable, not lacking). Folding
#: the last two into the first would inflate exactly the number the gate counts.
REPLAYED_TOOL_NOT_OFFERED = "replayed but the boundary does not offer the tool"
REPLAYED_BOUNDARY_AMBIGUOUS = "replayed but the boundary routing is ambiguous"
REPLAYED_BOUNDARY_UNDECIDED = "replayed but the boundary toolset is undecided"

#: Prefix-to-label map for the engine's other verbatim unverified causes. Kept short
#: on purpose: the point is a stable bucket for the rate, not a second copy of the
#: engine's wording. Order matters — `canonical_cause` returns the FIRST match, so the
#: more specific replayed-dimension prefixes precede their catch-all (and `effect:network`
#: precedes `effect`, of which it is a prefix).
#:
#: THE SIX BOUNDARY ENTRIES BELOW ARE ORDERED, NOT DECORATIVE. `A2/replay:tool-not-offered`
#: starts with `A2/replay`, so an entry written after the catch-all can never be reached —
#: the bucket would exist, be registered, satisfy the interop reflection guard, and stay
#: permanently empty, which is G4 unmet while the checklist reads done. They are placed
#: ahead of both catch-alls for exactly the reason `effect:network` is, and the ordering is
#: asserted by test rather than trusted to this comment.
_PREFIX_LABELS: tuple[tuple[str, str], ...] = (
    ("no persisted snapshot manifest", MANIFEST_NOT_FOUND),
    (UNANSWERED_TARGET, REPLAY_DID_NOT_ANSWER),
    ("the tools/call has no recorded request frame", "no request frame to re-invoke"),
    ("the tools/call frame could not be read", "unreadable target frame"),
    ("unrecognised state_handle status", "unrecognised state handle"),
    ("an in-root path is embedded in an argument value", "embedded path unrelocatable"),
    (f"{REPLAYED_SUB_VERDICT} A2/replay:{TOOL_NOT_OFFERED}", REPLAYED_TOOL_NOT_OFFERED),
    (f"{REPLAYED_SUB_VERDICT} A2/effect:{TOOL_NOT_OFFERED}", REPLAYED_TOOL_NOT_OFFERED),
    (f"{REPLAYED_SUB_VERDICT} A2/replay:{BOUNDARY_AMBIGUOUS}", REPLAYED_BOUNDARY_AMBIGUOUS),
    (f"{REPLAYED_SUB_VERDICT} A2/effect:{BOUNDARY_AMBIGUOUS}", REPLAYED_BOUNDARY_AMBIGUOUS),
    (f"{REPLAYED_SUB_VERDICT} A2/replay:{BOUNDARY_UNDECIDED}", REPLAYED_BOUNDARY_UNDECIDED),
    (f"{REPLAYED_SUB_VERDICT} A2/effect:{BOUNDARY_UNDECIDED}", REPLAYED_BOUNDARY_UNDECIDED),
    (f"{REPLAYED_SUB_VERDICT} A2/replay", REPLAYED_RESULT_UNVERIFIED),
    (f"{REPLAYED_SUB_VERDICT} A2/effect:network", REPLAYED_UNVERIFIED),
    (f"{REPLAYED_SUB_VERDICT} A2/effect", REPLAYED_EFFECT_UNVERIFIED),
    (f"{REPLAYED_SUB_VERDICT} A1/invariant", REPLAYED_INVARIANT_UNVERIFIED),
    (REPLAYED_SUB_VERDICT, REPLAYED_UNVERIFIED),
)


def canonical_cause(cause: Optional[str]) -> str:
    """A stable, non-empty named cause for `cause` — the bucket the rate breaks down by.

    Total by design: `None` and every unrecognised string still map to a name, because
    a causeless UNVERIFIED is the one bug this whole report exists to make impossible.
    A recorded `UnrestorableCause` is filed under its own value; the gate's
    non-member `SNAPSHOT_FAILED` under its string; the manifest-not-found and other
    engine strings under a short stable label; anything else under itself.
    """
    if cause is None:
        return _NO_RECORDED_CAUSE
    if cause in _UNRESTORABLE_VALUES or cause == _SNAPSHOT_FAILED:
        return cause
    for prefix, label in _PREFIX_LABELS:
        if cause.startswith(prefix):
            return label
    return cause


@dataclass(frozen=True)
class TurnReport:
    """One turn's replay, reduced to the fields the report shows — never a verdict.

    `status` is the engine's `REPLAYED` / `UNVERIFIED` / `NOT_VERIFIABLE`. For an
    unverified or not-verifiable turn, `cause` is the canonical named bucket and
    `raw_cause` the engine's verbatim string. For a replayed turn, `result_equivalence`
    is `equal` / `diverged` and `delta_summary` is a one-line description of the
    workspace change. `determinism` names a classification when `--replays > 1`.
    """

    turn_index: int
    tool: Optional[str]
    status: str
    cause: Optional[str] = None
    raw_cause: Optional[str] = None
    result_equivalence: Optional[str] = None
    delta_summary: Optional[str] = None
    determinism: Optional[str] = None
    reinvoked: bool = False


@dataclass(frozen=True)
class TraceReport:
    """The whole-trace aggregate: counts, the UNVERIFIED rate, and its by-cause breakdown.

    `unverified_rate` is `unverified / total` (0.0 for an empty trace). `by_cause`
    counts unverified turns by their canonical cause and — the invariant — sums to
    `unverified`: no unverified turn escapes the breakdown. `not_verifiable` is kept
    separate and OUT of the rate: an un-snapshotted turn never had a pre-state to
    restore, so it is not a restore that could not be trusted.
    """

    turns: list[TurnReport] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.turns)

    @property
    def replayed(self) -> int:
        return sum(1 for t in self.turns if t.status == REPLAYED)

    @property
    def unverified(self) -> int:
        return sum(1 for t in self.turns if t.status == UNVERIFIED)

    @property
    def not_verifiable(self) -> int:
        return sum(1 for t in self.turns if t.status == NOT_VERIFIABLE)

    @property
    def unverified_rate(self) -> float:
        return self.unverified / self.total if self.total else 0.0

    @property
    def by_cause(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for turn in self.turns:
            if turn.status != UNVERIFIED:
                continue
            # `turn.cause` is already canonicalised (never None for an unverified
            # turn), so every one lands in a named bucket.
            counts[turn.cause] = counts.get(turn.cause, 0) + 1
        return counts


def _tool_name(records: Sequence[dict], request_seq: Optional[int]) -> Optional[str]:
    """The `params.name` of the frame at `request_seq`, or `None`.

    The turn is already selected by the correlation index (`method == tools/call`),
    so this only reads the name off that exact frame — never used to find the turn.
    """
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


def _delta_summary(delta: Optional[list[FieldDiff]]) -> Optional[str]:
    """A one-line description of a replayed turn's workspace delta.

    `None` when there was no delta to summarise (an unverified turn never re-invoked,
    so it has no delta — and inventing "no change" there would read a non-replay as a
    clean one). An empty delta is "no state change"; otherwise the distinct paths that
    moved, named, because "something changed" is exactly the non-answer this project
    refuses.
    """
    if delta is None:
        return None
    if not delta:
        return "no state change"
    paths = sorted({d.path for d in delta})
    shown = ", ".join(p.decode("utf-8", errors="replace") for p in paths[:3])
    if len(paths) > 3:
        shown += f", +{len(paths) - 3} more"
    noun = "path" if len(paths) == 1 else "paths"
    return f"{len(paths)} {noun} changed: {shown}"


def _turn_report(
    records: Sequence[dict],
    n: int,
    request_seq: Optional[int],
    outcome: TurnReplay,
    determinism: Optional[str],
) -> TurnReport:
    tool = _tool_name(records, request_seq)
    if outcome.status == REPLAYED:
        return TurnReport(
            turn_index=n,
            tool=tool,
            status=REPLAYED,
            result_equivalence=outcome.result_equivalence,
            delta_summary=_delta_summary(outcome.delta),
            determinism=determinism,
            reinvoked=outcome.reinvoked,
        )
    # UNVERIFIED or NOT_VERIFIABLE: carry the engine's verbatim cause AND the canonical
    # bucket. `canonical_cause` is total, so `cause` is never empty even here — the
    # report cannot leave a non-replayed turn unnamed.
    return TurnReport(
        turn_index=n,
        tool=tool,
        status=outcome.status,
        cause=canonical_cause(outcome.cause),
        raw_cause=outcome.cause,
        reinvoked=outcome.reinvoked,
    )


def replay_trace(
    records: Sequence[dict],
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    replays: int = 1,
    only: Optional[int] = None,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> TraceReport:
    """Replay every recorded `tools/call` and aggregate the UNVERIFIED-rate report.

    Each turn is delegated to `engine.replay_turn`, which restores its pre-state and
    re-invokes it — or names, without re-invoking, why it could not. When `replays > 1`
    a `replayed` turn is additionally classified for determinism (a clock/random tool
    is nondeterminism, not infidelity); the classification is an observation shown
    beside the turn, never folded into the rate.

    `only` narrows the run to a single turn index — replaying just that one, and
    aggregating over it alone, so the numbers describe exactly what was replayed rather
    than a whole-trace total the caller did not ask for. Out of range raises
    `ValueError`.

    Returns a `TraceReport` whose `unverified_rate` and `by_cause` breakdown name every
    unverified turn. Emits observations only — no PASS/FAIL. The source trace is never
    written to; the report is the return value.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if only is not None and not (0 <= only < len(calls)):
        raise ValueError(
            f"no tools/call at turn {only}: the trace holds {len(calls)} tool call(s)"
        )
    selected = [only] if only is not None else range(len(calls))

    turns: list[TurnReport] = []
    for n in selected:
        entry = calls[n]
        outcome = replay_turn(
            records,
            n,
            server_command=server_command,
            manifest_dir=manifest_dir,
            network=network,
            timeout=timeout,
        )
        determinism_label: Optional[str] = None
        if replays > 1 and outcome.status == REPLAYED:
            classified = classify_determinism(
                records,
                n,
                server_command=server_command,
                manifest_dir=manifest_dir,
                replays=replays,
                network=network,
                timeout=timeout,
            )
            # A turn that replayed once may still classify NOT_REPLAYABLE on a flaky
            # re-restore; carry whatever the classifier honestly saw.
            determinism_label = classified.classification
            if classified.axis is not None:
                determinism_label = f"{classified.classification} ({classified.axis.value})"
        turns.append(
            _turn_report(records, n, entry.get("request_seq"), outcome, determinism_label)
        )
    return TraceReport(turns=turns)


__all__ = [
    "MANIFEST_NOT_FOUND",
    "REPLAY_DID_NOT_ANSWER",
    "TraceReport",
    "TurnReport",
    "canonical_cause",
    "replay_trace",
]
