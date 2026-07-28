"""Human adjudication of a corpus case: set the ground-truth label, nothing else.

`corpus add` stores a case with `human_label = pending`; a human then ADJUDICATES it into a
real label so `corpus score` can measure the engine's stored verdicts against human ground
truth. This module is that adjudication step, and it enforces the one boundary the whole
metric rests on (the same D3 separation the engine keeps from the other side): a human
adjudication touches ONLY `human_label` and NEVER rewrites `expected`, the verdict the engine
computed. If labeling could edit the verdict, scoring the engine against the labels would be
scoring it against itself.

Pure filesystem: `load_case` -> `dataclasses.replace` -> `write_case`. No replay, no clock, no
model. `Case` is frozen, so `replace` is the only way to change a field, and it necessarily
leaves every other field — `expected` above all — untouched.

Zero runtime dependencies (stdlib only), matching the rest of `src/belay`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from belay.corpus.case import _validate_root_cause, load_case, write_case

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

    relabeled = dataclasses.replace(case, human_label=label, root_cause=effective_cause)
    write_case(case_dir, relabeled)
    return case_dir
