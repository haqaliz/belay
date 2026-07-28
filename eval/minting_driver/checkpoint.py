"""The mint resume ledger: per-instance disposition, so a crash never restarts from zero.

A Phase-0 mint drives dozens of instances sequentially, each an expensive live model
session. If the run dies at instance 37, re-running must skip the 36 already dealt with,
not re-spend on them. This module is that memory: a small JSON ledger mapping each
`instance_id` to its `{status, reason, trace_path, accounting, history}`, where `status` is
`"captured"` (a trace was produced and bridged), `"failed"` (the instance errored —
recorded, not silently retried; re-running failures is an explicit choice, not automatic),
or `"no_observation"` (the instance was never actually driven — see below).

`"no_observation"` exists because "done" and "errored" are not the same thing. A provider
quota/period cap rejects the request outright: no session ran, no trace exists, nothing was
observed. Recording that as `"failed"` is what stranded 56 instances on 2026-07-24 — the
batch kept feeding the wall, every rejection landed as `"failed"`, and `is_done` then
treated all of them as dealt with, permanently. So `is_done` is TRUE for `"captured"` and
`"failed"` and FALSE for `"no_observation"`: a resume re-drives exactly the instances that
produced no observation, and nothing else. That asymmetry IS the re-arm mechanism — there
is deliberately no flag and no `--force`, because an instance that DID produce an
observation must never be re-rolled (`eval/README.md`, `mint-execution/spec.md`: "silently
re-rolling until the number looks good is precisely the dishonesty this project exists to
prevent").

Because a re-arm re-`record`s an instance that already has an entry, each entry carries an
append-only `history`: the prior `{status, reason}` is pushed onto it before the new entry
overwrites. `--force` is banned for losing "the record of what already ran"; the re-arm
must not lose it either. `_validate_entry` therefore names `history` explicitly — it
rebuilds entries from a fixed key set, so a field it does not name is silently dropped on
every load and the append-only guarantee would hold only in memory.

Each entry also carries an optional `accounting` — what that attempt COST
(`{wall_clock_seconds, model_requests, retry_count, input_tokens, output_tokens, model,
provider}`) — which is what makes a stop-loss expressible and lets the write-up state the
cost of the number. Two rules travel with it. **Absent is not zero**: a field the provider
never reported is OMITTED, never written as `0`, because an unmeasured quantity rendered
as a measured one is the same dishonesty as rendering `UNVERIFIED` as `PASS`. And **no
dollar amount is ever stored**: under a subscription there is no per-token price, so a
price would be invented precision; if a metered key is used later, price is applied at
report time from a stated rate. `_validate_entry` names `accounting` for exactly the same
reason it names `history`.

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

#: The only statuses a recorded instance may carry. `"captured"` (a trace was produced) and
#: `"failed"` (the instance errored) both count as "done" for the pass — re-running a
#: failure is a deliberate, separate decision. `"no_observation"` does NOT: nothing was
#: observed, so the instance is still eligible. See `is_done` and the module docstring.
_VALID_STATUSES = frozenset({"captured", "failed", "no_observation"})

#: The statuses that mean an observation was produced, and therefore that the instance is
#: finished for good. Deliberately a whitelist, not `_VALID_STATUSES - {"no_observation"}`:
#: a future status must be an explicit, considered decision to be "done", because getting
#: this wrong in the permissive direction silently drops instances from the denominator.
_OBSERVED_STATUSES = frozenset({"captured", "failed"})


class Checkpoint:
    """A mutable per-instance disposition ledger with a fail-closed load and atomic save.

    Internally a `dict[str, dict]`:
    `instance_id -> {"status", "reason", "trace_path", "history"}`. Construct via
    `load_checkpoint` (never call this directly with raw untrusted data — the classmethod
    `_from_entries` is validated and used by the loader).
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
        accounting: Optional[dict] = None,
    ) -> None:
        """Record one instance's disposition, superseding any prior entry for that id.

        `status` must be one of `_VALID_STATUSES` — an unknown status is a caller bug and
        raises immediately, so a typo can never enter the ledger and later fail the load.
        `reason` and `trace_path` are optional context (a failure message, the bridged trace
        path); they are stored verbatim and only validated for JSON-serializability at
        `save` time, keeping the atomic-write guarantee as the single point that rejects a
        value the ledger cannot durably hold.

        The prior entry is SUPERSEDED, NOT ERASED: its `{status, reason}` is appended to the
        new entry's `history`, after whatever history it had already accumulated. A re-arm
        is the only way a second `record` happens for one id, and `--force` is banned in
        `eval/README.md` precisely for losing "the record of what already ran" — so this
        keeps it. `trace_path` is deliberately NOT carried into history: a re-armed instance
        by definition produced no trace, so there is never one to lose.

        `accounting` is what THIS attempt cost — `{wall_clock_seconds, model_requests,
        retry_count, input_tokens, output_tokens, model, provider}`, with **absent fields
        omitted rather than nulled**: a provider that reported no token usage must not be
        recorded as having reported zero, exactly as `UNVERIFIED` is never rendered as
        `PASS`. It is stored verbatim (this ledger does not interpret it) and, like the
        prior `{status, reason}`, it is carried into `history` on a re-record — the
        quota-stopped attempt really did consume requests, and dropping its accounting on
        re-arm would under-report the cost of the number by exactly the attempts that
        failed. It is carried ONLY when there was one, so a pre-accounting entry produces
        the same two-key history item it always did.
        """
        if status not in _VALID_STATUSES:
            allowed = ", ".join(sorted(_VALID_STATUSES))
            raise ValueError(f"status must be one of: {allowed}; got {status!r}")
        prior = self._entries.get(instance_id)
        if prior is None:
            history: list[dict] = []
        else:
            superseded = {"status": prior["status"], "reason": prior.get("reason")}
            prior_accounting = prior.get("accounting")
            if prior_accounting is not None:
                superseded["accounting"] = prior_accounting
            history = [*prior.get("history", []), superseded]
        self._entries[instance_id] = {
            "status": status,
            "reason": reason,
            "trace_path": trace_path,
            "accounting": accounting,
            "history": history,
        }

    def is_done(self, instance_id: str) -> bool:
        """True only if this instance produced an OBSERVATION — `captured` or `failed`.

        A failed instance is done for this pass: it ran, it errored, the mint moves on, and
        re-running it is an explicit choice a later pass makes, not something `is_done`
        silently invites. A `no_observation` instance is NOT done — it never ran at all
        (a quota cap rejected the request; a transient blip outlived its retries), so
        nothing about it has been observed and a resume re-drives it.

        That asymmetry is the entire re-arm mechanism: there is no flag and no `--force`,
        because the honest rule and the re-arm rule are the same rule. Do NOT "simplify"
        this to `instance_id in self._entries` — that reinstates the 2026-07-24 defect,
        where 56 quota rejections recorded as `failed` were treated as done forever.
        """
        entry = self._entries.get(instance_id)
        return entry is not None and entry["status"] in _OBSERVED_STATUSES

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

    def accounting(self, instance_id: str) -> Optional[dict]:
        """What this instance's recorded attempt cost, or `None` if none was recorded.

        `None` — not `{}` — for both an unrecorded instance and one recorded before this
        field existed: "no accounting was captured" and "its accounting was all zeroes"
        are different facts, and a summary that totalled them together would be reporting
        a measurement nobody made. A copy is returned so a reader cannot mutate the ledger
        by holding onto it.
        """
        entry = self._entries.get(instance_id)
        if entry is None:
            return None
        accounting = entry.get("accounting")
        return None if accounting is None else dict(accounting)

    def history(self, instance_id: str) -> list[dict]:
        """The superseded `{status, reason}` dispositions, oldest first; `[]` if none.

        Unlike `reason`/`trace_path` this returns `[]` rather than `None` for an unrecorded
        instance: "never re-armed" and "never recorded" are both honestly an empty history,
        and a caller auditing re-arms should be able to iterate without a `None` check.
        A copy is returned so an auditor cannot mutate the ledger by holding onto it.
        """
        entry = self._entries.get(instance_id)
        return [] if entry is None else list(entry.get("history", []))

    def instance_ids(self) -> tuple[str, ...]:
        """Every recorded instance id, in the order it entered this ledger.

        The read side of an audit (`eval/scripts/rearm_checkpoint.py` walks these to find
        the stranded quota failures). A tuple, not the live keys view, so a caller can
        record while iterating without mutating what it is iterating over — and so no
        consumer is tempted to reach into `_entries` and re-implement the fail-closed
        load beside `load_checkpoint`.
        """
        return tuple(self._entries)

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
    an unknown `status`, or a malformed `history` each raise with a message naming the
    offending instance — a ledger that loaded wrong would misreport which instances still
    need running.

    This function rebuilds the entry from a FIXED key set, so any field it does not name
    here is dropped on load. That is why `history` must be named: without it the
    append-only guarantee would hold in memory and evaporate on every save/load, which is
    the exact silent data loss the history exists to prevent. An ABSENT `history` is the
    legitimate pre-`no_observation` ledger (the 68-entry Stage-3 file) and defaults to `[]`;
    a PRESENT but malformed one is corruption and raises, because a re-arm record that
    cannot be read cannot be audited either.
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
    accounting = raw.get("accounting")
    if accounting is not None and not isinstance(accounting, dict):
        raise ValueError(
            f"checkpoint entry for {instance_id!r} has an 'accounting' that is not a "
            f"JSON object, got {type(accounting).__name__}"
        )
    history = raw.get("history", [])
    if not isinstance(history, list):
        raise ValueError(
            f"checkpoint entry for {instance_id!r} has a 'history' that is not a list, "
            f"got {type(history).__name__}"
        )
    for item in history:
        if not isinstance(item, dict):
            raise ValueError(
                f"checkpoint entry for {instance_id!r} has a 'history' item that is not a "
                f"JSON object, got {type(item).__name__}"
            )
    return {
        "status": status,
        "reason": raw.get("reason"),
        "trace_path": raw.get("trace_path"),
        # NAMED, for the same reason `history` is: this function rebuilds the entry from a
        # fixed key set, so an accounting it did not name would be dropped on every load —
        # the spend would survive in memory and evaporate on the next resume, which is
        # precisely the silent loss the field exists to prevent.
        "accounting": None if accounting is None else dict(accounting),
        # Copied, not aliased: the parsed JSON is discarded by the caller, but sharing the
        # list would let a single loaded entry be mutated through two references.
        "history": list(history),
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
