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

from belay.corpus.case import load_case, write_case

#: The three REAL adjudications a human may assign. `pending` — the un-adjudicated default the
#: engine writes — is deliberately absent: `label` means "adjudicate", so resetting to pending
#: is not one of its verbs, and an unknown string is rejected here rather than silently written
#: and only caught on the next `load_case`. Fail-closed, mirroring `case._KNOWN_LABELS`.
ADJUDICATIONS = frozenset({"true-positive", "false-positive", "unverifiable"})

__all__ = ["set_label", "ADJUDICATIONS"]


def set_label(corpus_dir: Path, case_id: str, label: str) -> Path:
    """Adjudicate `<corpus_dir>/<case_id>` to `label`, rewriting only `human_label`.

    Rejects any `label` outside `ADJUDICATIONS` with a named `ValueError` before touching
    disk, so a bad label is never written. Re-labeling is allowed — a human correcting an
    earlier call. Loads fail-closed (a missing or corrupt case raises), replaces just the one
    field on the frozen `Case`, and writes it back. Returns the case directory.
    """
    if label not in ADJUDICATIONS:
        known = ", ".join(sorted(ADJUDICATIONS))
        raise ValueError(
            f"cannot set label {label!r}; a human adjudication must be one of: {known} "
            f"('pending' is the un-adjudicated default, not a label you set)"
        )

    case_dir = Path(corpus_dir) / case_id
    case = load_case(case_dir)  # fail-closed: a missing/corrupt case is a ValueError
    relabeled = dataclasses.replace(case, human_label=label)
    write_case(case_dir, relabeled)
    return case_dir
