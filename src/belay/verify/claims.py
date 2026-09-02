"""A3 — claim re-derivation: a model writes an executable check, EXECUTION decides.

A3 is the third verdict axis: the agent claimed *"all tests pass"*; a check author (a
model, behind an injectable seam) turns that claim plus the observed facts — the turn
facts and the final workspace's file list — into an **executable check**; the check
runner executes it against the **materialized final state**; and the exit code decides.

The honesty contract, stated once here:

- **A3 never emits PASS.** The axis's only decided status is FAIL (the check ran and
  exited non-zero); everything else is a named abstention or silence. `evaluate_claim`
  returns `None` in exactly two cases — no author configured (axis absent; the caller
  renders the coverage note) and exit 0 (D3: silence is not PASS) — and `None` is never
  rendered as PASS downstream.
- **Every UNVERIFIED verdict carries a named cause** (closed vocabulary, module-level
  constants, conventions of `trajectory.py:136-147`): `NO_CLAIM_RECORDED`,
  `CLAIM_UNCLASSIFIABLE`, `FINAL_STATE_UNOBSERVABLE`, `NO_CHECK_AUTHOR`,
  `CHECK_DID_NOT_EXECUTE`.
- **A check that did not execute is never a guess.** `exit_code=None` — launch failure
  or timeout — is UNVERIFIED with `CHECK_DID_NOT_EXECUTE`; the runner's `error` names
  which ("timed out after Ns" vs "could not launch"), and the message carries it
  verbatim, never inferred by the evaluator.
- **The check's source and its real exit code always surface** on a FAIL.
- **Everything is a seam.** The author (a model call in the real product) and the runner
  are injectable; this module and its tests contain no model call, no network, no clock.

The final state is materialized, never touched live: the LAST `tools/call` turn is
replayed through the existing engine into a scratch workspace (shell routing honored for
a final `run_process` turn, exactly like `verify_turn`), and the check runs inside that
workspace. A caller-supplied `workspace=` short-circuits the replay (the test seam; a
surface may pass it later — a follow-on optimization, not v0).

The decision table (each row a test in `tests/test_verify_claims.py`):

| Condition | Result |
|---|---|
| `author is None` | None (absent) |
| no claim record | UNVERIFIED `NO_CLAIM_RECORDED` |
| classification != VERIFICATION | UNVERIFIED `CLAIM_UNCLASSIFIABLE` |
| final state unobservable | UNVERIFIED `FINAL_STATE_UNOBSERVABLE` |
| author returns None / raises | UNVERIFIED `NO_CHECK_AUTHOR` |
| runner `exit_code=None` (launch failure / timeout) | UNVERIFIED `CHECK_DID_NOT_EXECUTE` |
| exit non-zero | FAIL |
| exit 0 | None (silence) |
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Protocol, Sequence

from belay.frames import message_of
from belay.index import derive_correlation, tool_calls
from belay.replay.engine import REPLAYED, replay_turn
from belay.sandbox.launch import contained
from belay.sandbox.seatbelt import NetworkPolicy
from belay.snapshot.bth1 import scan_tree
from belay.verify.trajectory import (
    ClaimClassification,
    TurnFact,
    assemble_turn_facts,
    classify_claim_text,
    extract_claim,
)
from belay.verify.trajectory import _EVIDENCE_TOOL  # noqa: PLC2701  (routing, as turn.py)
from belay.verify.verdict import Status, Verdict

if TYPE_CHECKING:
    from belay.replay.reader import Skip
    from belay.verify.turn import TurnVerdict


#: The default timeout for one A3 check, in seconds. The runner reports a killed check as
#: `timed out after Ns`, so this number is part of what a reader sees.
CHECK_TIMEOUT = 60.0

#: The named abstention causes (a CLOSED vocabulary — a reader of a stored verdict can
#: bucket on it without re-reading the trace). Conventions: `trajectory.py:136-147`.
CAUSE_NO_CLAIM_RECORDED = "NO_CLAIM_RECORDED"
CAUSE_CLAIM_UNCLASSIFIABLE = "CLAIM_UNCLASSIFIABLE"
CAUSE_NO_CHECK_AUTHOR = "NO_CHECK_AUTHOR"
#: A check that never executed — launch failure OR timeout, one cause; the message names
#: which. A single cause keeps the vocabulary smaller (spec open question, decided at
#: plan time).
CAUSE_CHECK_DID_NOT_EXECUTE = "CHECK_DID_NOT_EXECUTE"
CAUSE_FINAL_STATE_UNOBSERVABLE = "FINAL_STATE_UNOBSERVABLE"


@dataclass(frozen=True)
class Check:
    """One executable check, the artifact A3 surfaces — verbatim, nothing rewritten.

    `source` is the check as the author wrote it (the thing a reader quotes); `argv` is
    how to run it, relative to the final workspace's cwd — the check runs with the
    materialized final state as its working directory.
    """

    source: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class CheckResult:
    """What running one check observed.

    `exit_code` is the process's exit status; `None` means the check DID NOT EXECUTE —
    the sandbox could not launch it, or the timeout killed it — never a fabricated 0.
    `output` is the captured stdout; `error` the captured stderr, or a sentence naming
    the launch failure / timeout when there is no process to have written one.
    """

    exit_code: Optional[int]
    output: str
    error: Optional[str]


class CheckAuthor(Protocol):
    """The author seam: the claim + the observed facts -> one executable check, or none.

    A model-backed author lives behind this seam; every test injects a deterministic
    fake. Returns `None` when it cannot produce a check — a named abstention
    (`NO_CHECK_AUTHOR`), never a crash and never a guessed check.
    """

    def author_check(
        self,
        claim_text: str,
        *,
        classification: str,
        turns: Sequence[TurnFact],
        final_state_files: Sequence[str],
    ) -> Optional[Check]: ...


class CheckRunner(Protocol):
    """The runner seam: execute a check in the final workspace, contained.

    `exit_code=None` in the result means the check did not execute (launch failure or
    timeout) — the evaluator files `CHECK_DID_NOT_EXECUTE`, never a guess.
    """

    def run(self, check: Check, *, workspace: Path, timeout: float) -> CheckResult: ...


class ContainedRunner:
    """The real runner: `contained` around the check's argv, network denied, timeout kill.

    The check's argv runs inside the sandbox (`belay.sandbox.launch.contained`) with
    `deny-all` network, cwd at the materialized final workspace; stdout and stderr are
    captured. A check the sandbox could not launch (a missing binary, a backend-less
    platform) and a check that outlives `timeout` BOTH report `exit_code=None` — did not
    execute — with `error` naming which: `could not launch: <reason>` vs
    `timed out after Ns`. The evaluator carries that wording verbatim into the verdict
    message; it never infers which from anything else.

    **Named limitation, on the substrate wrappers:** a check binary that does not exist
    is refused INSIDE the wrapper (sandbox-exec exits 71, the Linux launcher exits 2)
    rather than at our Popen, so that shape reads as a non-zero exit — the wrapper's
    code, never the check's verdict — not as `CHECK_DID_NOT_EXECUTE`. Only a failure at
    our own layer (an unspawnable wrapper, a missing workspace cwd, a backend-less
    platform) reports `could not launch`. Never error-text matching: the wrapper's
    refusal is indistinguishable from a check that legitimately exits 71 by structure,
    and text would manufacture the distinction it does not have.
    """

    def run(self, check: Check, *, workspace: Path, timeout: float) -> CheckResult:
        try:
            with contained(
                list(check.argv), workspace=workspace, network=NetworkPolicy.deny_all()
            ) as spawn:
                proc = subprocess.Popen(
                    spawn.argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=workspace,
                )
                try:
                    out, err = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    return CheckResult(
                        exit_code=None,
                        output="",
                        error=f"timed out after {timeout:g}s",
                    )
        except Exception as exc:  # noqa: BLE001  (any spawn failure is a launch failure)
            return CheckResult(
                exit_code=None,
                output="",
                error=f"could not launch: {exc}",
            )
        return CheckResult(
            exit_code=proc.returncode,
            output=out.decode("utf-8", errors="replace"),
            error=err.decode("utf-8", errors="replace") or None,
        )


#: The check-runner seam. `evaluate_claim` runs the authored check through THIS binding;
#: tests replace it with a deterministic fake (the injectable-seam acceptance). The real
#: runner contains the check in the sandbox with network denied.
runner: CheckRunner = ContainedRunner()


class RecordingAuthor:
    """Wrap a `CheckAuthor` and remember the LAST check it produced (or None).

    The surfaces need the authored check AFTER `evaluate_claim` returns — the banked
    corpus case and the JSON/text records carry its source and exit code — and the
    evaluator returns only the verdict. This wrapper is that seam: what the author
    last wrote is exactly the check the returned verdict was decided by. `last_check`
    is `None` when the author abstained (returned `None`) or raised (the evaluator
    files `NO_CHECK_AUTHOR`; the wrapper resets before re-raising so it never
    remembers a check from a different invocation).
    """

    def __init__(self, inner: CheckAuthor):
        self._inner = inner
        self.last_check: Optional[Check] = None

    def author_check(
        self,
        claim_text: str,
        *,
        classification: str,
        turns: Sequence[TurnFact],
        final_state_files: Sequence[str],
    ) -> Optional[Check]:
        try:
            check = self._inner.author_check(
                claim_text,
                classification=classification,
                turns=turns,
                final_state_files=final_state_files,
            )
        except Exception:  # noqa: BLE001  (the evaluator owns the abstention; reset + re-raise)
            self.last_check = None
            raise
        self.last_check = check
        return check


def evaluate_claim(
    *,
    records: Sequence[dict],
    skips: Sequence["Skip"],
    verdicts: Mapping[int, "TurnVerdict"],
    author: Optional[CheckAuthor],
    manifest_dir: Path | str,
    server_command: Sequence[str],
    shell_server_command: Optional[Sequence[str]] = None,
    timeout: float = CHECK_TIMEOUT,
    replays: int = 3,
    workspace: Optional[Path] = None,
) -> Optional[Verdict]:
    """Evaluate ONE claim under A3: at most one verdict, or silence — never PASS.

    The decision table above, decided exactly and in order: an absent author returns
    `None` before anything else (the axis is absent — the caller renders the coverage
    note, never an UNVERIFIED); then the claim record; then its classification; then the
    final-state materialization; then the author; then the runner; then the exit code.

    `None` means either "axis absent" or "the check exited 0" — D3 silence, asserted by
    test to be never-PASS. A FAIL carries `observed=<exit code>`, `expected="exit 0"`,
    and the check source plus the real exit code in the message. Every UNVERIFIED verdict
    carries its named cause. The final state is a REPLAYED last `tools/call` turn's
    workspace (shell routing honored for a final `run_process`), or the caller-supplied
    `workspace=` short-circuit (the test seam) — never live state, never the original
    trace. `replays` is part of the pinned contract for later aspects; v0 materializes
    the final state with a single replay.
    """
    if author is None:
        return None

    claim_text, claim_seq = extract_claim(skips)
    if claim_seq is None:
        return _unverified(
            CAUSE_NO_CLAIM_RECORDED,
            claim_seq=None,
            detail="the trace records no claim record, so there is no claim to re-derive",
        )
    if claim_text is None or not claim_text.strip():
        return _unverified(
            CAUSE_CLAIM_UNCLASSIFIABLE,
            claim_seq=claim_seq,
            detail="the claim record carries no text, so it cannot be classified",
        )

    classification = classify_claim_text(claim_text)
    if classification is not ClaimClassification.VERIFICATION:
        return _unverified(
            CAUSE_CLAIM_UNCLASSIFIABLE,
            claim_seq=claim_seq,
            classification=classification,
            detail=(
                f"the claim {claim_text!r} classified as {classification.name} — "
                "completion-only or ambiguous text is not a verification claim"
            ),
        )

    turn_facts = assemble_turn_facts(records, verdicts)
    final_workspace = (
        workspace
        if workspace is not None
        else _materialize_final_state(
            records,
            manifest_dir=manifest_dir,
            server_command=server_command,
            shell_server_command=shell_server_command,
            timeout=timeout,
        )
    )
    if final_workspace is None:
        return _unverified(
            CAUSE_FINAL_STATE_UNOBSERVABLE,
            claim_seq=claim_seq,
            classification=classification,
            detail=(
                "the final turn's workspace could not be materialized — the last "
                "tools/call turn did not replay to a replayed workspace (or no turn "
                "exists), so the check has no final state to run against"
            ),
        )
    final_state_files = [
        os.fsdecode(record.path) for record in scan_tree(final_workspace) if record.path != b"."
    ]

    try:
        check = author.author_check(
            claim_text,
            classification=classification.name,
            turns=turn_facts,
            final_state_files=final_state_files,
        )
    except Exception as exc:  # noqa: BLE001  (an author failure is an abstention, never a crash)
        return _unverified(
            CAUSE_NO_CHECK_AUTHOR,
            claim_seq=claim_seq,
            classification=classification,
            detail=f"the check author raised {type(exc).__name__}",
        )
    if check is None:
        return _unverified(
            CAUSE_NO_CHECK_AUTHOR,
            claim_seq=claim_seq,
            classification=classification,
            detail="the check author returned no executable check",
        )

    try:
        result = runner.run(check, workspace=final_workspace, timeout=timeout)
    except Exception as exc:  # noqa: BLE001  (a runner failure is a non-execution, never a crash)
        return _unverified(
            CAUSE_CHECK_DID_NOT_EXECUTE,
            claim_seq=claim_seq,
            classification=classification,
            check=check,
            detail=f"the check runner raised {type(exc).__name__}",
        )
    if result.exit_code is None:
        return _unverified(
            CAUSE_CHECK_DID_NOT_EXECUTE,
            claim_seq=claim_seq,
            classification=classification,
            check=check,
            detail=(
                f"the check {check.source!r} did not execute: {result.error}"
                if result.error
                else f"the check {check.source!r} did not execute"
            ),
        )
    if result.exit_code == 0:
        return None
    return Verdict(
        "A3", "claim", Status.FAIL,
        observed=result.exit_code,
        expected="exit 0",
        message=f"{check.source} · exit {result.exit_code}",
    )


def _materialize_final_state(
    records: Sequence[dict],
    *,
    manifest_dir: Path | str,
    server_command: Sequence[str],
    shell_server_command: Optional[Sequence[str]],
    timeout: float,
) -> Optional[Path]:
    """The final state: the LAST `tools/call` turn replayed into a scratch workspace.

    `None` when there is no turn to replay, the replay did not reach REPLAYED, the
    replayed workspace was never observed, or the replay raised: the final state is
    genuinely unobservable (the caller files `FINAL_STATE_UNOBSERVABLE`) — never a
    guessed workspace. Shell routing is honored exactly like `verify_turn`: a final
    `run_process` turn replays against `shell_server_command` when one is given.
    """
    calls = tool_calls(derive_correlation(list(records)))
    if not calls:
        return None
    n = len(calls) - 1
    resolved = (
        shell_server_command
        if shell_server_command is not None and _tool_name(records, n) == _EVIDENCE_TOOL
        else server_command
    )
    try:
        reply = replay_turn(
            records, n,
            server_command=resolved, manifest_dir=manifest_dir, timeout=timeout,
        )
    except Exception:  # noqa: BLE001  (a substrate failure is an abstention, never a crash)
        return None
    if reply.status != REPLAYED or reply.workspace is None:
        return None
    return Path(reply.workspace)


def _tool_name(records: Sequence[dict], n: int) -> Optional[str]:
    """The Nth `tools/call`'s declared tool name, or `None` if it was never observed.

    Selects the turn by the correlation index, then reads `params.name` off that exact
    request frame — mirrors `turn._tool_name`; kept local so this module owns its own
    read of the trace.
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


def _unverified(
    cause: str,
    *,
    detail: str,
    claim_seq: Optional[int] = None,
    classification: Optional[ClaimClassification] = None,
    check: Optional[Check] = None,
) -> Verdict:
    """One named abstention: UNVERIFIED with its cause — never PASS, never FAIL.

    `expected` carries the cause plus whatever the evaluator reached before abstaining
    (the claim's seq and classification, the check's source), so a reader of a stored
    verdict can bucket on the cause without re-reading the trace.
    """
    expected: dict[str, Any] = {"axis": "A3", "kind": "claim", "cause": cause}
    if claim_seq is not None:
        expected["claim_seq"] = claim_seq
    if classification is not None:
        expected["classification"] = classification.name
    if check is not None:
        expected["check_source"] = check.source
    return Verdict(
        "A3", "claim", Status.UNVERIFIED,
        observed=None, expected=expected,
        message=f"A3 claim re-derivation is UNVERIFIED [{cause}]: {detail} — never PASS",
    )


def claim_case(verdict: Verdict, *, check: Optional[Check] = None) -> Optional[dict]:
    """An A3 claim verdict shaped as a v5 corpus claim expected field, or None.

    The failure-corpus banking seam for the A3 axis, mirroring `trajectory_case`
    (`invariants.py:732-772`): a PURE shaping function that turns one A3 verdict into
    the instance-level `claim` expected field `case.py`'s v5 loader validates — no
    persistence, no format beyond what the verdict already grounds.

    Returns None when the verdict is not an A3 claim FAIL or UNVERIFIED — a WARN
    (the vocabulary stays empty in v0) and a PASS (which A3 never emits) have no
    intent drift to record, so a caller keeps exactly the FAIL/UNVERIFIED cases. The
    FAIL shape carries `cause: null` (the check ran and decided; there is no named
    abstention) and the check's source plus the OBSERVED exit code — the real exit,
    never a fabricated 0. The UNVERIFIED shape carries its named cause (read from the
    verdict's `expected` dict) and a `check` entry whose `exit_code` is `null` — did
    not execute, the CheckResult contract — with the authored check's source when one
    was produced (`check=`, or `expected["check_source"]`), `""` when none was (the
    no-author abstention has no check to quote).
    """
    if verdict.axis != "A3" or verdict.kind != "claim":
        return None
    if verdict.status is Status.FAIL:
        return {
            "status": "FAIL",
            "cause": None,
            "check": {
                "source": check.source if check is not None else "",
                "exit_code": verdict.observed,
            },
        }
    if verdict.status is Status.UNVERIFIED:
        expected = verdict.expected if isinstance(verdict.expected, dict) else {}
        return {
            "status": "UNVERIFIED",
            "cause": expected.get("cause"),
            "check": {
                "source": (
                    check.source
                    if check is not None
                    else expected.get("check_source", "")
                ),
                "exit_code": None,
            },
        }
    return None


__all__ = [
    "CAUSE_CHECK_DID_NOT_EXECUTE",
    "CAUSE_CLAIM_UNCLASSIFIABLE",
    "CAUSE_FINAL_STATE_UNOBSERVABLE",
    "CAUSE_NO_CHECK_AUTHOR",
    "CAUSE_NO_CLAIM_RECORDED",
    "CHECK_TIMEOUT",
    "Check",
    "CheckAuthor",
    "CheckResult",
    "CheckRunner",
    "ContainedRunner",
    "RecordingAuthor",
    "claim_case",
    "evaluate_claim",
    "runner",
]