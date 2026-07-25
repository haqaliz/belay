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
`verify_turn` call could not replay the turn at all — `TurnVerdict.cause` is set exactly
when the turn was never REPLAYED (see `verify/turn.py`'s non-REPLAYED branch, covering
both an unrestorable snapshot and a turn that was never snapshotted) — the
`CorrelatedSpan.cause` is the named `unrestorable-pre-state`, derived structurally from
the presence of `TurnVerdict.cause` rather than re-parsing its string. A REPLAYED turn's
`TurnVerdict.cause` is always `None` (its `sub_verdicts` already explain it), so a matched,
replayed span's `CorrelatedSpan.cause` is `None` too — Task 3 invents no cause for it.

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
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, reduce

#: Named causes this module attaches. Never re-derived ad hoc elsewhere, so a reader
#: (and a later report/CLI surface) can match on these exact strings.
NO_MATCHING_MCP_TURN = "no-matching-mcp-turn"
AMBIGUOUS_CORRELATION = "ambiguous-correlation"
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
            # `TurnVerdict.cause` is set exactly on the non-REPLAYED branch of
            # `verify_turn` (an unrestorable or never-snapshotted pre-state) and is
            # ALWAYS `None` on a REPLAYED turn (verify/turn.py:212-218) — so its mere
            # presence, not its string content, is the structural signal that nothing
            # was actually re-invoked for this turn.
            cause = UNRESTORABLE_PRE_STATE if turn_verdict.cause is not None else None
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
