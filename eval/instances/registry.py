"""One mint instance as data, plus a fail-closed loader and a stable-diffing dumper.

The live Phase-0 mint is reproducible from the repo only if the instance set is committed
data: `instance_id -> (repo, base_commit, problem_statement, task_string)`, with controls
marked as such. `InstanceRecord` is that datum; `load_registry`/`dump_registry` are its
I/O.

Everything downstream — the task the agent is given, the commit the repo is checked out
at, the denominator of the published violation rate — is read out of these records, so a
field that loaded as `None` or `""` would not fail loudly here, it would mint the wrong
run and look fine. The loader is therefore fail-closed in the style of
`belay.phase0.ledger.from_json` and `belay.corpus.case.load_case`: a missing *or blank*
required field raises a `ValueError` naming both the field and the offending instance,
and a duplicate `instance_id` raises too (it would otherwise be run twice and counted
twice, distorting the very fraction the mint exists to publish). The single allowed
default is `is_control`, absent -> `False`, mirroring `load_case`'s `human_label`.

Controls are separated by the `is_control` field via `controls()`/`real()` — never by a
naming convention on `instance_id`, which is a string anyone can typo.

Pure and deterministic apart from the two explicit file reads/writes: no clock, no
network, no randomness. `dump_registry` emits a stable key order and a trailing newline
so a regenerated registry produces a reviewable diff rather than a reshuffled one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

#: Fields that MUST be present and non-blank in every registry entry. `is_control` is
#: deliberately absent: it has a declared default, and absent-means-False is an
#: intentional default rather than a silently-swallowed omission.
_REQUIRED_FIELDS = (
    "instance_id",
    "repo",
    "base_commit",
    "problem_statement",
    "task_string",
)

#: The serialization key order. Fixed, so a regenerated file diffs line-for-line.
_KEY_ORDER = _REQUIRED_FIELDS + ("is_control",)


@dataclass(frozen=True)
class InstanceRecord:
    """One SWE-bench-lite instance the mint will drive, as committed data.

    `problem_statement` is the benchmark's issue text (possibly truncated at fetch time);
    `task_string` is the mechanically derived instruction actually handed to the agent.
    Both are stored so the derivation is auditable from the committed file alone.
    `is_control` marks a control instance — a hand-written, trivially-correct task whose
    expected outcome is known — so the harness and the audit can tell one from a real
    instance by a field rather than by its name.
    """

    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    task_string: str
    is_control: bool = False


def controls(records: Iterable[InstanceRecord]) -> tuple[InstanceRecord, ...]:
    """The control instances in `records`, in order. Complement of `real`."""
    return tuple(record for record in records if record.is_control)


def real(records: Iterable[InstanceRecord]) -> tuple[InstanceRecord, ...]:
    """The non-control instances in `records`, in order. Complement of `controls`."""
    return tuple(record for record in records if not record.is_control)


def _record_to_json(record: InstanceRecord) -> dict:
    """One `InstanceRecord` as a plain JSON-able dict, in the fixed `_KEY_ORDER`."""
    return {
        "instance_id": record.instance_id,
        "repo": record.repo,
        "base_commit": record.base_commit,
        "problem_statement": record.problem_statement,
        "task_string": record.task_string,
        "is_control": record.is_control,
    }


def _record_from_json(raw: object, *, path: Path, index: int) -> InstanceRecord:
    """Rebuild one `InstanceRecord` from JSON, or raise a named `ValueError`."""
    if not isinstance(raw, dict):
        raise ValueError(
            f"registry file {str(path)!r} entry {index} must be a JSON object, "
            f"got {type(raw).__name__}"
        )

    # How to name the offending entry in an error. Prefer its `instance_id`; when that is
    # the field at fault (absent or blank) there is no id to name, so the position is the
    # only honest identifier.
    raw_id = raw.get("instance_id")
    ident = raw_id if isinstance(raw_id, str) and raw_id.strip() else f"entry {index}"

    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise ValueError(
                f"registry file {str(path)!r}: instance {ident!r} is missing required "
                f"field {field!r}"
            )
        value = raw[field]
        if not isinstance(value, str):
            raise ValueError(
                f"registry file {str(path)!r}: instance {ident!r} field {field!r} must "
                f"be a string, got {type(value).__name__}"
            )
        if not value.strip():
            raise ValueError(
                f"registry file {str(path)!r}: instance {ident!r} field {field!r} is "
                f"blank; required fields are never defaulted"
            )

    is_control = raw.get("is_control", False)
    if not isinstance(is_control, bool):
        raise ValueError(
            f"registry file {str(path)!r}: instance {ident!r} field 'is_control' must be "
            f"a boolean, got {type(is_control).__name__}"
        )

    return InstanceRecord(
        instance_id=raw["instance_id"],
        repo=raw["repo"],
        base_commit=raw["base_commit"],
        problem_statement=raw["problem_statement"],
        task_string=raw["task_string"],
        is_control=is_control,
    )


def load_registry(path: Path) -> tuple[InstanceRecord, ...]:
    """Load `path` into records, FAIL-CLOSED: never silently defaults a required field.

    Raises a named `ValueError` for an unreadable file, invalid JSON, a payload that is
    not an object, a missing/non-list `instances` key, any entry with a missing, blank,
    or wrongly-typed field, or a duplicated `instance_id`. Keys other than `instances` at
    the top level are ignored, so a later phase can add a provenance header (seed,
    target) without changing this format. Round-trips: `load_registry(dump_registry(...))`
    returns the records that were dumped.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read registry file {str(path)!r}: {exc}") from exc

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"registry file {str(path)!r} is not valid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(
            f"registry file {str(path)!r} must contain a JSON object, "
            f"got {type(raw).__name__}"
        )

    if "instances" not in raw:
        raise ValueError(
            f"registry file {str(path)!r} is missing required field 'instances'"
        )

    entries = raw["instances"]
    if not isinstance(entries, list):
        raise ValueError(
            f"registry file {str(path)!r} field 'instances' must be a list, "
            f"got {type(entries).__name__}"
        )

    records = tuple(
        _record_from_json(entry, path=path, index=index)
        for index, entry in enumerate(entries)
    )

    seen: set[str] = set()
    for record in records:
        if record.instance_id in seen:
            raise ValueError(
                f"registry file {str(path)!r} has a duplicate instance_id "
                f"{record.instance_id!r}; each instance must appear exactly once"
            )
        seen.add(record.instance_id)

    return records


def dump_registry(records: Iterable[InstanceRecord], path: Path) -> None:
    """Write `records` to `path` with a stable key order and a trailing newline.

    Stable so a regenerated registry produces a reviewable diff. Record order is
    preserved exactly as given — the draw upstream decides it, not this writer.
    """
    payload = {"instances": [_record_to_json(record) for record in records]}
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


__all__ = [
    "InstanceRecord",
    "controls",
    "real",
    "load_registry",
    "dump_registry",
]
