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
    DIVERGED + not offered      -> UNVERIFIED   (the boundary never ran the tool)
    DIVERGED + DETERMINISTIC    -> FAIL         (+ the recorded-vs-observed value diff)
    DIVERGED + NONDETERMINISTIC -> UNVERIFIED   (carry the axis; NEVER FAIL)
    DIVERGED + NOT_REPLAYABLE   -> UNVERIFIED   (could not be re-run enough to decide)
    None (nothing to compare)   -> UNVERIFIED

**A second gate sits in front of the determinism one, and it asks a question about the
BOUNDARY rather than about the tool.** A replay server that does not offer the recorded
tool answers *readably* — `no such tool`, or a JSON-RPC error — and answers the same way
every time, so the divergence is determinable and the tool classifies DETERMINISTIC. Every
step of that is correct and the conclusion is still fabricated: nothing was re-executed, so
nothing about the agent's call was refuted. What diverged is the operator's `--server`, not
the trace. So when the caller has asked the boundary what it offers (a `tools/list` probe —
positive evidence, never error-text matching, never an `isError` inference) and the answer
does not contain the tool, the divergence is UNVERIFIED here, and the classifier is never
consulted: re-proving that `"no such tool"` is self-consistent costs three more spawns and
buys nothing. An UNDECIDED boundary — the probe could not run, could not be read, or two
configured servers both claim the tool — is a THIRD outcome and abstains with its own
wording: absence of evidence is never evidence of absence.

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
    reply: TurnReplay,
    determinism: Optional[DeterminismResult],
    *,
    tool_offered: Optional[bool] = True,
    tool_name: Optional[str] = None,
    probe_note: Optional[str] = None,
) -> Verdict:
    """Turn one replay observation (and its determinism decision) into an A2 verdict.

    Pure: it re-runs nothing and consults no model. `determinism` must be supplied
    whenever `reply.result_equivalence` is DIVERGED **and the boundary offered the tool** —
    that is the gate, and calling this with such a reply and `determinism=None` is a
    programming error (the orchestrator is what runs the classifier). For EQUAL and None it
    is ignored.

    `tool_offered` is the boundary evidence, three-way and read ONLY on a DIVERGED reply:

    - `True` (the default) — the boundary offers the tool, so scoring is exactly what it
      has always been. It is the default because it is the assumption every caller made
      implicitly before the probe existed; a caller that has no boundary to ask gets
      today's behavior rather than an abstention it cannot justify.
    - `False` — the boundary was ASKED and does not offer the tool. The recorded call was
      never re-executed, so the divergence says nothing about it -> UNVERIFIED.
    - `None` — the boundary could not be settled (`probe_note` says why: an unreadable
      probe, or two configured servers both offering the tool). Ignorance, not knowledge
      of absence -> UNVERIFIED, worded so it can never be read as "not offered".

    `tool_name` names the tool in those two abstention messages; the FAIL path keeps taking
    the name from `determinism`, which is the classifier's own record of what it re-ran.
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
        # The BOUNDARY gate, ahead of the determinism gate — see the module docstring.
        # It is first because it is cheaper and because it can settle the turn outright:
        # a boundary that never offered the tool makes the classifier's three extra
        # re-invocations pure waste.
        boundary = _boundary_abstention(reply, tool_offered, tool_name, probe_note)
        if boundary is not None:
            return boundary
        if determinism is None:
            raise ValueError(
                "a DIVERGED result must be gated on determinism before a verdict; "
                "classify_determinism was not run (call verify_result, not the renderer)"
            )
        return _diverged_verdict(reply, determinism)

    raise ValueError(f"unrecognised result_equivalence {eq!r}")


def _boundary_abstention(
    reply: TurnReplay,
    tool_offered: Optional[bool],
    tool_name: Optional[str],
    probe_note: Optional[str],
) -> Optional[Verdict]:
    """The divergence the BOUNDARY explains, or `None` to let the determinism gate decide.

    Two shapes abstain, and they are kept apart in words because they are apart in fact:

    - **the boundary does not offer the tool** — it was asked and it answered. The reply
      the comparison diverged against was produced by a server that never ran the recorded
      call, so there is no re-execution to compare and nothing was refuted. Naming the tool
      and the boundary is what makes this actionable: the fix is the operator's `--server`.
    - **the boundary could not be settled** — the probe could not run or could not be read,
      or more than one configured server claims the tool so routing would be a guess.
      Whether the divergence belongs to the tool is UNDECIDED, and this wording must never
      read as "the boundary does not offer it": that would sell absence of evidence as
      evidence of absence, which is the one mistake this gate exists to avoid.

    Both carry the two replies as evidence, exactly as the FAIL does, so a reader can see
    what was compared and judge the abstention rather than take it on trust.
    """
    if tool_offered is True:
        return None
    named = repr(tool_name) if tool_name is not None else "the recorded tool"
    _rec_ok, rec = _decode(reply.recorded_reply)
    _rep_ok, rep = _decode(reply.replayed_reply)
    if tool_offered is False:
        message = (
            f"result-equivalence UNVERIFIED on tool {named}: the replay boundary does not "
            f"offer this tool, so the recorded call was never re-invoked and the reply this "
            f"comparison diverged against is the boundary's answer, not the tool's. Nothing "
            f"was re-executed, so nothing was refuted; a FAIL here would charge the trace "
            f"for the server it was replayed against"
        )
    else:
        note = probe_note or "the boundary could not be asked what it offers"
        message = (
            f"result-equivalence UNVERIFIED on tool {named}: the divergence cannot be "
            f"attributed, because the replay boundary's toolset is undecided ({note}). "
            f"Absence of evidence is never evidence of absence — this is NOT a finding that "
            f"the boundary lacks the tool, and it is not a finding against the trace either"
        )
    return Verdict(
        _AXIS, _KIND, Status.UNVERIFIED,
        observed=rep, expected=rec,
        message=message,
    )


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

    FAIL is the strong claim and only one shape earns it. Three shapes reach a DIVERGED
    reply and only the first is a finding against the trace:

    - a genuine value mismatch (both replies parse) is a determinable divergence -> FAIL,
      showing recorded vs observed.
    - an unparseable replayed reply cannot be compared as a value, so it does not clear
      the bar for a FAIL -> UNVERIFIED, with a message that names the parse failure
      plainly (a distinct grounding, never read as a value diff).
    - **a readable reply from a boundary that never offered the tool** parses perfectly,
      differs deterministically, and still refutes nothing — the divergence is between the
      trace and the operator's `--server`, not between the trace and re-execution. It is
      decided by `_boundary_abstention` UPSTREAM of this function rather than here, for
      one reason: it must be settled BEFORE the classifier spends three more spawns
      re-proving that a `"no such tool"` reply is self-consistent. Same reasoning, earlier
      gate.
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

    **This orchestrator does NOT run the boundary probe**, and says so rather than
    leaving it to be discovered: it is the single-verdict entry point (no product
    surface reaches it today — `belay verify` composes through `verify.turn`), and the
    probe needs the configured server SET to decide ambiguity, which a single
    `server_command` cannot supply. So `tool_offered` keeps its `True` default here and
    a not-offered tool still scores as it did before the probe existed. If this entry
    point ever becomes load-bearing, it must grow the same gate `verify_turn` has.
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
