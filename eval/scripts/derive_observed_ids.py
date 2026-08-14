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

`write_observed()` emits the derived set to `OBSERVED_OUTPUT_PATH` as a sorted JSON
list — the committed artifact regeneration is pinned byte-identical by
`tests/test_observed_ids.py`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

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

#: Recorded by `derive_observed_ids()` when the s3 ledger is missing or unreadable: the
#: derivation proceeds with the remaining sources and the gap is named here, never
#: silently absorbed. Reset to "" on every derivation that read the ledger.
S3_PARTIAL_NOTE = ""

#: The committed artifact the derived set is written to (AC-1: regeneration is
#: byte-identical). `derive_observed_ids()` is its generator; the committed file is the
#: script output, sorted.
OBSERVED_OUTPUT_PATH = "eval/instances/observed.json"


def _stage_registry_ids() -> set[str]:
    """The real ids of `STAGE_REGISTRY_SOURCES`, read through the shipped loader."""
    ids: set[str] = set()
    for relative in STAGE_REGISTRY_SOURCES:
        for record in real(load_registry(_REPO_ROOT / relative)):
            ids.add(record.instance_id)
    return ids


def _s3_ledger_ids() -> set[str]:
    """The real instance ids recorded by the committed s3-partial ledger.

    A ledger entry is a dict with a `trace_id` of the form `trace-<instance_id>`; the
    `<instance_id>` is an observed id unless it carries the `control__` prefix. A
    missing or unreadable ledger is recorded in `S3_PARTIAL_NOTE` and yields nothing —
    never a failure, never a silently smaller set.
    """
    global S3_PARTIAL_NOTE

    ledger_path = _REPO_ROOT / S3_PARTIAL_LEDGER_PATH
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        S3_PARTIAL_NOTE = (
            f"could not read the committed s3-partial ledger {str(ledger_path)!r}: "
            f"{exc}; the observed set is derived from the remaining sources only"
        )
        return set()

    ids: set[str] = set()
    entries = raw.get("instances") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        S3_PARTIAL_NOTE = (
            f"s3-partial ledger {str(ledger_path)!r} lacks an 'instances' list; the "
            "observed set is derived from the remaining sources only"
        )
        return set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        trace_id = entry.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id.startswith("trace-"):
            continue
        instance_id = trace_id[len("trace-"):]
        if instance_id.startswith("control__"):
            continue
        if not instance_id:
            continue
        ids.add(instance_id)
    return ids


def derive_observed_ids() -> tuple[str, ...]:
    """The previously-minted instance ids, sorted, from the committed sources above.

    Union of: the real ids of `STAGE_REGISTRY_SOURCES`, `EXCLUDED_INSTANCE_IDS`,
    `SMOKE_INSTANCE_ID`, and the s3-partial ledger's non-control trace ids. A pure
    function of committed files: two calls return identical bytes.
    """
    global S3_PARTIAL_NOTE
    S3_PARTIAL_NOTE = ""

    ids = _stage_registry_ids()
    ids.update(EXCLUDED_INSTANCE_IDS)
    ids.update(_s3_ledger_ids())
    ids.add(SMOKE_INSTANCE_ID)
    return tuple(sorted(ids))


def write_observed(path: Path | None = None) -> Path:
    """Write the derived set to `path` (default `OBSERVED_OUTPUT_PATH`) as sorted JSON.

    The file is a JSON list of instance ids — `json.dumps` with the same indent and
    encoding `dump_registry` uses, plus the trailing newline — so regenerating the
    committed artifact is byte-identical (AC-1).
    """
    output = Path(path) if path is not None else _REPO_ROOT / OBSERVED_OUTPUT_PATH
    text = json.dumps(list(derive_observed_ids()), indent=2, ensure_ascii=False) + "\n"
    output.write_text(text, encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the committed observed.json. No network, no clock; a re-run with an
    unchanged tree rewrites the identical bytes."""
    parser = argparse.ArgumentParser(
        description=(
            "Derive eval/instances/observed.json from the committed stage registries, "
            "EXCLUDED_INSTANCE_IDS, the s3-partial ledger and the smoke instance."
        )
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / OBSERVED_OUTPUT_PATH,
        help=f"output path (default: {OBSERVED_OUTPUT_PATH})",
    )
    args = parser.parse_args(argv)

    path = write_observed(args.out)
    derived = derive_observed_ids()
    note = f"; {S3_PARTIAL_NOTE}" if S3_PARTIAL_NOTE else ""
    print(f"wrote {path}: {len(derived)} observed instance ids{note}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = [
    "OBSERVED_OUTPUT_PATH",
    "S3_PARTIAL_LEDGER_PATH",
    "S3_PARTIAL_NOTE",
    "SMOKE_INSTANCE_ID",
    "STAGE_REGISTRY_SOURCES",
    "derive_observed_ids",
    "main",
    "write_observed",
]
