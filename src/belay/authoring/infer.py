"""The `belay invariant infer` orchestration: author -> validate -> calibrate -> emit.

The `authoring-protocol` aspect, phases 3-5. The author command proposes task-specific
A1 invariants from a task spec (the `protocol` seam); this module runs it, validates the
proposal, **calibrates the survivors against a known-clean control by execution** — the
same `verify_turn` composition `belay verify` calls, with the candidate invariants ONLY,
never the defaults — and emits the reviewable artifact (schema owned by `artifact-trust`,
digest computed with `canonical_policy_digest` so the loader's recompute matches).

The honesty contract, stated once:

- **D-5 — calibration is the shipped composition.** One pass over the control's turns,
  each through `belay.verify.turn.verify_turn`. A candidate whose A1 sub-verdict FAILs
  any control turn is rejected (`CALIBRATION_FAILED`), attributed per invariant via the
  sub-verdict's `expected["rule"]` + `expected["scope"]`. PASS and UNVERIFIED are kept —
  an invariant that cannot be grounded on a turn is not a violation, and rejecting every
  abstaining candidate would make honest-but-ungrounded rules unauthorable. There is no
  second evaluator; the structural pin is a test, not a comment.
- **D-6 — a vacuous calibration emits nothing.** If no control turn yields a DECIDED A2
  result sub-verdict (axis `A2`, kind exactly `replay`, status PASS or FAIL — the
  narrowed `replay:<reason>` abstentions do not count), the control never actually
  re-executed and calibration would be an empty ceremony. `CONTROL_UNREPLAYABLE`, exit
  2, no artifact, never a `"calibrated"` record. A control with zero tool calls is the
  same shape.
- **Fail-closed at every step, never raising.** A bad author, an unparseable proposal,
  an unknown rule, a calibration rejection, an unreadable task/control, missing
  manifests, a control that cannot be decided, an unwritable `--out` — every failure is
  a named outcome in `InferResult.cause` and no artifact is written (the `--out` path is
  untouched: emission is one atomic `os.replace`, so a failure can never leave a partial
  file). A bad author produces no policy, exactly as a bad invariant file produces a
  `ValueError` instead of a silent `[]`.
- **The artifact is deterministic** for fixed inputs: `sort_keys=True`, compact
  separators, no timestamps, no randomness. Re-running the same task, control and author
  produces byte-identical bytes.
- **The author never sees the control** (D-7): the input is task text + a bounded,
  sorted repo inventory (`--repo`, `.git` excluded, capped by the protocol) + the rule
  vocabulary + the library entries. Calibration is independent of the author.

Stdlib only (`json`, `hashlib`, `os`, `tempfile`, `dataclasses`, `pathlib`); the replay
composition is imported lazily inside `_calibrate` so this module stays light and the
structural-pin test can spy on `verify_turn` at call time.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from belay.authoring.protocol import (
    AUTHOR_FAILED,
    AUTHOR_OUTPUT_UNPARSEABLE,
    NO_AUTHOR_CONFIGURED,
    Candidate,
    SubprocessInvariantAuthor,
    build_author_input,
    parse_author_response,
)
from belay.verify.invariants import (
    AUTHORED_SCHEMA,
    Invariant,
    canonical_policy_digest,
)

#: The named failure causes this orchestration can produce. `AUTHOR_FAILED`,
#: `AUTHOR_OUTPUT_UNPARSEABLE`, `UNKNOWN_RULE` and `NO_AUTHOR_CONFIGURED` are the
#: protocol's own; the rest are infer's. Never verdicts — the verdict path has its own
#: closed vocabulary.
TASK_UNREADABLE = "TASK_UNREADABLE"
CONTROL_UNREADABLE = "CONTROL_UNREADABLE"
MANIFESTS_UNRESOLVABLE = "MANIFESTS_UNRESOLVABLE"
NO_SURVIVING_CANDIDATES = "NO_SURVIVING_CANDIDATES"
CALIBRATION_FAILED = "CALIBRATION_FAILED"
CONTROL_UNREPLAYABLE = "CONTROL_UNREPLAYABLE"
ARTIFACT_WRITE_FAILED = "ARTIFACT_WRITE_FAILED"

#: The VCS metadata directory, excluded from the repo inventory: its contents are never
#: source, and including them would crowd the bounded inventory with objects.
_REPO_EXCLUDED_DIRS = frozenset({".git"})


@dataclass(frozen=True)
class InferResult:
    """One infer run's structured outcome — every surface renders from this.

    `ok` is the verdict on the run as a whole; `cause` is the named failure when not ok
    (`None` on success). `candidates` are the SURVIVORS (validated AND calibrated — the
    exact policy the artifact carries), `rejections` the parse-level drops (unknown or
    malformed), and `calibration_rejects` the candidates calibration refused, each with
    its cause. `turns`/`decided_turns` describe the control (the calibration's evidence
    base), `model` is the author-reported model id (or `None`), and `artifact`/
    `artifact_path` are the emitted payload and its location (both `None` on failure).
    """

    ok: bool
    cause: Optional[str] = None
    artifact_path: Optional[str] = None
    artifact: Optional[dict] = None
    candidates: tuple[dict, ...] = ()
    rejections: tuple[dict, ...] = ()
    calibration_rejects: tuple[dict, ...] = ()
    turns: int = 0
    decided_turns: int = 0
    model: Optional[str] = None


def run_infer(
    *,
    task_path: Path | str,
    control_path: Path | str,
    author_command: Sequence[str],
    out_path: Path | str,
    manifest_dir: Path | str | None,
    server_command: Sequence[str],
    timeout: float,
    replays: int,
    repo_dir: Path | str | None = None,
    runner=None,
) -> InferResult:
    """Run the full infer pipeline; return a named outcome, never raise.

    Order of operations, each fail-closed before the next (a model call is never spent
    on a broken task/control, and calibration never runs on a proposal that cannot be
    trusted):

    1. `NO_AUTHOR_CONFIGURED` — an empty author argv.
    2. `TASK_UNREADABLE` — the task spec cannot be read as UTF-8 text.
    3. `CONTROL_UNREADABLE` — the control trace cannot be read (missing or corrupt).
    4. `MANIFESTS_UNRESOLVABLE` — no manifest dir was resolved, or it is not a
       directory (calibration needs the recorded snapshot manifests).
    5. Build the author input (D-7) and run the author; `AUTHOR_FAILED` /
       `AUTHOR_OUTPUT_UNPARSEABLE` (the protocol's own causes).
    6. Validate the proposal: unknown rules dropped with `UNKNOWN_RULE`; zero
       survivors -> `NO_SURVIVING_CANDIDATES`.
    7. Calibrate (D-5/D-6): one `verify_turn` per control turn with the candidates
       only; `CONTROL_UNREPLAYABLE` when no turn reaches a decided A2 result
       sub-verdict; candidates with any A1 FAIL rejected; zero survivors ->
       `CALIBRATION_FAILED`.
    8. Emit the artifact atomically; a write failure is `ARTIFACT_WRITE_FAILED`.
    """
    out = Path(out_path)

    if not author_command:
        return _failure(NO_AUTHOR_CONFIGURED, "no author command configured")

    task_path_p = Path(task_path)
    try:
        task_bytes = task_path_p.read_bytes()
    except OSError as exc:
        return _failure(
            TASK_UNREADABLE, f"task spec could not be read: {task_path_p} ({exc})"
        )
    try:
        task_text = task_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _failure(
            TASK_UNREADABLE,
            f"task spec is not UTF-8 text: {task_path_p} ({exc})",
        )
    task_sha256 = hashlib.sha256(task_bytes).hexdigest()

    control_path_p = Path(control_path)
    try:
        from belay.replay.reader import TraceCorrupt, read_trace

        read = read_trace(control_path_p)
    except (OSError, TraceCorrupt) as exc:
        return _failure(
            CONTROL_UNREADABLE, f"control trace could not be read: {control_path_p} ({exc})"
        )
    records = list(read.records)
    control_sha256 = hashlib.sha256(control_path_p.read_bytes()).hexdigest()

    if manifest_dir is None or not Path(manifest_dir).is_dir():
        return _failure(
            MANIFESTS_UNRESOLVABLE,
            "no manifest directory: pass --manifest-dir, or place the control's "
            "<stem>.manifests sibling next to the trace",
        )

    author = SubprocessInvariantAuthor(tuple(author_command), runner=runner)
    payload = build_author_input(
        task_text=task_text,
        repo_files=_repo_files(Path(repo_dir)) if repo_dir is not None else None,
    )
    stdout = author.author(payload)
    if stdout is None:
        return _failure(
            AUTHOR_FAILED,
            f"the author command {author_command!r} failed (non-zero exit, timeout, "
            "launch failure, or output past the cap)",
        )
    response = parse_author_response(stdout)
    if response.failure is not None:
        return _failure(response.failure, _describe_failure(response.failure))

    rejections = tuple(
        {
            "scope": r.scope,
            "rule": r.rule,
            "rationale": r.rationale,
            "cause": r.cause,
        }
        for r in response.rejections
    )
    if not response.candidates:
        return _failure(
            NO_SURVIVING_CANDIDATES,
            "the author proposed no surviving candidate(s)",
            rejections=rejections,
        )

    candidate_invariants = [
        Invariant(scope=os.fsencode(c.scope), rule=c.rule) for c in response.candidates
    ]
    calls, decided_turns, failed_keys = _calibrate(
        records,
        candidates=response.candidates,
        invariants=candidate_invariants,
        server_command=server_command,
        manifest_dir=Path(manifest_dir),
        timeout=timeout,
        replays=replays,
    )
    if decided_turns == 0:
        return _failure(
            CONTROL_UNREPLAYABLE,
            f"no control turn reached a decided A2 result sub-verdict over "
            f"{len(calls)} tool call(s): the control never re-executed, so "
            "calibration would be vacuous",
            rejections=rejections,
            turns=len(calls),
            decided_turns=0,
        )

    survivors = [
        c for c in response.candidates if (c.rule, c.scope) not in failed_keys
    ]
    calibration_rejects = tuple(
        {
            "scope": c.scope,
            "rule": c.rule,
            "rationale": c.rationale,
            "cause": CALIBRATION_FAILED,
        }
        for c in response.candidates
        if (c.rule, c.scope) in failed_keys
    )
    if not survivors:
        return _failure(
            CALIBRATION_FAILED,
            f"every candidate FAILed a control turn (rejected over {decided_turns} "
            "decided turn(s))",
            rejections=rejections,
            calibration_rejects=calibration_rejects,
            turns=len(calls),
            decided_turns=decided_turns,
        )

    survivors = sorted(survivors, key=lambda c: (c.rule, c.scope))
    survivor_invariants = [
        Invariant(scope=os.fsencode(c.scope), rule=c.rule) for c in survivors
    ]
    digest = canonical_policy_digest(
        invariants=survivor_invariants,
        task_sha256=task_sha256,
        control_sha256=control_sha256,
    )
    invariant_records: list[dict] = [
        {"scope": c.scope, "rule": c.rule, "rationale": c.rationale}
        for c in survivors
    ]
    artifact: dict = {
        "schema": AUTHORED_SCHEMA,
        "author": {
            "program": author_command[0],
            "model": response.model,
        },
        "task": {"path": str(task_path_p), "sha256": task_sha256},
        "control": {
            "trace": str(control_path_p),
            "sha256": control_sha256,
            "turns": len(calls),
            "calibrated": True,
        },
        "calibration": {"digest": digest},
        "invariants": invariant_records,
    }

    try:
        _write_atomic(out, artifact)
    except OSError as exc:
        return _failure(
            ARTIFACT_WRITE_FAILED,
            f"artifact could not be written to {out}: {exc}",
            rejections=rejections,
            calibration_rejects=calibration_rejects,
            turns=len(calls),
            decided_turns=decided_turns,
        )

    return InferResult(
        ok=True,
        artifact_path=str(out),
        artifact=artifact,
        candidates=tuple(invariant_records),
        rejections=rejections,
        calibration_rejects=calibration_rejects,
        turns=len(calls),
        decided_turns=decided_turns,
        model=response.model,
    )


def _calibrate(
    records,
    *,
    candidates: Sequence[Candidate],
    invariants: Sequence[Invariant],
    server_command: Sequence[str],
    manifest_dir: Path,
    timeout: float,
    replays: int,
) -> tuple[list, int, set[tuple[str, str]]]:
    """D-5/D-6: one `verify_turn` pass over the control; return (calls, decided, failed).

    The composition is imported HERE, at call time, so a test can monkeypatch
    `belay.verify.turn.verify_turn` and observe the exact calls — the structural pin
    that calibration uses the shipped evaluator and no second one.

    A decided A2 result sub-verdict is axis `A2`, kind EXACTLY `replay` (the narrow
    `replay:<reason>` abstentions do not count — `result.py` gives them their own kind
    so a boundary that never ran the tool cannot read as re-execution), status PASS or
    FAIL. A candidate is failed when any control turn's A1 `invariant` sub-verdict is
    FAIL; attribution is the sub-verdict's own `expected["rule"]`/`expected["scope"]` —
    the same fields `belay verify` renders, so the operator's fix is the same either
    way. PASS and UNVERIFIED A1s keep the candidate.
    """
    from belay.index import derive_correlation, tool_calls
    from belay.verify.turn import verify_turn
    from belay.verify.verdict import Status

    calls = tool_calls(derive_correlation(list(records)))
    decided_turns = 0
    failed: set[tuple[str, str]] = set()
    for n in range(len(calls)):
        verdict = verify_turn(
            records, n,
            server_command=server_command,
            manifest_dir=manifest_dir,
            replays=replays,
            timeout=timeout,
            invariants=invariants,
        )
        decided = False
        for sub in verdict.sub_verdicts:
            if sub.axis == "A2" and sub.kind == "replay" and sub.status in (
                Status.PASS,
                Status.FAIL,
            ):
                decided = True
            if sub.axis == "A1" and sub.kind == "invariant" and sub.status is Status.FAIL:
                expected = sub.expected if isinstance(sub.expected, dict) else {}
                rule = expected.get("rule")
                scope = expected.get("scope")
                if isinstance(rule, str) and isinstance(scope, str):
                    failed.add((rule, scope))
        if decided:
            decided_turns += 1
    return calls, decided_turns, failed


def _repo_files(root: Path) -> list[str]:
    """The bounded, sorted repo inventory: relative paths, `.git` excluded.

    Sorted first, then capped by the protocol's own `REPO_FILE_CAP` inside
    `build_author_input` — deterministic for a fixed tree, and a huge repo never blows
    the author prompt.
    """
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _REPO_EXCLUDED_DIRS)
        for name in sorted(filenames):
            files.append(
                os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            )
    return sorted(files)


def _write_atomic(path: Path, artifact: dict) -> None:
    """Emit the artifact atomically: temp file in the SAME directory, then `os.replace`.

    A reader can only ever see the complete artifact or none at all — never a partial
    file, and never a file whose name says "policy" while its bytes say otherwise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".belay-infer-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _describe_failure(cause: str) -> str:
    if cause == AUTHOR_FAILED:
        return "the author command failed (non-zero exit, timeout, or launch failure)"
    if cause == AUTHOR_OUTPUT_UNPARSEABLE:
        return "the author's stdout is not a parseable proposal (malformed JSON, a "
        "non-object, or a missing/non-list candidates key)"
    return f"the author proposal was rejected: {cause}"


def _failure(
    cause: str,
    detail: str,
    *,
    rejections: tuple[dict, ...] = (),
    calibration_rejects: tuple[dict, ...] = (),
    turns: int = 0,
    decided_turns: int = 0,
) -> InferResult:
    return InferResult(
        ok=False,
        cause=cause,
        rejections=rejections,
        calibration_rejects=calibration_rejects,
        turns=turns,
        decided_turns=decided_turns,
    )


__all__ = [
    "TASK_UNREADABLE",
    "CONTROL_UNREADABLE",
    "MANIFESTS_UNRESOLVABLE",
    "NO_SURVIVING_CANDIDATES",
    "CALIBRATION_FAILED",
    "CONTROL_UNREPLAYABLE",
    "ARTIFACT_WRITE_FAILED",
    "InferResult",
    "run_infer",
]