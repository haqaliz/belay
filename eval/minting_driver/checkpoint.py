"""The mint resume ledger: per-instance disposition, so a crash never restarts from zero.

A Phase-0 mint drives dozens of instances sequentially, each an expensive live model
session. If the run dies at instance 37, re-running must skip the 36 already dealt with,
not re-spend on them. This module is that memory: a small JSON ledger mapping each
`instance_id` to its `{status, reason, trace_path}`, where `status` is `"captured"` (a
trace was produced and bridged) or `"failed"` (the instance errored — recorded, not
silently retried; re-running failures is an explicit choice, not automatic).

Loading is FAIL-CLOSED, mirroring `belay.phase0.ledger.from_json`: a corrupt ledger must
never read as "nothing done yet", or the mint would silently re-run and double-spend, or
worse, over-count the denominator. `load_checkpoint` raises a named `ValueError` for
unreadable content, invalid JSON, a non-object payload, a non-object entry, a missing
`status`, or an unknown `status`. The one deliberately-tolerated case is a NON-EXISTENT
path: that is the legitimate first run, and it loads as an EMPTY checkpoint. A
present-but-corrupt file is a different thing entirely and always raises.

Saving is ATOMIC: the ledger is written to a temp file in the same directory and then
`os.replace`d over the destination, so a crash (or a serialization error) mid-save can
never leave a half-written, unreadable ledger where a valid one stood — the durable file
is only ever swapped in whole, or not at all.

Stdlib only (`json`, `os`, `tempfile`, `pathlib`); no clock, no network, no randomness.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

StrPath = Union[str, "os.PathLike[str]"]

#: The only statuses a recorded instance may carry. Both count as "done" for the pass:
#: a `"captured"` instance produced a trace; a `"failed"` one errored and is recorded so
#: it is not retried forever. Re-running failures is a deliberate, separate decision.
_VALID_STATUSES = frozenset({"captured", "failed"})


class Checkpoint:
    """A mutable per-instance disposition ledger with a fail-closed load and atomic save.

    Internally a `dict[str, dict]`: `instance_id -> {"status", "reason", "trace_path"}`.
    Construct via `load_checkpoint` (never call this directly with raw untrusted data —
    the classmethod `_from_entries` is validated and used by the loader).
    """

    def __init__(self, entries: Optional[dict[str, dict]] = None) -> None:
        # `entries` is trusted here: `load_checkpoint` validates before constructing, and
        # `record` only ever inserts well-formed entries. Copy so no external alias mutates
        # our state behind our back.
        self._entries: dict[str, dict] = {} if entries is None else dict(entries)

    def record(
        self,
        instance_id: str,
        status: str,
        *,
        reason: Optional[str] = None,
        trace_path: Optional[object] = None,
    ) -> None:
        """Record one instance's disposition, overwriting any prior entry for that id.

        `status` must be `"captured"` or `"failed"` — an unknown status is a caller bug and
        raises immediately, so a typo can never enter the ledger and later fail the load.
        `reason` and `trace_path` are optional context (a failure message, the bridged trace
        path); they are stored verbatim and only validated for JSON-serializability at
        `save` time, keeping the atomic-write guarantee as the single point that rejects a
        value the ledger cannot durably hold.
        """
        if status not in _VALID_STATUSES:
            allowed = ", ".join(sorted(_VALID_STATUSES))
            raise ValueError(f"status must be one of: {allowed}; got {status!r}")
        self._entries[instance_id] = {
            "status": status,
            "reason": reason,
            "trace_path": trace_path,
        }

    def is_done(self, instance_id: str) -> bool:
        """True if this instance has any recorded disposition — `captured` OR `failed`.

        A failed instance is done for this pass: the mint moves on. Re-running failures is
        an explicit choice a later pass makes, not something `is_done` silently invites.
        """
        return instance_id in self._entries

    def status(self, instance_id: str) -> Optional[str]:
        """The recorded status for `instance_id`, or `None` if it was never recorded."""
        entry = self._entries.get(instance_id)
        return None if entry is None else entry["status"]

    def reason(self, instance_id: str) -> Optional[str]:
        """The recorded `reason` for `instance_id`, or `None` if unrecorded or unset."""
        entry = self._entries.get(instance_id)
        return None if entry is None else entry.get("reason")

    def trace_path(self, instance_id: str) -> Optional[object]:
        """The recorded `trace_path` for `instance_id`, or `None` if unrecorded or unset."""
        entry = self._entries.get(instance_id)
        return None if entry is None else entry.get("trace_path")

    def save(self, path: StrPath) -> None:
        """Write the ledger to `path` ATOMICALLY: temp file in the same dir, then replace.

        Serialization happens into a NamedTemporaryFile in `path`'s directory; only once
        the bytes are fully written and flushed does `os.replace` swap the temp file over
        `path` (an atomic rename on the same filesystem). If serialization raises — e.g. a
        `trace_path` that is not JSON-serializable — the temp file is removed and the
        exception propagates, leaving any pre-existing `path` byte-for-byte unchanged. A
        crash can only ever leave the old whole ledger or the new whole ledger, never a
        torn one.
        """
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(dest.parent),
            prefix=f".{dest.name}.",
            suffix=".tmp",
            delete=False,
        )
        tmp_path = tmp.name
        try:
            with tmp:
                json.dump(self._entries, tmp, indent=2, sort_keys=True)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, dest)
        except BaseException:
            # Serialization (or the replace) failed: strip the partial temp file so no
            # stray artifact is left beside the intact original, then re-raise.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise


def _validate_entry(instance_id: object, raw: object) -> dict:
    """Validate one loaded ledger entry, or raise a named `ValueError`.

    Mirrors `phase0.ledger._instance_from_json`: a non-object entry, a missing `status`,
    or an unknown `status` each raise with a message naming the offending instance — a
    ledger that loaded wrong would misreport which instances still need running.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"checkpoint entry for {instance_id!r} must be a JSON object, "
            f"got {type(raw).__name__}"
        )
    if "status" not in raw:
        raise ValueError(
            f"checkpoint entry for {instance_id!r} is missing required field 'status'"
        )
    status = raw["status"]
    if status not in _VALID_STATUSES:
        allowed = ", ".join(sorted(_VALID_STATUSES))
        raise ValueError(
            f"checkpoint entry for {instance_id!r} has status {status!r}; "
            f"must be one of: {allowed}"
        )
    return {
        "status": status,
        "reason": raw.get("reason"),
        "trace_path": raw.get("trace_path"),
    }


def load_checkpoint(path: StrPath) -> Checkpoint:
    """Load the checkpoint at `path`, FAIL-CLOSED — or raise a named `ValueError`.

    A NON-EXISTENT `path` is the first-run case and loads as an EMPTY `Checkpoint`. Every
    other failure mode is fatal and distinguishable from that: an unreadable file, invalid
    JSON, a non-object top-level payload, a non-object entry, a missing `status`, or an
    unknown `status` each raise a named `ValueError`, because a corrupt ledger read as
    "empty" would silently re-run already-captured instances and double-spend.
    """
    src = Path(path)
    if not src.exists():
        return Checkpoint()

    try:
        text = src.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"checkpoint at {src} could not be read: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"checkpoint at {src} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"checkpoint at {src} must be a JSON object, got {type(data).__name__}"
        )

    entries = {
        instance_id: _validate_entry(instance_id, raw) for instance_id, raw in data.items()
    }
    return Checkpoint(entries)


__all__ = ["Checkpoint", "load_checkpoint"]
