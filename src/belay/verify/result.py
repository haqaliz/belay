"""A2 result-equivalence turned into a verdict — gated on determinism.

C3's `engine.replay_turn` replays one recorded turn against its restored pre-state and
OBSERVES whether the replayed reply matched the recorded one (`result_equivalence`:
EQUAL / DIVERGED / None). It emits no verdict, on purpose. C4 is where that observation
becomes the first grounded A2 verdict — *"did this step's result actually reproduce?"* —
by re-execution, with no model anywhere.

**The gate is the whole point of this module, and it is C2's warning made code.** A
single replay has ZERO knowledge of determinism, and a clock- or random-dependent tool
DIVERGES on re-execution *legitimately*. That is nondeterminism, not trace infidelity. If
C4 promoted every divergence to FAIL it would cry wolf on every timestamp, and a verifier
that cries wolf is one users learn to ignore — the exact failure C2 named. So a DIVERGED
result is never a verdict until `determinism.classify_determinism` has decided whether the
tool reproduces at all:

    EQUAL                       -> PASS         (one replay; the classifier is NOT run)
    DIVERGED + DETERMINISTIC    -> FAIL         (+ the recorded-vs-observed value diff)
    DIVERGED + NONDETERMINISTIC -> UNVERIFIED   (carry the axis; NEVER FAIL)
    DIVERGED + NOT_REPLAYABLE   -> UNVERIFIED   (could not be re-run enough to decide)
    None (nothing to compare)   -> UNVERIFIED

FAIL requires a *determinable value* divergence. An unparseable replayed reply — one of the
two shapes C3 folds into DIVERGED — cannot be compared as a value, so even on a
deterministic tool it is **UNVERIFIED, not FAIL**: the honest claim is "replay produced
something we could not read", never "the values differ". It carries a distinct message
naming the parse failure, so it never reads as a value mismatch.

**Cost discipline.** The classifier is consulted ONLY on a divergence. An EQUAL turn is a
reproduction at one replay — classifying it buys nothing and triples the replay cost — and
a nondeterministic tool that happened to match once is still a reproduction, so the match
stands. That is why the gate lives in `verify_result` (the orchestrator), which reaches
`classify_determinism` on DIVERGED and nowhere else; `render_result_verdict` receives an
already-decided classification (or `None`) and never re-runs anything.

**The diff message distinguishes a value mismatch from a malformed reply.** C3's
`_equivalence` returns DIVERGED both when the replayed reply is a genuinely different value
AND when it fails to parse. A FAIL must say which: a value mismatch shows recorded vs
observed; an unparseable replayed reply says so plainly — a distinct grounding, not a
value divergence. The raw `recorded_reply` / `replayed_reply` bytes are read to build this;
equivalence itself is never recomputed here (C3 owns that decision).

Zero runtime dependencies: stdlib `json` to render the two replies for the message; the
re-execution is C3's, the classification is `determinism`'s, the verdict shape is Task 1's.
No model is imported — the verdict is grounded in re-execution, never a judge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.determinism import (
    DETERMINISTIC,
    NONDETERMINISTIC,
    NOT_REPLAYABLE,
    DeterminismResult,
    classify_determinism,
)
from belay.replay.engine import DIVERGED, EQUAL, TurnReplay, replay_turn
from belay.verify.verdict import Status, Verdict

#: This module speaks only for the replay axis. A1 (invariants) and A3 (claim
#: re-derivation) are other capabilities; the reduction in `verdict.reduce` folds them
#: in by status alone.
_AXIS = "A2"
_KIND = "replay"


def _decode(reply: Optional[bytes]) -> tuple[bool, Any]:
    """`(parsed_ok, value)` — the parsed JSON on success, else the raw bytes.

    Used only to RENDER a reply for a human-readable message, never to decide
    equivalence (C3 already did). A reply that fails to parse is not coerced; its raw
    bytes are carried so the message can quote them exactly.
    """
    if reply is None:
        return False, None
    try:
        return True, json.loads(reply)
    except ValueError:
        return False, reply


def render_result_verdict(
    reply: TurnReplay, determinism: Optional[DeterminismResult]
) -> Verdict:
    """Turn one replay observation (and its determinism decision) into an A2 verdict.

    Pure: it re-runs nothing and consults no model. `determinism` must be supplied
    whenever `reply.result_equivalence` is DIVERGED — that is the gate, and calling this
    with a DIVERGED reply and `determinism=None` is a programming error (the orchestrator
    is what runs the classifier). For EQUAL and None it is ignored.
    """
    eq = reply.result_equivalence

    if eq == EQUAL:
        _ok, value = _decode(reply.replayed_reply)
        return Verdict(
            _AXIS, _KIND, Status.PASS,
            observed=value, expected=value,
            message="replayed reply reproduced the recorded reply",
        )

    if eq is None:
        # Nothing to compare: the recording had no reply, or the turn was not replayable
        # at all. Verified nothing -> UNVERIFIED, never PASS. The engine's own cause, if
        # any, names why re-execution produced no comparable result.
        cause = reply.cause or "the turn produced no reply to compare against the recording"
        return Verdict(
            _AXIS, _KIND, Status.UNVERIFIED,
            observed=None, expected=None,
            message=f"result-equivalence UNVERIFIED: {cause}",
        )

    if eq == DIVERGED:
        if determinism is None:
            raise ValueError(
                "a DIVERGED result must be gated on determinism before a verdict; "
                "classify_determinism was not run (call verify_result, not the renderer)"
            )
        return _diverged_verdict(reply, determinism)

    raise ValueError(f"unrecognised result_equivalence {eq!r}")


def _diverged_verdict(reply: TurnReplay, determinism: DeterminismResult) -> Verdict:
    """The gated half: a divergence is a FAIL only when the tool is DETERMINISTIC."""
    classification = determinism.classification

    if classification == DETERMINISTIC:
        return _deterministic_divergence_verdict(reply, determinism)

    if classification == NONDETERMINISTIC:
        # Legitimate divergence — a clock/random/pid tool does not reproduce, and that
        # is nondeterminism, not infidelity. Carry the axis when the classifier named
        # one; "axis unknown" is an honest outcome, never a guess. UNVERIFIED, never FAIL.
        axis = determinism.axis
        axis_note = axis.value if axis is not None else "unknown"
        _rec_ok, rec = _decode(reply.recorded_reply)
        _rep_ok, rep = _decode(reply.replayed_reply)
        return Verdict(
            _AXIS, _KIND, Status.UNVERIFIED,
            observed=rep, expected=rec,
            message=(
                f"result diverged but the tool {determinism.tool!r} is nondeterministic "
                f"(axis: {axis_note}); a legitimate divergence is not trace infidelity, "
                f"so this is UNVERIFIED, not FAIL"
            ),
        )

    if classification == NOT_REPLAYABLE:
        # The classifier could not re-run the turn enough to decide (an unrestorable
        # pre-state on a later replay, say). Determinism is undefined, so the divergence
        # cannot be grounded -> UNVERIFIED, carrying the classifier's reason.
        return Verdict(
            _AXIS, _KIND, Status.UNVERIFIED,
            observed=None, expected=None,
            message=(
                f"result diverged but the turn could not be re-run enough to classify "
                f"its determinism ({determinism.cause}); the divergence cannot be grounded"
            ),
        )

    raise ValueError(f"unrecognised determinism classification {classification!r}")


def _deterministic_divergence_verdict(
    reply: TurnReplay, determinism: DeterminismResult
) -> Verdict:
    """A DETERMINISTIC tool that diverges — a FAIL only when the values are comparable.

    The two shapes C3 folds into DIVERGED get different verdicts, because FAIL is the
    strong claim and only one shape earns it:

    - a genuine value mismatch (both replies parse) is a determinable divergence -> FAIL,
      showing recorded vs observed.
    - an unparseable replayed reply cannot be compared as a value, so it does not clear
      the bar for a FAIL -> UNVERIFIED, with a message that names the parse failure
      plainly (a distinct grounding, never read as a value diff).
    """
    tool = determinism.tool
    _rec_ok, rec = _decode(reply.recorded_reply)
    rep_ok, rep = _decode(reply.replayed_reply)

    if not rep_ok:
        return Verdict(
            _AXIS, _KIND, Status.UNVERIFIED,
            observed=reply.replayed_reply, expected=rec,
            message=(
                f"result-equivalence UNVERIFIED on deterministic tool {tool!r}: the "
                f"replayed reply could not be parsed as JSON ({reply.replayed_reply!r}), "
                f"so it cannot be compared against the recorded reply {rec!r}; replay "
                f"produced something unreadable, which is not a determinable value divergence"
            ),
        )

    return Verdict(
        _AXIS, _KIND, Status.FAIL,
        observed=rep, expected=rec,
        message=(
            f"result-equivalence FAIL on deterministic tool {tool!r}: the trace recorded "
            f"{rec!r} but replay deterministically reproduced {rep!r}"
        ),
    )


def verify_result(
    records: Sequence[dict],
    n: int,
    *,
    server_command: Sequence[str],
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    replays: int = 3,
) -> Verdict:
    """Replay the Nth recorded `tools/call`, and render its A2 result-equivalence verdict.

    Runs the replay once. If the observed reply matched the recorded one (or there was
    nothing to compare), the classifier is never consulted — the verdict is PASS or
    UNVERIFIED at one replay. Only on a DIVERGED reply does the determinism gate run:
    `classify_determinism` re-invokes the turn `replays` times, and the divergence is a
    FAIL only if the tool reproduces deterministically. This is the one place a false
    verdict is most likely, and the gate is what prevents it.
    """
    reply = replay_turn(
        records, n,
        server_command=server_command, manifest_dir=manifest_dir,
        network=network, timeout=timeout,
    )

    determinism: Optional[DeterminismResult] = None
    if reply.result_equivalence == DIVERGED:
        determinism = classify_determinism(
            records, n,
            server_command=server_command, manifest_dir=manifest_dir,
            replays=replays, network=network, timeout=timeout,
        )

    return render_result_verdict(reply, determinism)


__all__ = ["render_result_verdict", "verify_result"]
