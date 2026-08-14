"""The Phase-0 batch runner: walk traces, verify each turn, fold outcomes into a `RunLedger`.

`run_batch` is the driver that turns a directory of captured traces into Task 1's
`RunLedger` — the thing Task 2's report renders. For each trace file it verifies every
observed `tools/call` turn, ingests the FAILing ones as corpus cases (and a FAILing
INSTANCE-LEVEL trajectory verdict as a corrupt-success case — `corpus-trajectory`
phase 2), and classifies the instance's disposition from what actually happened during
verification. No CLI lives here
(that's a later task); this module is pure orchestration over the seams below.

## The seam: real functions by default, fakes injected in tests

`verifier` defaults to `belay.verify.turn.verify_turn` and `ingester` to
`belay.corpus.add.add_case` — both reused verbatim, never modified. A test can inject a fake
of either and never touch real replay or Seatbelt: capture, `derive_correlation`, and
`tool_calls` are pure and cross-platform, so a fake verifier keyed by turn index is enough to
exercise every disposition and ingest-outcome branch this module has to get right.

## One bad trace never aborts the batch

Each trace's whole body — read, correlate, verify every turn, ingest every FAIL — runs
inside one try/except. Any exception (a corrupt file, a verifier that raises, anything else)
turns that ONE instance into `Disposition.ERRORED` with the exception message recorded, and
the loop moves on to the next trace file. A batch run over a few hundred captured traces
must not die on trace #37; it must SAY #37 broke and keep going.

## The disposition rule, and why UNVERIFIED never promotes anything

- Any turn's status is FAIL -> `VERIFIED_FLAGGED` (a flagged-but-unaddable turn still counts:
  see below).
- OR the instance-level trajectory verdict is FAIL (`suite-before-success-claim`: a
  verification claim with zero observed command evidence — the corrupt-success shape) ->
  `VERIFIED_FLAGGED`, same bucket as a turn FAIL (PRD decision). A trajectory
  UNVERIFIED abstention never flags.
- Else, any turn REPLAYED (status PASS or WARN -- a real, decided, non-UNVERIFIED verdict) ->
  `VERIFIED_CLEAN`. One decided turn is a real verification, even alongside UNVERIFIED
  siblings.
- Else (zero `tools/call` turns, or every turn UNVERIFIED) -> `NO_VERIFIABLE_TURNS`: nothing
  was ever verified, so this instance must not silently read as "clean".
- A turn whose status were `NOT_COVERED` counts as NEITHER replayed nor UNVERIFIED. It is
  unreachable (`verdict.reduce` drops that status before ranking) but it is written as an
  explicit branch rather than swept into the `else`, because sweeping it up would let a
  coverage boundary promote an instance to `VERIFIED_CLEAN`. Separately, every turn's
  NOT_COVERED SUB-verdicts are tallied by kind into `InstanceRecord.not_covered_turns`, so
  the coverage boundary is persisted and survives into `belay phase0 report`.
- `ERRORED` is reserved for the exception path above; it is never assigned by this rule.

A flagged turn whose ingest raises `ValueError` (the corpus's "no restorable pre-state"
case, `belay.corpus.add.add_case`) is bucketed into `flagged_unaddable`, NOT dropped and NOT
promoted to CLEAN -- it is still an observed FAIL, so the instance is still
`VERIFIED_FLAGGED` and still counts in the violation numerator. Only the *corpus case* failed
to compose; the *violation* is unaffected.

## No clock, no network, no randomness

`captured_at` is injected by the caller (the CLI boundary reads the clock; this module never
does) and passed through to the ingester byte-for-byte. `default_manifest_dir_for` is a pure
path computation -- the trace's `.manifests` sibling, by the mint convention C2/C3 already
use; Task 5's darwin e2e is what confirms that convention matches the real snapshot layout,
since the fake verifier injected here does not care what the directory contains.

stdlib only; `verify_turn`, `add_case`, `read_trace`, `derive_correlation`, and `tool_calls`
are reused verbatim -- this module composes them, and changes none of them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence

from belay.corpus.add import add_case
from belay.index import derive_correlation, tool_calls
from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.reader import ReadResult, read_trace
from belay.replay.report import canonical_cause
from belay.verify.invariants import INSTANCE_LEVEL_RULES, Invariant, trajectory_case
from belay.verify.trajectory import (
    _EVIDENCE_TOOL,
    evaluate_trajectory_rules,
    extract_claim,
)
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status, Verdict

#: The `unverified_causes` bucket for a turn whose `TurnVerdict.cause` is `None` -- should
#: not happen for a real UNVERIFIED verdict (`verify_turn` always names a cause), but a fake
#: verifier could omit one, and a missing bucket must never silently vanish from the tally.
_UNKNOWN_CAUSE = "unknown"


def _resolve_server_command(
    tool_name: Optional[str],
    server_command: list[str],
    shell_server_command: list[str] | None,
) -> list[str]:
    """The ONE command a given turn actually replays against — the ingest-seam rule.

    A turn whose tool name is exactly `_EVIDENCE_TOOL` (`run_process`) and for which a
    shell command is given replays against the shell command; every other turn — and
    every turn when no shell command was given — replays against `server_command`. This
    is the runner's OWN resolution, mirroring `verify_turn`'s routing (which decides
    what actually replayed): a corpus case must store the command its turn really
    replayed against, so a shell case carries the shell command and an fs case the fs
    command. With `shell_server_command=None` this always answers `server_command` —
    byte-for-byte today.
    """
    if tool_name == _EVIDENCE_TOOL and shell_server_command is not None:
        return shell_server_command
    return server_command


def default_manifest_dir_for(trace_path: Path) -> Path:
    """The trace's `.manifests` sibling dir, by the mint convention: `<stem>.manifests`.

    A pure path computation, no filesystem check -- the directory need not exist for this
    function to answer. Confirmed against the real snapshot layout by Task 5's darwin e2e;
    every test in this module injects a fake verifier that ignores the directory's contents,
    so this convention is exercised here only as a name, never as a real snapshot tree.
    """
    trace_path = Path(trace_path)
    return trace_path.parent / (trace_path.stem + ".manifests")


def run_batch(
    trace_dir: Path,
    *,
    corpus_dir: Path,
    server_command: list[str] | None = None,
    shell_server_command: list[str] | None = None,
    invariants: Sequence[Invariant],
    captured_at: str,
    replays: int = 3,
    timeout: float = DEFAULT_TIMEOUT,
    manifest_dir_for: Callable[[Path], Path] = default_manifest_dir_for,
    server_command_for: Callable[[Path], list[str]] | None = None,
    verifier: Callable[..., TurnVerdict] = verify_turn,
    ingester: Callable[..., Path] = add_case,
    ingest: bool = True,
) -> RunLedger:
    """Verify every trace in `trace_dir`, ingest FAILing turns, and return the `RunLedger`.

    Enumerates `sorted(trace_dir.glob("trace-*.jsonl"))` -- stable order, so a re-run over
    the same directory produces instances in the same sequence. Each trace's `source_trace_id`
    is its file stem. See the module docstring for the disposition rule and the ERRORED
    exception boundary.

    The server command is resolved PER TRACE. `server_command_for(trace_path) -> list[str]`
    is the library seam (what `eval/` calls) for a batch whose traces need different
    commands; the plain `server_command` list stays the ordinary case and is simply wrapped
    in a constant resolver, so every existing caller is unaffected. Note that varying the
    *workspace root* alone needs NEITHER: `belay.replay.engine.WORKSPACE_PLACEHOLDER`
    (`{workspace}`) in one static command is substituted with each trace's own recorded
    `source_root`, which is strictly more correct than restating a root the trace carries.
    Exactly one of the two must be given.

    `ingest=False` makes this a PURE MEASUREMENT: the corpus is never written, so the
    ingester is never called at all. Detection is untouched -- every turn is still verified,
    every FAIL still counted in `flagged_turns`, and the disposition is unchanged. What
    changes is only the ingest ACCOUNTING: both `flagged_addable` and `flagged_unaddable`
    stay empty, because nothing was attempted. That empty pair is exactly why the caller
    must SAY ingestion was disabled -- unlabelled, it reads as "nothing could be added"
    (see `belay.cli._cmd_phase0_run`).

    `shell_server_command` (optional) is the dual-server axis: it is threaded to the
    verifier on every turn, so `verify_turn` can route `run_process` turns against it,
    and — resolved PER FLAGGED TURN by that turn's `tool_name` — to each `ingester(...)`
    call, so a corpus case stores the command its turn actually replayed against. With
    `None` (the default) the resolved command is always `server_command` and everything
    is byte-for-byte today.
    """
    if (server_command is None) == (server_command_for is None):
        raise TypeError("run_batch requires exactly one of server_command / server_command_for")
    if server_command_for is None:
        constant = list(server_command or [])
        server_command_for = lambda _trace_path: constant  # noqa: E731

    instances: list[InstanceRecord] = []

    for trace_path in sorted(Path(trace_dir).glob("trace-*.jsonl")):
        source_trace_id = trace_path.stem
        try:
            instance = _verify_one_trace(
                trace_path,
                source_trace_id=source_trace_id,
                corpus_dir=corpus_dir,
                server_command=server_command_for(trace_path),
                shell_server_command=shell_server_command,
                invariants=invariants,
                captured_at=captured_at,
                replays=replays,
                timeout=timeout,
                manifest_dir_for=manifest_dir_for,
                verifier=verifier,
                ingester=ingester,
                ingest=ingest,
            )
        except Exception as exc:  # noqa: BLE001 -- one bad trace must never abort the batch
            instance = InstanceRecord(
                trace_id=source_trace_id,
                disposition=Disposition.ERRORED,
                turn_status_counts={},
                flagged_turns=[],
                flagged_addable=[],
                flagged_unaddable=[],
                unverified_causes={},
                error=str(exc),
                # Decided explicitly, not left to the dataclass default: an ERRORED
                # instance never reached the verification loop, so `exposure=None` here
                # says "unrecorded", never "the rule judged nothing" -- a zeroed dict
                # would assert the exact false finding this aspect exists to prevent.
                exposure=None,
            )
        instances.append(instance)

    return RunLedger(instances=instances)


def _verify_one_trace(
    trace_path: Path,
    *,
    source_trace_id: str,
    corpus_dir: Path,
    server_command: list[str],
    shell_server_command: list[str] | None = None,
    invariants: Sequence[Invariant],
    captured_at: str,
    replays: int,
    timeout: float,
    manifest_dir_for: Callable[[Path], Path],
    verifier: Callable[..., TurnVerdict],
    ingester: Callable[..., Path],
    ingest: bool = True,
) -> InstanceRecord:
    """One trace file, fully verified: every `tools/call` turn, every FAIL ingested.

    Ingest covers two shapes: the FAILing TURNS (one case each, target = the failing
    turn) and, when the instance's trajectory verdict is FAIL, ONE instance-level
    corrupt-success case (target = the final turn, schema-v4 `trajectory` expected) —
    see the ingest block below.

    Raises whatever `read_trace` / `verifier` / `ingester` raise for anything other than the
    ingester's `ValueError` (the one exception this function itself handles, per turn and
    per trajectory case, since an unaddable case is a bucketed fact, not a batch-ending
    error). `run_batch` is the layer that turns any OTHER exception here into
    `Disposition.ERRORED`.

    `ingest=False` skips the ingest loop wholesale (see `run_batch`): the verdicts, the
    `flagged_turns` list and the disposition are computed exactly as before, and only the
    two ingest-outcome buckets are left empty.
    """
    read_result: ReadResult = read_trace(trace_path)
    records = list(read_result.records)
    calls = tool_calls(derive_correlation(records))
    manifest_dir = manifest_dir_for(trace_path)

    turn_status_counts: dict[str, int] = {}
    unverified_causes: dict[str, int] = {}
    not_covered_turns: dict[str, int] = {}
    verdicts: dict[int, TurnVerdict] = {}
    replayed_any = False

    # Exposure accounting (Task 1's `expected["exposure"]` on an A1 sub-verdict, C5's
    # `no-assertion-weakening` content rule). WHAT IS AND IS NOT DEDUPLICATED, exactly:
    # `turns_recorded` and `turns_judging` count the TURN once however many A1 sub-verdicts
    # it carries (like `not_covered_turns` above), so a turn judged under both default
    # scopes (`tests` + `testing`) is one turn, not two. `files_compared` is SUMMED across
    # those sub-verdicts and is NOT deduplicated: a file matching both default scopes is
    # counted twice. That is real, not hypothetical -- sympy has
    # `sympy/testing/tests/test_*.py`, which is under a `testing` segment AND a `tests` one.
    # Deliberate: the number answers "how many judgments did the rule make", and both rules
    # really did judge that file. It is NOT a count of distinct files, and must never be
    # read against a file count.
    exposure_files_compared = 0
    exposure_turns_judging = 0
    exposure_turns_recorded = 0

    for n in range(len(calls)):
        verifier_kwargs = dict(
            records=records,
            n=n,
            server_command=server_command,
            manifest_dir=manifest_dir,
            invariants=invariants,
            replays=replays,
            timeout=timeout,
        )
        # The shell axis is threaded ONLY when set: `None` must mean "today's behavior"
        # byte-for-byte, and a fake verifier written before the kwarg existed must keep
        # working (the resolution is `verify_turn`'s, and it gets both commands only
        # when the batch actually has both).
        if shell_server_command is not None:
            verifier_kwargs["shell_server_command"] = shell_server_command
        verdict = verifier(**verifier_kwargs)
        verdicts[n] = verdict
        turn_status_counts[verdict.status.name] = turn_status_counts.get(verdict.status.name, 0) + 1

        # The coverage boundary, tallied per TURN (a kind is counted once however many
        # sub-verdicts of that kind the turn carries) so `n/total_turns` reads as a
        # fraction of turns. This is what makes the boundary reachable from a STORED
        # ledger, i.e. from `belay phase0 report`, which re-renders JSON and computes
        # nothing.
        for kind in sorted({s.kind for s in verdict.sub_verdicts if s.status is Status.NOT_COVERED}):
            not_covered_turns[kind] = not_covered_turns.get(kind, 0) + 1

        # A turn contributes to `turns_recorded` iff AT LEAST ONE A1 sub-verdict carried an
        # `"exposure"` key at all -- a `read-only`-only turn, or one whose content rule hit
        # one of the five early abstains (`invariants.py`'s `_evaluate_content_rule`), never
        # carries the key and must never be coerced into a recorded zero. `files_compared`
        # sums each such sub-verdict's `"compared"` count with `.get(..., 0)`, which is what
        # makes the file-budget abstain's partial `{"in_scope": M}` (no `compared` key)
        # contribute 0 files rather than raising or fabricating a count.
        turn_exposures = [
            s.expected["exposure"]
            for s in verdict.sub_verdicts
            if s.axis == "A1"
            and s.kind == "invariant"
            and isinstance(s.expected, dict)
            and "exposure" in s.expected
        ]
        if turn_exposures:
            exposure_turns_recorded += 1
            turn_compared = sum(exp.get("compared", 0) for exp in turn_exposures)
            exposure_files_compared += turn_compared
            if turn_compared >= 1:
                exposure_turns_judging += 1

        if verdict.status is Status.UNVERIFIED:
            # Bucket by the CANONICAL name, as the runner spec says this table does
            # (`phase0-runner/spec.md:48`) — it never actually called `canonical_cause`,
            # it copied the field, so any caller handing over a verbatim engine string got
            # its own per-turn row in the published breakdown. `verify_turn` already
            # canonicalises on both of its paths, so for the real verifier this is a
            # no-op; it is the seam that keeps every OTHER verifier honest. A `None` cause
            # still goes to the catch-all rather than through `canonical_cause`, which
            # would relabel it "unrestorable (no recorded cause)" and assert a restore
            # failure nobody observed.
            bucket = canonical_cause(verdict.cause) if verdict.cause is not None else _UNKNOWN_CAUSE
            unverified_causes[bucket] = unverified_causes.get(bucket, 0) + 1
        elif verdict.status is Status.NOT_COVERED:
            # DECIDED, not accidental. `verdict.reduce` filters NOT_COVERED out before
            # ranking, so a turn's reduced status can never BE NOT_COVERED and this branch
            # is unreachable through the real verifier. It is written anyway because the
            # old `else` swept it up and set `replayed_any = True` BY ACCIDENT — a turn
            # whose status said "outside what Belay checks" would have promoted the whole
            # instance to VERIFIED_CLEAN, i.e. a coverage boundary manufacturing a clean
            # denominator entry. A NOT_COVERED turn verified NOTHING, so it does not count
            # as replayed; if every turn were one the instance is NO_VERIFIABLE_TURNS.
            pass
        else:
            replayed_any = True

    flagged_turns = [n for n in range(len(calls)) if verdicts[n].status is Status.FAIL]

    # `exposure` stays `None` when NO turn recorded anything -- including the whole-instance
    # case where A1 never ran at all (no invariants declared, or only `read-only`, which has
    # no exposure concept). A zeroed dict there would assert "the rule judged nothing",
    # which is a different, false, claim from "the rule was never asked to judge".
    exposure = (
        {
            "files_compared": exposure_files_compared,
            "turns_judging": exposure_turns_judging,
            "turns_recorded": exposure_turns_recorded,
        }
        if exposure_turns_recorded > 0
        else None
    )

    # INSTANCE-LEVEL rules (the trajectory seam): evaluated ONCE per instance, before
    # the ingest section (a trajectory FAIL ingests its own case) and before
    # the disposition is decided, from the narrow facts seam — the claim record (the
    # reader's skips) plus per-turn replayed facts — never raw records
    # (`test_no_invariant_is_ever_sourced_from_a_trace`). The verdict is held as a
    # serialized summary `{"status", "cause", "evidence_count"}` on the instance
    # record, present ONLY when the rule was declared (absent-never-zero: a run that
    # never declared the rule has no verdict to record). A run_process turn after the
    # claim's seq is never evidence — the claim is the final statement, so its seq is
    # the boundary.
    trajectory = evaluate_trajectory_rules(
        invariants,
        skips=read_result.skips,
        records=records,
        verdicts=verdicts,
    )

    flagged_addable: list[int] = []
    flagged_unaddable: list[dict] = []
    trajectory_addable = False
    trajectory_unaddable: Optional[dict] = None
    # `ingest=False` means the corpus is never written, so the ingester is never CALLED --
    # skipping the loop is the whole implementation. The turn buckets therefore stay empty:
    # a turn nobody tried to add is NOT an unaddable turn, and recording it as one would
    # assert a composition failure that never happened. `flagged_turns` above is already
    # computed, so the turn keeps its real FAIL and its place in the numerator.
    if ingest:
        for n in flagged_turns:
            try:
                ingester(
                    corpus_dir,
                    records=records,
                    target_turn_index=n,
                    verdict=verdicts[n],
                    manifest_dir=manifest_dir,
                    server_command=_resolve_server_command(
                        verdicts[n].tool_name, server_command, shell_server_command
                    ),
                    invariants=list(invariants),
                    human_label="pending",
                    replays=replays,
                    timeout=timeout,
                    source_trace_id=source_trace_id,
                    captured_at=captured_at,
                )
                flagged_addable.append(n)
            except ValueError as exc:
                flagged_unaddable.append({"turn": n, "cause": str(exc)})

        # A trajectory FAIL ingests its OWN case, alongside the per-turn ingest: every
        # caught failure becomes a case (moat #2). The case is shaped by
        # `trajectory_case` (the instance-level sibling of `corrupt_success_case` —
        # the rule/scope/message it names are what the stored A1 sub-verdict carries),
        # targets the instance's FINAL turn (the full trace is stored, so the case holds
        # the claim record and every prior turn), and declares the instance-level
        # expected verdict through `add_case`'s schema-v4 `trajectory` field — the
        # corpus-collision guard and the pre-state bundling apply identically. A FAILing
        # ingest is a bucketed fact, never an exception: the same `ValueError` handling
        # as the per-turn loop, so a re-run over an existing case cannot error the
        # instance and shrink the denominator (the fake-PIVOT hazard). A trajectory
        # PASS or UNVERIFIED abstention ingests nothing.
        if trajectory is not None and trajectory.get("status") == "FAIL":
            final_turn = len(calls) - 1
            instance_rule = next(
                (inv for inv in invariants if inv.rule in INSTANCE_LEVEL_RULES), None
            )
            if instance_rule is not None:
                claim_text, _claim_seq = extract_claim(read_result.skips)
                # The trajectory case targets the instance's FINAL turn, so its tool name
                # decides which command the case stores — the same per-turn rule as above.
                final_tool_name = (
                    verdicts[final_turn].tool_name if final_turn in verdicts else None
                )
                shaped = trajectory_case(
                    instance_rule,
                    trajectory=trajectory,
                    final_turn=final_turn,
                    tool_name=final_tool_name,
                    claim_text=claim_text,
                )
                if shaped is not None:
                    # The case must be SELF-CONTAINED for a later `corpus run` recompute:
                    # the reader skips `claim` records (unknown kind) out of `records`, so
                    # the full trajectory this verdict judged is `records` PLUS the claim
                    # records, carried in the skip list. The per-turn ingest deliberately
                    # keeps the reader's `records` — a turn case needs the replay handshake,
                    # never the claim — and only the instance-level case appends them.
                    trajectory_records = [
                        *records,
                        *(
                            skip.record
                            for skip in read_result.skips
                            if skip.kind == "claim" and skip.record is not None
                        ),
                    ]
                    trajectory_verdict = TurnVerdict(
                        turn_index=final_turn,
                        tool_name=shaped["tool_name"],
                        status=Status.FAIL,
                        sub_verdicts=[
                            Verdict(
                                "A1",
                                "invariant",
                                Status.FAIL,
                                observed=None,
                                expected={"rule": shaped["rule"], "scope": shaped["scope"]},
                                message=shaped["message"],
                            )
                        ],
                    )
                    try:
                        ingester(
                            corpus_dir,
                            records=trajectory_records,
                            target_turn_index=final_turn,
                            verdict=trajectory_verdict,
                            manifest_dir=manifest_dir,
                            server_command=_resolve_server_command(
                                final_tool_name, server_command, shell_server_command
                            ),
                            invariants=list(invariants),
                            human_label="pending",
                            replays=replays,
                            timeout=timeout,
                            source_trace_id=source_trace_id,
                            captured_at=captured_at,
                            trajectory={"status": "FAIL", "cause": trajectory.get("cause")},
                        )
                        trajectory_addable = True
                    except ValueError as exc:
                        trajectory_unaddable = {"cause": str(exc)}

    # The disposition rule, PRD decision: a trajectory FAIL lands in the SAME bucket as
    # a turn FAIL — the instance is VERIFIED_FLAGGED and counts in the violation
    # numerator, whatever its turns said. A trajectory UNVERIFIED (no claim, an
    # unclassifiable claim, unobservable evidence) never flags — an abstention is not a
    # violation — so only status FAIL participates here.
    if flagged_turns or (trajectory is not None and trajectory.get("status") == "FAIL"):
        disposition = Disposition.VERIFIED_FLAGGED
    elif replayed_any:
        disposition = Disposition.VERIFIED_CLEAN
    else:
        disposition = Disposition.NO_VERIFIABLE_TURNS

    return InstanceRecord(
        trace_id=source_trace_id,
        disposition=disposition,
        turn_status_counts=turn_status_counts,
        flagged_turns=flagged_turns,
        flagged_addable=flagged_addable,
        flagged_unaddable=flagged_unaddable,
        unverified_causes=unverified_causes,
        error=None,
        not_covered_turns=not_covered_turns,
        exposure=exposure,
        trajectory=trajectory,
        trajectory_addable=trajectory_addable,
        trajectory_unaddable=trajectory_unaddable,
    )


__all__ = ["run_batch", "default_manifest_dir_for"]
