"""Attach the replayed verdict to a correlated span — C9 computes NO verdict of its own.

Task 2's `correlate.py` answers, per span, which recorded `tools/call` turn it names (if
any). This module is the last step: for a `Matched` span, hand the UNCHANGED turn ordinal
to the UNCHANGED `belay.verify.turn.verify_turn` and attach whatever `TurnVerdict` it
returns, verbatim. For an `Unmatched` or `Ambiguous` span, `verify_turn` is never even
called — the honest answer is `UNVERIFIED` with a named cause, never a guessed attach and
never a hand-built `PASS`.

**Why this module must not compute a verdict.** Belay's entire value is that a verdict is
grounded in re-execution, never asserted. If this module invented its own status for an
uncovered span — even a plausible-sounding one — it would be exactly the kind of
ungrounded claim the rest of the engine exists to refuse. So the only two sources of
`Status` a `CorrelatedSpan` can ever carry are: (1) a real `TurnVerdict.status`, forwarded
unchanged from `verify_turn`, or (2) `UNVERIFIED`, via the SAME reduction machinery
(`verify.verdict.reduce(())`) every other "nothing was verified" case in this codebase
goes through — never a clean PASS hand-written down here.

**The `cause` field.** For `Unmatched`/`Ambiguous` spans it names WHY nothing was
attached (`no-matching-mcp-turn` / `ambiguous-correlation`). For a `Matched` span whose
`verify_turn` call could not replay the turn at all — an unrestorable snapshot, or a turn
that was never snapshotted — the `CorrelatedSpan.cause` is the named
`unrestorable-pre-state`. A turn that DID replay gets `cause=None` here: its
`sub_verdicts` already explain it, and Task 3 invents no cause of its own.

**Why the discriminator is a cause vocabulary and not `cause is not None`.** This module
originally read the mere *presence* of `TurnVerdict.cause` as "nothing was re-invoked",
because the non-REPLAYED branch was the only one that set it. The `NOT_COVERED` release
deliberately ended that: `verify/turn.py` now also names a cause on the REPLAYED path
whenever such a turn reduces to `UNVERIFIED`, so that every unverified turn traces to a
named cause. `_replayed_cause`'s own contract states the consequence — the cause is
*"a stable LABEL on both paths and a consumer never has to know which path produced it."*
Presence therefore no longer distinguishes anything, and reading it as though it did made
this module report a **snapshot-restore failure that never happened** — Belay inventing a
fact about its own execution, which is worse than saying nothing.

So the test is membership in `_REPLAYED_CAUSES`, the closed set of buckets
`_replayed_cause` can produce. It is closed by construction: that function always builds
its string from the `REPLAYED_SUB_VERDICT` prefix, and `canonical_cause`'s prefix table
ends in a catch-all mapping that prefix to `REPLAYED_UNVERIFIED`, so every replayed cause
lands on one of these four labels. `test_replayed_cause_vocabulary_is_closed` fails loudly
if a fifth is ever added.

**The `verify=` seam.** `correlate_and_attach` takes an optional `verify` callable,
defaulting to the real `verify_turn`, purely so the correlation/attach LOGIC can be unit
tested with a stub or a spy without paying for a real sandboxed replay on every test. It
changes nothing about production behaviour: unless a caller overrides it, every `Matched`
span is verified by the real engine.

Zero runtime dependencies: stdlib only. No model/inference import anywhere in this
module or its dependencies — the verdict is grounded in re-execution, never a judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from belay.interop.correlate import Ambiguous, Matched, Unmatched, build_turn_index, match_span
from belay.interop.otlp import Span
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.report import (
    REPLAYED_BOUNDARY_AMBIGUOUS,
    REPLAYED_BOUNDARY_UNDECIDED,
    REPLAYED_EFFECT_UNVERIFIED,
    REPLAYED_INVARIANT_UNVERIFIED,
    REPLAYED_RESULT_UNVERIFIED,
    REPLAYED_TOOL_NOT_OFFERED,
    REPLAYED_UNVERIFIED,
)
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, reduce

#: Named causes this module attaches. Never re-derived ad hoc elsewhere, so a reader
#: (and a later report/CLI surface) can match on these exact strings.
NO_MATCHING_MCP_TURN = "no-matching-mcp-turn"
AMBIGUOUS_CORRELATION = "ambiguous-correlation"

#: The closed set of `TurnVerdict.cause` values that mean "this turn REPLAYED and only
#: then reduced to UNVERIFIED" — i.e. the pre-state WAS restored and the tool WAS
#: re-invoked. A cause in this set must never be reported as `unrestorable-pre-state`.
_REPLAYED_CAUSES = frozenset(
    {
        REPLAYED_RESULT_UNVERIFIED,
        REPLAYED_EFFECT_UNVERIFIED,
        REPLAYED_INVARIANT_UNVERIFIED,
        REPLAYED_UNVERIFIED,
        REPLAYED_TOOL_NOT_OFFERED,
        REPLAYED_BOUNDARY_AMBIGUOUS,
        REPLAYED_BOUNDARY_UNDECIDED,
    }
)
UNRESTORABLE_PRE_STATE = "unrestorable-pre-state"

#: The signature `verify_turn` (and any injected stand-in) must satisfy.
VerifyTurn = Callable[..., TurnVerdict]


@dataclass(frozen=True)
class CorrelatedSpan:
    """One span's outcome: which turn it named (if any), and the verdict attached.

    `verdict` is `None` for an uncovered span (`Unmatched`/`Ambiguous`) — there is no
    `TurnVerdict` to show, only the named `cause`. For a `Matched` span it is the EXACT
    `TurnVerdict` `verify_turn` returned; nothing here re-derives or adjusts it.
    `status` is the one place a caller who does not care about the distinction can read
    a single `Status` for every case.
    """

    span_id: str
    turn_index: Optional[int]
    verdict: Optional[TurnVerdict]
    cause: Optional[str]

    @property
    def status(self) -> Status:
        """The TurnVerdict's status for a matched span; `UNVERIFIED` otherwise.

        Routed through `reduce(())` rather than spelling `Status.UNVERIFIED` directly:
        an uncovered span goes through the exact same "nothing was verified ->
        UNVERIFIED" reduction every other axis in this codebase uses, not a value
        written down ad hoc in this one property.
        """
        if self.verdict is not None:
            return self.verdict.status
        return reduce(())


def _uncovered(span: Span, cause: str) -> CorrelatedSpan:
    return CorrelatedSpan(span_id=span.span_id, turn_index=None, verdict=None, cause=cause)


def correlate_and_attach(
    records: Sequence[dict],
    spans: Sequence[Span],
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    replays: int = 3,
    invariants: Sequence[Invariant] = (),
    verify: VerifyTurn = verify_turn,
) -> list[CorrelatedSpan]:
    """Build the turn index once; resolve each span to a `CorrelatedSpan`.

    `Matched(n)` spans call `verify(records, n, server_command=..., manifest_dir=...,
    ...)` — `verify_turn` by default — and attach its `TurnVerdict` unchanged. An
    `Unmatched`/`Ambiguous` span never reaches `verify` at all: it is `UNVERIFIED` with
    its named cause, immediately, with no attempt to replay anything. Deterministic:
    a pure function of `records`/`spans` plus whatever `verify` observes.
    """
    records = list(records)
    index = build_turn_index(records)

    results: list[CorrelatedSpan] = []
    for span in spans:
        match = match_span(span, index)

        if isinstance(match, Matched):
            turn_verdict = verify(
                records,
                match.n,
                server_command=server_command,
                manifest_dir=manifest_dir,
                network=network,
                timeout=timeout,
                replays=replays,
                invariants=invariants,
            )
            # Both branches of `verify_turn` can set `cause`, so presence alone says
            # nothing about whether anything was re-invoked (see the module docstring).
            # Only a cause OUTSIDE the replayed vocabulary means the pre-state could not
            # be restored — anything else would assert a restore failure that never
            # happened.
            #
            # A cause INSIDE that vocabulary is now carried through verbatim rather than
            # dropped to `None`. It used to be dropped because the four buckets it could
            # hold were all one fact ("something downstream of the replay abstained"), and
            # the sub-verdicts said which. That stopped being true when the boundary
            # abstention got its own name: *"the server you named does not offer this tool"*
            # is actionable, is the number the Phase-0 gate counts, and a span rendered as a
            # bare, causeless UNVERIFIED hides it on the one surface built to sit beside an
            # existing observability stack. The rule this codebase applies everywhere else —
            # the named cause travels with the status — applies here too.
            cause = (
                UNRESTORABLE_PRE_STATE
                if turn_verdict.cause is not None
                and turn_verdict.cause not in _REPLAYED_CAUSES
                else turn_verdict.cause
            )
            results.append(
                CorrelatedSpan(
                    span_id=span.span_id,
                    turn_index=match.n,
                    verdict=turn_verdict,
                    cause=cause,
                )
            )
        elif isinstance(match, Unmatched):
            results.append(_uncovered(span, NO_MATCHING_MCP_TURN))
        else:
            assert isinstance(match, Ambiguous), f"unhandled match result: {match!r}"
            results.append(_uncovered(span, AMBIGUOUS_CORRELATION))

    return results


__all__ = [
    "CorrelatedSpan",
    "correlate_and_attach",
    "NO_MATCHING_MCP_TURN",
    "AMBIGUOUS_CORRELATION",
    "UNRESTORABLE_PRE_STATE",
]
