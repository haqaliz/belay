"""Human adjudication of a corpus case: set the ground-truth label, nothing else.

`corpus add` stores a case with `human_label = pending`; a human then ADJUDICATES it into a
real label so `corpus score` can measure the engine's stored verdicts against human ground
truth. This module is that adjudication step, and it enforces the one boundary the whole
metric rests on (the same D3 separation the engine keeps from the other side): a human
adjudication touches ONLY `human_label` (and its supporting `root_cause`/`recorded_miss`
fields) and NEVER rewrites `expected`, the verdict the engine computed. If labeling could
edit the verdict, scoring the engine against the labels would be scoring it against itself.

A human may ALSO declare, in the same act, that the case's stored verdict is a MISS the
engine produced — `recorded_miss`, schema v3. This is the only supported way to turn a
stored PASS/WARN case into a scored false negative (`corpus score`'s FN branch already reads
`human_label == "true-positive"` and a non-FAIL `expected`; nothing there changes), so the
declaration belongs beside the label rather than in a separate command.

Pure filesystem: `load_case` -> `dataclasses.replace` -> `write_case`. No replay, no clock, no
model. `Case` is frozen, so `replace` is the only way to change a field, and it necessarily
leaves every other field — `expected` above all — untouched.

Zero runtime dependencies (stdlib only), matching the rest of `src/belay`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from belay.corpus.case import (
    CASE_SCHEMA_VERSION,
    _validate_recorded_miss,
    _validate_root_cause,
    load_case,
    write_case,
)

#: The three REAL adjudications a human may assign. `pending` — the un-adjudicated default the
#: engine writes — is deliberately absent: `label` means "adjudicate", so resetting to pending
#: is not one of its verbs, and an unknown string is rejected here rather than silently written
#: and only caught on the next `load_case`. Fail-closed, mirroring `case._KNOWN_LABELS`.
ADJUDICATIONS = frozenset({"true-positive", "false-positive", "unverifiable"})

__all__ = ["set_label", "ADJUDICATIONS"]


def set_label(
    corpus_dir: Path,
    case_id: str,
    label: str,
    root_cause: dict | None = None,
    recorded_miss: dict | None = None,
) -> Path:
    """Adjudicate `<corpus_dir>/<case_id>` to `label`, rewriting only the human's fields.

    Rejects any `label` outside `ADJUDICATIONS` with a named `ValueError` before touching
    disk, so a bad label is never written. Re-labeling is allowed — a human correcting an
    earlier call. Loads fail-closed (a missing or corrupt case raises), replaces just the
    human-authored fields on the frozen `Case`, and writes it back. Returns the case
    directory.

    A `true-positive` REQUIRES a `root_cause`. The pre-registered gate criteria demand a
    root cause beside every TP so a reader can judge independence directly, so a TP without
    one is a finding the gate cannot evaluate — refused here rather than scored later. The
    other two adjudications may omit it.

    `root_cause` is validated to the same shape `load_case` enforces, BEFORE any write: a
    malformed cause caught only on the next load would leave a corrupt case on disk.
    Passing `root_cause=None` to a re-label PRESERVES any cause already recorded — a
    correction of the label is not a retraction of the reasoning.

    `recorded_miss` declares that the case's STORED verdict (`expected`, untouched by this
    call) is a miss the engine produced, not a catch — shape `{"note": <non-empty str>}`.
    Validated against `case.py`'s own rule (`_validate_recorded_miss`), which also refuses
    the declaration outright when the stored verdict is already `FAIL` (a miss that was
    caught is a contradiction) — checked here, BEFORE any write, the same as `root_cause`.
    This function never derives the declaration's content from anything it loaded or
    computed: it only ever stores the caller's argument, or — when the caller passes
    `None` on a re-label — preserves whatever was already on the case. There is no path
    from `case.expected`, a verdict, or `label` to the VALUE written here; `case.expected`
    is consulted only to VALIDATE the human's own claim, never to construct one.

    Introducing a declaration onto a case that had none also BUMPS `schema_version` to
    `CASE_SCHEMA_VERSION`, because a v3 field on a case still claiming v2 is read by pre-v3
    code as an ordinary case. A relabel that writes no declaration leaves the version
    exactly as loaded.
    """
    if label not in ADJUDICATIONS:
        known = ", ".join(sorted(ADJUDICATIONS))
        raise ValueError(
            f"cannot set label {label!r}; a human adjudication must be one of: {known} "
            f"('pending' is the un-adjudicated default, not a label you set)"
        )

    if root_cause is not None:
        # Same validator the loader uses, so a cause is rejected at adjudication time
        # rather than becoming an unloadable case.
        _validate_root_cause(root_cause, Path(corpus_dir) / case_id / "case.json")

    case_dir = Path(corpus_dir) / case_id
    case = load_case(case_dir)  # fail-closed: a missing/corrupt case is a ValueError

    effective_cause = root_cause if root_cause is not None else case.root_cause
    if label == "true-positive" and effective_cause is None:
        raise ValueError(
            f"cannot label {case_id!r} 'true-positive' without a root cause; the "
            f"pre-registered gate criteria require a root cause beside every true "
            f"positive so that independent findings can be counted"
        )

    effective_miss = recorded_miss if recorded_miss is not None else case.recorded_miss
    if effective_miss is not None:
        # Same validator the loader uses, including the FAIL-contradiction check (on the
        # per-turn reduced status AND the instance-level claim status), so a bad
        # declaration is rejected here rather than becoming an unloadable case.
        _validate_recorded_miss(
            effective_miss,
            case_dir / "case.json",
            case.expected["reduced_status"],
            claim_status=case.claim["status"] if case.claim else None,
        )

    # A NEWLY introduced declaration carries the version bump with it. `replace` preserves
    # the version loaded from disk, and every human-labeled case in existence today is v2 —
    # so without this the realistic first declaration writes `{"schema_version": 2,
    # "recorded_miss": {...}}`, which pre-v3 code reads as an ordinary case and classifies
    # `MATCH`: the regression suite certifying a blind spot as agreement, exactly the silent
    # misclassification the bump exists to make visible (`case.py:74-81`).
    #
    # Conditioned on the declaration being NEW, never applied to every write: an ordinary
    # relabel writes no v3 field, so restamping its version would assert a format the case
    # does not carry — the same "a default is never a declaration" rule the loader keeps.
    # `max` rather than assignment, so this only ever moves the version FORWARD.
    declaring = recorded_miss is not None and case.recorded_miss is None
    schema_version = (
        max(case.schema_version, CASE_SCHEMA_VERSION) if declaring else case.schema_version
    )

    relabeled = dataclasses.replace(
        case,
        human_label=label,
        root_cause=effective_cause,
        recorded_miss=effective_miss,
        schema_version=schema_version,
    )
    write_case(case_dir, relabeled)
    return case_dir
