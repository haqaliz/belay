"""The previously-minted set, derived deterministically from committed artifacts.

Every instance that has ever been driven live must be excluded from the gate mint's
fresh draws: re-running a banked instance silently inflates the denominator with
evidence the published number has already counted (or failed on). The observed set is
not written down by hand — it is derived from the committed artifacts that record the
captures:

* the **real** (non-control) ids of the committed stage registries
  (`eval/instances/stage2.json`, `stage4.json`, `stage4a.json`). These also cover the
  s4a/s4b/s5a/s5b mint-ledger captures, whose real ids are exactly the stage4.json real
  ids;
* `EXCLUDED_INSTANCE_IDS` from `eval/scripts/build_stage4_registry.py` — the banked
  s2/s3 corpus ids, transcribed from the committed miss-measurement ledgers
  (`docs/planning/under-firing-measurable/miss-measurement/ledgers/miss-{s2,s3}.json`);
* `SMOKE_INSTANCE_ID` — the 2026-08-05 live smoke capture (`subscription-model-client`);
* the **s3-partial** observed ids, mechanically derived from the committed s3 ledger
  (`S3_PARTIAL_LEDGER_PATH`): `trace_id` values of the form `trace-<instance_id>`,
  with controls filtered out by their `control__` prefix. The ledger is committed
  today, so the derivation is total; if it is ever absent the script derives what it
  can and records the gap in `S3_PARTIAL_NOTE` — a missing ledger is never a silently
  smaller set.

The result is returned sorted, so two runs compare byte-for-byte regardless of the
order the sources were read in. Controls can never appear: every source is filtered to
real ids, and that is asserted by `tests/test_observed_ids.py` (AC-1).
"""

from __future__ import annotations

from pathlib import Path

from eval.instances.registry import load_registry, real
from eval.scripts.build_stage4_registry import EXCLUDED_INSTANCE_IDS

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: The committed stage registries whose real ids are previously-minted. Repo-relative,
#: so the derivation reproduces on another machine.
STAGE_REGISTRY_SOURCES: tuple[str, ...] = (
    "eval/instances/stage2.json",
    "eval/instances/stage4.json",
    "eval/instances/stage4a.json",
)

#: The 2026-08-05 live smoke capture — the first real instance ever driven live
#: end-to-end (the stage registries do not record it; the smoke ran outside a stage).
SMOKE_INSTANCE_ID = "pytest-dev__pytest-7432"

#: The committed s3-partial ledger, repo-relative. Its `trace_id` values are
#: `trace-<instance_id>` for real instances and `trace-control__*` for controls; only
#: the former are observed ids.
S3_PARTIAL_LEDGER_PATH = (
    "docs/planning/under-firing-measurable/miss-measurement/ledgers/miss-s3.json"
)

#: Recorded when the s3 ledger is missing or unreadable: the derivation proceeds with
#: the remaining sources and the gap is named here, never silently absorbed.
S3_PARTIAL_NOTE = ""

#: The committed artifact the derived set is written to (AC-1: regeneration is
#: byte-identical). `derive_observed_ids()` is its generator; the committed file is the
#: script output, sorted.
OBSERVED_OUTPUT_PATH = "eval/instances/observed.json"


def derive_observed_ids() -> tuple[str, ...]:
    """The previously-minted instance ids, sorted, from the committed sources above."""
    raise NotImplementedError(
        "derive_observed_ids() is not implemented yet: union the real ids of "
        "STAGE_REGISTRY_SOURCES (via load_registry + real()), EXCLUDED_INSTANCE_IDS, "
        "SMOKE_INSTANCE_ID and the s3-partial ledger's non-control trace ids, then "
        "return tuple(sorted(...))"
    )


__all__ = [
    "OBSERVED_OUTPUT_PATH",
    "S3_PARTIAL_LEDGER_PATH",
    "S3_PARTIAL_NOTE",
    "SMOKE_INSTANCE_ID",
    "STAGE_REGISTRY_SOURCES",
    "derive_observed_ids",
]
