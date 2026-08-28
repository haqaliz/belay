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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.determinism import DeterminismResult, classify_determinism
from belay.replay.engine import (
    DIVERGED,
    REPLAYED,
    TurnReplay,
    replay_turn,
    resolve_server_argv,
)
from belay.replay.probe import offered_tools
from belay.replay.report import REPLAYED_SUB_VERDICT, canonical_cause
from belay.verify.effect import network_subverdict, render_effect_verdict
from belay.verify.invariants import (
    CONTENT_GROUNDED_RULES,
    INSTANCE_LEVEL_RULES,
    Invariant,
    evaluate_invariant,
)
from belay.verify.prestate import content_roots
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
    #: The observed `isError` of the REPLAYED reply — the fact the instance-level
    #: trajectory rule counts as "a command's observed outcome". Set ONLY on the
    #: REPLAYED path, from the replayed reply's JSON `result.isError`; `None` (absent)
    #: for a non-REPLAYED turn and for a reply whose outcome cannot be read (no reply,
    #: unparseable, or no bool `isError` key). Never a fabricated `False`: `None` is
    #: "unobservable", which `trajectory.assemble_turn_facts` maps to not-replayed.
    replayed_is_error: Optional[bool] = None


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


def _replayed_is_error(reply: TurnReplay) -> Optional[bool]:
    """The observed `isError` of a REPLAYED turn's reply, or `None` when it cannot be read.

    Read from the replayed reply's JSON `result.isError` (the MCP response envelope; a
    bare-result reply is accepted too, since some servers omit the wrapper). `None` —
    never a coerced `False` — when there is no reply, it does not parse, the result is
    not an object, or the key is absent or not a bool. Only ever called on the REPLAYED
    path, so a `None` here means "the turn replayed but its outcome is unreadable",
    which the trajectory rule counts as unobservable rather than as evidence either way.
    """
    if reply.replayed_reply is None:
        return None
    try:
        parsed = json.loads(reply.replayed_reply)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    result = parsed.get("result")
    is_error = result.get("isError") if isinstance(result, dict) else parsed.get("isError")
    return is_error if isinstance(is_error, bool) else None


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


def _replayed_cause(sub_verdicts: Sequence[Verdict]) -> Optional[str]:
    """The canonical named cause for a turn that REPLAYED and *then* reduced to UNVERIFIED.

    The gate's contract is that EVERY unverified turn traces to a named cause. That held
    only for turns that never replayed (`_unverifiable_verdict` above); this path returned
    `cause=None` unconditionally, so `phase0.runner` filed a replayed-but-unverified turn
    under its causeless catch-all — the Stage-1 re-mint published `unknown: 12`.

    The cause names the DECIDING sub-verdict — the first UNVERIFIED one in composition
    order, which is the one `reduce`'s worst-status-wins actually settled on — not an
    arbitrary member of the list: "the reply could not be compared" and "the declared
    filesystem contract could not be checked" are different findings. Its verbatim message
    is carried for detail and then bucketed by `canonical_cause`, exactly as the
    non-replayed path does, so `TurnVerdict.cause` is a stable LABEL on both paths and a
    consumer never has to know which path produced it. Returns `None` for any other
    reduced status: `cause` explains an UNVERIFIED and nothing else.
    """
    deciding = next((v for v in sub_verdicts if v.status is Status.UNVERIFIED), None)
    if deciding is None:
        # `reduce` also answers UNVERIFIED when nothing SCORED remains (every sub-verdict
        # was NOT_COVERED, or there were none) — unreachable on this path, which always
        # composes the two A2 checks, but still named rather than left causeless.
        return canonical_cause(REPLAYED_SUB_VERDICT)
    return canonical_cause(
        f"{REPLAYED_SUB_VERDICT} {deciding.axis}/{deciding.kind}: {deciding.message}"
    )


#: What `_boundary_offer` reports when the boundary itself could not be settled. These are
#: message DETAIL, not bucket labels: they explain an abstention in prose and are
#: deliberately not registered anywhere — naming and rendering the bucket is a later slice.
_PROBE_UNREADABLE = (
    "the tools/list probe against that boundary could not be run, or its answer could not "
    "be read"
)


def _boundary_offer(
    reply: TurnReplay,
    tool_name: Optional[str],
    *,
    routed: Sequence[str],
    configured: Sequence[Sequence[str]],
    network: Any,
    timeout: float,
) -> tuple[Optional[bool], Optional[str]]:
    """Ask the replay boundary whether it offers this turn's tool. `(tool_offered, note)`.

    Three-way and fail-closed, mirroring the probe's own contract:

    - `(True, None)` — the routed boundary offers the tool and no OTHER configured server
      does, so routing was not a choice and today's scoring stands.
    - `(False, None)` — the routed boundary was asked and does not offer it.
    - `(None, note)` — undecided, for one of two reasons the note distinguishes: the probe
      could not be read at all, or **two or more configured servers offer the tool**, which
      makes "which server should have served this turn" a guess. `verify_turn` routes
      `run_process` to `--shell-server` by tool NAME (see below), so two servers that both
      claim a tool is a real, reachable ambiguity the moment `--shell-server` is given, and
      a guess is exactly what a fail-closed engine must refuse.

    **The routed boundary is asked FIRST and can settle the turn alone.** If it does not
    offer the tool, that is decisive no matter what the other server offers: the reply the
    comparison diverged against came from *this* boundary. Only when it DOES offer the tool
    does the alternate matter, and only then is a second spawn paid for.

    **The argv is never re-resolved for the routed server.** `reply.boundary.argv` is the
    command `replay_turn` actually spawned, already through the single `resolve_server_argv`
    site, so the probe asks the same boundary by construction rather than by agreement. An
    ALTERNATE server was never spawned, so its `{workspace}` must be resolved — through that
    same exported helper, against the same manifest root, never a second copy of the rule.

    A replay observation with no `boundary` names no boundary to ask, so there is nothing to
    settle and the answer is `(True, None)` — byte-for-byte the scoring that preceded this
    gate. The real engine cannot produce that on a REPLAYED status (manifest, resolved argv
    and relocation decision are all settled before it can spawn); it is reachable only from
    a hand-built or stubbed observation, and there "score as before" is the honest default.
    """
    boundary = reply.boundary
    if boundary is None or tool_name is None:
        return True, None

    routed_offer = offered_tools(
        list(boundary.argv),
        snapshot_manifest=boundary.manifest_path,
        source_root=boundary.relocation_root,
        network=network,
        timeout=timeout,
    )
    if routed_offer is None:
        return None, _PROBE_UNREADABLE
    if tool_name not in routed_offer:
        return False, None

    # The routed boundary offers it. Ambiguity is now the only thing left to rule out, and
    # it exists only when the operator configured a server this turn was NOT routed to.
    for other in configured:
        if list(other) == list(routed):
            continue
        argv, rootless = resolve_server_argv(other, boundary.source_root)
        if argv is None:
            return None, (
                f"another configured server could not be resolved against this turn's "
                f"recorded root ({rootless}), so whether it also offers this tool is unknown"
            )
        other_offer = offered_tools(
            argv,
            snapshot_manifest=boundary.manifest_path,
            source_root=boundary.relocation_root,
            network=network,
            timeout=timeout,
        )
        if other_offer is None:
            return None, (
                "another configured server could not be probed, so whether it also offers "
                "this tool is unknown"
            )
        if tool_name in other_offer:
            return None, (
                "more than one configured server offers this tool, so which one should have "
                "served this turn is a routing guess, and this engine does not guess"
            )
    return True, None


def verify_turn(
    records: Sequence[dict],
    n: int,
    *,
    server_command: Sequence[str],
    shell_server_command: Sequence[str] | None = None,
    manifest_dir: Path | str,
    network: Any = None,
    timeout: float = DEFAULT_TIMEOUT,
    replays: int = 3,
    invariants: Sequence[Invariant] = (),
) -> TurnVerdict:
    """Compose the Nth `tools/call`'s per-turn verdict — replay once, both A2 checks, reduce.

    Replays the turn a SINGLE time. On a REPLAYED turn both A2 checks run against that one
    replay (the determinism gate consulting the classifier only on a DIVERGED reply) and
    reduce worst-status-wins. On any non-REPLAYED status the turn is UNVERIFIED directly —
    nothing was re-invoked, so A2 verified nothing, and an un-restored or un-snapshotted
    turn must never fall through to PASS. Emits a grounded verdict; no model anywhere.

    **Boundary rule (ahead of the determinism gate):** on a DIVERGED reply the boundary is
    asked what it offers — `offered_tools`, a `tools/list` probe against the SAME resolved
    argv, snapshot and relocation root the replay used — before `classify_determinism` is
    consulted. A boundary that does not offer the recorded tool never re-executed the call,
    so the divergence refutes nothing and the result sub-verdict abstains; an undecided
    boundary (unreadable probe, or two configured servers both offering the tool) abstains
    with distinct wording. Only an offered tool reaches the classifier, which is both the
    correctness fix and a saving: the classifier re-invokes the turn `replays` (>=3) more
    times, and those are spent on the turns that deserve them.

    **Server routing rule:** a turn whose recorded tool name is exactly `_EVIDENCE_TOOL`
    (`run_process`) and for which `shell_server_command` is given replays against the
    shell command; every other turn — and every turn when `shell_server_command` is
    absent — replays against `server_command`, byte-for-byte as before. The resolved
    command feeds BOTH `replay_turn` and `classify_determinism`, so the two can never
    disagree about which server observed the turn.
    """
    # Function-level import: `trajectory.py` imports `TurnVerdict` at module level, so a
    # module-level `turn -> trajectory` import would close the turn<->invariants<->trajectory
    # cluster into a cycle. The constant is resolved once per turn, which is negligible.
    from belay.verify.trajectory import _EVIDENCE_TOOL

    tool_name = _tool_name(records, n)
    resolved = (
        list(shell_server_command)
        if tool_name == _EVIDENCE_TOOL and shell_server_command is not None
        else server_command
    )
    reply = replay_turn(
        records, n,
        server_command=resolved, manifest_dir=manifest_dir,
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
    #
    # SHARP EDGE (named, not fixed here — `replay-batch-server-rooting`, 2026-07-23): the
    # classifier answers "does this TOOL behave deterministically?", but all it can actually
    # observe is "do N replays of this BROKEN invocation agree?". A *deterministically broken*
    # command — a server spawned at the wrong root, an unspawnable binary — agrees with itself
    # every time, so it is classified DETERMINISTIC and a rooting/spawn failure is promoted
    # into a confident FAIL (DIVERGED + DETERMINISTIC → FAIL, `verify/result.py`). The
    # mirror-image reading is worse: each replay restores into its OWN `mkdtemp` scratch, so
    # when the server's error text embeds that scratch path the probe replies differ from EACH
    # OTHER and the tool is called NONDETERMINISTIC — blaming the tool when the tool is fine
    # and the ROOTING was broken. `replay/determinism.py:154 _signature` compares raw parsed
    # replies with no root canonicalization, unlike the engine's recorded-vs-replayed
    # comparison, which substring-normalizes both roots. This is LATENT, not live: the engine's
    # relocation gate now abstains (UNROOTABLE_SERVER_COMMAND / ROOTLESS_RELOCATION) before any
    # spawn, so the mis-rooted case short-circuits above and never reaches this call. Do not
    # "fix" it by loosening the classifier — the real repair is to make the probe's comparison
    # root-aware, which is its own unit.
    #
    # BEFORE the classifier, ask the boundary what it offers. A server that does not offer
    # the recorded tool answers readably and identically every time, so the divergence is
    # determinable and the tool classifies DETERMINISTIC — a correct chain to a fabricated
    # conclusion, because nothing was re-executed. Probing first both fixes that and SAVES
    # the classifier's three re-invocations on exactly the turns that deserve them least;
    # it is skipped entirely unless the reply DIVERGED, so an EQUAL turn costs nothing.
    determinism: Optional[DeterminismResult] = None
    tool_offered: Optional[bool] = True
    probe_note: Optional[str] = None
    if reply.result_equivalence == DIVERGED:
        tool_offered, probe_note = _boundary_offer(
            reply, tool_name,
            routed=resolved,
            configured=[c for c in (server_command, shell_server_command) if c is not None],
            network=network, timeout=timeout,
        )
        if tool_offered is True:
            determinism = classify_determinism(
                records, n,
                server_command=resolved, manifest_dir=manifest_dir,
                replays=replays, network=network, timeout=timeout,
            )
    result_verdict = render_result_verdict(
        reply, determinism,
        tool_offered=tool_offered, tool_name=tool_name, probe_note=probe_note,
    )
    effect_verdict = render_effect_verdict(records, n, reply.delta)
    sub_verdicts = [result_verdict, effect_verdict]
    # The NETWORK dimension is a THIRD, separate sub-verdict — never folded into the
    # filesystem `effect_verdict` (that made a PASS message carry an UNVERIFIED status).
    # It is present only when the tool declared a network RESTRICTION Belay does not observe
    # (`openWorldHint` false / non-boolean); an un-annotated turn gets no network sub-verdict.
    #
    # This comment used to end: "`reduce` then lowers the turn to UNVERIFIED by
    # worst-status-wins, and the reader sees exactly which dimension was unverified." That
    # fold was REVERSED. The sub-verdict now carries `Status.NOT_COVERED`, which `reduce`
    # drops before ranking, so it no longer lowers the turn. Reason: Belay has no network
    # instrument at all, so this is a coverage boundary rather than a failed attempt to
    # verify — and the old rule made an honestly-declared closed posture strictly worse than
    # silence (declare nothing -> PASS; declare truthfully -> UNVERIFIED forever). The
    # sub-verdict is still composed here, is still never a PASS, and still cannot soften a
    # FAIL; what it no longer does is decide the turn. Rendering surfaces must show it
    # alongside the status — a PASS without its coverage line is the failure mode.
    net_verdict = network_subverdict(records, n)
    if net_verdict is not None:
        sub_verdicts.append(net_verdict)

    # A1 (C5) is the THIRD axis, folded in ADDITIVELY exactly like the network dimension
    # above: one A1 sub-verdict per operator-declared PER-TURN invariant, each evaluated
    # against the SAME replay's observed `delta`. `reduce` is axis-agnostic
    # worst-status-wins, so an A1 FAIL lowers an all-A2-PASS turn to FAIL — the divergence
    # that catches a cheating agent A2 cannot (a declared-false tool that guts a
    # task-protected test is a C4 effect PASS but an A1 FAIL). A1 is added ONLY on this
    # REPLAYED path: `evaluate_invariant` grounds in an OBSERVED delta, and the
    # non-REPLAYED early return has none — with no delta A1 could only ever be UNVERIFIED,
    # and that turn is ALREADY UNVERIFIED, so an A1 sub-verdict there changes no status and
    # adds only noise. With `invariants=()` (the default) this loop runs zero times and the
    # turn is byte-for-byte C4's.
    #
    # INSTANCE-LEVEL rules (`INSTANCE_LEVEL_RULES`) are NOT per-turn: evaluating
    # `suite-before-success-claim` here would emit an A1 sub-verdict on every turn, and
    # since UNVERIFIED outranks PASS every turn would reduce to UNVERIFIED ->
    # `NO_VERIFIABLE_TURNS` -> `INSTRUMENT SUSPECT` — the poisoning hazard this phase
    # exists to close. They are skipped below BY CONSTRUCTION and evaluated once at
    # instance close (the trajectory seam), never here.
    #
    # A CONTENT-grounded rule (`no-assertion-weakening`) needs two trees the delta cannot
    # supply: the TASK pre-state (turn 0's snapshot) and this replay's workspace. They are
    # resolved HERE, at the call site, and handed over as two paths — `invariants.py` is
    # deliberately kept unable to reach `records`, because its public surface is the
    # provenance boundary that stops an agent authoring its own policy. The resolution runs
    # only when a declared rule actually needs it, so a `read-only`-only run does exactly the
    # work it did before.
    roots = None
    if any(inv.rule in CONTENT_GROUNDED_RULES for inv in invariants):
        roots = content_roots(records, manifest_dir, reply.workspace)
    for inv in invariants:
        if inv.rule in INSTANCE_LEVEL_RULES:
            continue  # instance-level: never per-turn-evaluated, never a per-turn sub-verdict
        sub_verdicts.append(evaluate_invariant(inv, reply.delta, n, roots=roots))

    status = reduce(sub_verdicts)
    return TurnVerdict(
        turn_index=n,
        tool_name=tool_name,
        status=status,
        sub_verdicts=sub_verdicts,
        # A replayed turn can still reduce to UNVERIFIED, and the gate requires every one
        # of those to name a cause — see `_replayed_cause`. Any other status carries none.
        cause=_replayed_cause(sub_verdicts) if status is Status.UNVERIFIED else None,
        # The observed replay outcome: the trajectory rule's evidence seam. Set only on
        # this REPLAYED path — the non-REPLAYED early return above leaves it absent.
        replayed_is_error=_replayed_is_error(reply),
    )


__all__ = ["TurnVerdict", "verify_turn"]
