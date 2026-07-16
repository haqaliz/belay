"""Read a trace file back into records — the inverse of `belay.trace`'s writer.

`belay.trace` is writer-only; C3 owns reading it. The load-bearing rule this reader
enforces is the one C1 wrote into the format itself (see `trace.py:48-52` and
`docs/technical/TRACE_FORMAT.md`, "The unknown-kind rule"):

    A record whose `kind` is unknown, or whose `v` is higher than the reader
    understands, must be SKIPPED and the skip RECORDED. Never dropped silently,
    never fatal.

Two failures this rule forbids, and why each is the exact thing Belay exists to catch:

- **Silent drop.** A future capability (C4, C5, ...) appends a new record `kind`. A
  reader that quietly discards it returns a trace that *looks* complete but is not —
  the same false-completeness as a swallowed capture error. So every skip is an
  observable `Skip`, carrying the record's `seq`, what was unreadable (its `kind` or
  its `version`), and why.
- **Choke.** A reader that raises on an unknown kind cannot survive a newer writer,
  which defeats the whole point of a versioned append-only format. So an unknown
  kind or a newer version is a *skip*, never an exception.

A skip is therefore "I read a valid record and do not understand it". That is a
different fact from a **broken file** — a line that is not valid JSON, or valid JSON
that is not a record object at all. That is not a trace, and pretending it is a mere
skip would let a corrupted file read back as a merely-incomplete one. A broken line
raises `TraceCorrupt`.

The reader produces records and skips — facts, not judgements. It emits no verdict,
and it does not correlate: `belay.index.derive_correlation` already turns these exact
records into turns, so the reader hands them over unchanged rather than reimplementing
that pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from belay.trace import KINDS, SCHEMA_VERSION


class TraceCorrupt(ValueError):
    """A line in the trace is not a readable record — the file is broken, not merely new.

    Raised for a line that is not valid JSON, or that is valid JSON but not a record
    object. Deliberately distinct from a `Skip`: a skip is a valid record this reader
    does not understand (which the format promises to tolerate forever), whereas this
    is "the bytes on disk are not a trace", which nothing downstream can recover from.
    """


@dataclass(frozen=True)
class Skip:
    """One record the reader could not accept, recorded so the drop is never silent.

    `reason` says why in words; `seq` locates it in capture order when the record
    carried one; exactly one of `kind` / `version` names what was unreadable — the
    unknown kind, or the too-new schema version. Keeping the identifying fact on the
    `Skip` is what makes "the skip is recorded" mean a caller can *see* what was
    skipped, not merely count that something was.
    """

    reason: str
    seq: int | None = None
    kind: str | None = None
    version: object | None = None


@dataclass(frozen=True)
class ReadResult:
    """What one trace file read back to: the records understood, and the skips.

    `records` are the raw record dicts, byte-for-byte the writer's output, ready to
    hand to `derive_correlation` unchanged. `skips` is every record the reader could
    not accept — never an empty stand-in for "some were dropped".
    """

    records: list[dict] = field(default_factory=list)
    skips: list[Skip] = field(default_factory=list)


def read_trace(path: Path) -> ReadResult:
    """Read `path` into understood records and recorded skips.

    Each non-empty line is one JSON record. A record whose `v` this reader does not
    understand, or whose `kind` is not one of the current `KINDS`, is skipped and the
    skip recorded — never dropped, never raised. A line that is not a valid JSON
    record object raises `TraceCorrupt`: that is a broken file, not a skip.

    Version is checked before kind: a record can carry a `kind` this reader knows and
    still be unreadable because its schema version moved on (the `frame` a future
    writer emits may not be the `frame` this reader parses), so the version is the
    first thing that has to hold.
    """
    records: list[dict] = []
    skips: list[Skip] = []

    for lineno, line in enumerate(Path(path).read_bytes().split(b"\n"), start=1):
        if not line:
            continue

        try:
            record = json.loads(line)
        except ValueError as exc:
            raise TraceCorrupt(f"{path}:{lineno}: line is not valid JSON: {exc}") from exc
        if not isinstance(record, dict):
            raise TraceCorrupt(
                f"{path}:{lineno}: line is valid JSON but not a record object "
                f"(got {type(record).__name__})"
            )

        seq = record.get("seq")
        version = record.get("v")
        if version != SCHEMA_VERSION:
            skips.append(
                Skip(
                    reason=(
                        f"schema version {version!r} is not one this reader understands "
                        f"(v={SCHEMA_VERSION})"
                    ),
                    seq=seq,
                    kind=record.get("kind"),
                    version=version,
                )
            )
            continue

        kind = record.get("kind")
        if kind not in KINDS:
            skips.append(
                Skip(
                    reason=(
                        f"unknown kind {kind!r}: not one of the record kinds this reader "
                        f"understands ({', '.join(KINDS)})"
                    ),
                    seq=seq,
                    kind=kind,
                )
            )
            continue

        records.append(record)

    return ReadResult(records=records, skips=skips)


__all__ = ["ReadResult", "Skip", "TraceCorrupt", "read_trace"]
