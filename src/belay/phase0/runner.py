"""The Phase-0 batch runner: walk traces, verify each turn, fold outcomes into a `RunLedger`.

`run_batch` is the driver that turns a directory of captured traces into Task 1's
`RunLedger` — the thing Task 2's report renders. For each trace file it verifies every
observed `tools/call` turn, ingests the FAILing ones as corpus cases, and classifies the
instance's disposition from what actually happened during verification. No CLI lives here
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
- Else, any turn REPLAYED (status PASS or WARN -- a real, decided, non-UNVERIFIED verdict) ->
  `VERIFIED_CLEAN`. One decided turn is a real verification, even alongside UNVERIFIED
  siblings.
- Else (zero `tools/call` turns, or every turn UNVERIFIED) -> `NO_VERIFIABLE_TURNS`: nothing
  was ever verified, so this instance must not silently read as "clean".
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
from typing import Callable, Sequence

from belay.corpus.add import add_case
from belay.index import derive_correlation, tool_calls
from belay.phase0.ledger import Disposition, InstanceRecord, RunLedger
from belay.replay.client import DEFAULT_TIMEOUT
from belay.replay.reader import read_trace
from belay.verify.invariants import Invariant
from belay.verify.turn import TurnVerdict, verify_turn
from belay.verify.verdict import Status

#: The `unverified_causes` bucket for a turn whose `TurnVerdict.cause` is `None` -- should
#: not happen for a real UNVERIFIED verdict (`verify_turn` always names a cause), but a fake
#: verifier could omit one, and a missing bucket must never silently vanish from the tally.
_UNKNOWN_CAUSE = "unknown"


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
    server_command: list[str],
    invariants: Sequence[Invariant],
    captured_at: str,
    replays: int = 3,
    timeout: float = DEFAULT_TIMEOUT,
    manifest_dir_for: Callable[[Path], Path] = default_manifest_dir_for,
    verifier: Callable[..., TurnVerdict] = verify_turn,
    ingester: Callable[..., Path] = add_case,
) -> RunLedger:
    """Verify every trace in `trace_dir`, ingest FAILing turns, and return the `RunLedger`.

    Enumerates `sorted(trace_dir.glob("trace-*.jsonl"))` -- stable order, so a re-run over
    the same directory produces instances in the same sequence. Each trace's `source_trace_id`
    is its file stem. See the module docstring for the disposition rule and the ERRORED
    exception boundary.
    """
    instances: list[InstanceRecord] = []

    for trace_path in sorted(Path(trace_dir).glob("trace-*.jsonl")):
        source_trace_id = trace_path.stem
        try:
            instance = _verify_one_trace(
                trace_path,
                source_trace_id=source_trace_id,
                corpus_dir=corpus_dir,
                server_command=server_command,
                invariants=invariants,
                captured_at=captured_at,
                replays=replays,
                timeout=timeout,
                manifest_dir_for=manifest_dir_for,
                verifier=verifier,
                ingester=ingester,
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
            )
        instances.append(instance)

    return RunLedger(instances=instances)


def _verify_one_trace(
    trace_path: Path,
    *,
    source_trace_id: str,
    corpus_dir: Path,
    server_command: list[str],
    invariants: Sequence[Invariant],
    captured_at: str,
    replays: int,
    timeout: float,
    manifest_dir_for: Callable[[Path], Path],
    verifier: Callable[..., TurnVerdict],
    ingester: Callable[..., Path],
) -> InstanceRecord:
    """One trace file, fully verified: every `tools/call` turn, every FAIL ingested.

    Raises whatever `read_trace` / `verifier` / `ingester` raise for anything other than the
    ingester's `ValueError` (the one exception this function itself handles, per turn, since
    an unaddable case is a bucketed fact, not a batch-ending error). `run_batch` is the layer
    that turns any OTHER exception here into `Disposition.ERRORED`.
    """
    records = list(read_trace(trace_path).records)
    calls = tool_calls(derive_correlation(records))
    manifest_dir = manifest_dir_for(trace_path)

    turn_status_counts: dict[str, int] = {}
    unverified_causes: dict[str, int] = {}
    verdicts: dict[int, TurnVerdict] = {}
    replayed_any = False

    for n in range(len(calls)):
        verdict = verifier(
            records,
            n,
            server_command=server_command,
            manifest_dir=manifest_dir,
            invariants=invariants,
            replays=replays,
            timeout=timeout,
        )
        verdicts[n] = verdict
        turn_status_counts[verdict.status.name] = turn_status_counts.get(verdict.status.name, 0) + 1
        if verdict.status is Status.UNVERIFIED:
            bucket = verdict.cause if verdict.cause is not None else _UNKNOWN_CAUSE
            unverified_causes[bucket] = unverified_causes.get(bucket, 0) + 1
        else:
            replayed_any = True

    flagged_turns = [n for n in range(len(calls)) if verdicts[n].status is Status.FAIL]

    flagged_addable: list[int] = []
    flagged_unaddable: list[dict] = []
    for n in flagged_turns:
        try:
            ingester(
                corpus_dir,
                records=records,
                target_turn_index=n,
                verdict=verdicts[n],
                manifest_dir=manifest_dir,
                server_command=server_command,
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

    if flagged_turns:
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
    )


__all__ = ["run_batch", "default_manifest_dir_for"]
